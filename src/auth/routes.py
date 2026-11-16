from flask import Blueprint, request, jsonify
from database import get_db
from src.auth.service import (
    get_personas,
    get_persona_by_id,
    generate_token,
    decode_token,
    run_auth_pipeline,
    record_login_rejected_audit
)

auth_bp = Blueprint("auth", __name__)

def make_error(code: str, message: str, status_code: int):
    return jsonify({
        "error": {
            "code": code,
            "message": message
        }
    }), status_code

@auth_bp.route("/api/auth/personas", methods=["GET"])
def list_personas():
    """Returns the list of mock personas for the login screen user switcher."""
    return jsonify(get_personas()), 200

@auth_bp.route("/api/auth/mock-login", methods=["POST"])
def mock_login():
    """
    Mock login endpoint.
    Accepts { "personaId": string }.
    Validates tenant, active status, guest flag, and suspension.
    Issues 8-hour JWT token mirroring Entra ID claims.
    """
    data = request.get_json(silent=True) or {}
    persona_id = data.get("personaId")

    if not persona_id:
        return make_error("VALIDATION_FAILED", "Field 'personaId' is required.", 400)

    persona = get_persona_by_id(persona_id)
    if not persona:
        return make_error("NOT_FOUND", f"Persona '{persona_id}' not found.", 404)

    # Prepare claims to test through the auth pipeline
    claims = {
        "oid": persona["employeeId"],
        "tid": persona["tid"],
        "upn": persona["email"],
        "name": persona["name"],
        "roles": persona["roles"],
        "acct": persona["acct"]
    }

    # Run pipeline steps 2-5
    is_valid, me_dict, error_code, error_message = run_auth_pipeline(claims, allow_suspended=False)

    if not is_valid:
        # Record LOGIN_REJECTED audit row
        conn = get_db()
        try:
            record_login_rejected_audit(conn, persona["employeeId"], persona_id, error_code)
        finally:
            conn.close()
        return make_error(error_code, error_message, 403)

    # Issue JWT
    token = generate_token(persona)
    return jsonify({
        "token": token,
        "me": me_dict
    }), 200

@auth_bp.route("/api/me", methods=["GET"])
def get_current_user():
    """
    Returns authenticated user's profile and calculated points.
    Responds even if ACCOUNT_SUSPENDED so the frontend can display a suspension banner.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return make_error("UNAUTHENTICATED", "Missing or invalid Authorization header.", 401)

    token = auth_header.split(" ", 1)[1].strip()
    is_valid, claims, error_msg = decode_token(token)
    if not is_valid:
        return make_error("UNAUTHENTICATED", error_msg or "Invalid authentication token.", 401)

    # Pipeline validation (allow_suspended=True so GET /api/me still answers)
    success, me_dict, error_code, error_message = run_auth_pipeline(claims, allow_suspended=True)
    if not success:
        return make_error(error_code, error_message, 403)

    return jsonify(me_dict), 200

