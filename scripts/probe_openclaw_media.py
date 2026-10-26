#!/usr/bin/env python3
"""Dump redacted getupdates item_list samples for media-type reverse engineering.

Usage (from Callus-Bridge root, with a logged-in data/openclaw/state.json):

  .venv/bin/python scripts/probe_openclaw_media.py
  .venv/bin/python scripts/probe_openclaw_media.py --wait 120

Never prints bot_token. Writes docs/openclaw-media-samples.md structure notes
plus a redacted JSON under data/openclaw/probe/ (gitignored).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from openclaw.client import OpenClawClient
from openclaw.store import OpenClawStore

_SECRET_KEYS = {
    "bot_token",
    "token",
    "aes_key",
    "aeskey",
    "context_token",
    "encrypt_query_param",
    "full_url",
    "Authorization",
}


def _redact(value: object) -> object:
    """Recursively redact secret-looking fields; keep type/shape for analysis."""
    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            if key in _SECRET_KEYS or key.endswith("_token") or key.endswith("_key"):
                text = str(child)
                out[key] = f"<redacted len={len(text)}>"
            else:
                out[key] = _redact(child)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _classify_items(item_list: list) -> list[str]:
    """Return human labels for item types present in one message."""
    labels = []
    for raw in item_list:
        if not isinstance(raw, dict):
            continue
        t = int(raw.get("type") or 0)
        labels.append(
            {
                1: "text",
                2: "image",
                3: "voice",
                4: "file",
                5: "video",
            }.get(t, f"type_{t}")
        )
    return labels


def main() -> int:
    """Poll getupdates once or until timeout; write redacted samples."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait", type=float, default=5.0, help="seconds to poll")
    parser.add_argument(
        "--out",
        type=Path,
        default=_ROOT / "data" / "openclaw" / "probe" / "last_samples.json",
        help="redacted JSON output path",
    )
    args = parser.parse_args()

    store = OpenClawStore()
    state = store.load_state()
    token = str(state.get("token") or "").strip()
    if not token:
        print("no token in data/openclaw/state.json — login first (make openclaw)", file=sys.stderr)
        return 1
    base = str(state.get("base_url") or "").strip() or None
    sync_buf = str(state.get("sync_buf") or "")
    client = OpenClawClient(base_url=base or OpenClawClient().base_url, token=token)

    deadline = time.time() + max(1.0, args.wait)
    collected: list[dict] = []
    while time.time() < deadline:
        data = client.get_updates(sync_buf)
        new_buf = data.get("get_updates_buf")
        if new_buf:
            sync_buf = str(new_buf)
            state["sync_buf"] = sync_buf
            store.save_state(state)
        msgs = data.get("msgs") if isinstance(data.get("msgs"), list) else []
        for raw in msgs:
            if not isinstance(raw, dict):
                continue
            items = raw.get("item_list") if isinstance(raw.get("item_list"), list) else []
            collected.append(
                {
                    "labels": _classify_items(items),
                    "from_user_id_len": len(str(raw.get("from_user_id") or "")),
                    "has_context_token": bool(str(raw.get("context_token") or "").strip()),
                    "item_list": _redact(items),
                    "keys": sorted(raw.keys()),
                }
            )
        if collected:
            break
        time.sleep(0.5)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"count": len(collected), "samples": collected}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"samples={len(collected)} wrote={args.out}")
    for i, sample in enumerate(collected):
        print(f"  [{i}] labels={sample['labels']} keys={sample['keys']}")
    if not collected:
        print(
            "no inbound msgs in window — send image/voice/merge/sticker to the bot, then re-run",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
