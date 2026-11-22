"""
Reports (owner: Nathan). Requirement 10. VISIBLE posts only; no privacy thresholds.

  GET /api/admin/reports/summary?from=&to=&kindness=     -> ReportSummaryDto (A4 contract)
  GET /api/admin/reports/insights?from=&to=              -> ReportInsightsDto (new; to be added to shared/types.ts)
  GET /api/admin/reports/export.csv?from=&to=&kindness=  -> text/csv, one row per shout-out x recipient

Who sees what (src/reports/access.py):
  admins and the Senior Leadership Team   everything (scope ALL)
  a manager                               their team only (scope TEAM): the people who report
                                          directly to them

from / to are calendar dates (YYYY-MM-DD, UTC, inclusive). Leave both out for all time.
kindness=true limits the report or export to acts of kindness (certification evidence).
"By team" uses each person's current team: the backend doesn't store their team at post time.

An SLT shout-out is posted by an admin on the leadership team's behalf. It counts for the people
it recognises, but never on the giving side (top givers, giving teams, who gave, cross-team, flows).

In a TEAM report each figure means:
  total, byMonth, byPrinciple, byWeekday, kindness, likes, mostLiked, byCountry
                         posts a team member gave or received
  peopleRecognised, participation
                         team members only, out of the team's size
  crossTeam              share of the team's recognitions that went to people outside the team
  byTeam                 teams the team recognised most (given by members, by recipient's team)
  byGiverTeam            teams that recognised the team most (received by members, by sender's team)
  topReceivers, topGivers team members only
  teamFlows              empty (byTeam and byGiverTeam cover it)
  export.csv             rows where the sender or the recipient is a team member
"""
import csv
import io
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from flask import Blueprint, Response, g, jsonify, request

from database import get_db
from src.admin.common import employee_summary, post_filter, read_date_range
from src.reports.access import MEMBERS, ReportScope, require_reports_access

reports_bp = Blueprint("reports", __name__)

TOP_N = 5
WEEKDAYS = 7  # 0 = Monday ... 6 = Sunday

NOT_SLT = "s.kind != 'SLT'"


# ───── shared filtering ─────

def _today() -> date:
    return datetime.now(timezone.utc).date()


def _kindness_only() -> bool:
    return (request.args.get("kindness") or "").strip().lower() in ("true", "1", "yes")


def _scope_sql(scope: ReportScope) -> Dict[str, str]:
    """
    The SQL conditions that differ between an ALL report and a TEAM one. None takes parameters:
    the team's people are in the scope_members temp table (see ReportScope.attach).
      post       posts the report covers                                  (alias s)
      giver      recognitions counted on the giving side                  (alias s)
      receiver   recipient rows counted on the receiving side             (alias sr)
      by_team    recipient rows behind byTeam                             (aliases s, sr)
      by_giver   recipient rows behind byGiverTeam                        (aliases s, sr)
      people     the employees the participation figures are about        (alias e)
      crossed    a recipient row that crossed a team boundary             (aliases sr, se, re)
      csv_row    recipient rows in the export                             (aliases s, sr)
    """
    if not scope.is_team:
        return {
            "post": "1 = 1",
            "giver": NOT_SLT,
            "receiver": "1 = 1",
            "by_team": "1 = 1",
            "by_giver": NOT_SLT,
            "people": "1 = 1",
            "crossed": "se.team_id != re.team_id",
            "csv_row": "1 = 1",
        }
    gave = f"({NOT_SLT} AND s.sender_id IN {MEMBERS})"
    return {
        "post": f"""({gave} OR EXISTS (SELECT 1 FROM shoutout_recipients x
                     WHERE x.shoutout_id = s.id AND x.recipient_id IN {MEMBERS}))""",
        "giver": gave,
        "receiver": f"sr.recipient_id IN {MEMBERS}",
        "by_team": gave,
        "by_giver": f"({NOT_SLT} AND sr.recipient_id IN {MEMBERS})",
        "people": f"e.employee_id IN {MEMBERS}",
        "crossed": f"sr.recipient_id NOT IN {MEMBERS}",
        "csv_row": f"({gave} OR sr.recipient_id IN {MEMBERS})",
    }


def _effective_range(conn, date_from, date_to, where, params) -> Tuple[str, str]:
    """The dates the report actually covers: the request, or the first post .. today."""
    if not date_from:
        row = conn.execute(f"SELECT min(substr(s.created_at, 1, 10)) AS d FROM shoutouts s WHERE {where}", params).fetchone()
        date_from = row["d"] or _today().isoformat()
    return date_from, date_to or _today().isoformat()


def _months_between(first: str, last: str) -> List[str]:
    """Every 'YYYY-MM' from first to last inclusive, so the trend line has no gaps."""
    year, month = int(first[:4]), int(first[5:7])
    end = (int(last[:4]), int(last[5:7]))
    months = []
    while (year, month) <= end:
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return months


def _share(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


# ───── summary (A4 ReportSummaryDto) ─────

def _summary(conn, scope: ReportScope, date_from, date_to, kindness) -> Dict[str, Any]:
    where, params = post_filter(date_from, date_to, kindness)
    sql = _scope_sql(scope)
    posts = f"{where} AND {sql['post']}"
    eff_from, eff_to = _effective_range(conn, date_from, date_to, posts, params)

    totals = conn.execute(
        f"SELECT COUNT(*) AS total, COALESCE(SUM(s.act_of_kindness), 0) AS kind FROM shoutouts s WHERE {posts}", params
    ).fetchone()

    by_principle = conn.execute(
        f"""SELECT p.name, COUNT(s.id) AS n
            FROM principles p LEFT JOIN shoutouts s ON s.principle_id = p.id AND {posts}
            GROUP BY p.id HAVING n > 0 OR p.status = 'ACTIVE'
            ORDER BY n DESC, p.display_order, p.id""",
        params,
    ).fetchall()

    by_team = conn.execute(
        f"""SELECT e.team_id, t.team_name, COUNT(*) AS n
            FROM shoutouts s
            JOIN shoutout_recipients sr ON sr.shoutout_id = s.id
            JOIN employees e ON e.employee_id = sr.recipient_id
            LEFT JOIN teams t ON t.team_id = e.team_id
            WHERE {where} AND {sql['by_team']}
            GROUP BY e.team_id ORDER BY n DESC, t.team_name""",
        params,
    ).fetchall()

    by_country = conn.execute(
        f"SELECT s.country, COUNT(*) AS n FROM shoutouts s WHERE {posts} GROUP BY s.country ORDER BY n DESC, s.country",
        params,
    ).fetchall()

    month_counts = {
        r["m"]: r["n"]
        for r in conn.execute(
            f"SELECT substr(s.created_at, 1, 7) AS m, COUNT(*) AS n FROM shoutouts s WHERE {posts} GROUP BY m", params
        )
    }

    return {
        "from": eff_from,
        "to": eff_to,
        "total": totals["total"],
        "actsOfKindness": totals["kind"],
        "byPrinciple": [{"name": r["name"], "count": r["n"]} for r in by_principle],
        "byTeam": [{"teamId": r["team_id"], "teamName": r["team_name"] or "", "count": r["n"]} for r in by_team],
        "byCountry": [{"country": r["country"], "count": r["n"]} for r in by_country],
        "byMonth": [{"month": m, "count": month_counts.get(m, 0)} for m in _months_between(eff_from[:7], eff_to[:7])],
    }


@reports_bp.route("/api/admin/reports/summary", methods=["GET"])
@require_reports_access
def report_summary():
    date_from, date_to, error = read_date_range()
    if error:
        return error
    conn = get_db()
    try:
        g.report_scope.attach(conn)
        return jsonify(_summary(conn, g.report_scope, date_from, date_to, _kindness_only())), 200
    finally:
        conn.close()


# ───── insights (new ReportInsightsDto) ─────

def _top_people(conn, count_sql: str, params) -> List[Dict[str, Any]]:
    rows = conn.execute(
        f"""SELECT e.*, t.team_name, c.n FROM ({count_sql}) c
            JOIN employees e ON e.employee_id = c.employee_id
            LEFT JOIN teams t ON t.team_id = e.team_id
            ORDER BY c.n DESC, e.employee_name COLLATE NOCASE, e.employee_id LIMIT ?""",
        (*params, TOP_N),
    ).fetchall()
    return [{"employee": employee_summary(r), "count": r["n"]} for r in rows]


@reports_bp.route("/api/admin/reports/insights", methods=["GET"])
@require_reports_access
def report_insights():
    date_from, date_to, error = read_date_range()
    if error:
        return error
    scope: ReportScope = g.report_scope

    conn = get_db()
    try:
        scope.attach(conn)
        sql = _scope_sql(scope)
        where, params = post_filter(date_from, date_to)
        posts_where = f"{where} AND {sql['post']}"
        eff_from, eff_to = _effective_range(conn, date_from, date_to, posts_where, params)

        posts = conn.execute(
            f"""SELECT COUNT(*) AS total,
                       COALESCE(SUM(s.act_of_kindness), 0) AS kind,
                       COALESCE(SUM(s.recognition_type = 'TEAM'), 0) AS team_posts,
                       COALESCE(SUM(s.like_count), 0) AS likes
                FROM shoutouts s WHERE {posts_where}""",
            params,
        ).fetchone()
        total = posts["total"]

        # The same number of days just before `from` (only when a start date was asked for).
        previous = None
        if date_from:
            start = date.fromisoformat(eff_from)
            days = (date.fromisoformat(eff_to) - start).days + 1
            prev_from, prev_to = (start - timedelta(days=days)).isoformat(), (start - timedelta(days=1)).isoformat()
            pw, pp = post_filter(prev_from, prev_to)
            prev_total = conn.execute(
                f"SELECT COUNT(*) AS n FROM shoutouts s WHERE {pw} AND {sql['post']}", pp
            ).fetchone()["n"]
            previous = {"from": prev_from, "to": prev_to, "total": prev_total}

        # Participation among the people the report is about: every active employee
        # (status ACTIVE or SUSPENDED; INACTIVE = left), or the team's members.
        people = f"e.status != 'INACTIVE' AND {sql['people']}"
        active = conn.execute(f"SELECT COUNT(*) AS n FROM employees e WHERE {people}").fetchone()["n"]
        gave = conn.execute(
            f"""SELECT COUNT(DISTINCT s.sender_id) AS n FROM shoutouts s
                JOIN employees e ON e.employee_id = s.sender_id AND {people} WHERE {where} AND {NOT_SLT}""",
            params,
        ).fetchone()["n"]
        received = conn.execute(
            f"""SELECT COUNT(DISTINCT sr.recipient_id) AS n FROM shoutouts s
                JOIN shoutout_recipients sr ON sr.shoutout_id = s.id
                JOIN employees e ON e.employee_id = sr.recipient_id AND {people} WHERE {where}""",
            params,
        ).fetchone()["n"]
        either = conn.execute(
            f"""SELECT COUNT(*) AS n FROM (
                    SELECT s.sender_id AS id FROM shoutouts s WHERE {where} AND {NOT_SLT}
                    UNION
                    SELECT sr.recipient_id FROM shoutouts s JOIN shoutout_recipients sr ON sr.shoutout_id = s.id WHERE {where}
                ) p JOIN employees e ON e.employee_id = p.id AND {people}""",
            params + params,
        ).fetchone()["n"]

        # Recognitions given, and how many crossed a team boundary.
        rows = conn.execute(
            f"""SELECT COUNT(*) AS n, COALESCE(SUM({sql['crossed']}), 0) AS cross_team
                FROM shoutouts s
                JOIN shoutout_recipients sr ON sr.shoutout_id = s.id
                JOIN employees se ON se.employee_id = s.sender_id
                JOIN employees re ON re.employee_id = sr.recipient_id
                WHERE {where} AND {sql['giver']}""",
            params,
        ).fetchone()
        people_recognised = conn.execute(
            f"""SELECT COUNT(DISTINCT sr.recipient_id) AS n FROM shoutouts s
                JOIN shoutout_recipients sr ON sr.shoutout_id = s.id WHERE {where} AND {sql['receiver']}""",
            params,
        ).fetchone()["n"]

        most_liked = conn.execute(
            f"""SELECT s.id, s.like_count, s.created_at, s.kind, se.employee_name AS sender, p.name AS principle
                FROM shoutouts s JOIN employees se ON se.employee_id = s.sender_id
                JOIN principles p ON p.id = s.principle_id
                WHERE {posts_where} AND s.like_count > 0
                ORDER BY s.like_count DESC, s.created_at DESC, s.id DESC LIMIT 1""",
            params,
        ).fetchone()

        # SQLite %w: 0 = Sunday. Shift so 0 = Monday.
        weekday_counts = [0] * WEEKDAYS
        for r in conn.execute(
            f"SELECT CAST(strftime('%w', substr(s.created_at, 1, 19)) AS INTEGER) AS w, COUNT(*) AS n FROM shoutouts s WHERE {posts_where} GROUP BY w",
            params,
        ):
            weekday_counts[(r["w"] + 6) % 7] = r["n"]

        # Busiest routes between org teams. A team report shows byTeam and byGiverTeam instead.
        flows = [] if scope.is_team else conn.execute(
            f"""SELECT se.team_id AS from_id, st.team_name AS from_name,
                       re.team_id AS to_id, rt.team_name AS to_name, COUNT(*) AS n
                FROM shoutouts s
                JOIN shoutout_recipients sr ON sr.shoutout_id = s.id
                JOIN employees se ON se.employee_id = s.sender_id
                JOIN employees re ON re.employee_id = sr.recipient_id
                LEFT JOIN teams st ON st.team_id = se.team_id
                LEFT JOIN teams rt ON rt.team_id = re.team_id
                WHERE {where} AND {NOT_SLT} AND se.team_id != re.team_id
                GROUP BY se.team_id, re.team_id
                ORDER BY n DESC, st.team_name, rt.team_name LIMIT ?""",
            (*params, TOP_N),
        ).fetchall()

        # Recipient rows by the sender's current team: who did the recognising.
        by_giver_team = conn.execute(
            f"""SELECT se.team_id, st.team_name, COUNT(*) AS n
                FROM shoutouts s
                JOIN shoutout_recipients sr ON sr.shoutout_id = s.id
                JOIN employees se ON se.employee_id = s.sender_id
                LEFT JOIN teams st ON st.team_id = se.team_id
                WHERE {where} AND {sql['by_giver']}
                GROUP BY se.team_id ORDER BY n DESC, st.team_name""",
            params,
        ).fetchall()

        return jsonify({
            "from": eff_from,
            "to": eff_to,
            "scope": {"kind": scope.kind, "teamSize": scope.team_size},
            "total": total,
            "previousPeriod": previous,
            "peopleRecognised": people_recognised,
            "participation": {
                "activeEmployees": active,
                "gave": gave,
                "received": received,
                "involved": either,
                "neverRecognised": active - received,
                "involvedShare": _share(either, active),
            },
            "crossTeam": {"recipientRows": rows["n"], "crossTeamRows": rows["cross_team"],
                          "share": _share(rows["cross_team"], rows["n"])},
            "teamShoutouts": {"count": posts["team_posts"], "share": _share(posts["team_posts"], total)},
            "kindness": {"count": posts["kind"], "share": _share(posts["kind"], total)},
            "likes": {"total": posts["likes"], "averagePerPost": round(posts["likes"] / total, 2) if total else 0.0},
            "mostLiked": {
                "shoutoutId": most_liked["id"],
                "senderName": "Senior Leadership Team" if most_liked["kind"] == "SLT" else most_liked["sender"],
                "principleName": most_liked["principle"], "likeCount": most_liked["like_count"],
                "createdAt": most_liked["created_at"],
            } if most_liked else None,
            "topGivers": _top_people(
                conn, f"SELECT s.sender_id AS employee_id, COUNT(*) AS n FROM shoutouts s WHERE {where} AND {sql['giver']} GROUP BY s.sender_id", params),
            "topReceivers": _top_people(
                conn, f"""SELECT sr.recipient_id AS employee_id, COUNT(*) AS n FROM shoutouts s
                          JOIN shoutout_recipients sr ON sr.shoutout_id = s.id
                          WHERE {where} AND {sql['receiver']} GROUP BY sr.recipient_id""", params),
            "byWeekday": [{"weekday": i, "count": weekday_counts[i]} for i in range(WEEKDAYS)],
            "teamFlows": [
                {"fromTeamId": f["from_id"], "fromTeamName": f["from_name"] or "",
                 "toTeamId": f["to_id"], "toTeamName": f["to_name"] or "", "count": f["n"]}
                for f in flows
            ],
            "byGiverTeam": [
                {"teamId": r["team_id"], "teamName": r["team_name"] or "", "count": r["n"]} for r in by_giver_team
            ],
        }), 200
    finally:
        conn.close()


# ───── CSV export ─────

CSV_COLUMNS = [
    "shoutout_id", "created_at", "recognition_type", "sender_id", "sender_name", "sender_team",
    "recipient_id", "recipient_name", "recipient_team", "principle", "reason", "impact",
    "act_of_kindness", "like_count", "kind",
]
# B3: a value starting with = + - @ gets a leading ' so spreadsheets don't run it as a formula.
# Tab and carriage return are guarded too (the OWASP CSV-injection list).
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


@reports_bp.route("/api/admin/reports/export.csv", methods=["GET"])
@require_reports_access
def report_export_csv():
    date_from, date_to, error = read_date_range()
    if error:
        return error
    kindness = _kindness_only()
    scope: ReportScope = g.report_scope

    conn = get_db()
    try:
        scope.attach(conn)
        where, params = post_filter(date_from, date_to, kindness)
        rows = conn.execute(
            f"""SELECT s.id, s.created_at, s.recognition_type, s.sender_id, se.employee_name AS sender_name,
                       st.team_name AS sender_team, sr.recipient_id, re.employee_name AS recipient_name,
                       rt.team_name AS recipient_team, p.name AS principle, s.reason, s.impact,
                       s.act_of_kindness, s.like_count, s.kind
                FROM shoutouts s
                JOIN shoutout_recipients sr ON sr.shoutout_id = s.id
                JOIN employees se ON se.employee_id = s.sender_id
                JOIN employees re ON re.employee_id = sr.recipient_id
                LEFT JOIN teams st ON st.team_id = se.team_id
                LEFT JOIN teams rt ON rt.team_id = re.team_id
                JOIN principles p ON p.id = s.principle_id
                WHERE {where} AND {_scope_sql(scope)['csv_row']}
                ORDER BY s.created_at, s.id, re.employee_name COLLATE NOCASE""",
            params,
        ).fetchall()
    finally:
        conn.close()

    out = io.StringIO()
    writer = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for r in rows:
        writer.writerow([csv_safe(v) for v in (
            r["id"], r["created_at"], r["recognition_type"], r["sender_id"], r["sender_name"], r["sender_team"],
            r["recipient_id"], r["recipient_name"], r["recipient_team"], r["principle"], r["reason"], r["impact"],
            "true" if r["act_of_kindness"] else "false", r["like_count"], r["kind"],
        )])

    name = "ourshout-kindness" if kindness else "ourshout-shoutouts"
    if date_from or date_to:
        name += f"-{date_from or 'start'}-to-{date_to or _today().isoformat()}"
    # The BOM makes Excel open the file as UTF-8, so names and quotes display correctly.
    return Response(
        "﻿" + out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
    )
