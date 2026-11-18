"""
Newsfeed service: reads, likes and edits shout-outs.

Rules enforced here (section A4 of the build plan):
- The feed only ever returns VISIBLE posts from the caller's country.
- Likes are idempotent, and like_count is updated in the same transaction.
- Only the sender can edit a post, and only while it is VISIBLE. Recipients never change.
"""
import base64
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50
MAX_TEXT_LENGTH = 500
SORTS = ("newest", "most_liked")


class ShoutoutError(Exception):
    """A request the API answers with { error: { code, message } }."""

    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def utc_now_iso() -> str:
    """ISO timestamp in UTC, e.g. 2026-11-18T05:10:00.000Z (matches the seeded rows)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"


# ---------------------------------------------------------------- cursors

def encode_cursor(values: List[Any]) -> str:
    """The cursor is opaque to the client: base64 of the last row's sort values."""
    return base64.urlsafe_b64encode(json.dumps(values).encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str, expected_length: int) -> List[Any]:
    try:
        values = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
    except Exception:
        raise ShoutoutError("VALIDATION_FAILED", "Invalid cursor.", 400)
    if not isinstance(values, list) or len(values) != expected_length:
        raise ShoutoutError("VALIDATION_FAILED", "Invalid cursor.", 400)
    return values


# ---------------------------------------------------------------- DTOs

def _employee_summary(row) -> Dict[str, Any]:
    return {
        "employeeId": row["employee_id"],
        "name": row["employee_name"],
        "email": row["email_id"],
        "jobTitle": row["job_title"],
        "teamId": row["team_id"],
        "teamName": row["team_name"] or "",
        "country": row["country"] or "AU",
    }


def _build_dtos(conn, rows, viewer_id: str) -> List[Dict[str, Any]]:
    """Turns shout-out rows into ShoutoutDto dicts, loading people and likes in bulk."""
    if not rows:
        return []
    ids = [row["id"] for row in rows]
    marks = ",".join("?" for _ in ids)

    recipients: Dict[int, List[Dict[str, Any]]] = {i: [] for i in ids}
    for rec in conn.execute(f"""
        SELECT sr.shoutout_id, e.*, t.team_name
        FROM shoutout_recipients sr
        JOIN employees e ON e.employee_id = sr.recipient_id
        LEFT JOIN teams t ON t.team_id = e.team_id
        WHERE sr.shoutout_id IN ({marks})
        ORDER BY e.employee_name, e.employee_id
    """, ids):
        recipients[rec["shoutout_id"]].append(_employee_summary(rec))

    liked = {
        row["shoutout_id"]
        for row in conn.execute(
            f"SELECT shoutout_id FROM likes WHERE employee_id = ? AND shoutout_id IN ({marks})",
            [viewer_id] + ids,
        )
    }

    dtos = []
    for row in rows:
        target_team = None
        if row["target_team_id"]:
            target_team = {"teamId": row["target_team_id"], "teamName": row["target_team_name"] or ""}
        dtos.append({
            "id": row["id"],
            "sender": {
                "employeeId": row["sender_id"],
                "name": row["sender_name"],
                "email": row["sender_email"],
                "jobTitle": row["sender_job_title"],
                "teamId": row["sender_team_id"],
                "teamName": row["sender_team_name"] or "",
                "country": row["sender_country"] or "AU",
            },
            "recipients": recipients[row["id"]],
            "targetTeam": target_team,
            "recognitionType": row["recognition_type"],
            "principle": {"id": row["principle_id"], "name": row["principle_name"]},
            "reason": row["reason"],
            "impact": row["impact"],
            "actOfKindness": bool(row["act_of_kindness"]),
            "country": row["country"],
            "likeCount": row["like_count"],
            "likedByMe": row["id"] in liked,
            "canEdit": row["sender_id"] == viewer_id,
            "visibility": row["visibility"],
            "createdAt": row["created_at"],
            "editedAt": row["edited_at"],
        })
    return dtos


_SHOUTOUT_SELECT = """
    SELECT s.*,
           p.name AS principle_name,
           tt.team_name AS target_team_name,
           se.employee_name AS sender_name,
           se.email_id AS sender_email,
           se.job_title AS sender_job_title,
           se.team_id AS sender_team_id,
           se.country AS sender_country,
           st.team_name AS sender_team_name
    FROM shoutouts s
    JOIN principles p ON p.id = s.principle_id
    JOIN employees se ON se.employee_id = s.sender_id
    LEFT JOIN teams st ON st.team_id = se.team_id
    LEFT JOIN teams tt ON tt.team_id = s.target_team_id
"""


def _get_visible_row(conn, shoutout_id: int, viewer: Dict[str, Any]):
    """The post, if the viewer is allowed to see it on the feed. Otherwise NOT_FOUND."""
    row = conn.execute(
        _SHOUTOUT_SELECT + " WHERE s.id = ? AND s.visibility = 'VISIBLE' AND s.country = ?",
        (shoutout_id, viewer["country"]),
    ).fetchone()
    if not row:
        raise ShoutoutError("NOT_FOUND", "Shout-out not found.", 404)
    return row


# ---------------------------------------------------------------- feed

def list_feed(
    conn,
    viewer: Dict[str, Any],
    sort: str = "newest",
    principle_id: Optional[int] = None,
    team_id: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    """
    GET /api/shoutouts. Returns Page<ShoutoutDto>: { items, nextCursor }.
    newest     = created_at DESC, id DESC
    most_liked = like_count DESC, created_at DESC, id DESC
    """
    if sort not in SORTS:
        raise ShoutoutError("VALIDATION_FAILED", "sort must be 'newest' or 'most_liked'.", 400)
    limit = max(1, min(limit, MAX_PAGE_SIZE))

    where = ["s.visibility = 'VISIBLE'", "s.country = ?"]
    params: List[Any] = [viewer["country"]]

    if principle_id is not None:
        where.append("s.principle_id = ?")
        params.append(principle_id)

    if team_id:
        # Matches any recipient's team.
        where.append("""EXISTS (
            SELECT 1 FROM shoutout_recipients sr
            JOIN employees re ON re.employee_id = sr.recipient_id
            WHERE sr.shoutout_id = s.id AND re.team_id = ?
        )""")
        params.append(team_id)

    if sort == "most_liked":
        order_by = "s.like_count DESC, s.created_at DESC, s.id DESC"
        if cursor:
            where.append("(s.like_count, s.created_at, s.id) < (?, ?, ?)")
            params.extend(decode_cursor(cursor, 3))
    else:
        order_by = "s.created_at DESC, s.id DESC"
        if cursor:
            where.append("(s.created_at, s.id) < (?, ?)")
            params.extend(decode_cursor(cursor, 2))

    # Ask for one extra row to know whether there is another page.
    rows = conn.execute(
        f"{_SHOUTOUT_SELECT} WHERE {' AND '.join(where)} ORDER BY {order_by} LIMIT ?",
        params + [limit + 1],
    ).fetchall()

    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = page[-1]
        if sort == "most_liked":
            next_cursor = encode_cursor([last["like_count"], last["created_at"], last["id"]])
        else:
            next_cursor = encode_cursor([last["created_at"], last["id"]])

    return {"items": _build_dtos(conn, page, viewer["employeeId"]), "nextCursor": next_cursor}


# ---------------------------------------------------------------- likes

def set_like(conn, viewer: Dict[str, Any], shoutout_id: int, liked: bool) -> Dict[str, Any]:
    """POST (liked=True) or DELETE (liked=False) /api/shoutouts/:id/like. Safe to repeat."""
    _get_visible_row(conn, shoutout_id, viewer)
    try:
        if liked:
            changed = conn.execute(
                "INSERT OR IGNORE INTO likes (shoutout_id, employee_id, created_at) VALUES (?, ?, ?)",
                (shoutout_id, viewer["employeeId"], utc_now_iso()),
            ).rowcount
            if changed:
                conn.execute("UPDATE shoutouts SET like_count = like_count + 1 WHERE id = ?", (shoutout_id,))
        else:
            changed = conn.execute(
                "DELETE FROM likes WHERE shoutout_id = ? AND employee_id = ?",
                (shoutout_id, viewer["employeeId"]),
            ).rowcount
            if changed:
                conn.execute(
                    "UPDATE shoutouts SET like_count = MAX(like_count - 1, 0) WHERE id = ?", (shoutout_id,)
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    count = conn.execute("SELECT like_count FROM shoutouts WHERE id = ?", (shoutout_id,)).fetchone()
    return {"likeCount": count["like_count"], "likedByMe": liked}


# ---------------------------------------------------------------- edit

def _clean_text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ShoutoutError("VALIDATION_FAILED", f"'{field}' must be text.", 400)
    text = value.strip()
    if not 1 <= len(text) <= MAX_TEXT_LENGTH:
        raise ShoutoutError(
            "VALIDATION_FAILED", f"'{field}' must be between 1 and {MAX_TEXT_LENGTH} characters.", 400
        )
    return text


def _record_audit(conn, actor_id: str, action: str, target_id: int, before: Dict, after: Dict):
    """Writes an audit row when the audit_events table exists (same approach as the auth service)."""
    table_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events'"
    ).fetchone()
    if table_exists:
        conn.execute("""
            INSERT INTO audit_events (actor_id, action, target_type, target_id, before, after, created_at)
            VALUES (?, ?, 'SHOUTOUT', ?, ?, ?, CURRENT_TIMESTAMP)
        """, (actor_id, action, str(target_id), json.dumps(before), json.dumps(after)))


def edit_shoutout(conn, viewer: Dict[str, Any], shoutout_id: int, body: Any) -> Dict[str, Any]:
    """PATCH /api/shoutouts/:id. Body: any of principleId, reason, impact, actOfKindness."""
    if not isinstance(body, dict):
        raise ShoutoutError("VALIDATION_FAILED", "Request body must be a JSON object.", 400)

    row = _get_visible_row(conn, shoutout_id, viewer)
    if row["sender_id"] != viewer["employeeId"]:
        raise ShoutoutError("FORBIDDEN", "Only the sender can edit this shout-out.", 403)

    changes: Dict[str, Any] = {}

    if "principleId" in body:
        principle_id = body["principleId"]
        if isinstance(principle_id, bool) or not isinstance(principle_id, int):
            raise ShoutoutError("VALIDATION_FAILED", "'principleId' must be a number.", 400)
        # Keeping the current principle is fine even if it has since been retired.
        if principle_id != row["principle_id"]:
            principle = conn.execute("SELECT status FROM principles WHERE id = ?", (principle_id,)).fetchone()
            if not principle or principle["status"] != "ACTIVE":
                raise ShoutoutError("PRINCIPLE_RETIRED", "That principle is not available.", 400)
            changes["principle_id"] = principle_id

    if "reason" in body:
        reason = _clean_text(body["reason"], "reason")
        if reason != row["reason"]:
            changes["reason"] = reason

    if "impact" in body:
        impact = _clean_text(body["impact"], "impact")
        if impact != row["impact"]:
            changes["impact"] = impact

    if "actOfKindness" in body:
        if not isinstance(body["actOfKindness"], bool):
            raise ShoutoutError("VALIDATION_FAILED", "'actOfKindness' must be true or false.", 400)
        if body["actOfKindness"] != bool(row["act_of_kindness"]):
            changes["act_of_kindness"] = 1 if body["actOfKindness"] else 0

    if changes:
        before = {column: row[column] for column in changes}
        changes["edited_at"] = utc_now_iso()
        assignments = ", ".join(f"{column} = ?" for column in changes)
        try:
            conn.execute(
                f"UPDATE shoutouts SET {assignments} WHERE id = ?", list(changes.values()) + [shoutout_id]
            )
            _record_audit(conn, viewer["employeeId"], "SHOUTOUT_EDITED", shoutout_id, before, changes)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    updated = _get_visible_row(conn, shoutout_id, viewer)
    return _build_dtos(conn, [updated], viewer["employeeId"])[0]


# ---------------------------------------------------------------- filter options

def list_active_principles(conn) -> List[Dict[str, Any]]:
    """GET /api/principles: ACTIVE principles in display order."""
    rows = conn.execute(
        "SELECT * FROM principles WHERE status = 'ACTIVE' ORDER BY display_order, id"
    ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "displayOrder": row["display_order"],
            "status": row["status"],
        }
        for row in rows
    ]


def list_teams(conn, country: str) -> List[Dict[str, Any]]:
    """GET /api/teams: teams with their number of active members in the caller's country."""
    rows = conn.execute("""
        SELECT t.team_id, t.team_name, COUNT(e.employee_id) AS member_count
        FROM teams t
        LEFT JOIN employees e
               ON e.team_id = t.team_id AND e.status != 'INACTIVE' AND e.country = ?
        GROUP BY t.team_id, t.team_name
        ORDER BY t.team_name
    """, (country,)).fetchall()
    return [
        {"teamId": row["team_id"], "teamName": row["team_name"], "memberCount": row["member_count"]}
        for row in rows
    ]
