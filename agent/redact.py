# Copyright (c) Tencent openclaw-weixin contributors and nightsailer/wechat-clawbot.
# SPDX-License-Identifier: MIT
#
# Ported/adapted from:
#   https://github.com/Tencent/openclaw-weixin/blob/main/src/util/redact.ts
#   https://github.com/nightsailer/wechat-clawbot/blob/master/src/wechat_clawbot/util/redact.py
# Callus uses "<redacted>" as the JSON value placeholder (upstream used a space).

"""Sensitive-data masking helpers for safe Callus agent logging."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse, urlunparse

_DEFAULT_BODY_MAX_LEN = 200
_DEFAULT_TOKEN_PREFIX_LEN = 6

_SENSITIVE_FIELDS_RE = re.compile(
    r'"(context_token|bot_token|token|authorization|Authorization)"\s*:\s*"[^"]*"'
)

_URL_WITH_QUERY_RE = re.compile(r"(https?://[^\s\"']+)\?[^\s\"']*")


def truncate(s: str | None, max_len: int = _DEFAULT_BODY_MAX_LEN) -> str:
    """Truncate *s*, appending a length indicator when trimmed."""
    if not s:
        return ""
    if len(s) <= max_len:
        return s
    return f"{s[:max_len]}…(len={len(s)})"


def redact_token(token: str | None, prefix_len: int = _DEFAULT_TOKEN_PREFIX_LEN) -> str:
    """Show only the first few chars of a token plus its total length."""
    if not token:
        return "(none)"
    if len(token) <= prefix_len:
        return f"****(len={len(token)})"
    return f"{token[:prefix_len]}…(len={len(token)})"


def redact_body(body: str | None, max_len: int = _DEFAULT_BODY_MAX_LEN) -> str:
    """Redact known sensitive JSON fields, then truncate for safe logging."""
    if not body:
        return "(empty)"
    redacted = _SENSITIVE_FIELDS_RE.sub(r'"\1":"<redacted>"', body)
    if len(redacted) <= max_len:
        return redacted
    return f"{redacted[:max_len]}…(truncated, totalLen={len(redacted)})"


def redact_url(raw_url: str) -> str:
    """Strip query string from a URL, keeping only origin + pathname."""
    try:
        parsed = urlparse(raw_url)
        clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
        return f"{clean}?" if parsed.query else clean
    except Exception:
        return truncate(raw_url, 80)


def scrub_message(msg: str) -> str:
    """Best-effort scrub of a free-form log message (tokens JSON + URL queries)."""
    if not msg:
        return msg
    out = _SENSITIVE_FIELDS_RE.sub(r'"\1":"<redacted>"', msg)
    out = _URL_WITH_QUERY_RE.sub(lambda m: redact_url(m.group(0)), out)
    return out


def safe_exc(exc: BaseException) -> str:
    """Exception type plus a short category; never include URL or response bodies."""
    name = type(exc).__name__
    text = str(exc) or ""
    lower = text.lower()
    if "size" in lower or "limit" in lower or "too large" in lower:
        category = "size_limit"
    elif "aes" in lower or "key" in lower:
        category = "crypto_key"
    elif "missing" in lower and ("url" in lower or "media" in lower):
        category = "missing_source"
    elif "http" in lower or "status" in lower:
        category = "http"
    elif "timeout" in lower:
        category = "timeout"
    else:
        category = "error"
    return f"{name}:{category}"


class RedactingFilter(logging.Filter):
    """Scrub sensitive fragments from LogRecord messages before emit."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Mutate record.msg / args into a scrubbed, already-formatted message."""
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg = scrub_message(message)
        record.args = ()
        return True


def install_agent_log_filter() -> None:
    """Attach RedactingFilter to the agent package logger (idempotent)."""
    logger = logging.getLogger("agent")
    for existing in logger.filters:
        if isinstance(existing, RedactingFilter):
            return
    logger.addFilter(RedactingFilter())
