from flask import Blueprint, request, jsonify, g
from database import get_db
from src.auth.middleware import require_auth, make_error
from src.shoutouts.service import (
    DEFAULT_PAGE_SIZE,
    ShoutoutError,
    edit_shoutout,
    list_active_principles,
    list_feed,
    list_teams,
    set_like,
)

shoutouts_bp = Blueprint("shoutouts", __name__)


@shoutouts_bp.errorhandler(ShoutoutError)
def handle_shoutout_error(error: ShoutoutError):
    return make_error(error.code, error.message, error.status_code)


def _int_arg(name: str, default=None):
    """Reads an optional whole-number query parameter."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ShoutoutError("VALIDATION_FAILED", f"'{name}' must be a whole number.", 400)


@shoutouts_bp.route("/api/shoutouts", methods=["GET"])
@require_auth
def get_feed():
    """
    The newsfeed: VISIBLE shout-outs from the caller's country.
    Query: sort=newest|most_liked, principleId, teamId, cursor, limit (default 20).
    Returns { items: ShoutoutDto[], nextCursor: string | null }.
    """
    conn = get_db()
    try:
        page = list_feed(
            conn,
            g.user,
            sort=request.args.get("sort", "newest"),
            principle_id=_int_arg("principleId"),
            team_id=request.args.get("teamId") or None,
            cursor=request.args.get("cursor") or None,
            limit=_int_arg("limit", DEFAULT_PAGE_SIZE),
        )
        return jsonify(page), 200
    finally:
        conn.close()


@shoutouts_bp.route("/api/shoutouts/<int:shoutout_id>/like", methods=["POST", "DELETE"])
@require_auth
def like_shoutout(shoutout_id: int):
    """POST likes, DELETE unlikes. Both are safe to repeat. Returns { likeCount, likedByMe }."""
    conn = get_db()
    try:
        result = set_like(conn, g.user, shoutout_id, liked=request.method == "POST")
        return jsonify(result), 200
    finally:
        conn.close()


@shoutouts_bp.route("/api/shoutouts/<int:shoutout_id>", methods=["PATCH"])
@require_auth
def patch_shoutout(shoutout_id: int):
    """Edit your own shout-out: principleId, reason, impact, actOfKindness. Returns the ShoutoutDto."""
    conn = get_db()
    try:
        dto = edit_shoutout(conn, g.user, shoutout_id, request.get_json(silent=True))
        return jsonify(dto), 200
    finally:
        conn.close()


# The feed's filter dropdowns need these two lists. They live here until the
# principles and directory routes from the plan are built.

@shoutouts_bp.route("/api/principles", methods=["GET"])
@require_auth
def get_principles():
    """ACTIVE principles in display order."""
    conn = get_db()
    try:
        return jsonify(list_active_principles(conn)), 200
    finally:
        conn.close()


@shoutouts_bp.route("/api/teams", methods=["GET"])
@require_auth
def get_teams():
    """Teams with their active member counts."""
    conn = get_db()
    try:
        return jsonify(list_teams(conn, g.user["country"])), 200
    finally:
        conn.close()
