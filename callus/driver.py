"""Host-facing capture contract. Implementations wrap the WeJam-compatible Client."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class MediaRef:
    """One local media file produced by the bridge."""

    kind: str
    path: str
    sha256: str = ""
    sampled: bool = False
    frame_index: int = 0


@dataclass(frozen=True)
class SeenCapture:
    """One observed message with optional attachments."""

    chat: str
    text: str
    sender: str = ""
    from_self: bool = False
    preview: bool = False
    chat_type: str = ""
    unread: int = 0
    message_id: str = ""
    content_type: str = "text"
    index: int = 0
    stable_id: str = ""
    attachments: tuple[MediaRef, ...] = field(default_factory=tuple)


@runtime_checkable
class CaptureDriver(Protocol):
    """Read/write surface matching the bridge Client, plus Callus capture calls.

    Existing WeJam Client methods stay available on concrete adapters so a host
    can swap bridge addresses without rewriting the chat brain.
    """

    def list_chats(self):
        """Return the session list response (wire-compatible)."""

    def list_messages(self, chat: str = "", limit: int = 0):
        """Return the visible window (wire-compatible)."""

    def watch_messages(self, chat: str = "", timeout=None) -> Iterator:
        """Yield MessageEvent values (wire-compatible)."""

    def send_text(self, chat: str, text: str):
        """Send one text bubble (wire-compatible)."""

    def read_latest(self, chat: str = "") -> SeenCapture | None:
        """Return the newest bubble including sender; no scroll wait."""

    def read_context(self, chat: str = "", limit: int = 0) -> list[SeenCapture]:
        """Scroll and return up to ``limit`` messages; limit is caller-owned."""

    def capture_message_media(
        self,
        chat: str,
        index: int,
        max_frames: int = 0,
        interval_ms: int = 0,
    ) -> list[MediaRef]:
        """Crop bubble media for one message index."""

    def close(self) -> None:
        """Release the transport."""
