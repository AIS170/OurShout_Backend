"""
Shared helpers for Nathan's routes (admin, leaderboard, reports).

- make_error / read_json_object: the A4 error shape and request-body parsing.
- *_dto: turn database rows into the JSON shapes from shared/types.ts.
- record_audit: insert one audit_events row (requirement 18).
"""
import json
from typing import Any, Dict, Optional, Tuple

from flask import jsonify, request

# The only allowed values of AuditEvent.action (A3).
AUDIT_ACTIONS = {
    "SHOUTOUT_CREATED", "SHOUTOUT_EDITED", "SHOUTOUT_HIDDEN", "SHOUTOUT_UNHIDDEN",
    "SHOUTOUT_DELETED", "PRINCIPLE_CREATED", "PRINCIPLE_UPDATED", "USER_SUSPENDED",
    "USER_REINSTATED", "EMAIL_RETRIED", "LOGIN_REJECTED",
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
