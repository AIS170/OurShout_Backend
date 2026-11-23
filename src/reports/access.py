"""
Who may open Reports, and how much they see (owner: Nathan).

  ADMIN        everything: every manager and employee  -> scope ALL
  a manager    only the people who report directly     -> scope TEAM
               to them (not the people under those)
  anyone else  403

A manager is anyone with people reporting to them. That includes the Senior Leadership Team:
a director or head gets a report on their own direct reports, the same as any other manager.

The scope always comes from who is signed in, never from the request, so a manager can't ask
for another team's report. /api/me tells the web app which of these applies (reportsAccess).
"""
from functools import wraps
from typing import List

from flask import g

from src.auth.middleware import make_error, require_auth

# The people a TEAM report covers. A temp table (one per connection, so one per request) keeps
# every query a plain "IN (SELECT employee_id FROM scope_members)".
MEMBERS = "(SELECT employee_id FROM scope_members)"


def direct_reports(conn, manager_id: str) -> List[str]:
    """
    The people whose manager is this person. Leavers are left out.
    Direct reports only: a manager of managers doesn't see the people under those managers
    (only admins see everyone).
    """
    rows = conn.execute(
        """
        SELECT employee_id FROM employees
        WHERE manager_id = ? AND status != 'INACTIVE' AND employee_id != ?
        ORDER BY employee_id
        """,
        (manager_id, manager_id),
    ).fetchall()
    return [r["employee_id"] for r in rows]


class ReportScope:
    """What the signed-in person's report covers."""

    def __init__(self, kind: str, manager_id: str):
        self.kind = kind  # ALL | TEAM
        self.manager_id = manager_id
        self.team_size = None

    @property
    def is_team(self) -> bool:
        return self.kind == "TEAM"

    def attach(self, conn) -> None:
        """Call once on the request's connection before running report queries."""
        if not self.is_team:
            return
        members = direct_reports(conn, self.manager_id)
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS scope_members (employee_id TEXT PRIMARY KEY)")
        conn.execute("DELETE FROM scope_members")
        conn.executemany("INSERT INTO scope_members (employee_id) VALUES (?)", [(m,) for m in members])
        self.team_size = len(members)


def require_reports_access(f):
    """Admins (everything) or managers (their direct reports). Puts the scope on g.report_scope."""
    @wraps(f)
    @require_auth
    def decorated(*args, **kwargs):
        access = g.user.get("reportsAccess")
        if access not in ("ALL", "TEAM"):
            return make_error("FORBIDDEN", "Reports are for admins and managers.", 403)
        g.report_scope = ReportScope(access, g.user["employeeId"])
        return f(*args, **kwargs)

    return decorated
