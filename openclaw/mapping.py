"""Map openclaw JSON messages onto wejam-shaped dicts used by the servicer."""

from __future__ import annotations

import hashlib
import time
from typing import Any


ITEM_TYPE_TEXT = 1
ITEM_TYPE_IMAGE = 2
ITEM_TYPE_VOICE = 3
ITEM_TYPE_FILE = 4
ITEM_TYPE_VIDEO = 5

_CONTENT_BY_TYPE = {
    ITEM_TYPE_IMAGE: ("image", "[图片]"),
    ITEM_TYPE_VOICE: ("voice", "[语音]"),
    ITEM_TYPE_FILE: ("file", "[文件]"),
    ITEM_TYPE_VIDEO: ("video", "[视频]"),
}


def display_chat_name(user_id: str, aliases: dict[str, str]) -> str:
    """Prefer alias display name; fall back to ilink user id."""
    return aliases.get(user_id, user_id)


def resolve_user_id(chat: str, aliases: dict[str, str]) -> str:
    """Map allowlist / SendText chat name back to ilink user id."""
    needle = (chat or "").strip()
    if not needle:
        return ""
    for user_id, name in aliases.items():
        if name == needle:
            return user_id
    return needle


def text_from_item_list(item_list: list[Any]) -> tuple[str, str]:
    """Extract (text, content_type) from an openclaw item_list."""
    texts: list[str] = []
    content_type = "text"
    for raw in item_list or []:
        if not isinstance(raw, dict):
            continue
        item_type = int(raw.get("type") or 0)
        if item_type == ITEM_TYPE_TEXT:
            text_item = raw.get("text_item") or {}
            piece = str(text_item.get("text") or "").strip()
            if piece:
                texts.append(piece)
            continue
        kind, placeholder = _CONTENT_BY_TYPE.get(item_type, ("text", "[消息]"))
        content_type = kind
        texts.append(placeholder)
    body = "\n".join(texts).strip()
    if not body:
        body = "[消息]"
        content_type = content_type if content_type != "text" else "text"
    return body, content_type


def inbound_to_message(
    msg: dict[str, Any],
    *,
    aliases: dict[str, str],
    account_id: str = "",
) -> dict[str, Any] | None:
    """Convert one getupdates msgs[] entry to an internal message dict."""
    from_user_id = str(msg.get("from_user_id") or "").strip()
    if not from_user_id:
        return None
    item_list = msg.get("item_list") if isinstance(msg.get("item_list"), list) else []
    text, content_type = text_from_item_list(item_list)
    message_id = str(msg.get("message_id") or msg.get("msg_id") or "").strip()
    if not message_id:
        message_id = hashlib.sha1(
            f"{from_user_id}|{text}|{msg.get('create_time_ms') or msg.get('create_time')}".encode()
        ).hexdigest()[:16]
    create = msg.get("create_time_ms") or msg.get("create_time")
    if isinstance(create, (int, float)) and create > 1_000_000_000_000:
        ts = int(create / 1000)
    elif isinstance(create, (int, float)):
        ts = int(create)
    else:
        ts = int(time.time())
    time_text = time.strftime("%H:%M", time.localtime(ts))
    chat = display_chat_name(from_user_id, aliases)
    from_self = bool(account_id) and from_user_id == account_id
    context_token = str(msg.get("context_token") or "").strip()
    return {
        "id": message_id,
        "user_id": from_user_id,
        "chat": chat,
        "sender": "",
        "text": text,
        "time_text": time_text,
        "kind": "TEXT",
        "index": 0,
        "preview_only": False,
        "from_self": from_self,
        "content_type": content_type,
        "context_token": context_token,
        "stable_id": from_user_id,
    }


def api_ok(payload: dict[str, Any]) -> bool:
    """True when ilink JSON does not report a hard errcode failure."""
    if not payload:
        return True
    if "errcode" in payload and payload.get("errcode") not in (0, None, "0"):
        try:
            if int(payload["errcode"]) != 0:
                return False
        except (TypeError, ValueError):
            return False
    ret = payload.get("ret")
    if ret not in (None, 0, "0"):
        try:
            if int(ret) != 0:
                return False
        except (TypeError, ValueError):
            pass
    return True
