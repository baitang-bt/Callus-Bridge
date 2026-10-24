"""Minimal sync HTTP client for ilink/bot openclaw endpoints."""

from __future__ import annotations

import base64
import random
from typing import Any

import httpx

from openclaw import CHANNEL_VERSION, DEFAULT_BASE_URL


class OpenClawClient:
    """Call ilink bot APIs with optional bearer token."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        token: str | None = None,
        timeout_seconds: float = 35.0,
    ) -> None:
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.token = (token or "").strip() or None
        self.timeout_seconds = timeout_seconds

    def with_token(self, token: str | None) -> OpenClawClient:
        """Return a shallow copy that uses a different bearer token."""
        return OpenClawClient(
            base_url=self.base_url,
            token=token,
            timeout_seconds=self.timeout_seconds,
        )

    def _headers(self, *, token_required: bool) -> dict[str, str]:
        """Build common ilink headers; attach Bearer when required and present."""
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": base64.b64encode(
                str(random.getrandbits(32)).encode("utf-8")
            ).decode("utf-8"),
        }
        if token_required and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def request_json(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        token_required: bool = False,
        timeout_seconds: float | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """POST/GET JSON; raise RuntimeError on HTTP >= 400."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = self._headers(token_required=token_required)
        if extra_headers:
            headers.update(extra_headers)
        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        with httpx.Client(timeout=timeout) as client:
            response = client.request(
                method,
                url,
                params=params,
                json=payload,
                headers=headers,
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"{method} {endpoint} failed: {response.status_code} {response.text[:300]}"
            )
        if not response.text:
            return {}
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"{method} {endpoint}: response is not a JSON object")
        return data

    def get_bot_qrcode(self, bot_type: str = "3") -> dict[str, Any]:
        """Request a login QR; returns qrcode handle + qrcode_img_content payload."""
        return self.request_json(
            "GET",
            "ilink/bot/get_bot_qrcode",
            params={"bot_type": bot_type},
            token_required=False,
            timeout_seconds=15.0,
        )

    def get_qrcode_status(self, qrcode: str) -> dict[str, Any]:
        """Long-poll QR scan status until confirmed / expired / cancel."""
        return self.request_json(
            "GET",
            "ilink/bot/get_qrcode_status",
            params={"qrcode": qrcode},
            token_required=False,
            timeout_seconds=max(self.timeout_seconds, 35.0),
            extra_headers={"iLink-App-ClientVersion": "1"},
        )

    def get_updates(self, sync_buf: str) -> dict[str, Any]:
        """Long-poll inbound messages; pass prior get_updates_buf as sync cursor."""
        return self.request_json(
            "POST",
            "ilink/bot/getupdates",
            payload={
                "base_info": {"channel_version": CHANNEL_VERSION},
                "get_updates_buf": sync_buf or "",
            },
            token_required=True,
            timeout_seconds=max(self.timeout_seconds, 35.0),
        )

    def send_text(
        self,
        *,
        to_user_id: str,
        text: str,
        context_token: str,
        client_id: str,
    ) -> dict[str, Any]:
        """Send one plain-text bubble to an ilink user session."""
        return self.request_json(
            "POST",
            "ilink/bot/sendmessage",
            payload={
                "base_info": {"channel_version": CHANNEL_VERSION},
                "msg": {
                    "from_user_id": "",
                    "to_user_id": to_user_id,
                    "client_id": client_id,
                    "message_type": 2,
                    "message_state": 2,
                    "context_token": context_token,
                    "item_list": [{"type": 1, "text_item": {"text": text}}],
                },
            },
            token_required=True,
            timeout_seconds=30.0,
        )
