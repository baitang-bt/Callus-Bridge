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


def test_client_send_uses_callus_channel_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """sendmessage base_info.channel_version stays callus-bridge (not astrbot)."""
    from openclaw import CHANNEL_VERSION

    captured: list[dict[str, Any]] = []

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, method, url, params=None, json=None, headers=None, timeout=None):
            captured.append(json or {})
            return _FakeResponse(200, {"errcode": 0})

    monkeypatch.setattr("openclaw.client.httpx.Client", _FakeClient)
    OpenClawClient(base_url="https://ilink.test", token="tok").send_text(
        to_user_id="u1", text="hi", context_token="ctx", client_id="c1"
    )
    assert CHANNEL_VERSION == "callus-bridge"
    assert captured[0]["base_info"]["channel_version"] == "callus-bridge"


def test_apply_updates_stores_context_then_send(tmp_path: Path) -> None:
    """Inbound getupdates msg stores context_token; SendText can follow."""
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
    fake.send_text.return_value = {"errcode": 0}
    runtime = OpenClawRuntime(store, client_factory=lambda base, token: fake)
    runtime._phase = PHASE_LOGGED_IN
    runtime._token = "tok"
    runtime._account_id = "bot"
    n = runtime.apply_updates(
        {
            "errcode": 0,
            "get_updates_buf": "cursor-2",
            "msgs": [
                {
                    "from_user_id": "u1",
                    "message_id": "m9",
                    "context_token": "ctx-from-inbound",
                    "create_time": 1_700_000_000,
                    "item_list": [{"type": 1, "text_item": {"text": "ping"}}],
                }
            ],
        }
    )
    assert n == 1
    assert runtime._sync_buf == "cursor-2"
    assert runtime._context_tokens["u1"] == "ctx-from-inbound"
    inbox = runtime.pop_inbox(timeout=0.2)
    assert inbox is not None and inbox["text"] == "ping"
    ok, detail = runtime.send_text("u1", "pong")
    assert ok is True
    assert "sent" in detail
    fake.send_text.assert_called_once()
    assert fake.send_text.call_args.kwargs["context_token"] == "ctx-from-inbound"


def test_gui_rpcs_refuse_on_openclaw_servicer() -> None:
    """GUI-only RPCs abort or return explicit failure — never silent success."""
    from openclaw.server import OpenClawServicer

    fake_rt = MagicMock()
    svc = OpenClawServicer(fake_rt)
    ctx = MagicMock()
    svc.ReadContext(MagicMock(), ctx)
    ctx.abort.assert_called_once()
    assert ctx.abort.call_args.args[0].name == "UNIMPLEMENTED"
    assert "unsupported" in ctx.abort.call_args.args[1]

    cap = svc.CaptureMessageMedia(MagicMock(), MagicMock())
    assert cap.ok is False
    assert "unsupported" in cap.detail
