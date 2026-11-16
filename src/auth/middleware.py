from functools import wraps
from flask import request, jsonify, g
from src.auth.service import decode_token, run_auth_pipeline

def make_error(code: str, message: str, status_code: int):
    return jsonify({
        "error": {
            "code": code,
            "message": message
        }
    }), status_code

def require_auth(f):
    """
    Decorator for routes requiring authenticated active Sandoz employee.
    Enforces JWT validity, single-tenant restriction, guest blocking,
    directory presence, and non-suspended status.
    Attaches authenticated employee context to Flask's `g.user`.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return make_error("UNAUTHENTICATED", "Authentication required. Missing Bearer token.", 401)

        token = auth_header.split(" ", 1)[1].strip()
        is_valid, claims, error_msg = decode_token(token)
        if not is_valid:
            return make_error("UNAUTHENTICATED", error_msg or "Invalid authentication token.", 401)

        # Run auth pipeline (allow_suspended=False for standard protected operations)
        success, me_dict, error_code, error_message = run_auth_pipeline(claims, allow_suspended=False)
        if not success:
            return make_error(error_code, error_message, 403)

        # Attach safe authenticated identity to request context
        g.user = me_dict
        return f(*args, **kwargs)

    return decorated

def require_admin(f):
    """
    Decorator for routes requiring an ADMIN role.
    Must be used in combination with or following authentication.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return make_error("UNAUTHENTICATED", "Authentication required. Missing Bearer token.", 401)

        token = auth_header.split(" ", 1)[1].strip()
        is_valid, claims, error_msg = decode_token(token)
        if not is_valid:
            return make_error("UNAUTHENTICATED", error_msg or "Invalid authentication token.", 401)

        success, me_dict, error_code, error_message = run_auth_pipeline(claims, allow_suspended=False)
        if not success:
            return make_error(error_code, error_message, 403)

        if me_dict.get("role") != "ADMIN":
            return make_error("FORBIDDEN", "Admin privileges required to access this resource.", 403)

        g.user = me_dict
        return f(*args, **kwargs)

    return decorated

