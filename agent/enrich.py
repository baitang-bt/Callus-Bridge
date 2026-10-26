"""Optional inbound enrichment for GUI bridge (voice transcript / bubble crop)."""

from __future__ import annotations

import logging
from typing import Any

from . import capture, message_actions
from .redact import install_agent_log_filter, safe_exc

_log = logging.getLogger(__name__)
install_agent_log_filter()

_VOICE_PLACEHOLDERS = {"", "[语音]", "[消息]"}


def enrich_inbound_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy with GUI-side media/voice fills when cheap enough.

    Failures never raise: placeholders stay so Watch/List still deliver text rows.
    """
    out = dict(msg)
    content_type = (out.get("content_type") or "text").strip().lower() or "text"
    chat_name = out.get("chat") or ""
    index = int(out.get("index") or 0)

    if content_type == "voice" and (out.get("text") or "").strip() in _VOICE_PLACEHOLDERS:
        try:
            ok, detail, text = message_actions.voice_to_text(chat_name, index)
            if ok and text:
                out["text"] = text
            else:
                _log.info("voice_to_text skipped detail=%s", detail)
        except Exception as exc:
            _log.warning("voice_to_text failed err=%s", safe_exc(exc))

    if content_type in {"emotion", "image"} and not out.get("attachments"):
        try:
            ok, detail, items = capture.capture_message_media(chat_name, index)
            if ok and items:
                out["attachments"] = items
            else:
                _log.info("auto capture skipped detail=%s", detail)
        except Exception as exc:
            _log.warning("auto capture failed err=%s", safe_exc(exc))

    return out
