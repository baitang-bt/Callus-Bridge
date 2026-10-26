"""In-process openclaw session: login phases, inbox, send, chat list."""

from __future__ import annotations

import collections
import logging
import threading
import time
import uuid
from typing import Any, Callable

from openclaw import DEFAULT_BASE_URL, DEFAULT_BOT_TYPE
from openclaw.client import OpenClawClient
from openclaw.mapping import (
    api_ok,
    display_chat_name,
    inbound_to_message,
    resolve_user_id,
)
from openclaw.redact import install_openclaw_log_filter, redact_token, safe_exc
from openclaw.store import OpenClawStore

_log = logging.getLogger(__name__)
install_openclaw_log_filter()

PHASE_STARTING = "starting"
PHASE_QR_READY = "qr_ready"
PHASE_WAIT_PHONE = "wait_phone"
PHASE_LOGGED_IN = "logged_in"
PHASE_UNKNOWN = "unknown"


class OpenClawRuntime:
    """Owns login state and a background getupdates poller."""

    def __init__(
        self,
        store: OpenClawStore | None = None,
        *,
        bot_type: str = DEFAULT_BOT_TYPE,
        poll_qr_seconds: float = 1.5,
        client_factory: Callable[[str, str | None], OpenClawClient] | None = None,
    ) -> None:
        self.store = store or OpenClawStore()
        self.bot_type = bot_type
        self.poll_qr_seconds = poll_qr_seconds
        self._client_factory = client_factory or (
            lambda base, token: OpenClawClient(base_url=base, token=token)
        )
        self._lock = threading.RLock()
        self._started_at = time.time()
        self._phase = PHASE_STARTING
        self._detail = ""
        self._markers: list[str] = []
        self._phase_since_ms = int(time.time() * 1000)
        self._qr_handle = ""
        self._qr_payload = ""
        self._qr_revision = ""
        self._qr_fetched_ms = 0
        self._token = ""
        self._account_id = ""
        self._base_url = DEFAULT_BASE_URL
        self._sync_buf = ""
        self._context_tokens: dict[str, str] = {}
        self._chats: dict[str, dict[str, Any]] = {}
        self._recent: dict[str, list[dict[str, Any]]] = {}
        self._inbox: collections.deque[dict[str, Any]] = collections.deque(maxlen=500)
        self._login_subs: list[collections.deque] = []
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._load_persisted()

    def _load_persisted(self) -> None:
        """Hydrate token/sync/chats from disk."""
        state = self.store.load_state()
        self._token = str(state.get("token") or "").strip()
        self._account_id = str(state.get("account_id") or "").strip()
        base = str(state.get("base_url") or "").strip()
        if base:
            self._base_url = base.rstrip("/")
        self._sync_buf = str(state.get("sync_buf") or "")
        tokens = state.get("context_tokens") or {}
        if isinstance(tokens, dict):
            self._context_tokens = {
                str(k).strip(): str(v).strip()
                for k, v in tokens.items()
                if str(k).strip() and str(v).strip()
            }
        chats = state.get("chats") or {}
        if isinstance(chats, dict):
            self._chats = {str(k): v for k, v in chats.items() if isinstance(v, dict)}
        if self._token:
            self._set_phase(PHASE_LOGGED_IN, "restored token", ["openclaw"])
        else:
            self._set_phase(PHASE_STARTING, "need qr", [])

    def _persist(self) -> None:
        """Write current session fields to state.json."""
        self.store.save_state(
            {
                "token": self._token,
                "account_id": self._account_id,
                "user_id": self._account_id,
                "base_url": self._base_url,
                "sync_buf": self._sync_buf,
                "context_tokens": dict(self._context_tokens),
                "chats": dict(self._chats),
            }
        )

    def _client(self) -> OpenClawClient:
        """HTTP client bound to current base_url and token."""
        return self._client_factory(self._base_url, self._token or None)

    def _aliases(self) -> dict[str, str]:
        """Reload aliases each call so edits apply without restart."""
        return self.store.load_aliases()

    def _set_phase(self, phase: str, detail: str, markers: list[str]) -> None:
        """Update login phase and notify WatchLogin subscribers."""
        with self._lock:
            if phase != self._phase:
                self._phase_since_ms = int(time.time() * 1000)
            self._phase = phase
            self._detail = detail
            self._markers = list(markers)
            snap = self.snapshot()
            for q in list(self._login_subs):
                q.append(snap)

    def snapshot(self) -> dict[str, Any]:
        """Login snapshot compatible with GUI agent machine shape."""
        with self._lock:
            return {
                "phase": self._phase,
                "detail": self._detail,
                "markers": list(self._markers),
                "since_unix_ms": self._phase_since_ms,
            }

    def uptime_ms(self) -> int:
        """Milliseconds since this runtime was constructed."""
        return int((time.time() - self._started_at) * 1000)

    def subscribe_login(self) -> collections.deque:
        """Register for login phase snapshots."""
        q: collections.deque = collections.deque(maxlen=32)
        with self._lock:
            self._login_subs.append(q)
            q.append(self.snapshot())
        return q

    def unsubscribe_login(self, q: collections.deque) -> None:
        """Drop a login subscriber queue."""
        with self._lock:
            if q in self._login_subs:
                self._login_subs.remove(q)

    def start(self) -> None:
        """Start QR refresh and getupdates background threads."""
        if self._threads:
            return
        self._stop.clear()
        t_login = threading.Thread(target=self._login_loop, name="openclaw-login", daemon=True)
        t_poll = threading.Thread(target=self._updates_loop, name="openclaw-updates", daemon=True)
        self._threads = [t_login, t_poll]
        t_login.start()
        t_poll.start()

    def stop(self) -> None:
        """Signal background threads to exit."""
        self._stop.set()

    def _login_loop(self) -> None:
        """Keep a fresh QR while logged out; poll status while waiting."""
        while not self._stop.is_set():
            try:
                with self._lock:
                    phase = self._phase
                    token = self._token
                if token:
                    time.sleep(2.0)
                    continue
                if phase in (PHASE_STARTING, PHASE_UNKNOWN) or (
                    phase == PHASE_QR_READY and not self._qr_handle
                ):
                    self._refresh_qr()
                elif phase in (PHASE_QR_READY, PHASE_WAIT_PHONE) and self._qr_handle:
                    self._poll_qr_once()
                else:
                    time.sleep(self.poll_qr_seconds)
            except Exception as exc:
                _log.warning("openclaw login loop error err=%s", safe_exc(exc))
                self._set_phase(PHASE_UNKNOWN, "login loop error", [])
                time.sleep(3.0)

    def _refresh_qr(self) -> None:
        """Fetch a new bot QR from ilink."""
        data = self._client().get_bot_qrcode(self.bot_type)
        handle = str(data.get("qrcode") or "").strip()
        payload = str(data.get("qrcode_img_content") or "").strip()
        if not handle or not payload:
            self._set_phase(PHASE_UNKNOWN, "qr response incomplete", [])
            time.sleep(3.0)
            return
        with self._lock:
            self._qr_handle = handle
            self._qr_payload = payload
            self._qr_revision = hashlib_revision(payload)
            self._qr_fetched_ms = int(time.time() * 1000)
        self._set_phase(PHASE_QR_READY, "scan with mobile WeChat", ["openclaw", "qr"])

    def _poll_qr_once(self) -> None:
        """One get_qrcode_status round; promote to logged-in on confirmed."""
        handle = self._qr_handle
        if not handle:
            return
        data = self._client().get_qrcode_status(handle)
        status = str(data.get("status") or "wait").strip()
        if status == "confirmed":
            token = str(data.get("bot_token") or "").strip()
            account = str(data.get("ilink_bot_id") or "").strip()
            base = str(data.get("baseurl") or "").strip()
            if not token:
                self._set_phase(PHASE_UNKNOWN, "confirmed without token", [])
                return
            with self._lock:
                self._token = token
                self._account_id = account
                if base:
                    self._base_url = base.rstrip("/")
                self._qr_handle = ""
                self._qr_payload = ""
                self._persist()
            self._set_phase(PHASE_LOGGED_IN, "openclaw logged in", ["openclaw"])
            return
        if status == "expired":
            with self._lock:
                self._qr_handle = ""
                self._qr_payload = ""
            self._set_phase(PHASE_STARTING, "qr expired", [])
            return
        if status in {"cancel", "canceled", "denied"}:
            with self._lock:
                self._qr_handle = ""
                self._qr_payload = ""
            self._set_phase(PHASE_STARTING, "qr cancelled", [])
            return
        if status not in {"wait", "scanned", ""}:
            self._set_phase(PHASE_WAIT_PHONE, status, ["openclaw"])
        elif status == "scanned":
            self._set_phase(PHASE_WAIT_PHONE, "scanned, confirm on phone", ["openclaw"])
        time.sleep(self.poll_qr_seconds)

    def apply_updates(self, data: dict[str, Any]) -> int:
        """Ingest one getupdates JSON body; return how many msgs were queued.

        Used by the poller and by unit tests. Persists sync cursor and any
        context_token values needed for later SendText. CDN downloads run
        outside the session lock so long polls stay responsive.
        """
        if not api_ok(data):
            err = data.get("errcode", data.get("ret"))
            _log.warning(
                "getupdates errcode=%s token=%s",
                err,
                redact_token(self._token),
            )
            if err in (-14, "-14"):
                self.logout_local("session timeout")
            return 0
        new_buf = data.get("get_updates_buf")
        msgs = data.get("msgs") if isinstance(data.get("msgs"), list) else []
        aliases = self._aliases()
        with self._lock:
            if new_buf:
                self._sync_buf = str(new_buf)
            account_id = self._account_id
        media_root = self.store.media_dir()
        mapped_rows: list[dict[str, Any]] = []
        for raw in msgs:
            if not isinstance(raw, dict):
                continue
            mapped = inbound_to_message(
                raw,
                aliases=aliases,
                account_id=account_id,
                media_root=media_root,
            )
            if mapped is not None:
                mapped_rows.append(mapped)
        with self._lock:
            for mapped in mapped_rows:
                uid = mapped["user_id"]
                ctx = mapped.get("context_token") or ""
                if ctx:
                    self._context_tokens[uid] = ctx
                self._remember_chat(mapped)
                self._recent.setdefault(uid, []).append(mapped)
                self._recent[uid] = self._recent[uid][-50:]
                self._inbox.append(mapped)
            self._persist()
        return len(mapped_rows)

    def _updates_loop(self) -> None:
        """Long-poll getupdates while logged in."""
        while not self._stop.is_set():
            try:
                with self._lock:
                    token = self._token
                    sync_buf = self._sync_buf
                if not token:
                    time.sleep(1.0)
                    continue
                data = self._client().get_updates(sync_buf)
                if not api_ok(data):
                    self.apply_updates(data)
                    time.sleep(5.0)
                    continue
                self.apply_updates(data)
            except Exception as exc:
                _log.warning("openclaw updates loop error err=%s", safe_exc(exc))
                time.sleep(5.0)

    def _remember_chat(self, mapped: dict[str, Any]) -> None:
        """Update chat list preview row for ListChats."""
        uid = mapped["user_id"]
        self._chats[uid] = {
            "user_id": uid,
            "name": mapped["chat"],
            "last_message": mapped["text"],
            "last_time": mapped["time_text"],
            "unread_count": 0 if mapped.get("from_self") else 1,
            "pinned": False,
            "muted": False,
        }

    def qr(self) -> dict[str, Any]:
        """Current QR payload for GetLoginQRCode."""
        with self._lock:
            return {
                "payload": self._qr_payload,
                "revision": self._qr_revision,
                "fetched_unix_ms": self._qr_fetched_ms,
            }

    def list_chats(self) -> list[dict[str, Any]]:
        """Session rows derived from inbound traffic + aliases."""
        aliases = self._aliases()
        with self._lock:
            rows = []
            for uid, row in self._chats.items():
                name = display_chat_name(uid, aliases)
                rows.append(
                    {
                        "name": name,
                        "last_message": row.get("last_message", ""),
                        "last_time": row.get("last_time", ""),
                        "unread_count": int(row.get("unread_count") or 0),
                        "pinned": bool(row.get("pinned")),
                        "muted": bool(row.get("muted")),
                    }
                )
            return rows

    def list_messages(self, chat: str, limit: int = 0) -> tuple[str, list[dict[str, Any]]]:
        """Return recent cached messages for a chat (by alias or id)."""
        aliases = self._aliases()
        uid = resolve_user_id(chat, aliases)
        with self._lock:
            msgs = list(self._recent.get(uid, []))
        if limit and limit > 0:
            msgs = msgs[-limit:]
        name = display_chat_name(uid, aliases) if uid else chat
        out = []
        for i, m in enumerate(msgs):
            item = dict(m)
            item["index"] = i
            item["chat"] = name
            out.append(item)
        return name, out

    def pop_inbox(self, timeout: float = 1.0) -> dict[str, Any] | None:
        """Block briefly for the next inbound mapped message."""
        deadline = time.time() + max(0.0, timeout)
        while time.time() < deadline:
            with self._lock:
                if self._inbox:
                    return self._inbox.popleft()
            time.sleep(0.05)
        return None

    def send_text(self, chat: str, text: str) -> tuple[bool, str]:
        """Send plain text; requires prior context_token for that user."""
        body = (text or "").strip()
        if not body:
            return False, "empty text"
        aliases = self._aliases()
        uid = resolve_user_id(chat, aliases)
        with self._lock:
            token = self._token
            ctx = self._context_tokens.get(uid, "")
        if not token:
            return False, "not logged in"
        if not uid:
            return False, "empty chat"
        if not ctx:
            return (
                False,
                "该会话尚无 context_token；请等对方先发一条消息后再回",
            )
        try:
            data = self._client().send_text(
                to_user_id=uid,
                text=body,
                context_token=ctx,
                client_id=uuid.uuid4().hex,
            )
        except Exception as exc:
            return False, str(exc)[:200]
        if not api_ok(data):
            return False, f"send failed: {data.get('errcode') or data.get('ret') or data}"
        mapped = {
            "id": uuid.uuid4().hex[:16],
            "user_id": uid,
            "chat": display_chat_name(uid, aliases),
            "sender": "",
            "text": body,
            "time_text": time.strftime("%H:%M"),
            "kind": "TEXT",
            "index": 0,
            "preview_only": False,
            "from_self": True,
            "content_type": "text",
            "context_token": ctx,
            "stable_id": uid,
        }
        with self._lock:
            self._remember_chat(mapped)
            self._recent.setdefault(uid, []).append(mapped)
            self._recent[uid] = self._recent[uid][-50:]
            self._persist()
        return True, f"sent {len(body)} chars"

    def logout_local(self, detail: str = "logged out") -> None:
        """Clear token and return to QR flow (no GUI logout)."""
        with self._lock:
            self._token = ""
            self._account_id = ""
            self._sync_buf = ""
            self._context_tokens = {}
            self._qr_handle = ""
            self._qr_payload = ""
            self.store.clear_login()
        self._set_phase(PHASE_STARTING, detail, [])


def hashlib_revision(payload: str) -> str:
    """Short fingerprint so clients know the QR image changed."""
    import hashlib

    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
