"""Background images uploaded for a dashboard.

The image is a file on disk, not bytes in the database: a dashboard row is read
on every listing, and a megabyte of base64 riding along with it would be paid
for on every one of them.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings

MAX_BACKGROUND_BYTES = 8 * 1024 * 1024

# Sniffed from the bytes rather than trusted from the name or the browser's
# content type, both of which the uploader chooses. SVG is deliberately absent:
# it is a document that can carry script, and this file is served back from the
# API's own origin.
SIGNATURES: list[tuple[bytes, str, str]] = [
    (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
    (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
    (b"GIF87a", ".gif", "image/gif"),
    (b"GIF89a", ".gif", "image/gif"),
]


class BackgroundError(ValueError):
    """The uploaded bytes are not an image this can serve."""


def backgrounds_path() -> Path:
    return get_settings().storage_path / "dashboard-backgrounds"


def sniff(data: bytes) -> tuple[str, str]:
    """Return (suffix, content type), or raise if this is not a usable image."""
    for magic, suffix, content_type in SIGNATURES:
        if data.startswith(magic):
            return suffix, content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    raise BackgroundError("Upload a PNG, JPEG, GIF or WebP image")


def save_background(dashboard_id: str, data: bytes) -> str:
    """Write the image and return the file name to store on the dashboard."""
    if not data:
        raise BackgroundError("The uploaded file is empty")
    if len(data) > MAX_BACKGROUND_BYTES:
        limit = MAX_BACKGROUND_BYTES // (1024 * 1024)
        raise BackgroundError(f"Background images are limited to {limit} MB")

    suffix, _ = sniff(data)
    directory = backgrounds_path()
    directory.mkdir(parents=True, exist_ok=True)
    # One file per dashboard, named after it, so replacing a background leaves
    # nothing behind and a deleted dashboard's file is findable.
    for stale in directory.glob(f"{dashboard_id}.*"):
        stale.unlink(missing_ok=True)
    name = f"{dashboard_id}{suffix}"
    (directory / name).write_bytes(data)
    return name


def background_file(dashboard_id: str, name: str | None) -> tuple[Path, str] | None:
    """Locate a stored background, or None if the dashboard has none on disk."""
    if not name:
        return None
    # The name is only ever one this module wrote, but it reaches here through a
    # JSON column an editor can PATCH, so it is checked rather than trusted.
    if Path(name).name != name or not name.startswith(f"{dashboard_id}."):
        return None
    path = backgrounds_path() / name
    if not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            _, content_type = sniff(handle.read(16))
    except (BackgroundError, OSError):
        return None
    return path, content_type


def remove_background(dashboard_id: str) -> None:
    for stale in backgrounds_path().glob(f"{dashboard_id}.*"):
        stale.unlink(missing_ok=True)
