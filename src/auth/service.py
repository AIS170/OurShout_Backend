import os
import time
import json
import jwt
from typing import Dict, Any, List, Optional, Tuple
from database import get_db

JWT_SECRET = os.getenv("JWT_SECRET", "sandoz-ourshout-jwt-secret-key-2026-secure-32bytes")
TENANT_ID = os.getenv("TENANT_ID", "sandoz-mock-tenant")
TOKEN_EXPIRY_SECONDS = 8 * 3600  # 8 hours

PERSONAS: List[Dict[str, Any]] = [
    {
        "personaId": "employee",
        "label": "Priya Raman (E0005)",
        "description": "Sales — Sandoz tenant, standard employee",
        "expected": "OK",
        "employeeId": "E0005",
        "name": "Priya Raman",
        "email": "priya.raman@sandoz.test",
        "tid": "sandoz-mock-tenant",
        "acct": 0,
        "roles": []
    },
    {
        "personaId": "employee2",
        "label": "Aisha Rahman (E0013)",
        "description": "Sales — Sandoz tenant, colleague",
        "expected": "OK",
        "employeeId": "E0013",
        "name": "Aisha Rahman",
        "email": "aisha.rahman@sandoz.test",
        "tid": "sandoz-mock-tenant",
        "acct": 0,
        "roles": []
    },
    {
        "personaId": "manager",
        "label": "Olivia Chen (E0011)",
        "description": "Commercial & General Management — Sandoz tenant, manager",
        "expected": "OK",
        "employeeId": "E0011",
        "name": "Olivia Chen",
        "email": "olivia.chen@sandoz.test",
        "tid": "sandoz-mock-tenant",
        "acct": 0,
        "roles": []
    },
    {
        "personaId": "admin",
        "label": "Natalie Moreau (E0039)",
        "description": "Human Resources — Sandoz tenant, Admin role",
        "expected": "OK",
        "employeeId": "E0039",
        "name": "Natalie Moreau",
        "email": "natalie.moreau@sandoz.test",
        "tid": "sandoz-mock-tenant",
        "acct": 0,
        "roles": ["Admin"]
    },
    {
        "personaId": "suspended",
        "label": "Oliver Grant (E0029)",
        "description": "Technical Operations — Sandoz tenant, status: SUSPENDED",
        "expected": "ACCOUNT_SUSPENDED",
        "employeeId": "E0029",
        "name": "Oliver Grant",
        "email": "oliver.grant@sandoz.test",
        "tid": "sandoz-mock-tenant",
        "acct": 0,
        "roles": []
    },
    {
        "personaId": "left",
        "label": "Benjamin Clarke (E0032)",
        "description": "RND — Sandoz tenant, status: INACTIVE (former employee)",
        "expected": "NOT_ACTIVE_EMPLOYEE",
        "employeeId": "E0032",
        "name": "Benjamin Clarke",
        "email": "benjamin.clarke@sandoz.test",
        "tid": "sandoz-mock-tenant",
        "acct": 0,
        "roles": []
    },
    {
        "personaId": "guest",
        "label": "External Partner (GUEST-001)",
        "description": "External partner account (acct = 1, not in directory)",
        "expected": "GUEST_NOT_ALLOWED",
        "employeeId": "GUEST-001",
        "name": "External Partner",
        "email": "guest.partner@partner.test",
        "tid": "sandoz-mock-tenant",
        "acct": 1,
        "roles": []
    },
    {
        "personaId": "othertenant",
        "label": "Other Tenant User",
        "description": "User from an external company tenant",
        "expected": "WRONG_TENANT",
        "employeeId": "E9999",
        "name": "External Tenant User",
        "email": "user@othercompany.test",
        "tid": "other-tenant",
        "acct": 0,
        "roles": []
    }
]

def get_personas() -> List[Dict[str, Any]]:
    """Return public list of personas for the user switcher."""
    return [
        {
            "personaId": p["personaId"],
            "label": p["label"],
            "description": p["description"],
            "expected": p["expected"],
            "email": p["email"],
            "employeeId": p["employeeId"],
            "name": p["name"],
            "roles": p["roles"]
        }
        for p in PERSONAS
    ]

def get_persona_by_id(persona_id: str) -> Optional[Dict[str, Any]]:
    target = persona_id.strip().lower()
    for p in PERSONAS:
        if (
            p["personaId"].lower() == target
            or p["email"].lower() == target
            or p["employeeId"].lower() == target
        ):
            return p
    return None

def generate_token(persona: Dict[str, Any]) -> str:
    now = int(time.time())
    payload = {
        "oid": persona["employeeId"],
        "tid": persona["tid"],
        "upn": persona["email"],
        "name": persona["name"],
        "roles": persona["roles"],
        "acct": persona["acct"],
        "iat": now,
        "exp": now + TOKEN_EXPIRY_SECONDS
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def decode_token(token: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Decodes and verifies JWT.
    Returns (is_valid, payload, error_message).
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return True, payload, None
    except jwt.ExpiredSignatureError:
        return False, None, "Token has expired."
    except jwt.InvalidTokenError as e:
        return False, None, f"Invalid token: {str(e)}"

def calculate_points_for_employee(conn, employee_id: str) -> int:
    """
    Points = 25 * (visible shout-outs sent) + 25 * (visible shout-outs received).
    Only counts VISIBLE posts.
    """
    try:
        # Check if shoutouts table exists
        shoutouts_exist = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='shoutouts'"
        ).fetchone()
        if not shoutouts_exist:
            return 0

        # Sent visible count
        sent_row = conn.execute(
            "SELECT COUNT(*) as count FROM shoutouts WHERE sender_id = ? AND visibility = 'VISIBLE'",
            (employee_id,)
        ).fetchone()
        sent_count = sent_row["count"] if sent_row else 0

        # Received visible count
        rec_row = conn.execute("""
            SELECT COUNT(DISTINCT sr.shoutout_id) as count
            FROM shoutout_recipients sr
            JOIN shoutouts s ON sr.shoutout_id = s.id
            WHERE sr.recipient_id = ? AND s.visibility = 'VISIBLE'
        """, (employee_id,)).fetchone()
        rec_count = rec_row["count"] if rec_row else 0

        return (sent_count * 25) + (rec_count * 25)
    except Exception:
        return 0

def record_login_rejected_audit(conn, actor_id: str, target_id: str, reason_code: str):
    """Logs LOGIN_REJECTED audit row if audit_events table exists."""
    try:
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events'"
        ).fetchone()
        if table_exists:
            conn.execute("""
                INSERT INTO audit_events (actor_id, action, target_type, target_id, before, after, created_at)
                VALUES (?, 'LOGIN_REJECTED', 'AUTH', ?, NULL, ?, CURRENT_TIMESTAMP)
            """, (actor_id, target_id, json.dumps({"reason": reason_code})))
            conn.commit()
    except Exception:
        pass

def run_auth_pipeline(claims: Dict[str, Any], allow_suspended: bool = False) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """
    Applies the auth pipeline rules:
    1. Token verified (already done by caller)
    2. tid must match TENANT_ID
    3. acct must not be 1 (guest)
    4. oid must exist in employees and be active
    5. employee status must not be SUSPENDED (unless allow_suspended=True for GET /api/me)

    Returns: (is_success, me_dict, error_code, error_message)
    """
    tid = claims.get("tid")
    if tid != TENANT_ID:
        return False, None, "WRONG_TENANT", "Access denied: single-tenant application. Guest and external tenants are rejected."

    acct = claims.get("acct")
    if acct == 1:
        return False, None, "GUEST_NOT_ALLOWED", "Access denied: guest accounts cannot access OurShout."

    oid = claims.get("oid")
    conn = get_db()
    try:
        # Check employee in directory
        emp = conn.execute("""
            SELECT e.*, t.team_name
            FROM employees e
            LEFT JOIN teams t ON e.team_id = t.team_id
            WHERE e.employee_id = ?
        """, (oid,)).fetchone()

        if not emp or emp["status"] == "INACTIVE":
            return False, None, "NOT_ACTIVE_EMPLOYEE", "Access denied: employee not found in directory or no longer active."

        # Role and status are directly on the employee record!
        role = emp["role"] or "EMPLOYEE"
        status = emp["status"] or "ACTIVE"

        if status == "SUSPENDED" and not allow_suspended:
            return False, None, "ACCOUNT_SUSPENDED", "Your OurShout account has been suspended. Please contact Human Resources."

        points = calculate_points_for_employee(conn, oid)

        me_dict = {
            "employeeId": emp["employee_id"],
            "name": emp["employee_name"],
            "email": emp["email_id"],
            "jobTitle": emp["job_title"],
            "teamId": emp["team_id"],
            "teamName": emp["team_name"] or "",
            "country": emp["country"] or "AU",
            "role": role,
            "status": status,
            "points": points
        }

        return True, me_dict, None, None
    finally:
        conn.close()

