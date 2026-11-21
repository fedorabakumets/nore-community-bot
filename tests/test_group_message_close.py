from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ChatMemberStatus
from aiogram.methods import EditMessageReplyMarkup, SendMediaGroup, SendMessage, SendRichMessage, SendSticker
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputRichBlockButtons,
    InputRichBlockParagraph,
    InputRichMessage,
    Message,
    RichMessageButton,
    User,
)

from community_bot import durak_rooms, game_lobby_posts
from community_bot.game_invitations import announce_quick_lobby, deliver_game_invitation
from community_bot.group_message_close import (
    GroupCloseCallbackMiddleware,
    GroupCloseSendMiddleware,
    group_message_actors,
)
from tests.test_game_invitations import db as room_db

db = room_db
GROUP = -100123
NORA = User(id=999, is_bot=True, first_name="Nora")


def user(uid):
    return User(id=uid, is_bot=False, first_name=f"User {uid}")


def message(mid=10, chat=GROUP, markup=None, actor=NORA):
    return Message(message_id=mid, chat=Chat(id=chat, type="supergroup" if chat < 0 else "private"),
                   date=datetime.now(UTC), from_user=actor, reply_markup=markup)


def fake_bot(db, *, is_admin=False):
    settings = SimpleNamespace(community_chat_id=GROUP, moderator_ids=set(), is_owner=lambda uid: uid == 8)
    return SimpleNamespace(id=NORA.id, community_db=db, community_settings=settings, delete_message=AsyncMock(),
                           get_chat_member=AsyncMock(return_value=SimpleNamespace(
                               status=ChatMemberStatus.ADMINISTRATOR if is_admin else ChatMemberStatus.MEMBER)))


def keyboard(action):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Button", callback_data=action)]])


@pytest.mark.parametrize("method", [
    SendMessage(chat_id=GROUP, text="Text", reply_markup=keyboard("ui:close")),
    SendSticker(chat_id=GROUP, sticker="file_id"),
    SendRichMessage(chat_id=GROUP, rich_message=InputRichMessage(blocks=[
        InputRichBlockParagraph(text="Play"),
        InputRichBlockButtons(buttons=[
            RichMessageButton(text="✕", callback_data="game-invite:close:2:1"),
            RichMessageButton(text="Join", url="https://t.me/nora_bot"),
        ]),
    ])),
])
async def test_group_close_button_and_owner_survive_edits(db, method):
    bot = fake_bot(db)
    sent = AsyncMock(return_value=message())
    middleware = GroupCloseSendMiddleware()
    with group_message_actors(1, 2):
        await middleware(sent, bot, method)
    outgoing = sent.await_args.args[1]
    assert outgoing.reply_markup.inline_keyboard[-1][0].callback_data == "nora:close:1:2"
    assert outgoing.reply_markup.inline_keyboard[-1][0].text == "✕ Закрыть"
    if isinstance(outgoing, SendRichMessage):
        assert [button.text for button in outgoing.rich_message.blocks[-1].buttons] == ["Join"]
    with group_message_actors(3):
        await GroupCloseSendMiddleware()(sent, bot, EditMessageReplyMarkup(
            chat_id=GROUP, message_id=10, reply_markup=keyboard("play:accept"),
        ))
    edited = sent.await_args.args[1]
    assert [button.callback_data for row in edited.reply_markup.inline_keyboard for button in row] == [
        "play:accept", "nora:close:1:2",
    ]
    private = SendMessage(chat_id=1, text="Hello", reply_markup=keyboard("ui:close"))
    await middleware(sent, bot, private)
    assert sent.await_args.args[1] is private


async def test_batch_media_gets_buttons_of_its_own(db):
    bot = fake_bot(db)
    sent = AsyncMock(side_effect=[[message(10), message(11)], message(10), message(11)])
    method = SendMediaGroup(chat_id=GROUP, media=[InputMediaPhoto(media="one"), InputMediaPhoto(media="two")])
    with group_message_actors(1):
        await GroupCloseSendMiddleware()(sent, bot, method)
    calls = [call.args[1] for call in sent.await_args_list]
    assert calls[0] == method
    assert [call.message_id for call in calls[1:]] == [10, 11]
    assert all(call.reply_markup.inline_keyboard[-1][0].callback_data == "nora:close:1" for call in calls[1:])


@pytest.mark.parametrize(("uid", "admin", "callback", "author", "allowed"), [
    (1, False, "nora:close:1:2", NORA, True),
    (2, False, "nora:close:1:2", NORA, True),
    (3, False, "nora:close:1:2", NORA, False),
    (3, True, "nora:close:1:2", NORA, True),
    (8, False, "nora:close:1:2", NORA, True),
    (8, False, "nora:close:8", NORA, False),
    (8, False, "nora:close:1:2", user(4), False),
])
async def test_group_close_checks_real_button_author_and_permissions(db, monkeypatch, uid, admin, callback, author,
                                                                allowed):
    bot = fake_bot(db, is_admin=admin)
    answer = AsyncMock()
    monkeypatch.setattr(CallbackQuery, "answer", answer)
    event = CallbackQuery(id="event", from_user=user(uid), chat_instance="test", data=callback,
                          message=message(markup=keyboard("nora:close:1:2"), actor=author))
    downstream = AsyncMock()
    await GroupCloseCallbackMiddleware()(downstream, event, {"db": db, "bot": bot,
                                                              "settings": bot.community_settings})
    if allowed:
        bot.delete_message.assert_awaited_once_with(GROUP, 10)
    else:
        bot.delete_message.assert_not_called()
        assert answer.await_args.kwargs.get("show_alert")
    downstream.assert_not_called()


async def test_global_announcement_only_admin_and_legacy_staff_override(db, monkeypatch):
    await db.set_role(3, "admin")
    bot = fake_bot(db)
    monkeypatch.setattr(CallbackQuery, "answer", AsyncMock())
    for data in ("nora:close:0", "ui:close", "game-invite:close:2:1"):
        event = CallbackQuery(id="event", from_user=user(3), chat_instance="test", data=data,
                              message=message(markup=keyboard(data)))
        await GroupCloseCallbackMiddleware()(AsyncMock(), event, {"db": db, "bot": bot,
                                                                  "settings": bot.community_settings})
    assert bot.delete_message.await_count == 3
    bot.get_chat_member.assert_not_awaited()


def command(action, nonce, **fields):
    return {"action": action, "nonce": f"{nonce:016d}", **fields}


async def test_quick_post_expires_at_two_minutes_without_cancelling_waiting_room(db):
    rid, _ = await durak_rooms.command(db, 1, command("quick", 1, config={"stake": 5}), game="barricade")
    bot = fake_bot(db)
    bot.me = AsyncMock(return_value=SimpleNamespace(username="test_nora"))
    outgoing = AsyncMock(return_value=message())

    async def send(chat_id, *, rich_message):
        method = SendRichMessage(chat_id=chat_id, rich_message=rich_message)
        return await GroupCloseSendMiddleware()(outgoing, bot, method)

    bot.send_rich_message = send
    await announce_quick_lobby(bot, db, bot.community_settings, "barricade", rid, 1, 5)
    method = outgoing.await_args.args[1]
    assert method.reply_markup.inline_keyboard[0][0].callback_data == "nora:close:1"
    row = await db.fetchone("SELECT json_extract(value,'$[4]') AS until FROM bot_state WHERE key=?",
                            (f"game-lobby-post:{GROUP}:10",))
    await game_lobby_posts.cleanup(db, bot, now=row["until"] - 0.001)
    bot.delete_message.assert_not_called()
    await game_lobby_posts.cleanup(db, bot, now=row["until"])
    await game_lobby_posts.cleanup(db, bot, now=row["until"] + 1)
    bot.delete_message.assert_awaited_once_with(GROUP, 10)
    assert (await db.fetchone("SELECT status FROM durak_rooms WHERE id=?", (rid,)))["status"] == "waiting"


async def test_mini_app_start_retires_both_copies_of_the_invitation(db):
    rid, _ = await durak_rooms.command(db, 1, command("create", 1, config={"stake": 5, "private": True}))
    _, notice = await durak_rooms.command(db, 1, command("invite", 2, room=rid, friend=2))
    app_bot = fake_bot(db)
    app_bot.me = AsyncMock(return_value=SimpleNamespace(username="test_nora"))
    app_bot.send_rich_message = AsyncMock(side_effect=lambda chat, **_: message(10, chat))
    await deliver_game_invitation(app_bot, db, app_bot.community_settings, "durak", rid, 1, 2, notice[0])
    await game_lobby_posts.cleanup(db, app_bot)
    app_bot.delete_message.assert_not_called()
    await durak_rooms.command(db, 2, command("join", 3, room=rid))
    await game_lobby_posts.cleanup(db, app_bot)
    assert {call.args for call in app_bot.delete_message.await_args_list} == {(GROUP, 10), (2, 10)}
    assert (await db.fetchone("SELECT status FROM durak_rooms WHERE id=?", (rid,)))["status"] == "playing"
