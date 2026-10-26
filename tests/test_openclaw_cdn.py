"""Unit tests for CDN AES helpers and media ingest without network."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from openclaw.cdn import (
    MAX_IMAGE_BYTES,
    MediaSourceError,
    SizeLimitError,
    decrypt_aes_ecb,
    download_bytes,
    download_and_decrypt_media,
    parse_aes_key,
)
from openclaw.mapping import inbound_to_message, text_from_item_list
from openclaw.media_ingest import ingest_item_list, save_bytes_atomic


def _pkcs7_pad(data: bytes, block: int = 16) -> bytes:
    """Pad plaintext for AES-ECB test vectors."""
    n = block - (len(data) % block)
    return data + bytes([n]) * n


def _encrypt_ecb(plain: bytes, key: bytes) -> bytes:
    """Encrypt with AES-128-ECB + PKCS#7 for round-trip tests."""
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return encryptor.update(_pkcs7_pad(plain)) + encryptor.finalize()


def test_parse_aes_key_hex_and_base64() -> None:
    """Key parser accepts hex and base64(raw) forms."""
    import base64

    key = bytes(range(16))
    assert parse_aes_key(key.hex()) == key
    assert parse_aes_key(base64.b64encode(key).decode()) == key
    assert parse_aes_key(base64.b64encode(key.hex().encode()).decode()) == key


def test_decrypt_aes_ecb_roundtrip() -> None:
    """Decrypt reverses a known AES-128-ECB ciphertext."""
    key = bytes(range(16))
    plain = b"hello-openclaw-media"
    cipher = _encrypt_ecb(plain, key)
    assert decrypt_aes_ecb(cipher, key) == plain


def test_voice_transcript_without_cdn() -> None:
    """Offline mapping prefers voice_item.text over the voice placeholder."""
    text, kind = text_from_item_list(
        [{"type": 3, "voice_item": {"text": "今天下午三点开会"}}]
    )
    assert kind == "voice"
    assert text == "今天下午三点开会"


def test_ingest_image_with_fake_download(tmp_path: Path) -> None:
    """Image item is saved under media_root via injected downloader."""
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

    def _fake_download(media, **kwargs):
        return png

    text, kind, atts = ingest_item_list(
        [
            {
                "type": 2,
                "image_item": {
                    "aeskey": "00112233445566778899aabbccddeeff",
                    "media": {"encrypt_query_param": "x", "aes_key": "y"},
                },
            }
        ],
        media_root=tmp_path,
        download=_fake_download,
    )
    assert kind == "image"
    assert text == "[图片]"
    assert len(atts) == 1
    assert Path(atts[0]["path"]).is_file()
    assert Path(atts[0]["path"]).read_bytes().startswith(b"\x89PNG")
    assert not list(tmp_path.glob("*.part"))


def test_ingest_gif_marked_emotion(tmp_path: Path) -> None:
    """GIF image_item is labeled emotion for sticker-like payloads."""
    gif = b"GIF89a" + b"\x00" * 20

    text, kind, atts = ingest_item_list(
        [
            {
                "type": 2,
                "image_item": {
                    "aeskey": "00112233445566778899aabbccddeeff",
                    "media": {
                        "full_url": "https://x",
                        "aes_key": "00112233445566778899aabbccddeeff",
                    },
                },
            }
        ],
        media_root=tmp_path,
        download=lambda media, **k: gif,
    )
    assert kind == "emotion"
    assert atts[0]["kind"] == "emotion"
    assert text == "[图片]"


def test_ingest_rejects_unknown_magic(tmp_path: Path) -> None:
    """Non png/jpg/gif/webp payloads are not written to disk."""
    text, kind, atts = ingest_item_list(
        [
            {
                "type": 2,
                "image_item": {
                    "aeskey": "00112233445566778899aabbccddeeff",
                    "media": {"full_url": "https://x", "aes_key": "k"},
                },
            }
        ],
        media_root=tmp_path,
        download=lambda media, **k: b"NOT_AN_IMAGE",
    )
    assert kind == "image"
    assert text == "[图片]"
    assert atts == []
    assert list(tmp_path.iterdir()) == []


def test_ingest_skips_disallowed_file_extension(tmp_path: Path) -> None:
    """File suffix outside allowlist is not persisted."""
    called = {"n": 0}

    def _dl(media, **kwargs):
        called["n"] += 1
        return b"payload"

    text, kind, atts = ingest_item_list(
        [
            {
                "type": 4,
                "file_item": {
                    "file_name": "evil.exe",
                    "media": {"encrypt_query_param": "p", "aes_key": "k"},
                },
            }
        ],
        media_root=tmp_path,
        download=_dl,
    )
    assert kind == "file"
    assert "[文件]" in text
    assert atts == []
    assert called["n"] == 0


def test_download_requires_url_and_key() -> None:
    """Missing CDN URL or AES key must not download."""
    with pytest.raises(MediaSourceError):
        download_and_decrypt_media({})
    with pytest.raises(MediaSourceError):
        download_and_decrypt_media({"full_url": "https://example/x"})


def test_save_bytes_atomic_cleans_part_on_verify_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failed verification deletes the .part file."""
    real_read = Path.read_bytes

    def _bad_read(self: Path):
        if str(self).endswith(".part"):
            return b"tampered"
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", _bad_read)
    with pytest.raises(RuntimeError):
        save_bytes_atomic(tmp_path, "stem", b"\x89PNG" + b"\x00" * 8, ".png", kind="image")
    assert list(tmp_path.glob("*.part")) == []


def test_download_bytes_streams_and_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chunked download stops once max_bytes would be exceeded."""

    class _Resp:
        status_code = 200

        def iter_bytes(self, chunk_size=0):
            yield b"a" * 100
            yield b"b" * 100

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, *a, **k):
            return _Resp()

    monkeypatch.setattr("openclaw.cdn.httpx.Client", _Client)
    with pytest.raises(SizeLimitError):
        download_bytes("https://example/x", max_bytes=150)
    ok = download_bytes("https://example/x", max_bytes=250)
    assert len(ok) == 200


def test_ingest_merge_file_extracts_text(tmp_path: Path) -> None:
    """Chat-record-named file_item yields merge content_type and body text."""
    payload = "甲: 你好\n乙: 在的\n".encode("utf-8")

    text, kind, atts = ingest_item_list(
        [
            {
                "type": 4,
                "file_item": {
                    "file_name": "聊天记录.txt",
                    "media": {"encrypt_query_param": "p", "aes_key": "k"},
                },
            }
        ],
        media_root=tmp_path,
        download=lambda media, **k: payload,
    )
    assert kind == "merge"
    assert "甲: 你好" in text
    assert atts == []


def test_inbound_to_message_with_media_root(tmp_path: Path) -> None:
    """Full inbound mapper attaches decrypted image paths when media_root set."""
    mapped = inbound_to_message(
        {
            "from_user_id": "u1",
            "message_id": "m1",
            "context_token": "ctx",
            "create_time": 1_700_000_000,
            "item_list": [
                {
                    "type": 2,
                    "image_item": {
                        "aeskey": "00112233445566778899aabbccddeeff",
                        "media": {
                            "full_url": "https://x",
                            "aes_key": "00112233445566778899aabbccddeeff",
                        },
                    },
                }
            ],
        },
        aliases={},
        media_root=tmp_path,
        download=lambda media, **k: b"\x89PNG\r\n\x1a\n" + b"\x00" * 8,
    )
    assert mapped is not None
    assert mapped["content_type"] == "image"
    assert mapped["attachments"]
    assert Path(mapped["attachments"][0]["path"]).is_file()


def test_ingest_passes_image_size_cap(tmp_path: Path) -> None:
    """Image downloader is invoked with the 20MiB cap."""
    fake = MagicMock(return_value=b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    ingest_item_list(
        [
            {
                "type": 2,
                "image_item": {
                    "aeskey": "00112233445566778899aabbccddeeff",
                    "media": {"full_url": "https://x", "aes_key": "k"},
                },
            }
        ],
        media_root=tmp_path,
        download=fake,
    )
    assert fake.call_args.kwargs.get("max_bytes") == MAX_IMAGE_BYTES
