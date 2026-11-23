"""Shared Telegram-channel links in Telegram Rich cards and Mini App profiles."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import Chat, Message, User

from community_bot.database import Database
from community_bot.group_profile import group_profile_body
from community_bot.profile_fields import normalize_tg_channel_url
from community_bot.routers.group import text_moderation_reason
from community_bot.routers.profile import PendingTgkReply, request_tgk, save_tgk_reply


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("@my_channel", "https://t.me/my_channel"),
        ("t.me/my_channel", "https://t.me/my_channel"),
        ("http://telegram.me/my_channel", "https://t.me/my_channel"),
        ("https://t.me/+ABCdef_123", "https://t.me/+ABCdef_123"),
        ("https://t.me/joinchat/ABCdef_123", "https://t.me/joinchat/ABCdef_123"),
        ("удалить", ""),
        ("-", ""),
    ],
)
def test_tgk_url_is_normalized(raw, expected):
    assert normalize_tg_channel_url(raw) == expected


@pytest.mark.parametrize(
    "invalid",
    [
        "https://t.me.evil.example/my_channel",
        "https://example.com/my_channel",
        "https://t.me/share/url?url=https://example.com",
        "https://t.me/my_channel/123",
        "https://t.me/my_channel?start=malicious",
        "https://t.me/addstickers",
        "https://t.me/%6d%79_channel",
        "any text https://t.me/my_channel",
        "@bad",
        "",
    ],
)
def test_tgk_url_rejects_non_channel_addresses(invalid):
    with pytest.raises(ValueError):
        normalize_tg_channel_url(invalid)


async def test_tgk_persists_and_is_rendered_as_rich_link(tmp_path):
    db = Database(tmp_path / "channels.db")
    await db.initialize()
    await db.ensure_user(7, telegram_name="Анна")
    settings = SimpleNamespace(restricted_reputation_threshold=50)
    bot = SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(username="nora_bot")))

    user = await db.get_user(7)
    body, *_ = await group_profile_body(db, settings, user, 7, bot)
    assert body[1].text[-1].button.callback_data == "gprofile:tgk:7"

    await db.update_profile(7, "tg_channel_url", "@my_channel")
    await db.initialize()  # repeated startup must not lose an existing channel
    saved = await db.get_user(7)
    assert saved["tg_channel_url"] == "https://t.me/my_channel"
    body, *_ = await group_profile_body(db, settings, saved, 7, bot)
    assert body[1].text[-1].button.url == "https://t.me/my_channel"
    assert body[1].text[-1].button.callback_data is None

    await db.update_profile(7, "tg_channel_url", "удалить")
    assert (await db.get_user(7))["tg_channel_url"] == ""


async def test_only_owner_can_start_and_answer_tgk_prompt(tmp_path, monkeypatch):
    db = Database(tmp_path / "tgk-prompt.db")
    await db.initialize()
    await db.ensure_user(7, telegram_name="Анна")
    await db.ensure_user(8, telegram_name="Пётр")
    chat = Chat(id=-100123, type="supergroup")
    source = Message(message_id=20, date=1725000000, chat=chat)
    prompt = Message(message_id=21, date=1725000000, chat=chat, text="🔗 ТГК: настройка")
    send_reply = AsyncMock(return_value=prompt)
    monkeypatch.setattr(Message, "reply", send_reply)

    callback = SimpleNamespace(
        data="gprofile:tgk:7", message=source, from_user=User(id=8, is_bot=False, first_name="Пётр"),
        answer=AsyncMock(),
    )
    await request_tgk(callback, db)
    assert await db.fetchone("SELECT * FROM profile_tgk_prompts") is None
    send_reply.assert_not_awaited()

    callback.from_user = User(id=7, is_bot=False, first_name="Анна")
    await request_tgk(callback, db)
    stored = await db.fetchone(
        "SELECT user_id FROM profile_tgk_prompts WHERE chat_id=? AND message_id=?",
        (chat.id, prompt.message_id),
    )
    assert stored["user_id"] == 7

    foreign_reply = Message(
        message_id=22, date=1725000000, chat=chat, reply_to_message=prompt,
        from_user=User(id=8, is_bot=False, first_name="Пётр"), text="https://t.me/others_channel",
    )
    await save_tgk_reply(foreign_reply, db)
    assert (await db.get_user(7))["tg_channel_url"] == ""

    owner_reply = foreign_reply.model_copy(update={
        "from_user": User(id=7, is_bot=False, first_name="Анна"),
        "text": "https://t.me/my_channel",
    })
    await save_tgk_reply(owner_reply, db)
    assert (await db.get_user(7))["tg_channel_url"] == "https://t.me/my_channel"
    assert await db.fetchone("SELECT * FROM profile_tgk_prompts") is None


async def test_tgk_prompt_expires(tmp_path, monkeypatch):
    db = Database(tmp_path / "expired.db")
    await db.initialize()
    await db.ensure_user(7, telegram_name="Анна")
    chat = Chat(id=-100123, type="supergroup")
    prompt = Message(message_id=30, date=1725000000, chat=chat, text="🔗 ТГК: настройка")
    await db.execute(
        "INSERT INTO profile_tgk_prompts(chat_id,message_id,user_id,expires_at) VALUES(?,?,?,?)",
        (chat.id, prompt.message_id, 7, (datetime.now(UTC) - timedelta(hours=1)).isoformat()),
    )
    monkeypatch.setattr(Message, "reply", AsyncMock())
    reply = Message(
        message_id=31, date=1725000000, chat=chat, reply_to_message=prompt,
        from_user=User(id=7, is_bot=False, first_name="Анна"), text="https://t.me/my_channel",
    )
    await save_tgk_reply(reply, db)
    assert (await db.get_user(7))["tg_channel_url"] == ""
    assert await db.fetchone("SELECT * FROM profile_tgk_prompts") is None


async def test_tgk_reply_matches_prompt_by_id_without_telegram_text(tmp_path, monkeypatch):
    """Replies to Rich messages often have no reply_to_message.text."""
    db = Database(tmp_path / "tgk-rich-reply.db")
    await db.initialize()
    await db.ensure_user(7, telegram_name="Анна")
    chat = Chat(id=-100123, type="supergroup")
    prompt = Message(message_id=41, date=1725000000, chat=chat)
    await db.execute(
        "INSERT INTO profile_tgk_prompts(chat_id,message_id,user_id,expires_at) VALUES(?,?,?,?)",
        (chat.id, prompt.message_id, 7, (datetime.now(UTC) + timedelta(hours=1)).isoformat()),
    )
    reply = Message(
        message_id=42, date=1725000000, chat=chat, reply_to_message=prompt,
        from_user=User(id=7, is_bot=False, first_name="Анна"),
        text="https://t.me/my_channel",
    )
    match = PendingTgkReply()
    assert await match(reply, db)
    unrelated = reply.model_copy(update={
        "reply_to_message": Message(message_id=999, date=1725000000, chat=chat),
    })
    assert not await match(unrelated, db)
    monkeypatch.setattr(Message, "reply", AsyncMock())
    await save_tgk_reply(reply, db)
    assert (await db.get_user(7))["tg_channel_url"] == "https://t.me/my_channel"
    assert not await match(reply, db)  # One-time prompt consumed on success.


async def test_tgk_link_moderation_exception_is_narrow():
    settings = SimpleNamespace(timezone="Europe/Moscow")
    flags = {"link_filter": True}
    url = "https://t.me/my_channel"
    assert await text_moderation_reason(None, settings, flags, url, 10) is not None
    assert await text_moderation_reason(
        None, settings, flags, url, 10, allow_tgk_link=True,
    ) is None
    assert await text_moderation_reason(
        None, settings, flags, "https://example.com", 10,
    ) is not None
