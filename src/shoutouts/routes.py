import base64
import os
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
    get_profile,
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


# ---------------------------------------------------------------- profile

@shoutouts_bp.route("/api/profile/<employee_id>", methods=["GET"])
@require_auth
def get_profile_route(employee_id: str):
    """A person's recognition profile. "me" is accepted in place of your own employee ID."""
    if employee_id == "me":
        employee_id = g.user["employeeId"]
    conn = get_db()
    try:
        return jsonify(get_profile(conn, g.user, employee_id)), 200
    finally:
        conn.close()


# ---------------------------------------------------------------- avatar uploads

ALLOWED_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5 MB


def _allowed_avatar(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_AVATAR_EXTENSIONS


@shoutouts_bp.route("/api/profile/avatar", methods=["POST"])
@require_auth
def upload_avatar():
    """
    POST /api/profile/avatar.
    Uploads an avatar image for the authenticated user.
    Accepts multipart/form-data with field 'avatar' or 'file', or JSON with 'avatarBase64'.
    """
    employee_id = g.user["employeeId"]
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    avatars_dir = os.path.join(base_dir, "static", "avatars")
    os.makedirs(avatars_dir, exist_ok=True)

    file_bytes = None
    ext = "jpg"

    if "avatar" in request.files or "file" in request.files:
        uploaded_file = request.files.get("avatar") or request.files.get("file")
        if not uploaded_file or uploaded_file.filename == "":
            return make_error("VALIDATION_FAILED", "No file selected.", 400)
        if not _allowed_avatar(uploaded_file.filename):
            return make_error("VALIDATION_FAILED", "Allowed formats: PNG, JPG, JPEG, WEBP, GIF.", 400)
        ext = uploaded_file.filename.rsplit(".", 1)[1].lower()
        file_bytes = uploaded_file.read()
    else:
        json_data = request.get_json(silent=True) or {}
        base64_str = json_data.get("avatarBase64") or json_data.get("image")
        if not base64_str:
            return make_error("VALIDATION_FAILED", "Please provide an image file or base64 data.", 400)
        if "," in base64_str:
            header, base64_str = base64_str.split(",", 1)
            if "png" in header:
                ext = "png"
            elif "webp" in header:
                ext = "webp"
            elif "gif" in header:
                ext = "gif"
            else:
                ext = "jpg"
        try:
            file_bytes = base64.b64decode(base64_str)
        except Exception:
            return make_error("VALIDATION_FAILED", "Invalid base64 image data.", 400)

    if not file_bytes:
        return make_error("VALIDATION_FAILED", "Empty image payload.", 400)

    if len(file_bytes) > MAX_AVATAR_BYTES:
        return make_error("VALIDATION_FAILED", "Image exceeds maximum size of 5 MB.", 400)

    # Clean previous avatars for this user
    for existing in os.listdir(avatars_dir):
        if existing.startswith(f"{employee_id}_") or existing.startswith(f"{employee_id}."):
            try:
                os.remove(os.path.join(avatars_dir, existing))
            except Exception:
                pass

    timestamp = int(time.time())
    new_filename = f"{employee_id}_{timestamp}.{ext}"
    filepath = os.path.join(avatars_dir, new_filename)

    with open(filepath, "wb") as f:
        f.write(file_bytes)

    avatar_url = f"/static/avatars/{new_filename}"

    conn = get_db()
    try:
        conn.execute(
            "UPDATE employees SET avatar_url = ?, updated_at = CURRENT_TIMESTAMP WHERE employee_id = ?",
            (avatar_url, employee_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        "avatarUrl": avatar_url,
        "message": "Profile picture updated successfully."
    }), 200


@shoutouts_bp.route("/api/profile/avatar", methods=["DELETE"])
@require_auth
def delete_avatar():
    """DELETE /api/profile/avatar. Clears the user's avatar."""
    employee_id = g.user["employeeId"]
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    avatars_dir = os.path.join(base_dir, "static", "avatars")

    if os.path.exists(avatars_dir):
        for existing in os.listdir(avatars_dir):
            if existing.startswith(f"{employee_id}_") or existing.startswith(f"{employee_id}."):
                try:
                    os.remove(os.path.join(avatars_dir, existing))
                except Exception:
                    pass

    conn = get_db()
    try:
        conn.execute(
            "UPDATE employees SET avatar_url = NULL, updated_at = CURRENT_TIMESTAMP WHERE employee_id = ?",
            (employee_id,),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        "avatarUrl": None,
        "message": "Profile picture removed successfully."
    }), 200

