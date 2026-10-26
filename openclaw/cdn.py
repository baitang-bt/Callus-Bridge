"""Download and AES-128-ECB decrypt openclaw CDN media blobs."""

from __future__ import annotations

import base64
import logging
from typing import Any
from urllib.parse import quote

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from openclaw import DEFAULT_BASE_URL
from openclaw.redact import install_openclaw_log_filter, safe_exc

_log = logging.getLogger(__name__)
install_openclaw_log_filter()

DEFAULT_CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_FILE_BYTES = 50 * 1024 * 1024
_CHUNK = 64 * 1024


class SizeLimitError(RuntimeError):
    """Raised when a CDN download exceeds the configured byte cap."""


class MediaSourceError(RuntimeError):
    """Raised when media lacks a downloadable URL or decryption key."""


def parse_aes_key(raw: str) -> bytes:
    """Decode CDNMedia.aes_key or image_item.aeskey into 16 raw key bytes.

    Accepts: 32-char hex, base64(16 raw bytes), or base64(32-char hex ASCII).
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty aes key")
    if len(text) == 32 and all(c in "0123456789abcdefABCDEF" for c in text):
        return bytes.fromhex(text)
    decoded = base64.b64decode(text)
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32 and all(
        chr(b) in "0123456789abcdefABCDEF" for b in decoded
    ):
        return bytes.fromhex(decoded.decode("ascii"))
    raise ValueError(f"unsupported aes key encoding (decoded_len={len(decoded)})")


def decrypt_aes_ecb(ciphertext: bytes, key: bytes) -> bytes:
    """AES-128-ECB decrypt with PKCS#7 unpadding."""
    if len(key) != 16:
        raise ValueError("AES-128 key must be 16 bytes")
    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    if not padded:
        return padded
    pad_len = padded[-1]
    if pad_len < 1 or pad_len > 16 or pad_len > len(padded):
        return padded
    if padded[-pad_len:] != bytes([pad_len]) * pad_len:
        return padded
    return padded[:-pad_len]


def build_cdn_download_url(encrypt_query_param: str, cdn_base: str = DEFAULT_CDN_BASE) -> str:
    """Build CDN GET URL from encrypt_query_param when full_url is absent."""
    base = (cdn_base or DEFAULT_CDN_BASE).rstrip("/")
    return f"{base}/download?encrypted_query_param={quote(encrypt_query_param, safe='')}"


def media_download_url(media: dict[str, Any], cdn_base: str = DEFAULT_CDN_BASE) -> str | None:
    """Prefer media.full_url; else construct from encrypt_query_param."""
    if not isinstance(media, dict):
        return None
    full = str(media.get("full_url") or "").strip()
    if full:
        return full
    param = str(media.get("encrypt_query_param") or "").strip()
    if not param:
        return None
    return build_cdn_download_url(param, cdn_base)


def download_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout_seconds: float = 60.0,
) -> bytes:
    """HTTP GET raw CDN bytes in chunks; abort once *max_bytes* would be exceeded."""
    if max_bytes <= 0:
        raise SizeLimitError("max_bytes must be positive")
    chunks: list[bytes] = []
    total = 0
    with httpx.Client(timeout=timeout_seconds) as client:
        with client.stream("GET", url) as response:
            if response.status_code >= 400:
                raise RuntimeError(f"CDN download failed: {response.status_code}")
            for chunk in response.iter_bytes(_CHUNK):
                if not chunk:
                    continue
                if total + len(chunk) > max_bytes:
                    raise SizeLimitError(f"download exceeds {max_bytes} bytes")
                chunks.append(chunk)
                total += len(chunk)
    return b"".join(chunks)


def download_and_decrypt_media(
    media: dict[str, Any],
    *,
    aes_key_hint: str | None = None,
    cdn_base: str = DEFAULT_CDN_BASE,
    max_bytes: int = MAX_FILE_BYTES,
    timeout_seconds: float = 60.0,
) -> bytes:
    """Download CDN media and decrypt. Requires URL and AES key; no plain fallback."""
    url = media_download_url(media, cdn_base)
    if not url:
        raise MediaSourceError("CDN media missing download URL")
    key_raw = (aes_key_hint or "").strip() or str(media.get("aes_key") or "").strip()
    if not key_raw:
        raise MediaSourceError("CDN media missing aes key")
    try:
        blob = download_bytes(url, max_bytes=max_bytes, timeout_seconds=timeout_seconds)
        return decrypt_aes_ecb(blob, parse_aes_key(key_raw))
    except SizeLimitError:
        raise
    except MediaSourceError:
        raise
    except Exception as exc:
        _log.warning("cdn download/decrypt failed err=%s", safe_exc(exc))
        raise


def api_base_to_cdn_hint(base_url: str) -> str:
    """Keep default CDN base; login base_url is for API only."""
    _ = base_url or DEFAULT_BASE_URL
    return DEFAULT_CDN_BASE
