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
MAX_CAPTURE_BYTES = 20 * 1024 * 1024


def _media_root() -> Path:
    """Ensure the capture directory exists and return it."""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return MEDIA_DIR


def _sha256_bytes(data: bytes) -> str:
    """Hash raw image bytes for attachment identity."""
    return hashlib.sha256(data).hexdigest()


def _save_png(image, stem: str) -> tuple[str, str]:
    """Write a PNG via ``.part`` then rename; enforce size cap; return (path, sha256)."""
    import io

    raw = image.convert("RGB")
    buf = io.BytesIO()
    raw.save(buf, format="PNG")
    data = buf.getvalue()
    if len(data) > MAX_CAPTURE_BYTES:
        raise RuntimeError(f"capture exceeds {MAX_CAPTURE_BYTES} bytes")
    digest = _sha256_bytes(data)
    final = _media_root() / f"{stem}_{digest[:16]}.png"
    part = final.with_suffix(final.suffix + ".part")
    try:
        part.write_bytes(data)
        written = part.read_bytes()
        if len(written) != len(data) or _sha256_bytes(written) != digest:
            raise RuntimeError("part file failed size/hash verification")
        part.replace(final)
    except Exception:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return str(final), digest


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


def merge_older_batch(ordered_ids: list[str], by_id: dict, batch: list[dict]) -> list[str]:
    """Prepend newly seen rows from an upward-scroll window.

    ``index`` is only valid inside one visible window, so we never sort by it.
    ``batch`` is old→new (top of the list first). Ids not yet in ``by_id`` are
    older messages revealed by Page_Up and go in front, keeping batch order.
    """
    before_ids = set(by_id)
    new_ids: list[str] = []
    for msg in batch:
        mid = msg["id"]
        by_id[mid] = msg
        if mid not in before_ids:
            new_ids.append(mid)
    if not new_ids:
        return ordered_ids
    known = [mid for mid in ordered_ids if mid not in set(new_ids)]
    return new_ids + known


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
    ordered_ids = [m["id"] for m in messages]
    stagnant = 0
    while len(ordered_ids) < limit and stagnant < 3:
        rect = geometry.node_physical_rect("list", chat.MESSAGE_LIST)
        if rect is None:
            break
        x, y, w, h = rect
        inputmod.click_at(x + w // 2, y + h // 2)
        time.sleep(0.12)
        inputmod.tap_key("Page_Up")
        time.sleep(0.35)
        _n, batch = chat.list_messages(chat=name, limit=0)
        before = len(ordered_ids)
        ordered_ids = merge_older_batch(ordered_ids, by_id, batch)
        if len(ordered_ids) == before:
            stagnant += 1
        else:
            stagnant = 0

    ordered = [by_id[mid] for mid in ordered_ids if mid in by_id]
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
