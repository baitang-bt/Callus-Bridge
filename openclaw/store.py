"""Persist openclaw tokens, sync cursor, context tokens, and chat aliases."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


def default_data_dir() -> Path:
    """Resolve data/openclaw under the Callus-Bridge repo root."""
    return Path(__file__).resolve().parent.parent / "data" / "openclaw"


class OpenClawStore:
    """JSON file store for login state and optional display-name aliases."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self._state_path = self.root / "state.json"
        self._alias_path = self.root / "aliases.json"
        self._lock = threading.Lock()

    def load_state(self) -> dict[str, Any]:
        """Read state.json; missing file yields empty defaults."""
        with self._lock:
            if not self._state_path.is_file():
                return _empty_state()
            try:
                raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return _empty_state()
            if not isinstance(raw, dict):
                return _empty_state()
            base = _empty_state()
            base.update(raw)
            return base

    def save_state(self, state: dict[str, Any]) -> None:
        """Atomically rewrite state.json."""
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            tmp.replace(self._state_path)

    def load_aliases(self) -> dict[str, str]:
        """Return by_id map: ilink user id → display name for whitelist."""
        with self._lock:
            if not self._alias_path.is_file():
                return {}
            try:
                raw = json.loads(self._alias_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            by_id = raw.get("by_id") if isinstance(raw, dict) else None
            if not isinstance(by_id, dict):
                return {}
            out: dict[str, str] = {}
            for key, value in by_id.items():
                kid = str(key).strip()
                name = str(value).strip()
                if kid and name:
                    out[kid] = name
            return out

    def clear_login(self) -> dict[str, Any]:
        """Drop token and related session fields; keep aliases file intact."""
        state = self.load_state()
        state["token"] = ""
        state["account_id"] = ""
        state["user_id"] = ""
        state["sync_buf"] = ""
        state["context_tokens"] = {}
        state["chats"] = {}
        self.save_state(state)
        return state


def _empty_state() -> dict[str, Any]:
    """Default empty persisted shape."""
    return {
        "token": "",
        "account_id": "",
        "user_id": "",
        "base_url": "",
        "sync_buf": "",
        "context_tokens": {},
        "chats": {},
    }
