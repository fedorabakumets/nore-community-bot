import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.enums import ChatMemberStatus
from aiogram.methods import (
    EditMessageReplyMarkup,
    PinChatMessage,
    SendMediaGroup,
    SendMessage,
    SendRichMessage,
    SendSticker,
    UnpinChatMessage,
)
from aiogram.types import (
    CallbackQuery,
    Chat,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputRichBlockButtons,
    InputRichBlockParagraph,
    InputRichMessage,
    Message,
    RichMessageButton,
    Update,
    User,
)

from community_bot import durak_rooms, game_lobby_posts
from community_bot.community_scope import CommunityScopeMiddleware
from community_bot.game_invitations import announce_quick_lobby, deliver_game_invitation
from community_bot.group_message_close import (
    GroupCloseCallbackMiddleware,
    GroupCloseSendMiddleware,
    GroupMessageActorsMiddleware,
    group_message_actors,
    normalize_current_pin,
)
from community_bot.message_widgets import WidgetUpdateMiddleware
from tests.test_game_invitations import db as room_db
from tests.test_private_rich import RecordingSession

db = room_db
GROUP = -100123
NORA = User(id=999, is_bot=True, first_name="Nora")


def user(uid):
    return User(id=uid, is_bot=False, first_name=f"User {uid}")


def message(mid=10, chat=GROUP, markup=None, actor=NORA, rich=None):
    return Message(message_id=mid, chat=Chat(id=chat, type="supergroup" if chat < 0 else "private"),
                   date=datetime.now(UTC), from_user=actor, reply_markup=markup, rich_message=rich)


def fake_bot(db, *, is_admin=False):
    settings = SimpleNamespace(community_chat_id=GROUP, moderator_ids=set(), is_owner=lambda uid: uid == 8)
    return SimpleNamespace(id=NORA.id, community_db=db, community_settings=settings,
                           default=SimpleNamespace(parse_mode=None), delete_message=AsyncMock(),
                           me=AsyncMock(return_value=SimpleNamespace(username="test_nora")),
                           get_chat_member=AsyncMock(return_value=SimpleNamespace(
                               status=ChatMemberStatus.ADMINISTRATOR if is_admin else ChatMemberStatus.MEMBER)))


def keyboard(action):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Button", callback_data=action)]])


@pytest.mark.parametrize("method", [
    SendMessage(chat_id=GROUP, text="Text", reply_markup=keyboard("ui:close")),
    SendRichMessage(chat_id=GROUP, rich_message=InputRichMessage(blocks=[
        InputRichBlockParagraph(text="Play"),
        InputRichBlockButtons(buttons=[
            RichMessageButton(text="✕", callback_data="game-invite:close:2:1"),
            RichMessageButton(text="✅", url="https://t.me/nora_bot"),
        ]),
        InputRichBlockParagraph(text="Rules"),
    ])),
])
async def test_group_close_button_and_owner_survive_edits(db, method):
    bot = fake_bot(db)
    async def telegram(bot, method):
        rich = getattr(method, "rich_message", None)
        return message(rich=rich.model_dump(exclude_none=True) if rich else None)

    sent = AsyncMock(side_effect=telegram)
    middleware = GroupCloseSendMiddleware()
    with group_message_actors(1, 2):
        await middleware(sent, bot, method)
    outgoing = sent.await_args.args[1]
    assert isinstance(outgoing, SendRichMessage) and outgoing.reply_markup is None
    rows = [block.buttons for block in outgoing.rich_message.blocks if isinstance(block, InputRichBlockButtons)]
    assert len(rows) == 1 and rows[0][-1].callback_data == "nora:close:1:2"
    assert rows[0][-1].text == "❌"
    if isinstance(method, SendRichMessage):
        assert [button.text for button in rows[0]] == ["✅", "❌"]
    with group_message_actors(3):
        await middleware(sent, bot, EditMessageReplyMarkup(
            chat_id=GROUP, message_id=10, reply_markup=keyboard("play:accept"),
        ))
    edited = sent.await_args.args[1]
    assert edited.reply_markup is None
    assert [[b.callback_data for b in block.buttons]
            for block in edited.rich_message.blocks if isinstance(block, InputRichBlockButtons)] == [
                ["play:accept", "nora:close:1:2"],
            ]
    private = SendMessage(chat_id=1, text="Hello", reply_markup=keyboard("ui:close"))
    await middleware(sent, bot, private)
    assert sent.await_args.args[1] is private


async def test_batch_media_gets_buttons_of_its_own(db):
    bot = fake_bot(db)
    sent = AsyncMock(side_effect=[[message(10), message(11)], message(12), message(13)])
    method = SendMediaGroup(chat_id=GROUP, media=[InputMediaPhoto(media="one"), InputMediaPhoto(media="two")])
    with group_message_actors(1):
        await GroupCloseSendMiddleware()(sent, bot, method)
    calls = [call.args[1] for call in sent.await_args_list]
    assert calls[0] == method
    assert [call.reply_parameters.message_id for call in calls[1:]] == [10, 11]
    assert all(call.reply_markup is None for call in calls[1:])
    assert all(call.rich_message.blocks[-1].buttons[0].callback_data == "nora:close:1" for call in calls[1:])


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
    await db.remember_bot_message(GROUP, 19)
    source = InaccessibleMessage(chat=Chat(id=GROUP, type="supergroup"), message_id=19)
    legacy = CallbackQuery(id="event", from_user=user(3), chat_instance="test", data="nora:close:0", message=source)
    await GroupCloseCallbackMiddleware()(AsyncMock(), legacy, {"db": db, "bot": bot,
                                                               "settings": bot.community_settings})
    assert bot.delete_message.await_count == 4
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
    assert method.reply_markup is None
    join, close = method.rich_message.blocks[-1].buttons
    assert join.text == "Присоединиться" and close.callback_data == "nora:close:1"
    row = await db.fetchone("SELECT json_extract(value,'$[4]') AS until FROM bot_state WHERE key=?",
                            (f"game-lobby-post:{GROUP}:10",))
    await game_lobby_posts.cleanup(db, bot, now=row["until"] - 0.001)
    bot.delete_message.assert_not_called()
    await game_lobby_posts.cleanup(db, bot, now=row["until"])
    await game_lobby_posts.cleanup(db, bot, now=row["until"] + 1)
    bot.delete_message.assert_awaited_once_with(GROUP, 10)
    assert (await db.fetchone("SELECT status FROM durak_rooms WHERE id=?", (rid,)))["status"] == "waiting"


async def test_mini_app_start_confirms_group_invitation_before_deleting_it(db):
    rid, _ = await durak_rooms.command(db, 1, command("create", 1, config={"stake": 5, "private": True}))
    _, notice = await durak_rooms.command(db, 1, command("invite", 2, room=rid, friend=2))
    app_bot = fake_bot(db)
    app_bot.me = AsyncMock(return_value=SimpleNamespace(username="test_nora"))
    app_bot.send_rich_message = AsyncMock(side_effect=lambda chat, **_: message(10, chat))
    app_bot.edit_message_text = AsyncMock()
    await deliver_game_invitation(app_bot, db, app_bot.community_settings, "durak", rid, 1, 2, notice[0])
    await game_lobby_posts.cleanup(db, app_bot)
    app_bot.delete_message.assert_not_called()
    await durak_rooms.command(db, 2, command("join", 3, room=rid))
    now = time.time()
    await game_lobby_posts.cleanup(db, app_bot, now=now)
    app_bot.edit_message_text.assert_awaited_once()
    edit = app_bot.edit_message_text.await_args.kwargs
    assert (edit["chat_id"], edit["message_id"]) == (GROUP, 10)
    assert [block.text for block in edit["rich_message"].blocks] == ["Игра принята ✅"]
    app_bot.delete_message.assert_awaited_once_with(2, 10)
    await game_lobby_posts.cleanup(db, app_bot, now=now + 1.99)
    app_bot.delete_message.assert_awaited_once_with(2, 10)
    # A tiny margin avoids crossing SQLite's floating-point timestamp boundary.
    await game_lobby_posts.cleanup(db, app_bot, now=now + 2.1)
    assert [call.args for call in app_bot.delete_message.await_args_list] == [(2, 10), (GROUP, 10)]
    app_bot.edit_message_text.assert_awaited_once()
    assert (await db.fetchone("SELECT status FROM durak_rooms WHERE id=?", (rid,)))["status"] == "playing"

async def test_roulette_only_confirms_accepted_challenge_without_adding_buttons(db):
    accepted = await db.create_roulette(GROUP, 1, 2)
    declined = await db.create_roulette(GROUP, 1, 3)
    await db.set_bot_state(f"{game_lobby_posts.PREFIX}{GROUP}:10",
                           f'["roulette",{accepted},{GROUP},10,{time.time() + 120},0]')
    await game_lobby_posts.remember(db, "roulette", declined, GROUP, message(11))
    assert (await db.settle_roulette(accepted, 2, 1))[0]
    assert await db.cancel_roulette(declined, 3)
    session = RecordingSession()
    async with Bot("999:TEST", session=session) as bot:
        bot.community_db = db
        bot.community_settings = fake_bot(db).community_settings
        bot.session.middleware.register(GroupCloseSendMiddleware())
        now = time.time()
        await game_lobby_posts.cleanup(db, bot, now=now)
        edit, delete = session.calls
        assert edit.message_id == 10 and edit.reply_markup is None
        assert [block.text for block in edit.rich_message.blocks] == ["Игра принята ✅"]
        assert delete.message_id == 11
        await game_lobby_posts.cleanup(db, bot, now=now + 1)
        assert len(session.calls) == 2
        # SQLite JSON float precision can put the 2s deadline just after now + 2.
        await game_lobby_posts.cleanup(db, bot, now=now + 2.1)
        assert session.calls[-1].__api_method__ == "deleteMessage" and session.calls[-1].message_id == 10


async def test_join_during_delivery_confirms_only_matching_and_older_invitations(db):
    rid, _ = await durak_rooms.command(db, 1, command("create", 1, config={"stake": 5, "players": 3}))
    sending = time.time()
    await durak_rooms.command(db, 2, command("join", 2, room=rid), now=sending + 1)
    await game_lobby_posts.remember(db, "durak", rid, GROUP, message(10),
                                    now=sending + 2, sent_since=sending, recipient=2)
    await game_lobby_posts.remember(db, "durak", rid, GROUP, message(11),
                                    now=sending + 2, sent_since=sending, recipient=3)
    await game_lobby_posts.remember(db, "durak", rid, GROUP, message(12), now=sending + 2, announcement=True)
    bot = fake_bot(db)
    bot.edit_message_text = AsyncMock()
    await game_lobby_posts.cleanup(db, bot, now=sending + 2)
    bot.edit_message_text.assert_awaited_once()
    assert bot.edit_message_text.await_args.kwargs["message_id"] == 10
    bot.delete_message.assert_not_awaited()


async def test_native_sticker_close_removes_companion_and_its_original(db, monkeypatch):
    bot = fake_bot(db)
    answer = AsyncMock()
    monkeypatch.setattr(CallbackQuery, "answer", answer)
    sent = AsyncMock(side_effect=[message(10), message(11)])
    with group_message_actors(1):
        await GroupCloseSendMiddleware()(sent, bot, SendSticker(chat_id=GROUP, sticker="sticker"))
    outgoing = sent.await_args.args[1]
    assert outgoing.reply_markup is None
    assert outgoing.rich_message.blocks[-1].buttons[0].text == "❌"
    # Some Telegram callback updates contain no usable author or Rich markup.
    source = InaccessibleMessage(chat=Chat(id=GROUP, type="supergroup"), message_id=11)
    event = CallbackQuery(id="event", from_user=user(1), chat_instance="test", data="nora:close:1", message=source)
    await GroupCloseCallbackMiddleware()(AsyncMock(), event, {"settings": bot.community_settings, "bot": bot, "db": db})
    assert [call.args for call in bot.delete_message.await_args_list] == [(GROUP, 10), (GROUP, 11)]


async def test_only_pinned_posts_get_one_nora_inline_link(db):
    bot = fake_bot(db)
    calls = []
    middleware = GroupCloseSendMiddleware()

    async def telegram(bot, method):
        calls.append(method)
        if isinstance(method, (PinChatMessage, UnpinChatMessage)):
            return True
        if rich := getattr(method, "rich_message", None):
            return message(rich=rich.model_dump(exclude_none=True))
        return message()

    await middleware(telegram, bot, SendMessage(chat_id=GROUP, text="Post", reply_markup=keyboard("open")))
    assert calls[-1].reply_markup is None
    await middleware(telegram, bot, PinChatMessage(chat_id=GROUP, message_id=10))
    inline = calls[-1].reply_markup.inline_keyboard
    assert len(inline) == len(inline[0]) == 1
    assert (inline[0][0].text, inline[0][0].url) == ("НОРА", "https://t.me/test_nora?startapp")
    await middleware(telegram, bot, EditMessageReplyMarkup(chat_id=GROUP, message_id=10,
                                                         reply_markup=keyboard("new")))
    assert calls[-1].reply_markup.inline_keyboard[0][0].text == "НОРА"
    rows = [block.buttons for block in calls[-1].rich_message.blocks
            if isinstance(block, InputRichBlockButtons)]
    assert [[b.callback_data for b in row] for row in rows] == [["new", "nora:close:0"], [None]]
    assert rows[-1][0].text == "📲 Добавить Нору на экран"
    assert rows[-1][0].url == "https://t.me/test_nora?startapp=nora_home_screen"
    await middleware(telegram, bot, UnpinChatMessage(chat_id=GROUP, message_id=10))
    assert calls[-1].reply_markup is None


async def test_restore_only_own_current_pin(db):
    bot = fake_bot(db)
    bot.get_chat = AsyncMock(return_value=SimpleNamespace(id=GROUP, pinned_message=message()))
    called = AsyncMock(return_value=message())

    class Client:
        def __getattr__(self, name):
            return getattr(bot, name)

        async def __call__(self, method):
            return await called(method)

    await normalize_current_pin(Client(), bot.community_settings)
    method = called.await_args.args[0]
    assert method.message_id == 10 and method.reply_markup.inline_keyboard[0][0].text == "НОРА"


async def test_rich_close_reaches_callback_handler_with_widget_middleware_enabled(db):
    session = RecordingSession()
    async with Bot("999:OFFLINE_RICH_CLOSE_TEST", session=session) as bot:
        settings = fake_bot(db).community_settings
        bot.community_db, bot.community_settings = db, settings
        bot.session.middleware.register(GroupCloseSendMiddleware())
        dispatcher = Dispatcher()
        dispatcher.update.outer_middleware(CommunityScopeMiddleware())
        dispatcher.update.outer_middleware(GroupMessageActorsMiddleware())
        dispatcher.update.outer_middleware(WidgetUpdateMiddleware())
        dispatcher.callback_query.outer_middleware(GroupCloseCallbackMiddleware())

        with group_message_actors(1):
            sent = await bot.send_rich_message(GROUP, rich_message=InputRichMessage(blocks=[
                InputRichBlockParagraph(text="Гайд по командам"),
            ]))
        close = sent.rich_message.blocks[-1].buttons[0]
        assert close.text == "❌" and sent.reply_markup is None
        card = message(sent.message_id, rich=sent.rich_message)
        callback = CallbackQuery(id="click-close", from_user=user(1), chat_instance="community", message=card,
                                 data=close.callback_data)
        await dispatcher.feed_update(bot, Update(update_id=1, callback_query=callback), db=db, settings=settings)

    assert [method.__api_method__ for method in session.calls] == [
        "sendRichMessage", "deleteMessage", "answerCallbackQuery",
    ]
    assert session.calls[-2].message_id == sent.message_id
    assert session.calls[-1].text is None
