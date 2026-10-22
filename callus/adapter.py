"""CaptureDriver adapter over the wire-compatible wejam.Client."""

from __future__ import annotations

from collections.abc import Iterator

from callus.driver import MediaRef, SeenCapture
from wejam.client import Client


def _attachments(msg) -> tuple[MediaRef, ...]:
    """Copy MediaAttachment protobuf rows into MediaRef values."""
    out: list[MediaRef] = []
    for row in getattr(msg, "attachments", ()) or ():
        out.append(
            MediaRef(
                kind=str(getattr(row, "kind", "") or ""),
                path=str(getattr(row, "path", "") or ""),
                sha256=str(getattr(row, "sha256", "") or ""),
                sampled=bool(getattr(row, "sampled", False)),
                frame_index=int(getattr(row, "frame_index", 0) or 0),
            )
        )
    return tuple(out)


def _seen(msg, chat_type: str = "") -> SeenCapture:
    """Map one wire Message onto SeenCapture."""
    return SeenCapture(
        chat=str(getattr(msg, "chat", "") or ""),
        text=str(getattr(msg, "text", "") or ""),
        sender=str(getattr(msg, "sender", "") or ""),
        from_self=bool(getattr(msg, "from_self", False)),
        preview=bool(getattr(msg, "preview_only", False)),
        chat_type=chat_type,
        message_id=str(getattr(msg, "id", "") or ""),
        content_type=str(getattr(msg, "content_type", "") or "text"),
        index=int(getattr(msg, "index", 0) or 0),
        stable_id=str(getattr(msg, "stable_id", "") or ""),
        attachments=_attachments(msg),
    )


class CallusClient:
    """wejam.Client plus CaptureDriver methods. Same target address as WeJam."""

    def __init__(self, target: str | None = None, timeout: int = 30) -> None:
        """Open a channel to a Callus (or WeJam-compatible) bridge."""
        self._client = Client(target=target, timeout=timeout)

    def close(self) -> None:
        """Close the gRPC channel."""
        self._client.close()

    def __enter__(self) -> CallusClient:
        """Enter the context manager."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close on exit."""
        self.close()

    def list_chats(self):
        """Wire-compatible ListChats."""
        return self._client.list_chats()

    def list_messages(self, chat: str = "", limit: int = 0):
        """Wire-compatible ListMessages."""
        return self._client.list_messages(chat=chat, limit=limit)

    def watch_messages(self, chat: str = "", timeout=None) -> Iterator:
        """Wire-compatible WatchMessages."""
        return self._client.watch_messages(chat=chat, timeout=timeout)

    def send_text(self, chat: str, text: str):
        """Wire-compatible SendText."""
        return self._client.send_text(chat, text)

    def login_state(self):
        """Wire-compatible GetLoginState."""
        return self._client.login_state()

    def qr_code(self):
        """Wire-compatible GetLoginQRCode."""
        return self._client.qr_code()

    def status(self):
        """Wire-compatible GetStatus."""
        return self._client.status()

    def read_latest(self, chat: str = "") -> SeenCapture | None:
        """Newest bubble including sender."""
        resp = self._client.read_latest(chat=chat)
        msg = getattr(resp, "message", None)
        if msg is None or not str(getattr(msg, "id", "") or ""):
            return None
        return _seen(msg, chat_type=str(getattr(resp, "chat_type", "") or ""))

    def read_context(self, chat: str = "", limit: int = 0) -> list[SeenCapture]:
        """Scroll-collect messages; ``limit`` comes from the host console."""
        resp = self._client.read_context(chat=chat, limit=limit)
        chat_type = str(getattr(resp, "chat_type", "") or "")
        return [_seen(m, chat_type=chat_type) for m in getattr(resp, "messages", ()) or ()]

    def capture_message_media(
        self,
        chat: str,
        index: int,
        max_frames: int = 0,
        interval_ms: int = 0,
    ) -> list[MediaRef]:
        """Crop bubble frames for one message."""
        resp = self._client.capture_message_media(
            chat, index, max_frames=max_frames, interval_ms=interval_ms
        )
        if not bool(getattr(resp, "ok", False)):
            return []
        return [
            MediaRef(
                kind=str(getattr(row, "kind", "") or ""),
                path=str(getattr(row, "path", "") or ""),
                sha256=str(getattr(row, "sha256", "") or ""),
                sampled=bool(getattr(row, "sampled", False)),
                frame_index=int(getattr(row, "frame_index", 0) or 0),
            )
            for row in getattr(resp, "attachments", ()) or ()
        ]
