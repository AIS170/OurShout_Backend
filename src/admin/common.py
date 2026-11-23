"""
Shared helpers for Nathan's routes (admin, leaderboard, reports).

- make_error / read_json_object: the A4 error shape and request-body parsing.
- read_date_range / post_filter: the from/to query parameters and the VISIBLE-posts filter.
- *_dto: turn database rows into the JSON shapes from shared/types.ts.
- record_audit: insert one audit_events row (requirement 18).
"""
import json
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from flask import jsonify, request

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# The only allowed values of AuditEvent.action (A3), plus the three auction actions.
AUDIT_ACTIONS = {
    "SHOUTOUT_CREATED", "SHOUTOUT_EDITED", "SHOUTOUT_HIDDEN", "SHOUTOUT_UNHIDDEN",
    "SHOUTOUT_DELETED", "PRINCIPLE_CREATED", "PRINCIPLE_UPDATED", "USER_SUSPENDED",
    "USER_REINSTATED", "EMAIL_RETRIED", "LOGIN_REJECTED",
    "AUCTION_ITEM_CREATED", "AUCTION_ITEM_REMOVED", "AUCTION_BID_PLACED",
    "AUCTION_BID_WITHDRAWN",
}


def make_error(code: str, message: str, status_code: int):
    """Error response in the A4 shape: { "error": { "code", "message" } }."""
    return jsonify({"error": {"code": code, "message": message}}), status_code


def read_json_object() -> Tuple[Optional[Dict[str, Any]], Any]:
    """Returns (body, None) for a JSON object body, or (None, error_response)."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None, make_error("VALIDATION_FAILED", "Request body must be a JSON object.", 400)
    return body, None


# ───── Date range (from / to are calendar dates, YYYY-MM-DD, UTC, inclusive) ─────

def read_date_range() -> Tuple[Optional[str], Optional[str], Optional[Any]]:
    """Returns (from, to, error_response). Dates are validated and from <= to."""
    date_from = (request.args.get("from") or "").strip() or None
    date_to = (request.args.get("to") or "").strip() or None
    for name, value in (("from", date_from), ("to", date_to)):
        if value:
            try:
                if not _DATE.match(value):
                    raise ValueError
                date.fromisoformat(value)
            except ValueError:
                return None, None, make_error("VALIDATION_FAILED", f"'{name}' must be a date like 2026-11-19.", 400)
    if date_from and date_to and date_from > date_to:
        return None, None, make_error("VALIDATION_FAILED", "'from' must be on or before 'to'.", 400)
    return date_from, date_to, None


def post_filter(date_from: Optional[str], date_to: Optional[str], kindness: bool = False, alias: str = "s"):
    """WHERE clause + params for VISIBLE posts in the range."""
    where = [f"{alias}.visibility = 'VISIBLE'"]
    params: List[Any] = []
    if date_from:
        where.append(f"substr({alias}.created_at, 1, 10) >= ?")
        params.append(date_from)
    if date_to:
        where.append(f"substr({alias}.created_at, 1, 10) <= ?")
        params.append(date_to)
    if kindness:
        where.append(f"{alias}.act_of_kindness = 1")
    return " AND ".join(where), params


# ───── DTOs (shapes from shared/types.ts) ─────

def employee_summary(row) -> Dict[str, Any]:
    """EmployeeSummary, from an employees row joined with teams (team_name)."""
    return {
        "employeeId": row["employee_id"],
        "name": row["employee_name"],
        "email": row["email_id"],
        "jobTitle": row["job_title"],
        "teamId": row["team_id"],
        "teamName": row["team_name"] or "",
        "country": row["country"] or "AU",
    }


def admin_user_dto(row) -> Dict[str, Any]:
    """
    AdminUserDto. The employees table keeps one status column
    (ACTIVE | SUSPENDED | INACTIVE), so INACTIVE (left Sandoz) maps to
    isActive = false, and the app status is then ACTIVE.
    """
    db_status = row["status"] or "ACTIVE"
    return {
        **employee_summary(row),
        "isActive": db_status != "INACTIVE",
        "role": row["role"] or "EMPLOYEE",
        "status": "SUSPENDED" if db_status == "SUSPENDED" else "ACTIVE",
    }


# ───── Audit ─────

def record_audit(conn, actor_id: str, action: str, target_type: str, target_id: str,
                 before: Optional[Dict[str, Any]] = None,
                 after: Optional[Dict[str, Any]] = None) -> None:
    """
    Inserts one audit row inside the caller's transaction (the caller commits).
    Audit rows are only ever inserted, never updated or deleted.

    TODO: switch to the shared record_audit() once the audit service and the
    audit_events table are on main. Until the table exists this is a no-op,
    the same approach as record_login_rejected_audit() in src/auth/service.py.
    """
    if action not in AUDIT_ACTIONS:
        raise ValueError(f"Unknown audit action: {action}")
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'audit_events'"
    ).fetchone()
    if not table:
        return
    conn.execute(
        """
        INSERT INTO audit_events (actor_id, action, target_type, target_id, before, after, created_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            actor_id, action, target_type, str(target_id),
            json.dumps(before) if before is not None else None,
            json.dumps(after) if after is not None else None,
        ),
    )
