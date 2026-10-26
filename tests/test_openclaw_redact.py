"""Unit tests for openclaw log redaction helpers."""

from __future__ import annotations

from openclaw.redact import (
    redact_body,
    redact_token,
    redact_url,
    safe_exc,
    scrub_message,
    truncate,
)


def test_redact_token_none_and_prefix() -> None:
    """Empty token is (none); longer tokens keep a short prefix and length."""
    assert redact_token(None) == "(none)"
    assert redact_token("") == "(none)"
    assert redact_token("abcdef123456") == "abcdef…(len=12)"
    assert redact_token("abc") == "****(len=3)"


def test_redact_body_masks_sensitive_json() -> None:
    """Sensitive JSON string values become <redacted> before truncate."""
    body = '{"context_token":"secret-ctx","text":"hi","bot_token":"btok"}'
    out = redact_body(body, max_len=500)
    assert "secret-ctx" not in out
    assert "btok" not in out
    assert "<redacted>" in out
    assert '"text":"hi"' in out


def test_redact_body_truncates_with_total_len() -> None:
    """Long bodies are truncated with totalLen marker."""
    body = '{"text":"' + ("x" * 400) + '"}'
    out = redact_body(body, max_len=50)
    assert "truncated" in out
    assert "totalLen=" in out


def test_redact_url_strips_query() -> None:
    """Query string is removed from logged URLs."""
    assert (
        redact_url("https://cdn.example/c2c/download?encrypted_query_param=SECRET")
        == "https://cdn.example/c2c/download?"
    )
    assert redact_url("https://cdn.example/path") == "https://cdn.example/path"


def test_truncate_and_scrub_message() -> None:
    """truncate reports original length; scrub_message masks JSON tokens."""
    assert truncate("abcdef", 3) == "abc…(len=6)"
    msg = scrub_message('fail "token":"abc123secret" ok')
    assert "abc123secret" not in msg
    assert "<redacted>" in msg


def test_safe_exc_categories() -> None:
    """safe_exc exposes type and coarse category only."""
    from openclaw.cdn import SizeLimitError

    assert safe_exc(SizeLimitError("download exceeds size limit")) == (
        "SizeLimitError:size_limit"
    )
    assert "missing_source" in safe_exc(RuntimeError("CDN media missing download URL"))
