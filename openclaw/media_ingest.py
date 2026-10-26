"""Turn openclaw item_list rows into text, content_type, and local attachments."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Callable

from openclaw.cdn import (
    DEFAULT_CDN_BASE,
    MAX_FILE_BYTES,
    MAX_IMAGE_BYTES,
    download_and_decrypt_media,
)
from openclaw.mapping import (
    ITEM_TYPE_FILE,
    ITEM_TYPE_IMAGE,
    ITEM_TYPE_TEXT,
    ITEM_TYPE_VIDEO,
    ITEM_TYPE_VOICE,
)
from openclaw.mime_allow import allowed_file_suffix
from openclaw.redact import install_openclaw_log_filter, safe_exc

_log = logging.getLogger(__name__)
install_openclaw_log_filter()

_MERGE_NAME_RE = re.compile(
    r"(聊天记录|合并转发|chat.?record|msg.?history)",
    re.IGNORECASE,
)

Downloader = Callable[..., bytes]

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _sha256(data: bytes) -> str:
    """Content hash for attachment identity."""
    return hashlib.sha256(data).hexdigest()


def image_suffix_from_magic(data: bytes) -> str | None:
    """Return png/jpg/gif/webp suffix from magic bytes, else None (do not save)."""
    if data.startswith(b"\x89PNG"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return ".webp"
    return None


def save_bytes_atomic(
    root: Path,
    stem: str,
    data: bytes,
    suffix: str,
    *,
    kind: str,
) -> dict[str, Any]:
    """Write via ``.part`` then rename; verify size and sha256 before commit."""
    root.mkdir(parents=True, exist_ok=True)
    digest = _sha256(data)
    final = root / f"{stem}_{digest[:16]}{suffix}"
    part = final.with_suffix(final.suffix + ".part")
    try:
        part.write_bytes(data)
        written = part.read_bytes()
        if len(written) != len(data) or _sha256(written) != digest:
            raise RuntimeError("part file failed size/hash verification")
        part.replace(final)
    except Exception:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return {
        "kind": kind,
        "path": str(final),
        "sha256": digest,
        "sampled": False,
        "frame_index": 0,
    }


def _file_looks_like_merge(file_item: dict[str, Any]) -> bool:
    """Heuristic: filename suggests a forwarded chat record."""
    name = str(file_item.get("file_name") or "")
    return bool(_MERGE_NAME_RE.search(name))


def _extract_textish(data: bytes, limit: int = 80_000) -> str:
    """Best-effort decode of a downloaded chat-record / text blob."""
    chunk = data[:limit]
    for encoding in ("utf-8", "utf-16", "gb18030"):
        try:
            text = chunk.decode(encoding)
        except UnicodeDecodeError:
            continue
        cleaned = text.strip()
        if cleaned and sum(1 for c in cleaned if c.isprintable() or c in "\n\r\t") > len(
            cleaned
        ) * 0.7:
            return cleaned
    try:
        rough = chunk.decode("utf-8", errors="ignore")
    except Exception:
        return ""
    stripped = re.sub(r"<[^>]+>", "\n", rough)
    lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
    return "\n".join(lines[:500])


def ingest_item_list(
    item_list: list[Any],
    *,
    media_root: Path,
    cdn_base: str = DEFAULT_CDN_BASE,
    download: Downloader | None = None,
    msg_stem: str = "msg",
) -> tuple[str, str, list[dict[str, Any]]]:
    """Map item_list → (text, content_type, attachments).

    Images require CDN URL + key, magic-matched suffix, and atomic disk write.
    Files require an allowlisted extension. Failures log type + error category only.
    """
    downloader = download or download_and_decrypt_media
    texts: list[str] = []
    attachments: list[dict[str, Any]] = []
    content_type = "text"
    image_count = 0

    for raw in item_list or []:
        if not isinstance(raw, dict):
            continue
        item_type = int(raw.get("type") or 0)

        if item_type == ITEM_TYPE_TEXT:
            piece = str((raw.get("text_item") or {}).get("text") or "").strip()
            if piece:
                texts.append(piece)
                if _MERGE_NAME_RE.search(piece) and content_type == "text":
                    content_type = "merge"
            continue

        if item_type == ITEM_TYPE_VOICE:
            voice = raw.get("voice_item") if isinstance(raw.get("voice_item"), dict) else {}
            transcript = str(voice.get("text") or "").strip()
            content_type = "voice"
            texts.append(transcript or "[语音]")
            continue

        if item_type == ITEM_TYPE_IMAGE:
            content_type = "image"
            image = raw.get("image_item") if isinstance(raw.get("image_item"), dict) else {}
            media = image.get("media") if isinstance(image.get("media"), dict) else {}
            texts.append("[图片]")
            if not media:
                _log.warning("image ingest skipped kind=image err=MediaSourceError:missing_source")
                continue
            try:
                data = downloader(
                    media,
                    aes_key_hint=str(image.get("aeskey") or "") or None,
                    cdn_base=cdn_base,
                    max_bytes=MAX_IMAGE_BYTES,
                )
                suffix = image_suffix_from_magic(data)
                if suffix is None:
                    _log.warning("image ingest skipped kind=image err=magic_mismatch")
                    continue
                image_count += 1
                kind = "emotion" if suffix in {".gif", ".webp"} else "image"
                att = save_bytes_atomic(
                    media_root,
                    f"{msg_stem}_img{image_count}",
                    data,
                    suffix,
                    kind=kind,
                )
                attachments.append(att)
            except Exception as exc:
                _log.warning("image ingest failed kind=image err=%s", safe_exc(exc))
            continue

        if item_type == ITEM_TYPE_FILE:
            file_item = raw.get("file_item") if isinstance(raw.get("file_item"), dict) else {}
            media = file_item.get("media") if isinstance(file_item.get("media"), dict) else {}
            name = str(file_item.get("file_name") or "file")
            suffix = Path(name).suffix.lower()
            if _file_looks_like_merge(file_item):
                content_type = "merge"
                if not media:
                    texts.append(
                        f"[合并转发] {name}（无 CDN 引用；openclaw 未提供可解析载荷）"
                    )
                    continue
                try:
                    data = downloader(
                        media,
                        aes_key_hint=None,
                        cdn_base=cdn_base,
                        max_bytes=MAX_FILE_BYTES,
                    )
                    extracted = _extract_textish(data)
                    if extracted:
                        texts.append(extracted)
                    else:
                        texts.append(
                            f"[合并转发] {name}（已下载但未能解析正文；请复制文字或逐条转发）"
                        )
                        if allowed_file_suffix(suffix or ".txt"):
                            use_suffix = suffix if allowed_file_suffix(suffix) else ".txt"
                            att = save_bytes_atomic(
                                media_root,
                                f"{msg_stem}_merge",
                                data,
                                use_suffix,
                                kind="file",
                            )
                            attachments.append(att)
                        else:
                            _log.warning(
                                "merge file ingest skipped kind=file err=ext_not_allowed"
                            )
                except Exception as exc:
                    _log.warning("merge file ingest failed kind=file err=%s", safe_exc(exc))
                    texts.append(f"[合并转发] {name}（下载失败；请复制文字或逐条转发）")
            else:
                content_type = "file"
                texts.append(f"[文件] {name}")
                if not media:
                    continue
                if not allowed_file_suffix(suffix):
                    _log.warning("file ingest skipped kind=file err=ext_not_allowed")
                    continue
                try:
                    data = downloader(
                        media,
                        aes_key_hint=None,
                        cdn_base=cdn_base,
                        max_bytes=MAX_FILE_BYTES,
                    )
                    att = save_bytes_atomic(
                        media_root,
                        f"{msg_stem}_file",
                        data,
                        suffix,
                        kind="file",
                    )
                    attachments.append(att)
                except Exception as exc:
                    _log.warning("file ingest failed kind=file err=%s", safe_exc(exc))
            continue

        if item_type == ITEM_TYPE_VIDEO:
            content_type = "video"
            texts.append("[视频]")
            continue

        texts.append("[消息]")

    body = "\n".join(t for t in texts if t).strip()
    if not body:
        body = "[消息]"
    if content_type == "image" and attachments:
        if any(a.get("kind") == "emotion" for a in attachments):
            content_type = "emotion"
    return body, content_type, attachments
