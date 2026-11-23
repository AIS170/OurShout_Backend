import base64
import time
from collections import defaultdict, deque
from threading import Lock

from flask import Blueprint, request, jsonify, g
from database import get_db
from src.auth.middleware import require_auth, make_error
from src.avatars.storage import AvatarStorageError, MAX_AVATAR_BYTES, get_avatar_storage, sniff_image_type
from src.shoutouts.service import (
    DEFAULT_PAGE_SIZE,
    ShoutoutError,
    add_comment,
    create_shoutout,
    delete_comment,
    edit_shoutout,
    get_profile,
    list_active_principles,
    list_comments,
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
            kind=request.args.get("kind") or None,
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


# ---------------------------------------------------------------- comments

# Same idea as the shout-out limit further down: only comments that were saved count, and the
# count is kept in memory.
COMMENT_LIMIT = 10
COMMENT_WINDOW_SECONDS = 60
_recent_comments = defaultdict(deque)
_recent_comments_lock = Lock()


def _check_comment_rate(employee_id: str):
    """Raises RATE_LIMITED when this person has already commented COMMENT_LIMIT times this minute."""
    now = time.monotonic()
    with _recent_comments_lock:
        recent = _recent_comments[employee_id]
        while recent and now - recent[0] > COMMENT_WINDOW_SECONDS:
            recent.popleft()
        if len(recent) >= COMMENT_LIMIT:
            raise ShoutoutError(
                "RATE_LIMITED", "You're commenting very quickly. Wait a minute and try again.", 429
            )


def _record_comment(employee_id: str):
    with _recent_comments_lock:
        _recent_comments[employee_id].append(time.monotonic())


@shoutouts_bp.route("/api/shoutouts/<int:shoutout_id>/comments", methods=["GET"])
@require_auth
def get_comments(shoutout_id: int):
    """The comments under a shout-out, oldest first. Returns { items: CommentDto[], commentCount }."""
    conn = get_db()
    try:
        return jsonify(list_comments(conn, g.user, shoutout_id)), 200
    finally:
        conn.close()


@shoutouts_bp.route("/api/shoutouts/<int:shoutout_id>/comments", methods=["POST"])
@require_auth
def post_comment(shoutout_id: int):
    """Comment on a shout-out. Body: { text }. Returns 201 with { comment: CommentDto, commentCount }."""
    _check_comment_rate(g.user["employeeId"])
    conn = get_db()
    try:
        result = add_comment(conn, g.user, shoutout_id, request.get_json(silent=True))
        _record_comment(g.user["employeeId"])
        return jsonify(result), 201
    finally:
        conn.close()


@shoutouts_bp.route("/api/shoutouts/<int:shoutout_id>/comments/<int:comment_id>", methods=["DELETE"])
@require_auth
def remove_comment(shoutout_id: int, comment_id: int):
    """Delete your own comment (an admin can delete any). Returns { commentCount }."""
    conn = get_db()
    try:
        return jsonify(delete_comment(conn, g.user, shoutout_id, comment_id)), 200
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


def _allowed_avatar(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_AVATAR_EXTENSIONS


def _set_avatar_url(employee_id: str, avatar_url):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE employees SET avatar_url = ?, updated_at = CURRENT_TIMESTAMP WHERE employee_id = ?",
            (avatar_url, employee_id),
        )
        conn.commit()
    finally:
        conn.close()


@shoutouts_bp.route("/api/profile/avatar", methods=["POST"])
@require_auth
def upload_avatar():
    """
    POST /api/profile/avatar.
    Sets the signed-in user's profile picture, replacing the one they had (a seeded demo
    picture included). Everyone sees the new one wherever that person appears.
    Accepts multipart/form-data with field 'avatar' or 'file', or JSON with 'avatarBase64'.
    The picture must really be a PNG, JPG, WEBP or GIF (checked from its contents, not its
    name) and at most 5 MB. Where it is kept is up to the storage in src/avatars/storage.py.
    """
    employee_id = g.user["employeeId"]
    file_bytes = None

    if "avatar" in request.files or "file" in request.files:
        uploaded_file = request.files.get("avatar") or request.files.get("file")
        if not uploaded_file or uploaded_file.filename == "":
            return make_error("VALIDATION_FAILED", "No file selected.", 400)
        if not _allowed_avatar(uploaded_file.filename):
            return make_error("VALIDATION_FAILED", "Allowed formats: PNG, JPG, JPEG, WEBP, GIF.", 400)
        file_bytes = uploaded_file.read()
    else:
        json_data = request.get_json(silent=True)
        if not isinstance(json_data, dict):
            json_data = {}
        base64_str = json_data.get("avatarBase64") or json_data.get("image")
        if not base64_str or not isinstance(base64_str, str):
            return make_error("VALIDATION_FAILED", "Please provide an image file or base64 data.", 400)
        if "," in base64_str:  # a data URL: keep the part after "data:image/...;base64,"
            base64_str = base64_str.split(",", 1)[1]
        try:
            # Line breaks and spaces are allowed in base64; anything else makes it invalid.
            file_bytes = base64.b64decode("".join(base64_str.split()), validate=True)
        except Exception:
            return make_error("VALIDATION_FAILED", "Invalid base64 image data.", 400)

    if not file_bytes:
        return make_error("VALIDATION_FAILED", "Empty image payload.", 400)

    if len(file_bytes) > MAX_AVATAR_BYTES:
        return make_error("VALIDATION_FAILED", "Image exceeds maximum size of 5 MB.", 400)

    # The file's own first bytes decide what it is, so a renamed file can't get through.
    extension = sniff_image_type(file_bytes)
    if not extension:
        return make_error("VALIDATION_FAILED", "That file isn't a PNG, JPG, WEBP or GIF image.", 400)

    try:
        avatar_url = get_avatar_storage().save(employee_id, file_bytes, extension)
    except AvatarStorageError as problem:
        return make_error("AVATARS_UNAVAILABLE", str(problem), 503)
    _set_avatar_url(employee_id, avatar_url)

    return jsonify({
        "avatarUrl": avatar_url,
        "message": "Profile picture updated successfully."
    }), 200


@shoutouts_bp.route("/api/profile/avatar", methods=["DELETE"])
@require_auth
def delete_avatar():
    """DELETE /api/profile/avatar. Removes the user's picture; their initials show in its place."""
    employee_id = g.user["employeeId"]
    try:
        get_avatar_storage().delete(employee_id)
    except AvatarStorageError as problem:
        return make_error("AVATARS_UNAVAILABLE", str(problem), 503)
    _set_avatar_url(employee_id, None)

    return jsonify({
        "avatarUrl": None,
        "message": "Profile picture removed successfully."
    }), 200
