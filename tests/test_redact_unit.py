"""Unit tests for agent.redact (no WeChat / network)."""

from __future__ import annotations

import logging

from agent.redact import (
    RedactingFilter,
    install_agent_log_filter,
    redact_body,
    redact_token,
    scrub_message,
)


def test_redact_token_prefix() -> None:
    """Tokens show a short prefix and total length only."""
    assert redact_token("abcdef123456") == "abcdef…(len=12)"
    assert redact_token("") == "(none)"


def test_redact_body_masks_sensitive_json() -> None:
    """Known JSON auth fields become <redacted> before truncate."""
    body = '{"token":"sekrit","ok":true}'
    out = redact_body(body, max_len=200)
    assert "sekrit" not in out
    assert "<redacted>" in out


def test_scrub_message_strips_url_query() -> None:
    """Query strings are dropped from logged URLs."""
    msg = 'fetch https://cdn.example/x?token=abc&sig=1 done'
    out = scrub_message(msg)
    assert "token=abc" not in out
    assert "https://cdn.example/x?" in out


def test_install_agent_log_filter_idempotent() -> None:
    """Filter attaches once to the agent logger."""
    install_agent_log_filter()
    install_agent_log_filter()
    logger = logging.getLogger("agent")
    assert sum(1 for f in logger.filters if isinstance(f, RedactingFilter)) == 1
