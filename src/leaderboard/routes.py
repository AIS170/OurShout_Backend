"""
Leaderboards (owner: Nathan). Any signed-in user.

  GET /api/leaderboard?period=month|all  -> LeaderboardDto

Two top-3 boards for the caller's country:
  mostShoutedOut      recipient rows: a team shout-out counts once for each person on it
  mostShoutOutsGiven  posts sent: a team shout-out counts once for its sender (SLT shout-outs don't count)
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


def _slt_board(conn, where: str, params: list) -> list:
    """Returns employees recognized by the Senior Leadership Team (kind == 'SLT')."""
    slt_where = f"{where} AND s.kind = 'SLT'"
    rows = conn.execute(
        f"""
        SELECT e.*, t.team_name, COUNT(DISTINCT s.id) AS n,
               MAX(s.created_at) AS latest_created_at,
               (
                   SELECT p2.name FROM shoutouts s2
                   JOIN principles p2 ON p2.id = s2.principle_id
                   JOIN shoutout_recipients sr2 ON sr2.shoutout_id = s2.id
                   WHERE sr2.recipient_id = e.employee_id AND s2.kind = 'SLT' AND s2.visibility = 'VISIBLE'
                   ORDER BY s2.created_at DESC LIMIT 1
               ) AS latest_principle,
               (
                   SELECT s3.reason FROM shoutouts s3
                   JOIN shoutout_recipients sr3 ON sr3.shoutout_id = s3.id
                   WHERE sr3.recipient_id = e.employee_id AND s3.kind = 'SLT' AND s3.visibility = 'VISIBLE'
                   ORDER BY s3.created_at DESC LIMIT 1
               ) AS latest_reason
        FROM shoutout_recipients sr
        JOIN shoutouts s ON s.id = sr.shoutout_id
        JOIN employees e ON e.employee_id = sr.recipient_id
        LEFT JOIN teams t ON t.team_id = e.team_id
        WHERE {slt_where}
        GROUP BY e.employee_id
        ORDER BY n DESC, latest_created_at DESC, e.employee_name COLLATE NOCASE
        """,
        params,
    ).fetchall()

    return [
        {
            "employee": employee_summary(r),
            "count": r["n"],
            "latestPrinciple": r["latest_principle"] or "",
            "latestReason": r["latest_reason"] or "",
            "latestCreatedAt": r["latest_created_at"] or "",
        }
        for r in rows
    ]


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
            # SLT shout-outs are posted by an admin on the leadership team's behalf: not "given" by them.
            f"""SELECT s.sender_id AS employee_id, COUNT(*) AS n
                FROM shoutouts s WHERE {where} AND s.kind != 'SLT' GROUP BY s.sender_id""",
            params,
        )
        slt_honorees = _slt_board(conn, where, params)
        return jsonify({
            "period": period,
            "month": month,
            "mostShoutedOut": shouted_out,
            "mostShoutOutsGiven": given,
            "sltHonorees": slt_honorees,
        }), 200
    finally:
        conn.close()


@leaderboard_bp.route("/api/leaderboard/slt", methods=["GET"])
@require_auth
def get_slt_leaderboard():
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
        honorees = _slt_board(conn, where, params)
        return jsonify({
            "period": period,
            "month": month,
            "honorees": honorees,
        }), 200
    finally:
        conn.close()
