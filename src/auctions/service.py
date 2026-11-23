"""
Auction service (owner: Nathan): items people bid on with their points.

Rules enforced here:
- An item's state comes from the clock: UPCOMING before starts_at, LIVE until ends_at, then ENDED.
- Bids are whole points and only on LIVE items. The first bid must be at least the starting bid,
  every later bid must beat the current one. You may raise your own bid.
- You can't bid more than you have available: your points minus the points held by your
  leading bids on other live items.
- Nothing is stored about balances. The winner's points come off through points_spent(): the
  highest bid on every ended item, which calculate_points_for_employee() subtracts.
"""
import base64
import binascii
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.admin.common import employee_summary, record_audit
from src.auth.service import calculate_points_for_employee

MAX_NAME_LENGTH = 80
MAX_DESCRIPTION_LENGTH = 500
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB, the same limit as profile pictures
ENDED_SHOWN = 10  # ended items people still see on the Auction Table

_IMAGE_TYPES = {"png": "png", "jpeg": "jpg", "jpg": "jpg", "webp": "webp", "gif": "gif"}
_DATA_URL = re.compile(r"^data:image/([a-zA-Z0-9.+-]+);base64,(.*)$", re.DOTALL)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IMAGES_DIR = os.path.join(_BASE_DIR, "static", "auctions")
IMAGES_URL = "/static/auctions"

# The bid that leads each item: the highest amount (the earliest wins a tie, though the bid
# rules never allow one).
_LEADING_BID = "(SELECT x.id FROM auction_bids x WHERE x.item_id = {item} ORDER BY x.amount DESC, x.id LIMIT 1)"


class AuctionError(Exception):
    """A request the API answers with { error: { code, message } }."""

    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------- time

def _iso(moment: datetime) -> str:
    """UTC ISO timestamp like 2026-11-18T05:10:00.000Z, the format the shout-outs use."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"


def now_iso() -> str:
    return _iso(datetime.now(timezone.utc))


def _parse_time(name: str, value: Any) -> str:
    """An ISO date-time from the client, normalised to the stored format. No offset = UTC."""
    if not isinstance(value, str) or not value.strip():
        raise AuctionError("VALIDATION_FAILED", f"'{name}' is required.", 400)
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise AuctionError("VALIDATION_FAILED", f"'{name}' must be a date and time like 2026-11-20T09:00:00Z.", 400)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return _iso(moment)


def item_status(row, now: str) -> str:
    if now < row["starts_at"]:
        return "UPCOMING"
    return "LIVE" if now < row["ends_at"] else "ENDED"


# ---------------------------------------------------------------- points

def points_spent(conn, employee_id: str, now: Optional[str] = None) -> int:
    """Points this person has spent: their winning bid on every item that has ended."""
    leading = _LEADING_BID.format(item="i.id")
    row = conn.execute(
        f"""SELECT COALESCE(SUM(b.amount), 0) AS n
            FROM auction_items i JOIN auction_bids b ON b.id = {leading}
            WHERE i.ends_at <= ? AND b.bidder_id = ?""",
        (now or now_iso(), employee_id),
    ).fetchone()
    return row["n"]


def points_held(conn, employee_id: str, now: Optional[str] = None, except_item: Optional[int] = None) -> int:
    """Points tied up in this person's leading bids on live items (optionally leaving one item out)."""
    now = now or now_iso()
    leading = _LEADING_BID.format(item="i.id")
    sql = f"""SELECT COALESCE(SUM(b.amount), 0) AS n
              FROM auction_items i JOIN auction_bids b ON b.id = {leading}
              WHERE i.starts_at <= ? AND i.ends_at > ? AND b.bidder_id = ?"""
    params: List[Any] = [now, now, employee_id]
    if except_item is not None:
        sql += " AND i.id != ?"
        params.append(except_item)
    return conn.execute(sql, params).fetchone()["n"]


def balance(conn, employee_id: str, now: Optional[str] = None) -> Dict[str, int]:
    """What the Auction Table shows: points earned, spent on won items, held by leading bids, and free to bid."""
    now = now or now_iso()
    points = calculate_points_for_employee(conn, employee_id)  # already net of points spent
    spent = points_spent(conn, employee_id, now)
    held = points_held(conn, employee_id, now)
    return {"earned": points + spent, "spent": spent, "held": held, "available": max(0, points - held)}


# ---------------------------------------------------------------- DTOs

def _bidder(row) -> Dict[str, Any]:
    return {**employee_summary(row), "avatarUrl": row["avatar_url"] if "avatar_url" in row.keys() else None}


def build_dtos(conn, rows, viewer_id: str, now: str) -> List[Dict[str, Any]]:
    """Turns auction_items rows into AuctionItemDto dicts, loading each item's leading bid in bulk."""
    if not rows:
        return []
    marks = ",".join("?" for _ in rows)
    leading = _LEADING_BID.format(item="b.item_id")
    top = {
        r["item_id"]: r
        for r in conn.execute(
            f"""SELECT b.item_id, b.amount, b.bidder_id, e.*, t.team_name,
                       (SELECT COUNT(*) FROM auction_bids c WHERE c.item_id = b.item_id) AS bid_count
                FROM auction_bids b
                JOIN employees e ON e.employee_id = b.bidder_id
                LEFT JOIN teams t ON t.team_id = e.team_id
                WHERE b.item_id IN ({marks}) AND b.id = {leading}""",
            [r["id"] for r in rows],
        ).fetchall()
    }

    # Load recent bid history for items
    recent_bids_map: Dict[int, List[Dict[str, Any]]] = {}
    for b in conn.execute(
        f"""SELECT b.id, b.item_id, b.amount, b.created_at, e.*, t.team_name
            FROM auction_bids b
            JOIN employees e ON e.employee_id = b.bidder_id
            LEFT JOIN teams t ON t.team_id = e.team_id
            WHERE b.item_id IN ({marks})
            ORDER BY b.amount DESC, b.id DESC""",
        [r["id"] for r in rows],
    ).fetchall():
        recent_bids_map.setdefault(b["item_id"], []).append({
            "id": b["id"],
            "amount": b["amount"],
            "createdAt": b["created_at"],
            "bidder": _bidder(b),
        })

    items = []
    for row in rows:
        lead = top.get(row["id"])
        items.append({
            "id": row["id"],
            "name": row["name"],
            "description": row["description"] or "",
            "imageUrl": row["image_url"],
            "startingBid": row["starting_bid"],
            "startsAt": row["starts_at"],
            "endsAt": row["ends_at"],
            "status": item_status(row, now),
            "currentBid": lead["amount"] if lead else None,
            "currentBidder": _bidder(lead) if lead else None,
            "bidCount": lead["bid_count"] if lead else 0,
            "recentBids": recent_bids_map.get(row["id"], [])[:5],
            "minNextBid": lead["amount"] + 1 if lead else row["starting_bid"],
            "leadingIsMe": bool(lead) and lead["bidder_id"] == viewer_id,
        })
    return items


# ---------------------------------------------------------------- reading

def list_items(conn, viewer_id: str, country: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Live items first (closing soonest), then upcoming (opening soonest), then ended (latest first).
    With a country (the Auction Table) only that country's items and the last few ended ones;
    without one (the admin page) everything.
    """
    now = now_iso()
    if country:
        rows = conn.execute("SELECT * FROM auction_items WHERE country = ?", (country,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM auction_items").fetchall()

    live = sorted((r for r in rows if item_status(r, now) == "LIVE"), key=lambda r: (r["ends_at"], r["id"]))
    upcoming = sorted((r for r in rows if item_status(r, now) == "UPCOMING"), key=lambda r: (r["starts_at"], r["id"]))
    ended = sorted((r for r in rows if item_status(r, now) == "ENDED"), key=lambda r: (r["ends_at"], r["id"]), reverse=True)
    if country:
        ended = ended[:ENDED_SHOWN]
    return build_dtos(conn, [*live, *upcoming, *ended], viewer_id, now)


def get_item(conn, item_id: int, viewer_id: str) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM auction_items WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise AuctionError("NOT_FOUND", f"Auction item {item_id} not found.", 404)
    return build_dtos(conn, [row], viewer_id, now_iso())[0]


# ---------------------------------------------------------------- bidding

def place_bid(conn, item_id: int, bidder: Dict[str, Any], amount: Any) -> Dict[str, Any]:
    """Checks and records a bid in one transaction, so two people can't both take the lead."""
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 1:
        raise AuctionError("VALIDATION_FAILED", "'amount' must be a whole number of points, 1 or more.", 400)
    bidder_id = bidder["employeeId"]

    conn.execute("BEGIN IMMEDIATE")
    try:
        now = now_iso()
        item = conn.execute("SELECT * FROM auction_items WHERE id = ?", (item_id,)).fetchone()
        if not item or item["country"] != bidder["country"]:
            raise AuctionError("NOT_FOUND", f"Auction item {item_id} not found.", 404)

        status = item_status(item, now)
        if status == "UPCOMING":
            raise AuctionError("AUCTION_NOT_OPEN", "Bidding on this item hasn't opened yet.", 409)
        if status == "ENDED":
            raise AuctionError("AUCTION_NOT_OPEN", "Bidding on this item has closed.", 409)

        lead = conn.execute(
            "SELECT amount FROM auction_bids WHERE item_id = ? ORDER BY amount DESC, id LIMIT 1", (item_id,)
        ).fetchone()
        if lead and amount <= lead["amount"]:
            raise AuctionError("BID_TOO_LOW", f"The current bid is {lead['amount']} points. Bid more than that.", 409)
        if not lead and amount < item["starting_bid"]:
            raise AuctionError("BID_TOO_LOW", f"The starting bid is {item['starting_bid']} points.", 409)

        # Points held by this item don't count against a new bid on it: raising replaces your own bid.
        available = calculate_points_for_employee(conn, bidder_id) - points_held(conn, bidder_id, now, except_item=item_id)
        if amount > available:
            raise AuctionError(
                "INSUFFICIENT_POINTS",
                f"You have {max(0, available)} points available to bid, so you can't bid {amount}.",
                400,
            )

        conn.execute(
            "INSERT INTO auction_bids (item_id, bidder_id, amount, created_at) VALUES (?, ?, ?, ?)",
            (item_id, bidder_id, amount, now),
        )
        record_audit(conn, bidder_id, "AUCTION_BID_PLACED", "AUCTION", item_id,
                     before={"currentBid": lead["amount"] if lead else None}, after={"currentBid": amount})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_item(conn, item_id, bidder_id)


# ---------------------------------------------------------------- admin: add and remove items

def _clean_text(name: str, value: Any, max_length: int, required: bool) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise AuctionError("VALIDATION_FAILED", f"'{name}' must be text.", 400)
    text = value.strip()
    if required and not text:
        raise AuctionError("VALIDATION_FAILED", f"'{name}' is required.", 400)
    if len(text) > max_length:
        raise AuctionError("VALIDATION_FAILED", f"'{name}' can be at most {max_length} characters.", 400)
    return text


def _decode_image(data_url: Any):
    """A data: URL from the admin form -> (bytes, file extension)."""
    match = _DATA_URL.match(data_url) if isinstance(data_url, str) else None
    extension = _IMAGE_TYPES.get(match.group(1).lower()) if match else None
    if not extension:
        raise AuctionError("VALIDATION_FAILED", "The image must be a PNG, JPG, WEBP or GIF.", 400)
    try:
        data = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError):
        raise AuctionError("VALIDATION_FAILED", "The image couldn't be read. Try another file.", 400)
    if not data:
        raise AuctionError("VALIDATION_FAILED", "The image is empty.", 400)
    if len(data) > MAX_IMAGE_BYTES:
        raise AuctionError("VALIDATION_FAILED", "The image is larger than 5 MB.", 400)
    return data, extension


def create_item(conn, admin: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    name = _clean_text("name", body.get("name"), MAX_NAME_LENGTH, required=True)
    description = _clean_text("description", body.get("description"), MAX_DESCRIPTION_LENGTH, required=False)
    starting_bid = body.get("startingBid")
    if isinstance(starting_bid, bool) or not isinstance(starting_bid, int) or starting_bid < 1:
        raise AuctionError("VALIDATION_FAILED", "'startingBid' must be a whole number of points, 1 or more.", 400)
    starts_at = _parse_time("startsAt", body.get("startsAt"))
    ends_at = _parse_time("endsAt", body.get("endsAt"))
    now = now_iso()
    if ends_at <= starts_at:
        raise AuctionError("VALIDATION_FAILED", "Bidding must end after it starts.", 400)
    if ends_at <= now:
        raise AuctionError("VALIDATION_FAILED", "Bidding must end in the future.", 400)
    image = _decode_image(body["imageBase64"]) if body.get("imageBase64") else None

    path = None
    try:
        cursor = conn.execute(
            """INSERT INTO auction_items (name, description, starting_bid, starts_at, ends_at, country, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, description or None, starting_bid, starts_at, ends_at, admin["country"], admin["employeeId"], now),
        )
        item_id = cursor.lastrowid
        if image:
            data, extension = image
            os.makedirs(IMAGES_DIR, exist_ok=True)
            filename = f"{item_id}_{int(time.time())}.{extension}"
            path = os.path.join(IMAGES_DIR, filename)
            with open(path, "wb") as f:
                f.write(data)
            conn.execute("UPDATE auction_items SET image_url = ? WHERE id = ?", (f"{IMAGES_URL}/{filename}", item_id))
        record_audit(conn, admin["employeeId"], "AUCTION_ITEM_CREATED", "AUCTION", item_id,
                     after={"name": name, "startingBid": starting_bid, "startsAt": starts_at, "endsAt": ends_at})
        conn.commit()
    except Exception:
        conn.rollback()
        if path and os.path.exists(path):
            os.remove(path)
        raise
    return get_item(conn, item_id, admin["employeeId"])


def remove_item(conn, admin: Dict[str, Any], item_id: int) -> None:
    """Takes an item off the table. Only while nobody has bid on it."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        item = conn.execute("SELECT * FROM auction_items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            raise AuctionError("NOT_FOUND", f"Auction item {item_id} not found.", 404)
        bids = conn.execute("SELECT COUNT(*) AS n FROM auction_bids WHERE item_id = ?", (item_id,)).fetchone()["n"]
        if bids:
            raise AuctionError("AUCTION_HAS_BIDS", "This item already has bids, so it can't be removed.", 409)
        conn.execute("DELETE FROM auction_items WHERE id = ?", (item_id,))
        record_audit(conn, admin["employeeId"], "AUCTION_ITEM_REMOVED", "AUCTION", item_id,
                     before={"name": item["name"], "startingBid": item["starting_bid"]})
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # The image is only ever one we wrote into IMAGES_DIR; never follow a path out of it.
    if item["image_url"]:
        path = os.path.join(IMAGES_DIR, os.path.basename(item["image_url"]))
        if os.path.isfile(path):
            os.remove(path)
