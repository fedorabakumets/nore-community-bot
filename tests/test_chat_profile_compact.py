from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendRichMessage
from aiogram.types import Chat, Message, RichMessage, User

from community_bot import friends_api
from community_bot.database import Database
from community_bot.domain import reputation_tier
from community_bot.group_friendship import group_friend_decision
from community_bot.group_profile import send_group_profile
from community_bot.routers import group, profile


@pytest.mark.parametrize("fallback", [False, True])
async def test_group_profile_card(tmp_path, fallback):
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await db.ensure_user(2, telegram_name="Анна <3")
    await db.update_profile(2, "profile_bio", "Люблю <музыку>")
    await db.update_profile(2, "hobbies", "Кино и книги")
    await db.update_profile(2, "avatar_file_id", "telegram-photo")
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
    blocks = bot.send_rich_message.await_args_list[0].kwargs["rich_message"].blocks
    photo, votes, name, _, about, hobbies, table, limits, actions = blocks
    assert photo.type == "photo" and photo.photo.media == "telegram-photo"
    assert name.type == "paragraph" and name.text[0].text == "Анна <3"
    assert name.text[2].button.text == "❤️ 0" and name.text[2].button.style == "link"
    assert name.text[2].button.callback_data == "gprofile:like:2"
    assert [(button.text, button.style) for button in actions.buttons] == [
        ("❌", "danger"), ("📱", "primary"), ("👤", "success"),
    ]
    assert actions.buttons[0].callback_data == "ui:close"
    assert actions.buttons[1].url == "https://t.me/nora_bot?startapp=nora_profile_2"
    assert actions.buttons[2].callback_data == "gprofile:friend:2"
    assert table.is_compact and [cell.text for cell in table.cells[0]] == ["🍪 Печеньки", "Репутация"]
    tier = reputation_tier(user["reputation"], 15)
    assert [cell.text for cell in table.cells[1]] == [str(user["cookies"]), f'{user["reputation"]}/100 · {tier.label}']
    assert limits.type == "details" and limits.summary == "Лимиты" and not limits.is_open
    limit_table, limit_action = limits.blocks
    assert limit_table.is_compact
    assert [row[0].text for row in limit_table.cells] == ["🐩", "📹", "🎧", "⚖️"]
    assert [row[1].text for row in limit_table.cells] == ["5/5", "5/5", "5/5", "1/1"]
    assert limit_action.buttons[0].text == "♻️ Восстановить лимиты"
    assert limit_action.buttons[0].callback_data == "gprofile:limits:restore:2"
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
        assert kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "gprofile:like:2"
        assert kwargs["reply_markup"].inline_keyboard[1][1].callback_data == "profile_action:rep_down:2"
        assert "Лимиты" in args[1] and "🐩" in args[1]
        assert kwargs["reply_markup"].inline_keyboard[2][0].callback_data == "gprofile:limits:restore:2"
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


@pytest.mark.parametrize("decline", [False, True])
async def test_group_friendship_request_and_removal(tmp_path, monkeypatch, decline):
    db = Database(tmp_path / "friends.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Пётр")
    await db.ensure_user(2, username="anna", telegram_name="Анна")
    await db.ensure_user(3, telegram_name="Третий участник")
    settings = SimpleNamespace(is_owner=lambda _: False, restricted_reputation_threshold=15)
    message = Message(message_id=8, date=1725000000, chat=Chat(id=-100123, type="supergroup"),
                      message_thread_id=123, is_topic_message=True)
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
    delete = AsyncMock()
    monkeypatch.setattr(Message, "delete", delete)
    deliver = AsyncMock()
    monkeypatch.setattr(friends_api, "deliver_notice", deliver)
    callback = SimpleNamespace(
        data="gprofile:friend:2", from_user=SimpleNamespace(id=1), message=message, answer=AsyncMock(),
    )
    await profile.group_profile_friend(callback, db, settings, bot)
    deliver.assert_awaited_once()
    assert await db.fetchone("SELECT requester_id FROM mini_friendships") == {"requester_id": 1}
    notice = await db.fetchone("SELECT user_id, text FROM notify_inbox")
    assert notice["user_id"] == 2 and "Пётр хочет добавить тебя в друзья" in notice["text"]
    sent = bot.send_rich_message.await_args.kwargs
    assert sent["message_thread_id"] == 123 and sent["reply_parameters"].message_id == message.message_id
    paragraph, actions = sent["rich_message"].blocks
    assert paragraph.text[0].user.id == 2 and paragraph.text[2].user.id == 1
    assert [button.text for button in actions.buttons] == ["Принять", "Отказаться"]
    invite_count = bot.send_rich_message.await_count
    await profile.group_profile_friend(callback, db, settings, bot)
    assert bot.send_rich_message.await_count == invite_count

    prompt = message.model_copy(update={"message_id": 9, "reply_to_message": message})
    decision = SimpleNamespace(
        data=actions.buttons[int(decline)].callback_data,
        from_user=SimpleNamespace(id=3), message=prompt, answer=AsyncMock(),
    )
    await group_friend_decision(decision, db, settings, bot)
    delete.assert_not_awaited()
    decision.from_user.id = 2
    await group_friend_decision(decision, db, settings, bot)
    delete.assert_awaited_once()
    if decline:
        assert await friends_api.current_relationship(db, 1, 2) is None
        edit.assert_not_awaited()
        return
    assert await friends_api.accepted(db, 1, 2)
    assert edit.await_args.kwargs["rich_message"].blocks[-1].buttons[2].text == "🫂"

    await profile.group_profile_friend(callback, db, settings, bot)
    warning, choices = bot.send_rich_message.await_args.kwargs["rich_message"].blocks
    assert warning.text[1].text == "@anna"
    assert [(btn.text, btn.style) for btn in choices.buttons] == [("ДА", "danger"), ("Нет", "link")]
    decision.message = prompt.model_copy(update={"message_id": 10})
    decision.data = choices.buttons[1].callback_data
    decision.from_user.id = 1
    await group_friend_decision(decision, db, settings, bot)
    assert await friends_api.accepted(db, 1, 2)
    assert delete.await_count == 2

    await profile.group_profile_friend(callback, db, settings, bot)
    choices = bot.send_rich_message.await_args.kwargs["rich_message"].blocks[-1]
    decision.message = prompt.model_copy(update={"message_id": 11})
    decision.data = choices.buttons[0].callback_data
    decision.from_user.id = 2
    await group_friend_decision(decision, db, settings, bot)
    assert await friends_api.accepted(db, 1, 2)
    assert delete.await_count == 2
    decision.from_user.id = 1
    await group_friend_decision(decision, db, settings, bot)
    assert not await friends_api.accepted(db, 1, 2)
    assert delete.await_count == 3
    edited = edit.await_args.kwargs["rich_message"]
    assert edited.blocks[-1].buttons[2].text == "👤"


@pytest.mark.parametrize(("direction", "value"), [("up", 65), ("down", 55)])
async def test_reputation_button_pings_target_only_on_success(tmp_path, monkeypatch, direction, value):
    db = Database(tmp_path / "reputation.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Пётр")
    await db.ensure_user(2, telegram_name="Анна")
    await db.execute("UPDATE users SET reputation=CASE WHEN user_id=1 THEN 80 ELSE 60 END")
    settings = SimpleNamespace(restricted_reputation_threshold=15, community_chat_id=-100123, timezone="UTC")
    chat = Chat(id=-100123, type="supergroup")
    message = Message(message_id=5, date=1725000000, chat=chat, message_thread_id=3, is_topic_message=True)
    callback = SimpleNamespace(
        id="first", data=f"profile_action:rep_{direction}:2",
        from_user=User(id=1, is_bot=False, first_name="Пётр"), message=message, answer=AsyncMock(),
    )
    post = AsyncMock()
    monkeypatch.setattr(Message, "answer", post)
    await group.profile_action(callback, db, settings, SimpleNamespace())
    post.assert_awaited_once()
    ping = post.await_args.args[0]
    assert '<a href="tg://user?id=2">Анна</a>' in ping and f"теперь {value}" in ping
    assert post.await_args.kwargs["parse_mode"] == "HTML"
    assert (await db.get_user(2))["reputation"] == value

    day = datetime.now(UTC).date()
    for _ in range(2):
        await db.apply_reputation(1, 2, 0, day)
    callback.id = "over-limit"
    await group.profile_action(callback, db, settings, SimpleNamespace())
    post.assert_awaited_once()
    assert "Дневной лимит исчерпан" in callback.answer.await_args.args[0]
    assert callback.answer.await_args.kwargs["show_alert"]
    assert (await db.get_user(2))["reputation"] == value
