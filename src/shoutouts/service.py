"""
Shout-out service: the newsfeed, likes, edits, giving a shout-out, profiles, and the
directory lookups the forms need.

Rules enforced here (section A4 of the build plan):
- The feed only ever returns VISIBLE posts from the caller's country.
- Likes are idempotent, and like_count is updated in the same transaction.
- Only the sender can edit a post, and only while it is VISIBLE. Recipients never change.
- Nobody can recognise themselves, and every recipient must be an active employee.
"""
import base64
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.auth.service import calculate_points_for_employee

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
    keys = row.keys()
    return {
        "employeeId": row["employee_id"],
        "name": row["employee_name"],
        "email": row["email_id"],
        "jobTitle": row["job_title"],
        "teamId": row["team_id"],
        "teamName": row["team_name"] or "",
        "country": row["country"] or "AU",
        "role": row["role"] if "role" in keys else "EMPLOYEE",
        "status": row["status"] if "status" in keys else "ACTIVE",
        "avatarUrl": row["avatar_url"] if "avatar_url" in keys else None,
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


# ---------------------------------------------------------------- directory lookups

_EMPLOYEE_SELECT = """
    SELECT e.*, t.team_name
    FROM employees e
    LEFT JOIN teams t ON t.team_id = e.team_id
"""

MIN_SEARCH_LENGTH = 2
MAX_SEARCH_RESULTS = 25


def search_directory(conn, viewer: Dict[str, Any], query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    GET /api/directory/search. People you can recognise: active employees in your country,
    never yourself. Every word typed must match the start of a word in the name, any case.
    """
    terms = query.strip().split()
    if len(query.strip()) < MIN_SEARCH_LENGTH or not terms:
        raise ShoutoutError(
            "VALIDATION_FAILED", f"Type at least {MIN_SEARCH_LENGTH} characters to search.", 400
        )
    limit = max(1, min(limit, MAX_SEARCH_RESULTS))

    where = ["e.status != 'INACTIVE'", "e.country = ?", "e.employee_id != ?"]
    params: List[Any] = [viewer["country"], viewer["employeeId"]]
    for term in terms:
        # Escape LIKE wildcards so a typed % or _ is matched literally.
        safe = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("(e.employee_name LIKE ? ESCAPE '\\' OR e.employee_name LIKE ? ESCAPE '\\')")
        params.extend([f"{safe}%", f"% {safe}%"])

    rows = conn.execute(
        f"{_EMPLOYEE_SELECT} WHERE {' AND '.join(where)} ORDER BY e.employee_name, e.employee_id LIMIT ?",
        params + [limit],
    ).fetchall()
    return [_employee_summary(row) for row in rows]


def list_team_members(conn, viewer: Dict[str, Any], team_id: str) -> List[Dict[str, Any]]:
    """GET /api/teams/:teamId/members. Active members in your country, never yourself."""
    team = conn.execute("SELECT team_id FROM teams WHERE team_id = ?", (team_id,)).fetchone()
    if not team:
        raise ShoutoutError("NOT_FOUND", "Team not found.", 404)
    rows = conn.execute(
        f"""{_EMPLOYEE_SELECT}
            WHERE e.team_id = ? AND e.status != 'INACTIVE' AND e.country = ? AND e.employee_id != ?
            ORDER BY e.employee_name, e.employee_id""",
        (team_id, viewer["country"], viewer["employeeId"]),
    ).fetchall()
    return [_employee_summary(row) for row in rows]


# ---------------------------------------------------------------- create

MIN_TEAM_RECIPIENTS = 2
MAX_TEAM_RECIPIENTS = 50


def create_shoutout(conn, viewer: Dict[str, Any], body: Any) -> Dict[str, Any]:
    """
    POST /api/shoutouts. Checks run in the order the build plan sets out:
    1. shape of the request        -> VALIDATION_FAILED
    2. sender among the recipients -> SELF_SHOUTOUT
    3. every recipient is active   -> RECIPIENT_NOT_ACTIVE
    4. the principle is ACTIVE     -> PRINCIPLE_RETIRED
    5. a whole-team shout-out matches that team's members exactly -> VALIDATION_FAILED
    Then the post and its recipients are saved in one transaction.

    Not done here yet, because the pieces don't exist in this codebase: the profanity check
    (CONTENT_REJECTED) and queueing one email per recipient. Both belong just before the insert.
    """
    if not isinstance(body, dict):
        raise ShoutoutError("VALIDATION_FAILED", "Request body must be a JSON object.", 400)

    # 1. Shape
    recognition_type = body.get("recognitionType")
    if recognition_type not in ("INDIVIDUAL", "TEAM"):
        raise ShoutoutError("VALIDATION_FAILED", "'recognitionType' must be INDIVIDUAL or TEAM.", 400)

    recipient_ids = body.get("recipientIds")
    if not isinstance(recipient_ids, list) or not all(isinstance(r, str) and r for r in recipient_ids):
        raise ShoutoutError("VALIDATION_FAILED", "'recipientIds' must be a list of employee IDs.", 400)
    if len(set(recipient_ids)) != len(recipient_ids):
        raise ShoutoutError("VALIDATION_FAILED", "Each person can only be recognised once per shout-out.", 400)
    if recognition_type == "INDIVIDUAL" and len(recipient_ids) != 1:
        raise ShoutoutError("VALIDATION_FAILED", "An individual shout-out needs exactly one person.", 400)
    if recognition_type == "TEAM" and not MIN_TEAM_RECIPIENTS <= len(recipient_ids) <= MAX_TEAM_RECIPIENTS:
        raise ShoutoutError(
            "VALIDATION_FAILED",
            f"A team shout-out needs between {MIN_TEAM_RECIPIENTS} and {MAX_TEAM_RECIPIENTS} people.",
            400,
        )

    principle_id = body.get("principleId")
    if isinstance(principle_id, bool) or not isinstance(principle_id, int):
        raise ShoutoutError("VALIDATION_FAILED", "'principleId' must be a number.", 400)

    reason = _clean_text(body.get("reason"), "reason")
    impact = _clean_text(body.get("impact"), "impact")

    act_of_kindness = body.get("actOfKindness")
    if not isinstance(act_of_kindness, bool):
        raise ShoutoutError("VALIDATION_FAILED", "'actOfKindness' must be true or false.", 400)

    target_team_id = body.get("targetTeamId")
    if target_team_id is not None and (not isinstance(target_team_id, str) or recognition_type != "TEAM"):
        raise ShoutoutError("VALIDATION_FAILED", "'targetTeamId' is only for team shout-outs.", 400)

    # 2. No recognising yourself
    if viewer["employeeId"] in recipient_ids:
        raise ShoutoutError("SELF_SHOUTOUT", "You can't give a shout-out to yourself.", 400)

    # 3. Every recipient is an active employee
    marks = ",".join("?" for _ in recipient_ids)
    active = {
        row["employee_id"]
        for row in conn.execute(
            f"SELECT employee_id FROM employees WHERE status != 'INACTIVE' AND employee_id IN ({marks})",
            recipient_ids,
        )
    }
    if len(active) != len(recipient_ids):
        raise ShoutoutError(
            "RECIPIENT_NOT_ACTIVE", "One of the people you picked is no longer an active employee.", 400
        )

    # 4. The principle can be used
    principle = conn.execute("SELECT status FROM principles WHERE id = ?", (principle_id,)).fetchone()
    if not principle or principle["status"] != "ACTIVE":
        raise ShoutoutError("PRINCIPLE_RETIRED", "That principle is not available.", 400)

    # 5. A whole-team shout-out is exactly that team's active members, minus the sender
    if target_team_id is not None:
        team = conn.execute("SELECT team_id FROM teams WHERE team_id = ?", (target_team_id,)).fetchone()
        members = {
            row["employee_id"]
            for row in conn.execute(
                "SELECT employee_id FROM employees WHERE team_id = ? AND status != 'INACTIVE' AND employee_id != ?",
                (target_team_id, viewer["employeeId"]),
            )
        }
        if not team or members != set(recipient_ids):
            raise ShoutoutError(
                "VALIDATION_FAILED", "The people picked don't match that team's current members.", 400
            )

    # 6. (Profanity check goes here once the moderation service exists.)

    # 7. Save everything together
    try:
        cursor = conn.execute("""
            INSERT INTO shoutouts (sender_id, recognition_type, target_team_id, principle_id, reason, impact,
                                   act_of_kindness, country, visibility, like_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'VISIBLE', 0, ?)
        """, (
            viewer["employeeId"], recognition_type, target_team_id, principle_id, reason, impact,
            1 if act_of_kindness else 0, viewer["country"], utc_now_iso(),
        ))
        shoutout_id = cursor.lastrowid
        conn.executemany(
            "INSERT INTO shoutout_recipients (shoutout_id, recipient_id) VALUES (?, ?)",
            [(shoutout_id, recipient_id) for recipient_id in recipient_ids],
        )
        _record_audit(
            conn, viewer["employeeId"], "SHOUTOUT_CREATED", shoutout_id, {},
            {"recipientIds": recipient_ids, "principleId": principle_id},
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    created = _get_visible_row(conn, shoutout_id, viewer)
    return _build_dtos(conn, [created], viewer["employeeId"])[0]


# ---------------------------------------------------------------- profile

RECENT_RECEIVED_LIMIT = 20


def get_profile(conn, viewer: Dict[str, Any], employee_id: str) -> Dict[str, Any]:
    """
    GET /api/profile/:employeeId. Returns ProfileDto for anyone in the viewer's country.
    Only VISIBLE posts count, so a hidden or deleted post drops out of every number here.
    Each metric is one grouped query; nothing loops over individual posts.
    """
    employee = conn.execute(
        f"{_EMPLOYEE_SELECT} WHERE e.employee_id = ? AND e.country = ?", (employee_id, viewer["country"])
    ).fetchone()
    if not employee:
        raise ShoutoutError("NOT_FOUND", "We couldn't find that person.", 404)

    # Shared conditions: posts this person received, and posts they gave, that the viewer may see.
    received = """
        FROM shoutout_recipients sr
        JOIN shoutouts s ON s.id = sr.shoutout_id
        WHERE sr.recipient_id = ? AND s.visibility = 'VISIBLE' AND s.country = ?
    """
    given = "FROM shoutouts s WHERE s.sender_id = ? AND s.visibility = 'VISIBLE' AND s.country = ?"
    args = (employee_id, viewer["country"])

    counts = conn.execute(
        f"SELECT COUNT(*) AS total, COALESCE(SUM(s.act_of_kindness), 0) AS kindness {received}", args
    ).fetchone()
    given_count = conn.execute(f"SELECT COUNT(*) AS total {given}", args).fetchone()["total"]

    top_received = conn.execute(f"""
        SELECT p.name, COUNT(*) AS total
        {received.replace("WHERE", "JOIN principles p ON p.id = s.principle_id WHERE")}
        GROUP BY p.id ORDER BY total DESC, p.display_order LIMIT 1
    """, args).fetchone()

    top_given = conn.execute(f"""
        SELECT p.name, COUNT(*) AS total
        {given.replace("WHERE", "JOIN principles p ON p.id = s.principle_id WHERE")}
        GROUP BY p.id ORDER BY total DESC, p.display_order LIMIT 1
    """, args).fetchone()

    recommender = conn.execute(f"""
        SELECT s.sender_id, COUNT(*) AS total, MAX(s.created_at) AS latest
        {received}
        GROUP BY s.sender_id ORDER BY total DESC, latest DESC LIMIT 1
    """, args).fetchone()
    top_recommender = None
    if recommender:
        person = conn.execute(
            f"{_EMPLOYEE_SELECT} WHERE e.employee_id = ?", (recommender["sender_id"],)
        ).fetchone()
        if person:
            top_recommender = {"employee": _employee_summary(person), "count": recommender["total"]}

    # created_at is an ISO string in UTC, so its first 7 characters are the month (YYYY-MM).
    busiest = conn.execute(f"""
        SELECT substr(s.created_at, 1, 7) AS month, COUNT(*) AS total
        {received}
        GROUP BY month ORDER BY total DESC, month DESC LIMIT 1
    """, args).fetchone()

    recent_rows = conn.execute(f"""
        {_SHOUTOUT_SELECT}
        WHERE s.visibility = 'VISIBLE' AND s.country = ?
          AND s.id IN (SELECT shoutout_id FROM shoutout_recipients WHERE recipient_id = ?)
        ORDER BY s.created_at DESC, s.id DESC LIMIT ?
    """, (viewer["country"], employee_id, RECENT_RECEIVED_LIMIT)).fetchall()

    return {
        "employee": _employee_summary(employee),
        "points": calculate_points_for_employee(conn, employee_id),
        "receivedCount": counts["total"],
        "givenCount": given_count,
        "kindnessReceivedCount": counts["kindness"],
        "topPrincipleReceived": top_received["name"] if top_received else None,
        "topRecommender": top_recommender,
        "busiestMonth": busiest["month"] if busiest else None,
        "topPrincipleGiven": top_given["name"] if top_given else None,
        "recentReceived": _build_dtos(conn, recent_rows, viewer["employeeId"]),
    }
