import time
from collections import defaultdict, deque
from threading import Lock

from flask import Blueprint, request, jsonify, g
from database import get_db
from src.auth.middleware import require_auth, make_error
from src.shoutouts.service import (
    DEFAULT_PAGE_SIZE,
    ShoutoutError,
    create_shoutout,
    edit_shoutout,
    list_active_principles,
    list_feed,
    list_team_members,
    list_teams,
    search_directory,
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


# ---------------------------------------------------------------- give a shout-out

# The plan allows 5 new shout-outs per minute per person. Only posts that were saved count, so
# fixing a mistake on the form never locks anyone out. The count is kept in memory, which is
# enough for one local server; a shared store would be needed behind a load balancer.
CREATE_LIMIT = 5
CREATE_WINDOW_SECONDS = 60
_recent_creates = defaultdict(deque)
_recent_creates_lock = Lock()


def _check_create_rate(employee_id: str):
    """Raises RATE_LIMITED when this person has already posted CREATE_LIMIT times this minute."""
    now = time.monotonic()
    with _recent_creates_lock:
        recent = _recent_creates[employee_id]
        while recent and now - recent[0] > CREATE_WINDOW_SECONDS:
            recent.popleft()
        if len(recent) >= CREATE_LIMIT:
            raise ShoutoutError(
                "RATE_LIMITED", "You're posting shout-outs very quickly. Wait a minute and try again.", 429
            )


def _record_create(employee_id: str):
    with _recent_creates_lock:
        _recent_creates[employee_id].append(time.monotonic())


@shoutouts_bp.route("/api/shoutouts", methods=["POST"])
@require_auth
def post_shoutout():
    """Give a shout-out. Body: CreateShoutoutRequest. Returns 201 with the new ShoutoutDto."""
    _check_create_rate(g.user["employeeId"])
    conn = get_db()
    try:
        dto = create_shoutout(conn, g.user, request.get_json(silent=True))
        _record_create(g.user["employeeId"])
        return jsonify(dto), 201
    finally:
        conn.close()


@shoutouts_bp.route("/api/directory/search", methods=["GET"])
@require_auth
def get_directory_search():
    """People to recognise, by name. Query: q (at least 2 characters), limit (default 10)."""
    conn = get_db()
    try:
        people = search_directory(conn, g.user, request.args.get("q", ""), _int_arg("limit", 10))
        return jsonify(people), 200
    finally:
        conn.close()


@shoutouts_bp.route("/api/teams/<team_id>/members", methods=["GET"])
@require_auth
def get_team_members(team_id: str):
    """Active members of a team, without the caller."""
    conn = get_db()
    try:
        return jsonify(list_team_members(conn, g.user, team_id)), 200
    finally:
        conn.close()
