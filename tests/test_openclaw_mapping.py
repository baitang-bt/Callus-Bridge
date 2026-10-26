"""Offline tests for openclaw → wejam field mapping."""

from openclaw.mapping import (
    api_ok,
    display_chat_name,
    inbound_to_message,
    resolve_user_id,
    text_from_item_list,
)


def test_text_from_item_list_plain() -> None:
    """type=1 text_item becomes body text."""
    text, kind = text_from_item_list([{"type": 1, "text_item": {"text": "你好"}}])
    assert text == "你好"
    assert kind == "text"


def test_text_from_item_list_image() -> None:
    """Non-text items become placeholders with content_type."""
    text, kind = text_from_item_list([{"type": 2}])
    assert text == "[图片]"
    assert kind == "image"


def test_text_from_item_list_voice_transcript() -> None:
    """Voice uses WeChat cloud transcript when voice_item.text is set."""
    text, kind = text_from_item_list(
        [{"type": 3, "voice_item": {"text": "转写内容"}}]
    )
    assert kind == "voice"
    assert text == "转写内容"


def test_aliases_roundtrip() -> None:
    """Display name and reverse resolve share the same map."""
    aliases = {"uid-1": "白糖"}
    assert display_chat_name("uid-1", aliases) == "白糖"
    assert resolve_user_id("白糖", aliases) == "uid-1"
    assert resolve_user_id("uid-1", aliases) == "uid-1"


def test_inbound_to_message() -> None:
    """Inbound msgs[] row maps to chat alias and context_token."""
    msg = {
        "from_user_id": "uid-1",
        "message_id": "m1",
        "context_token": "ctx",
        "create_time": 1_700_000_000,
        "item_list": [{"type": 1, "text_item": {"text": "hi"}}],
    }
    mapped = inbound_to_message(msg, aliases={"uid-1": "白糖"})
    assert mapped is not None
    assert mapped["chat"] == "白糖"
    assert mapped["text"] == "hi"
    assert mapped["context_token"] == "ctx"
    assert mapped["preview_only"] is False


def test_api_ok() -> None:
    """Non-zero errcode is treated as failure."""
    assert api_ok({}) is True
    assert api_ok({"errcode": 0}) is True
    assert api_ok({"errcode": -14}) is False
