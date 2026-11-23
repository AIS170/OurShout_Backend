"""
Profile pictures for the seed data.

seed_avatars/ (next to seed.py) holds one picture per employee, named by employee ID: the local
stand-in for the SharePoint folder planned for the final build. seed.py asks seed_picture() for
each person's picture, which looks there in this order:

  1. a photo:    E0005.jpg / .jpeg / .png / .webp / .gif   (drop one in to use a real photo)
  2. a portrait: E0005.svg   the drawn person that ships with the repo
  3. neither:    a generated cartoon face (demo_avatar_svg), so nobody is ever left blank

The seeded employees are made up, so the pictures that ship are drawings of people, not photos
of anyone. The drawings are not matched to names: nobody's looks are guessed from their name.
"""
import hashlib
import os
from typing import Dict, Optional, Tuple

from src.avatars.storage import BASE_DIR, MAX_AVATAR_BYTES, sniff_image_type

SEED_AVATAR_DIR = os.path.join(BASE_DIR, "seed_avatars")
PHOTO_EXTENSIONS = ("jpg", "jpeg", "png", "webp", "gif")


def _seed_files(directory: str) -> Dict[str, str]:
    """Lower-cased file name -> real file name, so e0005.JPG is found on any operating system."""
    if not os.path.isdir(directory):
        return {}
    return {name.lower(): name for name in os.listdir(directory)}


def seed_picture(employee_id: str, directory: Optional[str] = None) -> Tuple[bytes, str, str]:
    """
    This person's seed picture as (bytes, extension, kind). kind is 'photo', 'portrait' or
    'generated'. A photo that isn't really a PNG, JPG, WEBP or GIF, or is over 5 MB, is passed
    over with a note on the console.
    """
    directory = directory or SEED_AVATAR_DIR
    files = _seed_files(directory)
    wanted = employee_id.lower()

    for extension in PHOTO_EXTENSIONS:
        name = files.get(f"{wanted}.{extension}")
        if not name:
            continue
        with open(os.path.join(directory, name), "rb") as handle:
            data = handle.read()
        real_type = sniff_image_type(data)
        if real_type and len(data) <= MAX_AVATAR_BYTES:
            return data, real_type, "photo"
        print(f"   ! seed_avatars/{name} skipped: it isn't a PNG, JPG, WEBP or GIF of up to 5 MB.")

    name = files.get(f"{wanted}.svg")
    if name:
        with open(os.path.join(directory, name), "rb") as handle:
            return handle.read(), "svg", "portrait"

    return demo_avatar_svg(employee_id).encode("utf-8"), "svg", "generated"

# ---------------------------------------------------------------- the generated fallback

# (background, face, eyes and mouth). Each pair has enough contrast to read at 32 pixels.
PALETTES = [
    ("#1c59b5", "#a8d5ff", "#001c4a"),
    ("#001c4a", "#f6dc85", "#001c4a"),
    ("#a8d5ff", "#1c59b5", "#ffffff"),
    ("#f1ece9", "#d4a72c", "#3d2c00"),
    ("#0c3f8c", "#f4c7d9", "#4a0f2c"),
    ("#f6dc85", "#0c3f8c", "#ffffff"),
    ("#cfe8d5", "#1f7a4d", "#ffffff"),
    ("#f4c7d9", "#8a2c5a", "#ffffff"),
    ("#1f7a4d", "#d9f2e1", "#0b3d26"),
    ("#e2e5e9", "#3f4a5a", "#ffffff"),
    ("#8a2c5a", "#ffe3ee", "#4a0f2c"),
    ("#d4a72c", "#001c4a", "#ffffff"),
]

SIZE = 80  # the drawing's own units; it is shown at any size


def demo_avatar_svg(employee_id: str) -> str:
    """
    A cartoon face worked out from the employee ID alone: same ID, same picture. Used for anyone
    who has no file in seed_avatars/ (a new employee added to seed.py, say).
    """
    digest = hashlib.sha256(f"ourshout-avatar:{employee_id}".encode("utf-8")).digest()

    def pick(index: int, low: float, high: float) -> float:
        """A number between low and high, taken from one byte of the digest."""
        return round(low + (high - low) * digest[index] / 255, 1)

    background, face, features = PALETTES[digest[0] % len(PALETTES)]
    # The face is a rounded shape pushed off-centre and tilted; the eyes and mouth follow it.
    shift_x, shift_y = pick(1, -9, 9), pick(2, 4, 14)
    tilt = pick(3, -18, 18)
    corner = pick(4, 22, 40)
    look_x, look_y = pick(5, -5, 5), pick(6, -3, 4)
    eye_gap = pick(7, 6.5, 9.5)
    mouth = digest[8] % 3

    eye_y = 36 + look_y
    centre = 40 + look_x
    if mouth == 0:    # open smile
        mouth_svg = f'<path d="M{centre - 6},{eye_y + 9} a6,6 0 0 0 12,0 z" fill="{features}"/>'
    elif mouth == 1:  # curved smile
        mouth_svg = (
            f'<path d="M{centre - 7},{eye_y + 9} q7,7 14,0" fill="none" stroke="{features}" '
            f'stroke-width="2.4" stroke-linecap="round"/>'
        )
    else:             # small grin
        mouth_svg = (
            f'<path d="M{centre - 5},{eye_y + 10} q5,4 10,0" fill="none" stroke="{features}" '
            f'stroke-width="2.4" stroke-linecap="round"/>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" width="240" height="240">'
        f'<rect width="{SIZE}" height="{SIZE}" fill="{background}"/>'
        f'<g transform="translate({shift_x} {shift_y}) rotate({tilt} 40 40)">'
        f'<rect x="8" y="12" width="64" height="76" rx="{corner}" fill="{face}"/>'
        f'<rect x="{centre - eye_gap - 1.6}" y="{eye_y - 3}" width="3.2" height="5.6" rx="1.6" fill="{features}"/>'
        f'<rect x="{centre + eye_gap - 1.6}" y="{eye_y - 3}" width="3.2" height="5.6" rx="1.6" fill="{features}"/>'
        f'{mouth_svg}'
        f'</g>'
        f'</svg>'
    )
