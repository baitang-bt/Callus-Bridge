"""Callus capture helpers: scroll context and bubble media crops.

Keeps means (a11y / pixels) inside the agent. gRPC only sees paths and hashes.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from . import chat, geometry, message_actions, screen
from . import input as inputmod
from .ui import synchronized

MEDIA_DIR = Path(os.environ.get("CALLUS_MEDIA_DIR", "/data/media"))
DEFAULT_MAX_FRAMES = 8
DEFAULT_INTERVAL_MS = 200


def _media_root() -> Path:
    """Ensure the capture directory exists and return it."""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return MEDIA_DIR


def _sha256_bytes(data: bytes) -> str:
    """Hash raw image bytes for attachment identity."""
    return hashlib.sha256(data).hexdigest()


def _save_png(image, stem: str) -> tuple[str, str]:
    """Write a PNG under MEDIA_DIR; return (path, sha256)."""
    raw = image.convert("RGB")
    buf = raw.tobytes()
    digest = _sha256_bytes(buf)
    path = _media_root() / f"{stem}_{digest[:16]}.png"
    raw.save(path, format="PNG")
    return str(path), digest


@synchronized
def read_latest(chat_name: str = ""):
    """Open the chat if needed and return the newest TEXT/SYSTEM row.

    Nickname (sender) comes from the same pass as the bubble text.
    """
    name, messages = chat.list_messages(chat=chat_name, limit=0)
    info = chat.chat_header_info(name)
    latest = None
    for msg in reversed(messages):
        if msg.get("kind") in ("TEXT", "SYSTEM"):
            latest = msg
            break
    return name, latest, info


@synchronized
def read_context(chat_name: str = "", limit: int = 0):
    """Collect up to ``limit`` messages by scrolling the message list upward.

    ``limit <= 0`` means the currently visible window only (same as ListMessages).
    Caller owns the limit value; this module does not hard-code 30.
    """
    name, messages = chat.list_messages(chat=chat_name, limit=0)
    info = chat.chat_header_info(name)
    if limit <= 0 or len(messages) >= limit:
        if limit > 0 and len(messages) > limit:
            messages = messages[-limit:]
        return name, messages, info

    by_id = {m["id"]: m for m in messages}
    stagnant = 0
    while len(by_id) < limit and stagnant < 3:
        rect = geometry.node_physical_rect("list", chat.MESSAGE_LIST)
        if rect is None:
            break
        x, y, w, h = rect
        inputmod.click_at(x + w // 2, y + h // 2)
        time.sleep(0.12)
        inputmod.tap_key("Page_Up")
        time.sleep(0.35)
        _n, batch = chat.list_messages(chat=name, limit=0)
        before = len(by_id)
        for msg in batch:
            by_id[msg["id"]] = msg
        if len(by_id) == before:
            stagnant += 1
        else:
            stagnant = 0

    ordered = sorted(by_id.values(), key=lambda m: m.get("index", 0))
    if len(ordered) > limit:
        ordered = ordered[-limit:]
    return name, ordered, info


@synchronized
def capture_message_media(
    chat_name: str,
    index: int,
    max_frames: int = 0,
    interval_ms: int = 0,
):
    """Crop the bubble at ``index``; sample frames while pixels change.

    When the crop is unchanged across two samples, keep one still frame and
    set ``sampled=False``.
    """
    max_frames = max_frames or DEFAULT_MAX_FRAMES
    interval_ms = interval_ms or DEFAULT_INTERVAL_MS
    interval = max(0.05, interval_ms / 1000.0)

    ok, detail = chat.open_chat(chat_name)
    if not ok:
        return False, detail, []

    rect = message_actions.bubble_rect(chat_name, index)
    if rect is None:
        return False, "找不到该消息的气泡", []

    bx, by, bw, bh = rect
    attachments = []
    prev_digest = None
    stem = f"{chat_name}_{index}".replace("/", "_")[:48]

    for frame_i in range(max_frames):
        img, (ox, oy) = screen.capture_window()
        crop = img.crop((bx - ox, by - oy, bx - ox + bw, by - oy + bh))
        path, digest = _save_png(crop, f"{stem}_f{frame_i}")
        if digest == prev_digest:
            # Unchanged → still frame only; drop the duplicate file.
            if frame_i == 0:
                attachments.append(
                    {
                        "kind": "emotion",
                        "path": path,
                        "sha256": digest,
                        "sampled": False,
                        "frame_index": 0,
                    }
                )
            else:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass
            break
        prev_digest = digest
        attachments.append(
            {
                "kind": "emotion",
                "path": path,
                "sha256": digest,
                "sampled": True,
                "frame_index": frame_i,
            }
        )
        time.sleep(interval)
    else:
        # Hit max_frames while still changing; mark as sampled.
        pass

    if not attachments:
        return False, "裁切失败", []
    if len(attachments) == 1:
        attachments[0]["sampled"] = False
    return True, f"captured {len(attachments)} frame(s)", attachments
