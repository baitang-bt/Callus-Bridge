"""Unit tests for capture helpers that do not need a live WeChat UI."""

from __future__ import annotations

import hashlib
import sys
import types
from pathlib import Path


def _install_stubs() -> None:
    """Stub Linux-only deps so agent.capture imports on macOS hosts."""
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

from agent import capture  # noqa: E402


def test_sha256_bytes_stable() -> None:
    """Hash helper is deterministic for identical payloads."""
    payload = b"callus-frame"
    assert capture._sha256_bytes(payload) == hashlib.sha256(payload).hexdigest()


def test_save_png_writes_under_media_dir(tmp_path: Path, monkeypatch) -> None:
    """PNG crops land under CALLUS_MEDIA_DIR with a content hash in the name."""
    from PIL import Image

    monkeypatch.setenv("CALLUS_MEDIA_DIR", str(tmp_path))
    capture.MEDIA_DIR = tmp_path
    img = Image.new("RGB", (8, 8), color=(10, 20, 30))
    path, digest = capture._save_png(img, "unit")
    assert Path(path).is_file()
    assert Path(path).parent == tmp_path
    assert digest == capture._sha256_bytes(img.convert("RGB").tobytes())
    assert digest[:16] in Path(path).name


def test_merge_older_batch_prepends_without_using_index() -> None:
    """Upward scroll reveals older ids; they go in front, not by window index."""
    by_id = {
        "mid": {"id": "mid", "index": 0, "text": "m"},
        "new": {"id": "new", "index": 1, "text": "n"},
    }
    ordered = ["mid", "new"]
    batch = [
        {"id": "old1", "index": 0, "text": "o1"},
        {"id": "old2", "index": 1, "text": "o2"},
        {"id": "mid", "index": 2, "text": "m2"},
        {"id": "new", "index": 3, "text": "n2"},
    ]
    merged = capture.merge_older_batch(ordered, by_id, batch)
    assert merged == ["old1", "old2", "mid", "new"]
    assert by_id["mid"]["text"] == "m2"
    assert capture.merge_older_batch(merged, by_id, batch) == merged
