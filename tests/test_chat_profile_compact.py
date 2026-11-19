from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendRichMessage
from aiogram.types import Chat, Message, RichMessage

from community_bot.database import Database
from community_bot.domain import reputation_tier
from community_bot.group_profile import refresh_group_profile, send_group_profile
from community_bot.routers import profile


@pytest.mark.parametrize("fallback", [False, True])
async def test_group_profile_card(tmp_path, fallback):
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await db.ensure_user(2, telegram_name="Анна <3")
    await db.update_profile(2, "profile_bio", "Люблю <музыку>")
    await db.update_profile(2, "hobbies", "Кино и книги")
    user = await db.get_user(2)
    chat = Chat(id=-100123, type="supergroup", is_forum=True)
    message = Message(message_id=1, date=1725000000, chat=chat, message_thread_id=5, is_topic_message=True)
    sent = message.model_copy(update={"message_id": 10})
    bot = SimpleNamespace(
        me=AsyncMock(return_value=SimpleNamespace(username="nora_bot")),
        send_rich_message=AsyncMock(return_value=sent),
        send_message=AsyncMock(return_value=sent),
    )
    if fallback:
        bot.send_rich_message.side_effect = TelegramBadRequest(
            SendRichMessage(chat_id=chat.id, rich_message={"blocks": []}), "Rich message rejected",
        )
    await send_group_profile(message.as_(bot), db, SimpleNamespace(restricted_reputation_threshold=15), user, 1)

    send = bot.send_rich_message.await_args.kwargs
    assert send["message_thread_id"] == 5
    name, _, actions, table, about, hobbies, votes = send["rich_message"].blocks
    assert (name.type, name.text) == ("heading", "Анна <3")
    assert [(button.text, button.style) for button in actions.buttons] == [
        ("❌", "danger"), ("📱", "primary"), ("👤", "success"),
    ]
    assert actions.buttons[0].callback_data == "ui:close"
    assert actions.buttons[1].url == "https://t.me/nora_bot?startapp=nora_profile_2"
    assert actions.buttons[2].callback_data == "gprofile:friend:2"
    assert table.is_compact and [cell.text for cell in table.cells[0]] == ["🍪 Печеньки", "Репутация"]
    tier = reputation_tier(user["reputation"], 15)
    assert [cell.text for cell in table.cells[1]] == [str(user["cookies"]), f'{user["reputation"]}/100 · {tier.label}']
    assert (about.summary, hobbies.summary) == ("О себе", "Увлечения")
    assert not about.is_open and not hobbies.is_open
    assert about.blocks[0].text == "Люблю <музыку>"
    assert [button.callback_data for button in votes.buttons] == [
        "profile_action:rep_up:2", "profile_action:rep_down:2",
    ]
    assert await db.get_ui_owner(chat.id, sent.message_id) == 1
    if fallback:
        args, kwargs = bot.send_message.await_args
        assert "Анна &lt;3" in args[1] and "Люблю &lt;музыку&gt;" in args[1]
        assert kwargs["message_thread_id"] == 5
        assert kwargs["reply_markup"].inline_keyboard[1][1].callback_data == "profile_action:rep_down:2"
    else:
        bot.send_message.assert_not_awaited()


async def test_own_private_profile_is_not_published_to_group(monkeypatch):
    message = SimpleNamespace(
        chat=SimpleNamespace(type="group"), from_user=SimpleNamespace(id=1),
        reply_to_message=None, answer=AsyncMock(),
    )
    monkeypatch.setattr(profile, "register_telegram_user", AsyncMock(return_value={"user_id": 1, "profile_private": 1}))
    send = AsyncMock()
    monkeypatch.setattr(profile, "send_group_profile", send)
    await profile.show_profile(message, object(), object())
    message.answer.assert_awaited_once_with("🔒 Этот профиль скрыт.")
    send.assert_not_awaited()


async def test_friend_button_checks_clicker_and_updates_requester_icon(tmp_path, monkeypatch):
    db = Database(tmp_path / "friends.db")
    await db.initialize()
    for uid in (1, 2, 3):
        await db.ensure_user(uid)
    settings = SimpleNamespace(is_owner=lambda _: False, restricted_reputation_threshold=15)
    message = Message(message_id=8, date=1725000000, chat=Chat(id=-100123, type="group"))
    bot = SimpleNamespace(
        me=AsyncMock(return_value=SimpleNamespace(username="nora_bot")),
        send_rich_message=AsyncMock(return_value=message),
    )
    await send_group_profile(message.as_(bot), db, settings, await db.get_user(2), 1)
    rich = bot.send_rich_message.await_args.kwargs["rich_message"]
    received = RichMessage.model_validate(rich.model_dump(exclude_none=True))
    message = message.model_copy(update={"rich_message": received})
    edit = AsyncMock()
    monkeypatch.setattr(Message, "edit_text", edit)
    deliver = AsyncMock()
    monkeypatch.setattr(profile.friends_api, "deliver_notice", deliver)
    callback = SimpleNamespace(
        data="gprofile:friend:2", from_user=SimpleNamespace(id=3), message=message, answer=AsyncMock(),
    )
    await profile.group_profile_friend(callback, db, settings, bot)
    deliver.assert_awaited_once()
    assert await db.fetchone("SELECT requester_id FROM mini_friendships") == {"requester_id": 3}
    edit.assert_not_awaited()

    callback.from_user.id = 1
    await profile.group_profile_friend(callback, db, settings, bot)
    pending = await db.fetchone("SELECT token FROM mini_friendships WHERE low_id=1 AND high_id=2")
    await profile.friends_api.mutate(db, settings, 2, {"action": "accept", "target_id": 1, "token": pending["token"]})
    await profile.group_profile_friend(callback, db, settings, bot)
    callback.answer.assert_awaited_with("Вы уже друзья", show_alert=True)
    assert edit.await_args.kwargs["rich_message"].blocks[2].buttons[2].text == "🫂"

    await db.execute("UPDATE users SET reputation=75 WHERE user_id=2")
    await refresh_group_profile(message, db, settings, 2)
    edited = edit.await_args.kwargs["rich_message"]
    assert edited.blocks[3].cells[1][1].text.startswith("75/100")
    assert edited.blocks[2].buttons[2].text == "🫂"
