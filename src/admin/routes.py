"""
Admin routes (owner: Nathan). Every route here is admin-only.

  GET   /api/admin/users?q=&from=&to=        -> AdminUserDto[] + givenCount, receivedCount for the range
  GET   /api/admin/users/:employeeId?from=&to=  -> the same row + points
  PATCH /api/admin/users/:employeeId         { status: ACTIVE | SUSPENDED } -> AdminUserDto
  GET   /api/admin/audit?action=&actorId=&from=&to=&cursor=&limit=  -> Page<AuditEventDto>, read-only
  GET   /api/admin/shoutouts?visibility=&q=&between=&month=&employeeId=&kind=&cursor=&limit=  -> Page<ShoutoutDto>, every visibility
  POST  /api/admin/slt-shoutouts             CreateShoutoutRequest -> 201 ShoutoutDto with kind SLT
  GET   /api/admin/shoutouts/:id             -> ShoutoutDto, any visibility
  PATCH /api/admin/shoutouts/:id             { visibility } -> ShoutoutDto (HIDDEN <-> VISIBLE; DELETED is final)
  GET   /api/admin/alerts/reciprocal?month=YYYY-MM                  -> ReciprocalAlertDto[]

Suspending writes USER_SUSPENDED, reinstating writes USER_REINSTATED.
You can't suspend yourself. People who have left (status INACTIVE in the directory)
can't be suspended or reinstated: the employees table keeps a single status column,
so changing it would make a former employee active again.

The audit log is read-only: there is no route that edits or deletes audit rows.
Reports and failed emails come later.
"""
import base64
import binascii
import json
import re
from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request

from database import get_db
from src.admin.common import (
    AUDIT_ACTIONS,
    admin_user_dto,
    employee_summary,
    make_error,
    post_filter,
    read_date_range,
    read_json_object,
    record_audit,
)
from src.auth.middleware import require_admin
from src.auth.service import calculate_points_for_employee
# Reuse the feed's ShoutoutDto builder so admin and feed cards have exactly the same shape.
from src.shoutouts.service import (
    SHOUTOUT_KINDS,
    ShoutoutError,
    _SHOUTOUT_SELECT,
    _build_dtos,
    create_shoutout,
    decode_cursor,
    encode_cursor,
)

admin_bp = Blueprint("admin", __name__)

USER_STATUSES = {"ACTIVE", "SUSPENDED"}
MAX_USERS = 200

_USER_SELECT = """
    SELECT e.*, t.team_name
    FROM employees e
    LEFT JOIN teams t ON e.team_id = t.team_id
"""


def _like(q: str) -> str:
    """A LIKE pattern matching q anywhere, with % and _ in q taken literally."""
    escaped = q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _user_stats_select(date_from, date_to):
    """
    _USER_SELECT plus given_count (posts sent) and received_count (posts received) in the
    date range. VISIBLE posts only, the same rule as points and reports. SLT shout-outs don't
    count as given by the admin who posted them.
    """
    where, params = post_filter(date_from, date_to)
    sql = f"""
        SELECT e.*, t.team_name,
               COALESCE(gv.n, 0) AS given_count,
               COALESCE(rc.n, 0) AS received_count
        FROM employees e
        LEFT JOIN teams t ON e.team_id = t.team_id
        LEFT JOIN (
            SELECT s.sender_id AS id, COUNT(*) AS n FROM shoutouts s
            WHERE {where} AND s.kind != 'SLT' GROUP BY s.sender_id
        ) gv ON gv.id = e.employee_id
        LEFT JOIN (
            SELECT sr.recipient_id AS id, COUNT(*) AS n
            FROM shoutout_recipients sr JOIN shoutouts s ON s.id = sr.shoutout_id
            WHERE {where} GROUP BY sr.recipient_id
        ) rc ON rc.id = e.employee_id
    """
    return sql, params + params


def _user_stats_dto(row):
    """AdminUserDto plus the shout-out counts for the requested period."""
    return {**admin_user_dto(row), "givenCount": row["given_count"], "receivedCount": row["received_count"]}


@admin_bp.route("/api/admin/users", methods=["GET"])
@require_admin
def list_users():
    q = (request.args.get("q") or "").strip()
    date_from, date_to, error = read_date_range()
    if error:
        return error
    select, params = _user_stats_select(date_from, date_to)
    conn = get_db()
    try:
        if q:
            pattern = _like(q)
            rows = conn.execute(
                select + """
                WHERE lower(e.employee_name) LIKE ? ESCAPE '\\'
                   OR lower(e.email_id) LIKE ? ESCAPE '\\'
                   OR lower(coalesce(e.job_title, '')) LIKE ? ESCAPE '\\'
                   OR lower(coalesce(t.team_name, '')) LIKE ? ESCAPE '\\'
                ORDER BY e.employee_name COLLATE NOCASE, e.employee_id
                LIMIT ?
                """,
                (*params, pattern, pattern, pattern, pattern, MAX_USERS),
            ).fetchall()
        else:
            rows = conn.execute(
                select + " ORDER BY e.employee_name COLLATE NOCASE, e.employee_id LIMIT ?",
                (*params, MAX_USERS),
            ).fetchall()
        return jsonify([_user_stats_dto(r) for r in rows]), 200
    finally:
        conn.close()


@admin_bp.route("/api/admin/users/<employee_id>", methods=["GET"])
@require_admin
def get_user(employee_id: str):
    """One person for the admin user page: the list row plus their points."""
    date_from, date_to, error = read_date_range()
    if error:
        return error
    select, params = _user_stats_select(date_from, date_to)
    conn = get_db()
    try:
        row = conn.execute(select + " WHERE e.employee_id = ?", (*params, employee_id)).fetchone()
        if not row:
            return make_error("NOT_FOUND", f"Employee {employee_id} not found.", 404)
        return jsonify({**_user_stats_dto(row), "points": calculate_points_for_employee(conn, employee_id)}), 200
    finally:
        conn.close()


@admin_bp.route("/api/admin/users/<employee_id>", methods=["PATCH"])
@require_admin
def update_user_status(employee_id: str):
    body, error = read_json_object()
    if error:
        return error
    status = body.get("status")
    if status not in USER_STATUSES:
        return make_error("VALIDATION_FAILED", "'status' must be ACTIVE or SUSPENDED.", 400)

    actor_id = g.user["employeeId"]
    if employee_id == actor_id and status == "SUSPENDED":
        return make_error("FORBIDDEN", "You can't suspend yourself.", 403)

    conn = get_db()
    try:
        row = conn.execute(_USER_SELECT + " WHERE e.employee_id = ?", (employee_id,)).fetchone()
        if not row:
            return make_error("NOT_FOUND", f"Employee {employee_id} not found.", 404)
        if row["status"] == "INACTIVE":
            return make_error(
                "VALIDATION_FAILED",
                "This person has left Sandoz, so their account can't be suspended or reinstated.",
                400,
            )

        before = admin_user_dto(row)
        if before["status"] == status:
            return jsonify(before), 200  # nothing changed, nothing to audit

        conn.execute(
            "UPDATE employees SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE employee_id = ?",
            (status, employee_id),
        )
        after = admin_user_dto(conn.execute(_USER_SELECT + " WHERE e.employee_id = ?", (employee_id,)).fetchone())
        action = "USER_SUSPENDED" if status == "SUSPENDED" else "USER_REINSTATED"
        record_audit(conn, actor_id, action, "USER", employee_id,
                     before={"status": before["status"]}, after={"status": after["status"]})
        conn.commit()
        return jsonify(after), 200
    finally:
        conn.close()


# ───── Audit log (requirement 10) ─────

AUDIT_PAGE_SIZE = 20
AUDIT_MAX_PAGE_SIZE = 100
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _iso(timestamp: str) -> str:
    """SQLite CURRENT_TIMESTAMP ('YYYY-MM-DD HH:MM:SS', UTC) -> ISO 8601 with Z."""
    if not timestamp or "T" in timestamp:
        return timestamp
    return timestamp.replace(" ", "T") + "Z"


def _json_or_raw(value):
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _encode_cursor(created_at: str, row_id: int) -> str:
    """A4: the cursor is an opaque base64 string of <sortValue>|<id>."""
    return base64.urlsafe_b64encode(f"{created_at}|{row_id}".encode()).decode()


def _decode_cursor(cursor: str):
    created_at, row_id = base64.urlsafe_b64decode(cursor.encode()).decode().rsplit("|", 1)
    return created_at, int(row_id)


@admin_bp.route("/api/admin/audit", methods=["GET"])
@require_admin
def list_audit_events():
    args = request.args
    action = (args.get("action") or "").strip()
    actor_id = (args.get("actorId") or "").strip()
    date_from = (args.get("from") or "").strip()
    date_to = (args.get("to") or "").strip()
    cursor = (args.get("cursor") or "").strip()

    if action and action not in AUDIT_ACTIONS:
        return make_error("VALIDATION_FAILED", f"Unknown action '{action}'.", 400)
    for name, value in (("from", date_from), ("to", date_to)):
        if value and not _DATE.match(value):
            return make_error("VALIDATION_FAILED", f"'{name}' must be a date like 2026-11-16.", 400)
    try:
        limit = int(args.get("limit", AUDIT_PAGE_SIZE))
    except ValueError:
        return make_error("VALIDATION_FAILED", "'limit' must be a number.", 400)
    limit = max(1, min(limit, AUDIT_MAX_PAGE_SIZE))

    where, params = [], []
    if action:
        where.append("action = ?")
        params.append(action)
    if actor_id:
        where.append("actor_id = ?")
        params.append(actor_id)
    if date_from:  # calendar dates are UTC, inclusive at both ends
        where.append("date(created_at) >= ?")
        params.append(date_from[:10])
    if date_to:
        where.append("date(created_at) <= ?")
        params.append(date_to[:10])
    if cursor:
        try:
            cursor_at, cursor_id = _decode_cursor(cursor)
        except (ValueError, binascii.Error, UnicodeDecodeError):
            return make_error("VALIDATION_FAILED", "Invalid cursor.", 400)
        where.append("(created_at < ? OR (created_at = ? AND id < ?))")
        params.extend([cursor_at, cursor_at, cursor_id])

    conn = get_db()
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'audit_events'"
        ).fetchone()
        if not table:  # TODO: remove once the audit_events table is on main
            return jsonify({"items": [], "nextCursor": None}), 200

        sql = "SELECT * FROM audit_events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        rows = conn.execute(sql, (*params, limit + 1)).fetchall()  # one extra row = there's a next page

        has_more = len(rows) > limit
        rows = rows[:limit]

        # Resolve every actor with one query; actors not in the directory (guests) stay null.
        actor_ids = sorted({r["actor_id"] for r in rows})
        actors = {}
        if actor_ids:
            marks = ",".join("?" for _ in actor_ids)
            for e in conn.execute(_USER_SELECT + f" WHERE e.employee_id IN ({marks})", actor_ids).fetchall():
                actors[e["employee_id"]] = employee_summary(e)

        items = [
            {
                "id": r["id"],
                "actor": actors.get(r["actor_id"]),
                "action": r["action"],
                "targetType": r["target_type"],
                "targetId": r["target_id"],
                "before": _json_or_raw(r["before"]),
                "after": _json_or_raw(r["after"]),
                "createdAt": _iso(r["created_at"]),
            }
            for r in rows
        ]
        next_cursor = _encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if has_more else None
        return jsonify({"items": items, "nextCursor": next_cursor}), 200
    finally:
        conn.close()


# ───── Posts: moderation ─────

VISIBILITIES = {"VISIBLE", "HIDDEN", "DELETED"}
SHOUTOUT_PAGE_SIZE = 20
SHOUTOUT_MAX_PAGE_SIZE = 50
VISIBILITY_AUDIT = {"HIDDEN": "SHOUTOUT_HIDDEN", "VISIBLE": "SHOUTOUT_UNHIDDEN", "DELETED": "SHOUTOUT_DELETED"}


def _allowed_move(current: str, wanted: str) -> bool:
    """HIDDEN <-> VISIBLE, and either can become DELETED. DELETED is final."""
    if current == "DELETED" or current == wanted:
        return False
    return wanted == "DELETED" or {current, wanted} == {"VISIBLE", "HIDDEN"}


@admin_bp.route("/api/admin/shoutouts", methods=["GET"])
@require_admin
def list_admin_shoutouts():
    visibility = (request.args.get("visibility") or "").strip().upper()
    q = (request.args.get("q") or "").strip()
    cursor = (request.args.get("cursor") or "").strip()
    if visibility and visibility not in VISIBILITIES:
        return make_error("VALIDATION_FAILED", "'visibility' must be VISIBLE, HIDDEN or DELETED.", 400)
    try:
        limit = max(1, min(int(request.args.get("limit", SHOUTOUT_PAGE_SIZE)), SHOUTOUT_MAX_PAGE_SIZE))
    except ValueError:
        return make_error("VALIDATION_FAILED", "'limit' must be a number.", 400)

    where, params = [], []
    if visibility:
        where.append("s.visibility = ?")
        params.append(visibility)
    if q:
        # Text search over the message, the principle and every person on the post.
        pattern = _like(q)
        where.append(
            "(lower(s.reason) LIKE ? ESCAPE '\\' OR lower(s.impact) LIKE ? ESCAPE '\\'"
            " OR lower(p.name) LIKE ? ESCAPE '\\' OR lower(se.employee_name) LIKE ? ESCAPE '\\'"
            " OR EXISTS (SELECT 1 FROM shoutout_recipients sr"
            " JOIN employees re ON re.employee_id = sr.recipient_id"
            " WHERE sr.shoutout_id = s.id AND lower(re.employee_name) LIKE ? ESCAPE '\\'))"
        )
        params.extend([pattern] * 5)

    # between=E0005,E0013: posts either of the two sent with the other among the recipients.
    between = (request.args.get("between") or "").strip()
    if between:
        pair = [p.strip() for p in between.split(",") if p.strip()]
        if len(pair) != 2 or pair[0] == pair[1]:
            return make_error("VALIDATION_FAILED", "'between' must be two different employee IDs, e.g. E0005,E0013.", 400)
        where.append(
            "((s.sender_id = ? AND EXISTS (SELECT 1 FROM shoutout_recipients x WHERE x.shoutout_id = s.id AND x.recipient_id = ?))"
            " OR (s.sender_id = ? AND EXISTS (SELECT 1 FROM shoutout_recipients x WHERE x.shoutout_id = s.id AND x.recipient_id = ?)))"
        )
        params.extend([pair[0], pair[1], pair[1], pair[0]])

    month = (request.args.get("month") or "").strip()
    if month:
        if not _MONTH.match(month):
            return make_error("VALIDATION_FAILED", "'month' must look like 2026-11.", 400)
        where.append("substr(s.created_at, 1, 7) = ?")
        params.append(month)

    # kind=SLT: only shout-outs posted on the Senior Leadership Team's behalf.
    kind = (request.args.get("kind") or "").strip().upper()
    if kind:
        if kind not in SHOUTOUT_KINDS:
            return make_error("VALIDATION_FAILED", "'kind' must be STANDARD or SLT.", 400)
        where.append("s.kind = ?")
        params.append(kind)

    # employeeId=E0005: every post that person sent or received (the admin user page).
    employee_id = (request.args.get("employeeId") or "").strip()
    if employee_id:
        where.append(
            "(s.sender_id = ? OR EXISTS (SELECT 1 FROM shoutout_recipients x"
            " WHERE x.shoutout_id = s.id AND x.recipient_id = ?))"
        )
        params.extend([employee_id, employee_id])

    conn = get_db()
    try:
        if cursor:
            try:
                created_at, row_id = decode_cursor(cursor, 2)
            except ShoutoutError as e:
                return make_error(e.code, e.message, e.status_code)
            where.append("(s.created_at, s.id) < (?, ?)")
            params.extend([created_at, row_id])

        sql = _SHOUTOUT_SELECT
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY s.created_at DESC, s.id DESC LIMIT ?"
        rows = conn.execute(sql, (*params, limit + 1)).fetchall()  # one extra row = there's a next page
        page = rows[:limit]
        next_cursor = encode_cursor([page[-1]["created_at"], page[-1]["id"]]) if len(rows) > limit else None
        return jsonify({"items": _build_dtos(conn, page, g.user["employeeId"]), "nextCursor": next_cursor}), 200
    finally:
        conn.close()


@admin_bp.route("/api/admin/slt-shoutouts", methods=["POST"])
@require_admin
def create_slt_shoutout():
    """
    An SLT shout-out: the admin posts it on the Senior Leadership Team's behalf, and the feed
    shows it in gold as from the leadership team. Same body and checks as POST /api/shoutouts.
    The people recognised get their usual points; the admin gets none for posting it.
    """
    conn = get_db()
    try:
        created = create_shoutout(conn, g.user, request.get_json(silent=True), kind="SLT")
        return jsonify(created), 201
    except ShoutoutError as e:
        return make_error(e.code, e.message, e.status_code)
    finally:
        conn.close()


@admin_bp.route("/api/admin/shoutouts/<int:shoutout_id>", methods=["GET"])
@require_admin
def get_admin_shoutout(shoutout_id: int):
    """One post in any visibility, for the admin "View shout-out" page."""
    conn = get_db()
    try:
        row = conn.execute(_SHOUTOUT_SELECT + " WHERE s.id = ?", (shoutout_id,)).fetchone()
        if not row:
            return make_error("NOT_FOUND", f"Shout-out {shoutout_id} not found.", 404)
        return jsonify(_build_dtos(conn, [row], g.user["employeeId"])[0]), 200
    finally:
        conn.close()


@admin_bp.route("/api/admin/shoutouts/<int:shoutout_id>", methods=["PATCH"])
@require_admin
def update_shoutout_visibility(shoutout_id: int):
    body, error = read_json_object()
    if error:
        return error
    wanted = body.get("visibility")
    if wanted not in VISIBILITIES:
        return make_error("VALIDATION_FAILED", "'visibility' must be VISIBLE, HIDDEN or DELETED.", 400)

    conn = get_db()
    try:
        row = conn.execute(_SHOUTOUT_SELECT + " WHERE s.id = ?", (shoutout_id,)).fetchone()
        if not row:
            return make_error("NOT_FOUND", f"Shout-out {shoutout_id} not found.", 404)
        current = row["visibility"]
        if current == wanted:
            return jsonify(_build_dtos(conn, [row], g.user["employeeId"])[0]), 200  # nothing to do or audit
        if not _allowed_move(current, wanted):
            return make_error("VALIDATION_FAILED", f"A {current} post can't be made {wanted}. Deleting is final.", 400)

        conn.execute("UPDATE shoutouts SET visibility = ? WHERE id = ?", (wanted, shoutout_id))
        record_audit(conn, g.user["employeeId"], VISIBILITY_AUDIT[wanted], "SHOUTOUT", shoutout_id,
                     before={"visibility": current}, after={"visibility": wanted})
        conn.commit()
        updated = conn.execute(_SHOUTOUT_SELECT + " WHERE s.id = ?", (shoutout_id,)).fetchone()
        return jsonify(_build_dtos(conn, [updated], g.user["employeeId"])[0]), 200
    finally:
        conn.close()


# ───── Reciprocal alerts ─────

_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
RECIPROCAL_THRESHOLD = 3


def current_utc_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


@admin_bp.route("/api/admin/alerts/reciprocal", methods=["GET"])
@require_admin
def reciprocal_alerts():
    """
    Pairs who shouted each other out at least 3 times in a calendar month (UTC).
    aToB / bToA count recipient rows on VISIBLE posts; reciprocalTimes = min(aToB, bToA).
    """
    month = (request.args.get("month") or current_utc_month()).strip()
    if not _MONTH.match(month):
        return make_error("VALIDATION_FAILED", "'month' must look like 2026-11.", 400)

    conn = get_db()
    try:
        pairs = conn.execute(
            """
            WITH directed AS (
                SELECT s.sender_id AS a, sr.recipient_id AS b, COUNT(*) AS n
                FROM shoutouts s JOIN shoutout_recipients sr ON sr.shoutout_id = s.id
                WHERE s.visibility = 'VISIBLE' AND s.kind != 'SLT' AND substr(s.created_at, 1, 7) = ?
                GROUP BY s.sender_id, sr.recipient_id
            )
            SELECT x.a, x.b, x.n AS a_to_b, y.n AS b_to_a, min(x.n, y.n) AS times
            FROM directed x JOIN directed y ON y.a = x.b AND y.b = x.a
            WHERE x.a < x.b AND min(x.n, y.n) >= ?
            ORDER BY times DESC, x.a, x.b
            """,
            (month, RECIPROCAL_THRESHOLD),
        ).fetchall()

        ids = sorted({p["a"] for p in pairs} | {p["b"] for p in pairs})
        people = {}
        if ids:
            marks = ",".join("?" for _ in ids)
            for e in conn.execute(_USER_SELECT + f" WHERE e.employee_id IN ({marks})", ids).fetchall():
                people[e["employee_id"]] = employee_summary(e)

        return jsonify([
            {"month": month, "a": people[p["a"]], "b": people[p["b"]],
             "aToB": p["a_to_b"], "bToA": p["b_to_a"], "reciprocalTimes": p["times"]}
            for p in pairs if p["a"] in people and p["b"] in people
        ]), 200
    finally:
        conn.close()
