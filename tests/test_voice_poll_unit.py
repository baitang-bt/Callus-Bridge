"""Unit tests for voice_to_text bubble polling (mocked a11y / clipboard)."""

from __future__ import annotations

import sys
import types


def _install_stubs() -> None:
    """Stub Linux-only deps so agent.message_actions imports on macOS hosts."""
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

from agent import message_actions  # noqa: E402


def test_poll_voice_transcript_waits_for_bubble_text(monkeypatch) -> None:
    """Poller keeps reading until a11y shows a non-placeholder transcript."""
    reads = {"n": 0}

    def _bubble(chat, index):
        reads["n"] += 1
        if reads["n"] < 3:
            return "[语音]"
        return "你好啊"

    monkeypatch.setattr(message_actions, "_bubble_text_at", _bubble)
    monkeypatch.setattr(message_actions.time, "sleep", lambda *_a, **_k: None)
    out = message_actions._poll_voice_transcript("c", 1, attempts=5, interval_s=0.01)
    assert out == "你好啊"
    assert reads["n"] == 3


def test_poll_voice_transcript_empty_after_attempts(monkeypatch) -> None:
    """Poller returns empty when every bubble read stays a placeholder."""
    monkeypatch.setattr(
        message_actions, "_bubble_text_at", lambda chat, index: "[语音]"
    )
    monkeypatch.setattr(message_actions.time, "sleep", lambda *_a, **_k: None)
    out = message_actions._poll_voice_transcript("c", 2, attempts=3, interval_s=0.01)
    assert out == ""
