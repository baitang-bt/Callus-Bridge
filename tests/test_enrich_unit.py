"""Unit tests for optional inbound enrich (mocked voice/capture)."""

from __future__ import annotations

import sys
import types


def _install_stubs() -> None:
    """Stub Linux-only deps so agent.enrich imports on macOS hosts."""
    if "pyatspi" not in sys.modules:
        sys.modules["pyatspi"] = types.ModuleType("pyatspi")
    if "Xlib" not in sys.modules:
        xlib = types.ModuleType("Xlib")
        xlib.X = types.SimpleNamespace()
        xlib.display = types.ModuleType("Xlib.display")
        xlib.ext = types.ModuleType("Xlib.ext")
        sys.modules["Xlib"] = xlib
        sys.modules["Xlib.display"] = xlib.display
        sys.modules["Xlib.ext"] = xlib.ext
        sys.modules["Xlib.ext.xtest"] = types.ModuleType("Xlib.ext.xtest")
        sys.modules["Xlib.ext.composite"] = types.ModuleType("Xlib.ext.composite")


_install_stubs()

from agent import enrich  # noqa: E402


def test_enrich_voice_replaces_placeholder(monkeypatch) -> None:
    """Voice rows pick up transcript text when the menu probe succeeds."""
    monkeypatch.setattr(
        enrich.message_actions,
        "voice_to_text",
        lambda chat, index: (True, "ok", "你好啊"),
    )
    out = enrich.enrich_inbound_message(
        {"chat": "c", "index": 1, "content_type": "voice", "text": "[语音]"}
    )
    assert out["text"] == "你好啊"


def test_enrich_voice_transcript_writes_text(monkeypatch) -> None:
    """Dedicated voice helper writes STT text onto a placeholder row."""
    monkeypatch.setattr(
        enrich.message_actions,
        "voice_to_text",
        lambda chat, index: (True, "ok", "转写正文"),
    )
    out = enrich.enrich_voice_transcript(
        {"chat": "c", "index": 1, "content_type": "voice", "text": "[语音]"}
    )
    assert out["text"] == "转写正文"


def test_enrich_voice_transcript_keeps_placeholder_when_empty(monkeypatch) -> None:
    """Empty STT leaves the voice placeholder so the host can skip voice_empty."""
    monkeypatch.setattr(
        enrich.message_actions,
        "voice_to_text",
        lambda chat, index: (True, "已点 转文字 但未读到转写文本", ""),
    )
    src = {"chat": "c", "index": 4, "content_type": "voice", "text": "[语音]"}
    out = enrich.enrich_voice_transcript(src)
    assert out["text"] == "[语音]"
    assert out["content_type"] == "voice"


def test_enrich_image_fills_attachments(monkeypatch) -> None:
    """Image rows without attachments get a capture fill when available."""
    item = {"kind": "image", "path": "/tmp/x.png", "sha256": "abc", "sampled": False}
    monkeypatch.setattr(
        enrich.capture,
        "capture_message_media",
        lambda chat, index, **kw: (True, "ok", [item]),
    )
    out = enrich.enrich_inbound_message(
        {"chat": "c", "index": 2, "content_type": "image", "text": "[图片]", "attachments": []}
    )
    assert out["attachments"] == [item]


def test_enrich_media_attachments_passes_kind(monkeypatch) -> None:
    """Dedicated media helper tags capture with the row content_type."""
    seen: dict[str, str] = {}

    def _cap(chat, index, **kw):
        seen["kind"] = str(kw.get("kind") or "")
        return (
            True,
            "ok",
            [{"kind": kw.get("kind") or "emotion", "path": "/tmp/e.png", "sha256": "x"}],
        )

    monkeypatch.setattr(enrich.capture, "capture_message_media", _cap)
    out = enrich.enrich_media_attachments(
        {"chat": "c", "index": 5, "content_type": "image", "text": "[图片]"}
    )
    assert seen["kind"] == "image"
    assert out["attachments"][0]["kind"] == "image"


def test_enrich_failures_keep_placeholder(monkeypatch) -> None:
    """Capture/voice errors leave the original row intact."""
    monkeypatch.setattr(
        enrich.message_actions,
        "voice_to_text",
        lambda chat, index: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    src = {"chat": "c", "index": 3, "content_type": "voice", "text": "[语音]"}
    out = enrich.enrich_inbound_message(src)
    assert out["text"] == "[语音]"


def test_enrich_skips_plain_text(monkeypatch) -> None:
    """Plain text rows never open menus or capture."""
    called = {"v": 0, "c": 0}

    def _voice(*a, **k):
        called["v"] += 1
        return False, "no", ""

    def _cap(*a, **k):
        called["c"] += 1
        return False, "no", []

    monkeypatch.setattr(enrich.message_actions, "voice_to_text", _voice)
    monkeypatch.setattr(enrich.capture, "capture_message_media", _cap)
    out = enrich.enrich_inbound_message(
        {"chat": "c", "index": 0, "content_type": "text", "text": "hi"}
    )
    assert out["text"] == "hi"
    assert called == {"v": 0, "c": 0}
