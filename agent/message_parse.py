"""纯消息解析：发送者 / 自发侧 / 稳定 id（不依赖真实 AT-SPI 连接）。

结构思路对照 [cluic/wxauto](https://github.com/cluic/wxauto)（Windows UI Automation）：
头像 Button 名 → 发送者；头像相对气泡中线左右 → 是否自己；控件稳定标识 → id。
本模块只接受已抽出的名字与矩形，便于单测；不复制 wxauto 源码。
"""

from __future__ import annotations

import hashlib
from typing import Sequence

from .sender_name import is_plausible_sender_name

# Rect = (x, y, width, height) in any consistent coordinate space.
Rect = tuple[float, float, float, float]


def split_sender_and_text(
    raw: str,
    button_names: Sequence[str] = (),
) -> tuple[str, str]:
    """Pick sender/body for one bubble row.

    Prefer the first plausible avatar button name (wxauto-style); otherwise
    fall back to splitting on the first newline.
    """
    text = (raw or "").replace("\u00a0", " ").strip()
    if not text:
        return "", ""
    for name in button_names:
        cand = (name or "").strip()
        if not is_plausible_sender_name(cand):
            continue
        # Body is the row text with the sender line removed when present.
        body = text
        if body.startswith(cand):
            rest = body[len(cand) :].lstrip("\n").strip()
            if rest:
                body = rest
        return cand, body
    if "\n" in text:
        first, rest = text.split("\n", 1)
        cand = first.strip()
        if is_plausible_sender_name(cand) and rest.strip():
            return cand, rest.strip()
    return "", text


def avatar_side_is_self(
    bubble: Rect | None,
    avatar: Rect | None,
) -> bool | None:
    """Return True when the avatar sits on the right half of the bubble.

    None when either rect is missing or the centers are tied (cannot tell).
    """
    if bubble is None or avatar is None:
        return None
    _bx, _by, bw, _bh = bubble
    ax, _ay, aw, _ah = avatar
    if bw <= 0 or aw < 0:
        return None
    bubble_mid = _bx + bw / 2.0
    avatar_mid = ax + aw / 2.0
    if abs(avatar_mid - bubble_mid) < 1.0:
        return None
    return avatar_mid > bubble_mid


def message_id(
    chat: str,
    *,
    bucket: str,
    text: str,
    bucket_index: int,
    node_key: str | None = None,
) -> str:
    """Build a 16-hex message id.

    Prefer a per-node stable key (AT-SPI path / object id) when present;
    otherwise sha1(chat|bucket|text|n) — never the list index alone.
    """
    if node_key:
        digest = hashlib.sha1(f"{chat}|node|{node_key}".encode()).hexdigest()
        return digest[:16]
    key = f"{chat}|{bucket}|{text}|{bucket_index}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]
