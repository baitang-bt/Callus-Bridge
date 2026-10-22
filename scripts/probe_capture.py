"""One-shot probe: scroll, bubble rect, sticker animation inside Linux WeChat.

Run inside the session container with PYTHONPATH pointing at agent/.
Does not send messages. May open a chat and Page_Up the message list.
"""

from __future__ import annotations

import time


def main() -> None:
    """Print probe lines for scroll, bubble geometry, and frame change."""
    from agent import chat, geometry, screen
    from agent import input as inputmod
    from agent import message_actions

    lines: list[str] = []
    container = chat._node("list", chat.MESSAGE_LIST)
    lines.append(f"message_list_present={container is not None}")
    chats = chat.list_chats()
    lines.append(f"chat_count={len(chats)}")
    lines.append(f"sample_chats={[c['name'] for c in chats[:5]]!r}")

    target = None
    for row in chats:
        name = row.get("name") or ""
        if name and name != "文件传输助手":
            target = name
            break
    if target is None and chats:
        target = chats[0]["name"]
    lines.append(f"probe_chat={target!r}")
    if not target:
        print("\n".join(lines))
        return

    ok, detail = chat.open_chat(target)
    lines.append(f"open_chat_ok={ok} detail={detail!r}")
    _chat_name, messages = chat.list_messages(chat=target, limit=0)
    lines.append(f"visible_messages={len(messages)}")
    if messages:
        last = messages[-1]
        lines.append(
            "latest_sender={!r} content_type={!r} text={!r}".format(
                last.get("sender"),
                last.get("content_type"),
                (last.get("text") or "")[:40],
            )
        )

    before_ids = [m.get("id") for m in messages]
    rect = geometry.node_physical_rect("list", chat.MESSAGE_LIST)
    lines.append(f"message_list_rect={rect}")
    if rect:
        x, y, w, h = rect
        inputmod.click_at(x + w // 2, y + h // 2)
        time.sleep(0.2)
        for _ in range(3):
            inputmod.tap_key("Page_Up")
            time.sleep(0.35)
        time.sleep(0.5)
        _n, after_msgs = chat.list_messages(chat=target, limit=0)
        after_ids = [m.get("id") for m in after_msgs]
        lines.append(f"after_scroll_count={len(after_msgs)}")
        lines.append(f"scroll_changed={after_ids != before_ids}")
        lines.append(
            "new_ids={}".format(len([i for i in after_ids if i not in before_ids]))
        )
        messages = after_msgs

    emotion_idx = None
    for msg in reversed(messages):
        if msg.get("kind") != "TEXT":
            continue
        emotion_idx = msg.get("index")
        if msg.get("content_type") == "emotion":
            break
    lines.append(f"bubble_probe_index={emotion_idx}")
    if emotion_idx is not None:
        bubble = message_actions.bubble_rect(target, emotion_idx)
        lines.append(f"bubble_rect={bubble}")
        if bubble:
            img, (ox, oy) = screen.capture_window()
            bx, by, bw, bh = bubble
            crop = img.crop((bx - ox, by - oy, bx - ox + bw, by - oy + bh)).convert(
                "RGB"
            )
            first = crop.tobytes()
            time.sleep(0.45)
            img2, (ox2, oy2) = screen.capture_window()
            crop2 = img2.crop(
                (bx - ox2, by - oy2, bx - ox2 + bw, by - oy2 + bh)
            ).convert("RGB")
            second = crop2.tobytes()
            lines.append(
                f"animation_pixels_changed={first != second} crop_size={crop.size}"
            )

    print("\n".join(lines))


if __name__ == "__main__":
    main()
