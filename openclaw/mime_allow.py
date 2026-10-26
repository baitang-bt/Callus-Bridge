# Extension allowlist inspired by nightsailer/wechat-clawbot media/mime.py (MIT).
# SPDX-License-Identifier: MIT

"""Allowed inbound file extensions for openclaw media disk writes."""

from __future__ import annotations

ALLOWED_FILE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".txt",
        ".csv",
        ".zip",
        ".tar",
        ".gz",
        ".mp3",
        ".ogg",
        ".wav",
        ".mp4",
        ".mov",
        ".webm",
        ".mkv",
        ".avi",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
    }
)


def allowed_file_suffix(suffix: str) -> bool:
    """True when *suffix* (with leading dot) may be written to disk."""
    return (suffix or "").lower() in ALLOWED_FILE_EXTENSIONS
