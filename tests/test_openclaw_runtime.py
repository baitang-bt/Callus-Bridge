"""Mocked HTTP tests for OpenClawClient + OpenClawRuntime send/login helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from openclaw.client import OpenClawClient
from openclaw.runtime import OpenClawRuntime, PHASE_LOGGED_IN
from openclaw.store import OpenClawStore


class _FakeResponse:
    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status_code = status
        self._payload = payload
        self.text = "{}" if not payload else str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


def test_client_get_bot_qrcode(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_bot_qrcode issues GET without bearer and returns JSON body."""
    calls: list[dict[str, Any]] = []

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, method, url, params=None, json=None, headers=None, timeout=None):
            calls.append(
                {"method": method, "url": url, "params": params, "headers": headers}
            )
            return _FakeResponse(
                200,
                {"qrcode": "h1", "qrcode_img_content": "https://login.example/qr"},
            )

    monkeypatch.setattr("openclaw.client.httpx.Client", _FakeClient)
    client = OpenClawClient(base_url="https://ilink.test")
    data = client.get_bot_qrcode("3")
    assert data["qrcode"] == "h1"
    assert calls[0]["method"] == "GET"
    assert "Authorization" not in (calls[0]["headers"] or {})


def test_client_send_text_requires_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    """send_text attaches Authorization Bearer when token is set."""
    calls: list[dict[str, Any]] = []

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, method, url, params=None, json=None, headers=None, timeout=None):
            calls.append({"headers": headers, "json": json})
            return _FakeResponse(200, {"errcode": 0})

    monkeypatch.setattr("openclaw.client.httpx.Client", _FakeClient)
    client = OpenClawClient(base_url="https://ilink.test", token="tok")
    client.send_text(
        to_user_id="u1",
        text="hi",
        context_token="ctx",
        client_id="c1",
    )
    assert calls[0]["headers"]["Authorization"] == "Bearer tok"
    assert calls[0]["json"]["msg"]["to_user_id"] == "u1"


def test_runtime_send_without_context(tmp_path: Path) -> None:
    """Send fails clearly when context_token is missing."""
    store = OpenClawStore(tmp_path)
    store.save_state(
        {
            "token": "tok",
            "account_id": "bot",
            "base_url": "https://ilink.test",
            "sync_buf": "",
            "context_tokens": {},
            "chats": {},
        }
    )
    fake = MagicMock()
    runtime = OpenClawRuntime(
        store,
        client_factory=lambda base, token: fake,
    )
    # Avoid background threads talking to network in unit tests.
    runtime._phase = PHASE_LOGGED_IN
    runtime._token = "tok"
    ok, detail = runtime.send_text("u1", "hello")
    assert ok is False
    assert "context_token" in detail
    fake.send_text.assert_not_called()


def test_runtime_send_ok(tmp_path: Path) -> None:
    """Send succeeds when context_token is present and API returns ok."""
    store = OpenClawStore(tmp_path)
    store.save_state(
        {
            "token": "tok",
            "account_id": "bot",
            "base_url": "https://ilink.test",
            "sync_buf": "",
            "context_tokens": {"u1": "ctx"},
            "chats": {},
        }
    )
    fake = MagicMock()
    fake.send_text.return_value = {"errcode": 0}
    runtime = OpenClawRuntime(store, client_factory=lambda base, token: fake)
    runtime._phase = PHASE_LOGGED_IN
    runtime._token = "tok"
    runtime._context_tokens = {"u1": "ctx"}
    ok, detail = runtime.send_text("u1", "hello")
    assert ok is True
    fake.send_text.assert_called_once()
    assert "sent" in detail
