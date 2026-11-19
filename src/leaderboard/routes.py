"""
Leaderboards (owner: Nathan). Any signed-in user.

  GET /api/leaderboard?period=month|all  -> LeaderboardDto

Two top-3 boards for the caller's country:
  mostShoutedOut      recipient rows: a team shout-out counts once for each person on it
  mostShoutOutsGiven  posts sent: a team shout-out counts once for its sender
Only VISIBLE posts count, so hidden or deleted posts drop out. Ties are broken by name.
"month" is the current calendar month in UTC.
"""
from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request

from database import get_db
from src.admin.common import employee_summary, make_error
from src.auth.middleware import require_auth

leaderboard_bp = Blueprint("leaderboard", __name__)

PERIODS = {"month", "all"}
TOP_N = 3


def _board(conn, count_sql: str, params) -> list:
    """count_sql selects (employee_id, n); returns the top 3 as LeaderboardEntry dicts."""
    rows = conn.execute(
        f"""
        SELECT e.*, t.team_name, c.n
        FROM ({count_sql}) c
        JOIN employees e ON e.employee_id = c.employee_id
        LEFT JOIN teams t ON t.team_id = e.team_id
        ORDER BY c.n DESC, e.employee_name COLLATE NOCASE, e.employee_id
        LIMIT ?
        """,
        (*params, TOP_N),
    ).fetchall()
    return [{"employee": employee_summary(r), "count": r["n"]} for r in rows]


@leaderboard_bp.route("/api/leaderboard", methods=["GET"])
@require_auth
def get_leaderboard():
    period = (request.args.get("period") or "month").strip().lower()
    if period not in PERIODS:
        return make_error("VALIDATION_FAILED", "'period' must be 'month' or 'all'.", 400)

    month = datetime.now(timezone.utc).strftime("%Y-%m") if period == "month" else None
    where = "s.visibility = 'VISIBLE' AND s.country = ?"
    params = [g.user["country"]]
    if month:
        where += " AND substr(s.created_at, 1, 7) = ?"
        params.append(month)

    conn = get_db()
    try:
        shouted_out = _board(
            conn,
            f"""SELECT sr.recipient_id AS employee_id, COUNT(*) AS n
                FROM shoutout_recipients sr JOIN shoutouts s ON s.id = sr.shoutout_id
                WHERE {where} GROUP BY sr.recipient_id""",
            params,
        )
        given = _board(
            conn,
            f"""SELECT s.sender_id AS employee_id, COUNT(*) AS n
                FROM shoutouts s WHERE {where} GROUP BY s.sender_id""",
            params,
        )
        return jsonify({
            "period": period,
            "month": month,
            "mostShoutedOut": shouted_out,
            "mostShoutOutsGiven": given,
        }), 200
    finally:
        conn.close()
