"""
Where profile pictures are kept.

Everything that saves or removes a picture goes through one storage object, so the place they
live can change without touching the routes, the seed script or the web app:

  AVATAR_STORAGE=local       (default) files in static/avatars/, served at /static/avatars/...
  AVATAR_STORAGE=sharepoint  the plan for the final build: one SharePoint folder that holds
                             everyone's picture. Not built yet; see SharePointAvatarStorage.

A storage object does two things:
  save(employee_id, data, extension, label=None) -> the URL to store in employees.avatar_url
  delete(employee_id)                             -> removes that person's picture, if any

Each person has at most one picture: saving a new one replaces the old one.
"""
import os
import re
import time
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL_AVATAR_DIR = os.path.join(BASE_DIR, "static", "avatars")
LOCAL_AVATAR_URL = "/static/avatars"

MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5 MB

_SAFE_ID = re.compile(r"^[A-Za-z0-9-]{1,40}$")
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9]{1,20}$")


class AvatarStorageError(Exception):
    """Storage couldn't do what was asked. The routes answer 503 with this message."""


def sniff_image_type(data: bytes) -> Optional[str]:
    """
    The real type of an uploaded picture, read from its first bytes: 'png', 'jpg', 'gif' or
    'webp'. None for anything else, whatever the file was called.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _check_id(employee_id: str) -> str:
    """Employee IDs end up in file names, so only plain IDs are let through."""
    if not isinstance(employee_id, str) or not _SAFE_ID.match(employee_id):
        raise AvatarStorageError("That employee ID can't be used for a profile picture.")
    return employee_id


class LocalAvatarStorage:
    """Pictures as files in static/avatars/, named {employeeId}_{label}.{extension}."""

    def __init__(self, directory: str = LOCAL_AVATAR_DIR, url_prefix: str = LOCAL_AVATAR_URL):
        self.directory = directory
        self.url_prefix = url_prefix

    def _files_of(self, employee_id: str):
        if not os.path.isdir(self.directory):
            return []
        return [
            name for name in os.listdir(self.directory)
            if name.startswith(f"{employee_id}_") or name.startswith(f"{employee_id}.")
        ]

    def delete(self, employee_id: str) -> None:
        for name in self._files_of(_check_id(employee_id)):
            try:
                os.remove(os.path.join(self.directory, name))
            except OSError:
                pass

    def save(self, employee_id: str, data: bytes, extension: str, label: Optional[str] = None) -> str:
        """
        label defaults to the time of the upload, so a changed picture gets a new address and
        browsers never show the old one from their cache.
        """
        _check_id(employee_id)
        label = label or str(int(time.time() * 1000))
        if not _SAFE_LABEL.match(label) or not _SAFE_LABEL.match(extension):
            raise AvatarStorageError("That picture name can't be used.")
        os.makedirs(self.directory, exist_ok=True)
        self.delete(employee_id)
        filename = f"{employee_id}_{label}.{extension}"
        with open(os.path.join(self.directory, filename), "wb") as handle:
            handle.write(data)
        return f"{self.url_prefix}/{filename}"

    def clear(self) -> None:
        """Removes every picture (the seed script starts from a clean folder). Keeps .gitkeep."""
        if not os.path.isdir(self.directory):
            return
        for name in os.listdir(self.directory):
            path = os.path.join(self.directory, name)
            if name != ".gitkeep" and os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass


class SharePointAvatarStorage:
    """
    Placeholder for the final build, where one SharePoint folder holds everyone's profile
    picture. Nothing here calls SharePoint yet: choosing AVATAR_STORAGE=sharepoint makes
    uploads answer "not set up" instead of quietly saving files locally.

    TODO when the SharePoint folder exists (to be agreed with Ian and IT):
      - An Entra app registration that may read and write that one folder, and its site ID,
        drive ID and folder path as settings. The app reaches the files through Microsoft
        Graph (the drive item content endpoints), not through a browser link.
      - A naming rule for the files, e.g. {employeeId}.jpg, so a picture is found from the ID.
      - save(): upload the bytes to the folder under that name, replacing any older file.
      - delete(): remove that file.
      - Showing them: SharePoint links need a signed-in Microsoft session, so the browser
        can't load them directly. Add a route such as GET /api/avatars/<employeeId> that
        fetches the picture with the app's own token and returns it (with caching), and have
        save() return that route's address so employees.avatar_url keeps working as it does now.
      - seed.py: the demo pictures stay local; with SharePoint the real ones are already there.
    """

    def save(self, employee_id: str, data: bytes, extension: str, label: Optional[str] = None) -> str:
        raise AvatarStorageError("Profile pictures in SharePoint aren't set up yet.")

    def delete(self, employee_id: str) -> None:
        raise AvatarStorageError("Profile pictures in SharePoint aren't set up yet.")


def get_avatar_storage():
    """The storage chosen by AVATAR_STORAGE (local unless it says sharepoint)."""
    choice = (os.getenv("AVATAR_STORAGE") or "local").strip().lower()
    if choice == "sharepoint":
        return SharePointAvatarStorage()
    return LocalAvatarStorage()
