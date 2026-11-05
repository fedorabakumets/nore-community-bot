from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import EditMessageText, SendRichMessage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Chat,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichBlockButtons,
    InputRichBlockParagraph,
    InputRichMessage,
    Message,
    MessageEntity,
    RichMessageButton,
    Update,
    User,
)

from community_bot.access import OnboardingKeyboardMiddleware
from community_bot.blocks import answer_block, edit_block, replace_block
from community_bot.database import Database
from community_bot.ephemeral import patch_bot_ephemeral
from community_bot.keyboards import YES_NO_KEYBOARD, flow_reply_keyboard, ibtn, main_private_keyboard
from community_bot.navigation import CabinetNavigationMiddleware
from community_bot.private_rich import PrivateRichContextMiddleware, PrivateRichMiddleware, button_rows, text_blocks


def incoming(uid=7, text="/start", **kwargs):
    return Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=uid, type="private"),
                   from_user=User(id=uid, is_bot=False, first_name="Рома"), text=text, **kwargs)


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.fail = None
        self.next_id = 100
        self.uneditable = set()

    async def close(self):
        pass

    async def stream_content(self, url, **kwargs):
        yield b""

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 - BaseSession interface
        self.calls.append(method)
        # Exercise actual aiogram multipart serialization without network access.
        for value in method.model_dump(warnings=False).values():
            self.prepare_value(value, bot=bot, files={})
        if self.fail:
            error, self.fail = self.fail, None
            raise error
        if method.__api_method__ in {"answerCallbackQuery", "deleteMessage"}:
            return True
        uid = method.chat_id
        if isinstance(method, EditMessageText) and (uid, method.message_id) in self.uneditable:
            raise TelegramBadRequest(method=method, message="Bad Request: message can't be edited")
        if isinstance(method, SendRichMessage):
            mid = self.next_id
            self.next_id += 1
            if method.reply_markup is not None and not isinstance(method.reply_markup, InlineKeyboardMarkup):
                self.uneditable.add((uid, mid))
        else:
            mid = getattr(method, "message_id", 2)
        rich = getattr(method, "rich_message", None)
        fields = {}
        if rich:
            blocks = rich.model_dump(exclude_none=True, warnings=False)["blocks"]
            for block in blocks:
                kind = block["type"]
                if kind == "photo":
                    block[kind] = [{"file_id": "photo-cached", "file_unique_id": "photo-unique",
                                    "width": 500, "height": 300}]
                elif kind in {"document", "audio", "video", "animation", "voice_note"}:
                    block[kind] = {"file_id": kind + "-cached", "file_unique_id": kind + "-unique",
                                   "width": 100, "height": 100, "duration": 1}
            fields["rich_message"] = {"blocks": blocks}
        else:
            fields["text"] = getattr(method, "text", None)
        return Message(message_id=mid, date=datetime.now(UTC),
                       chat=Chat(id=uid, type="private" if uid > 0 else "supergroup"), **fields).as_(bot)


@pytest.fixture
async def setup(tmp_path):
    db = Database(tmp_path / "rich.db")
    await db.initialize()
    await db.ensure_user(7, telegram_name="Рома")
    app = await db.create_application(7, {})
    await db.decide_application(app, 99, "approved", None)
    settings = SimpleNamespace(is_owner=lambda uid: uid == 99, moderator_ids=frozenset())
    session = RecordingSession()
    bot = Bot("777777:TEST_TOKEN_FOR_OFFLINE_RICH_TESTS", session=session)
    bot.community_db, bot.community_settings = db, settings
    bot.session.middleware.register(OnboardingKeyboardMiddleware())
    bot.session.middleware.register(PrivateRichMiddleware())
    patch_bot_ephemeral(bot)
    state = SimpleNamespace(get_state=AsyncMock(return_value=None))
    return db, bot, session, state


async def turn(setup, handler, event=None):
    db, bot, _, state = setup
    return await PrivateRichContextMiddleware()(handler, (event or incoming()).as_(bot),
                                                {"bot": bot, "db": db, "state": state})


def content(call):
    return call.rich_message.model_dump(exclude_none=True, warnings=False)["blocks"]


def actions(call):
    return {button["callback_data"]: button for block in content(call) if block["type"] == "buttons"
            for button in block["buttons"] if button.get("callback_data")}


def test_html_and_entities_are_preserved_and_user_text_is_not_markup():
    rich = InputRichMessage(blocks=text_blocks(
        '<b>Нора &amp; Рома</b> <a href="tg://user?id=7">Рома</a>\n'
        '<blockquote>Текст <i>внутри</i></blockquote><blockquote expandable>Ещё</blockquote>'
        '<pre><code class="language-python">x &lt; 5</code></pre>'
        '<tg-emoji emoji-id="123">✨</tg-emoji>', "HTML",
    ))
    raw = rich.model_dump_json(exclude_none=True)
    assert '"type":"bold"' in raw and "Нора & Рома" in raw
    assert '"type":"blockquote"' in raw and '"type":"expandable_blockquote"' in raw
    assert '"type":"pre"' in raw and "x < 5" in raw
    assert '"alternative_text":"✨"' in raw
    assert text_blocks("<b>Рома</b>")[0]["text"] == "<b>Рома</b>"
    entity = text_blocks("✨ Рома", entities=[MessageEntity(type="bold", offset=3, length=4)])
    assert '"bold"' in json.dumps(entity)


def test_rich_buttons_preserve_callbacks_links_webapps_and_colors():
    rows = button_rows(InlineKeyboardMarkup(inline_keyboard=[[
        ibtn("Профиль", "menu:profile"), ibtn("Да", "yes"), ibtn("Нет", "no"),
        InlineKeyboardButton(text="Открыть", url="https://example.org"),
        InlineKeyboardButton(text="Приложение", web_app={"url": "https://example.org/app"}),
        InlineKeyboardButton(text="Копировать", copy_text={"text": "Рома"}),
    ]]))
    rich = InputRichMessage(blocks=rows)
    assert all(isinstance(b, RichMessageButton) for b in rich.blocks[0].buttons)
    buttons = rows[0]["buttons"]
    assert [b["style"] for b in buttons[:3]] == ["primary", "success", "danger"]
    assert buttons[3]["url"] == "https://example.org"
    assert buttons[4]["web_app"]["url"].endswith("/app")
    assert buttons[5]["copy_text"]["text"] == "Рома"


async def test_commands_and_repeated_callbacks_edit_one_rich_message(setup):
    _, bot, session, _ = setup
    first = await bot.send_message(7, "<b>Главная</b>", parse_mode="HTML", reply_markup=main_private_keyboard())
    assert isinstance(session.calls[0], SendRichMessage)
    assert session.calls[0].reply_markup is None
    await replace_block(first, "wallet", "Баланс", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        ibtn("Оплатить", "wallet:pay"), ibtn("Назад", "menu:home"),
    ]]))
    await edit_block(first, "Готово")
    assert len(session.calls) == 3
    assert all(isinstance(call, EditMessageText) and call.message_id == first.message_id for call in session.calls[1:])
    assert not session.calls[-1].reply_markup.inline_keyboard
    assert actions(session.calls[1])["wallet:pay"]["style"] == "success"
    assert actions(session.calls[1])["menu:home"]["style"] == "danger"


async def test_cover_long_text_and_secondary_keyboard_stay_in_one_page(setup):
    _, _, session, _ = setup

    async def handler(message, data):
        await answer_block(message, "wallet", "Большой текст " * 150, parse_mode="HTML", reply_markup=YES_NO_KEYBOARD)
        await message.answer("Следующий шаг", reply_markup=main_private_keyboard())

    await turn(setup, handler)
    assert sum(isinstance(c, SendRichMessage) for c in session.calls) == 1
    last = session.calls[-1]
    raw = json.dumps(content(last), ensure_ascii=False, default=str)
    assert "Большой текст" in raw and "Следующий шаг" in raw
    assert raw.count("Большой текст") == 150
    assert any(block["type"] == "photo" for block in content(last))
    assert actions(last)["application:interview:yes"]["style"] == "success"


async def test_guest_and_form_controls_do_not_expose_member_sections(setup):
    _, bot, session, state = setup
    await bot.send_message(8, "Добро пожаловать", reply_markup=main_private_keyboard())
    assert set(actions(session.calls[-1])) == {"start:apply", "menu:question"}
    state.get_state.return_value = "ApplicationForm:name"

    async def handler(message, data):
        await message.answer("Как тебя зовут?", reply_markup=flow_reply_keyboard())

    await turn(setup, handler, incoming(uid=8))
    assert set(actions(session.calls[-1])) == {"flow:cancel", "flow:restart", "menu:question"}
    assert actions(session.calls[-1])["flow:cancel"]["style"] == "danger"
    await bot.send_message(8, "Уведомление")
    raw = session.calls[-1].rich_message.model_dump_json()
    assert "Как тебя зовут?" in raw and "Уведомление" in raw
    assert "flow:cancel" in actions(session.calls[-1])


async def test_restarted_middleware_reuses_saved_panel_and_cached_photo(setup, tmp_path):
    db, bot, session, _ = setup
    first = await bot.send_photo(7, FSInputFile(tmp_path / "image.jpg"), caption="Обложка")
    saved = json.loads(await db.get_bot_state("private_rich_panel:7"))
    assert saved["body"][0]["photo"]["media"] == "photo-cached"
    bot.session.middleware.unregister(bot.session.middleware[1])
    bot.session.middleware.register(PrivateRichMiddleware())
    await first.edit_reply_markup(reply_markup=YES_NO_KEYBOARD)
    assert session.calls[-1].message_id == first.message_id
    assert content(session.calls[-1])[0]["photo"]["media"] == "photo-cached"


@pytest.mark.parametrize("method", [
    "send_photo", "send_video", "send_audio", "send_document", "send_voice", "send_animation",
])
@pytest.mark.parametrize("upload", [False, True])
async def test_all_supported_media_are_embedded(setup, method, upload):
    _, bot, session, _ = setup
    file = BufferedInputFile(b"offline-media", filename="upload.bin") if upload else "telegram-file"
    result = await getattr(bot, method)(7, file, caption="<b>Вложение</b>", parse_mode="HTML")
    assert getattr(result, method.removeprefix("send_")) is not None
    assert len(session.calls) == 1 and isinstance(session.calls[0], SendRichMessage)
    assert content(session.calls[0])[0]["type"] in {"photo", "video", "audio", "document", "voice_note", "animation"}


async def test_ticket_header_and_copied_attachment_include_all_text_and_actions(setup):
    _, bot, session, _ = setup
    source = incoming(text=None, caption="Ответ <без HTML>",
                      document={"file_id": "doc", "file_unique_id": "unique"})

    async def handler(message, data):
        await bot.send_message(8, "Ответ по тикету №1", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            ibtn("Ответить", "ticket:reply:1"),
        ]]))
        sent = await bot.copy_message(8, message.chat.id, message.message_id)
        assert sent.message_id == 100

    await turn(setup, handler, source)
    last = session.calls[-1]
    text = json.dumps(content(last), ensure_ascii=False, default=str)
    assert "Ответ по тикету №1" in text and "Ответ <без HTML>" in text
    assert "ticket:reply:1" in actions(last)
    assert any(b["type"] == "document" for b in content(last))
    assert len(session.calls) == 2 and isinstance(last, EditMessageText)


async def test_deleted_panel_is_recreated_once(setup):
    _, bot, session, _ = setup
    await bot.send_message(7, "Первый экран")
    session.fail = TelegramBadRequest(method=EditMessageText(chat_id=7, message_id=100, text="x"),
                                      message="Bad Request: message to edit not found")
    result = await bot.send_message(7, "Новый экран")
    assert result.message_id == 101
    assert [type(call) for call in session.calls] == [SendRichMessage, EditMessageText, SendRichMessage]


@pytest.mark.parametrize("error", ["format", "network", "rate", "unchanged", "uneditable"])
async def test_errors_do_not_send_duplicate_messages(setup, error):
    _, bot, session, _ = setup
    await bot.send_message(7, "Экран")
    method = EditMessageText(chat_id=7, message_id=100, text="x")
    errors = {
        "uneditable": TelegramBadRequest(method=method, message="Bad Request: message can't be edited"),
        "format": TelegramBadRequest(method=method, message="Bad Request: invalid rich block"),
        "network": TelegramNetworkError(method=method, message="timeout"),
        "rate": TelegramRetryAfter(method=method, message="flood", retry_after=1),
        "unchanged": TelegramBadRequest(method=method, message="Bad Request: message is not modified"),
    }
    session.fail = errors[error]
    if error == "unchanged":
        assert (await bot.send_message(7, "Экран")).message_id == 100
    else:
        with pytest.raises(type(errors[error])):
            await bot.send_message(7, "Другой экран")
    assert len(session.calls) == 2 and isinstance(session.calls[-1], EditMessageText)


async def test_concurrent_private_sends_create_only_one_panel(setup):
    _, bot, session, _ = setup
    await asyncio.gather(*(bot.send_message(7, str(i)) for i in range(5)))
    assert sum(isinstance(call, SendRichMessage) for call in session.calls) == 1


async def test_native_rich_and_buttons_are_preserved(setup):
    _, bot, session, _ = setup
    await bot.send_rich_message(7, InputRichMessage(blocks=[
        InputRichBlockParagraph(text="Подарок"), InputRichBlockButtons(buttons=[RichMessageButton(
            text="Забрать", style="success", callback_data="birthday:claim:2026-11-05:7",
        )]),
    ]))
    assert "birthday:claim:2026-11-05:7" in actions(session.calls[-1])


async def test_markup_cleanup_does_not_remove_buttons_of_next_screen(setup):
    _, bot, session, _ = setup
    first = await bot.send_message(7, "Приглашение")

    async def handler(message, data):
        await message.answer("Открыть лобби", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Лобби", web_app={"url": "https://example.org/lobby"}),
        ]]))
        await first.edit_reply_markup(reply_markup=None)

    await turn(setup, handler)
    assert len(session.calls) == 2
    assert "https://example.org/lobby" in session.calls[-1].rich_message.model_dump_json()


async def test_stale_callback_cannot_apply_business_action(setup):
    _, bot, session, _ = setup
    await bot.send_message(7, "Текущий экран")
    callback = CallbackQuery(id="old", from_user=incoming().from_user, chat_instance="x",
                             message=incoming(), data="shop:pay:old")
    handler = AsyncMock()
    await turn(setup, handler, callback)
    handler.assert_not_awaited()
    assert session.calls[-1].__api_method__ == "answerCallbackQuery"


async def test_close_keeps_panel_and_group_requests_are_untouched(setup):
    from community_bot.ephemeral import _PENDING
    from community_bot.routers.flows import ui_close

    _, bot, session, _ = setup
    first = await bot.send_message(7, "Экран")
    callback = CallbackQuery(id="close", from_user=incoming().from_user, chat_instance="x",
                             message=first, data="ui:close").as_(bot)
    await ui_close(callback)
    assert session.calls[-1].message_id == 100
    assert "menu:home" in actions(session.calls[-1])
    assert not any(call.__api_method__ == "deleteMessage" for call in session.calls)
    await bot.send_message(-100, "Группа", reply_markup=YES_NO_KEYBOARD)
    assert session.calls[-1].__api_method__ == "sendMessage"
    await asyncio.gather(*[task for task in _PENDING if task.get_loop() is asyncio.get_running_loop()])


async def test_navigation_cancels_intent_embedded_in_rich_buttons(setup):
    db, bot, _, state = setup
    first = await bot.send_message(7, "Оплата", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        ibtn("Оплатить", "shop:pay:test-intent"),
    ]]))
    callback = CallbackQuery(id="back", from_user=incoming().from_user, chat_instance="x",
                             message=first, data="menu:home")
    state.get_data = AsyncMock(return_value={})
    state.clear = AsyncMock()
    db.cancel_wallet_intent = AsyncMock()
    await CabinetNavigationMiddleware()(AsyncMock(), callback, {"db": db, "state": state})
    db.cancel_wallet_intent.assert_awaited_once_with(7, "test-intent")


@pytest.mark.parametrize("navigate_away", [False, True])
async def test_background_game_updates_respect_the_current_screen(setup, navigate_away):
    _, bot, session, _ = setup
    first = await bot.send_message(7, "Игра")
    ready = asyncio.Event()
    job = None

    async def handler(message, data):
        nonlocal job
        await first.edit_text("Игра идёт")

        async def tick():
            await ready.wait()
            await first.edit_text("Новый ход")

        job = asyncio.create_task(tick())

    await turn(setup, handler)
    if navigate_away:
        await bot.send_message(7, "Профиль")
    before = len(session.calls)
    ready.set()
    await job
    assert len(session.calls) == before + (0 if navigate_away else 1)


async def test_real_application_flow_finishes_in_one_message(setup):
    from community_bot.routers import private
    from community_bot.states import ApplicationForm

    db, bot, session, _ = setup
    bot.community_settings.reviewers = frozenset()
    dispatcher = Dispatcher()
    dispatcher.message.outer_middleware(PrivateRichContextMiddleware())
    dispatcher.callback_query.outer_middleware(PrivateRichContextMiddleware())
    router = Router()
    router.callback_query.register(private.begin_application_button, F.data == "start:apply")
    router.message.register(private.application_name, ApplicationForm.name)
    router.message.register(private.application_age, ApplicationForm.age)
    router.message.register(private.application_referral, ApplicationForm.referral)
    router.message.register(private.application_expectations, ApplicationForm.expectations)
    router.message.register(private.application_bio, ApplicationForm.bio)
    router.callback_query.register(private.finish_application, ApplicationForm.interview,
                                    F.data.startswith("application:interview:"))
    dispatcher.include_router(router)
    first = await bot.send_message(8, "Добро пожаловать")
    actor = incoming(uid=8).from_user

    async def callback(action, update_id, message):
        event = CallbackQuery(id=str(update_id), from_user=actor, chat_instance="x", message=message, data=action)
        await dispatcher.feed_update(bot, Update(update_id=update_id, callback_query=event),
                                     db=db, settings=bot.community_settings)

    await callback("start:apply", 1, first)
    for idx, text in enumerate(["Рома", "25", "От друзей", "Общение", "Люблю музыку"], 2):
        await dispatcher.feed_update(bot, Update(update_id=idx, message=incoming(uid=8, text=text)),
                                     db=db, settings=bot.community_settings)
    last = Message(message_id=first.message_id, date=datetime.now(UTC), chat=first.chat,
                   rich_message={"blocks": content(session.calls[-1])})
    await callback("application:interview:yes", 8, last)
    panels = [call for call in session.calls if isinstance(call, (SendRichMessage, EditMessageText))]
    assert sum(isinstance(call, SendRichMessage) for call in panels) == 1
    assert all(getattr(call, "message_id", first.message_id) == first.message_id for call in panels)
    assert await db.has_pending_application(8)
    assert "отправлена на проверку" in panels[-1].rich_message.model_dump_json()
    assert set(actions(panels[-1])) == {"menu:question"}
    await dispatcher.storage.close()


@pytest.mark.parametrize("operation", ["ticket", "broadcast", "upload"])
async def test_web_admin_ui_is_captured_before_rich_and_recipients_receive_rich(setup, operation):
    from community_bot.admin_web import AdminBridge

    db, bot, session, _ = setup
    settings = bot.community_settings
    settings.__dict__.update(owner_id=7, owner_ids=frozenset({7}), is_owner=lambda uid: uid == 7,
                             reviewers=frozenset({7}), restricted_reputation_threshold=0,
                             timezone="Europe/Moscow", community_chat_id=-100123,
                             community_invite_url="", cookie_price_rub=1)
    await db.ensure_user(8, telegram_name="Участник")
    await bot.send_message(7, "Личное меню")
    bridge = AdminBridge(db, settings, bot)
    actor = {"id": 7, "first_name": "Владелец"}

    async def click(view, label):
        selected = next(b for card in view["cards"] for row in card["buttons"] for b in row
                        if label in b["text"] and "action" in b)
        return await bridge.action(actor, {"action": selected["action"], "version": view["version"]})

    view = await bridge.open(actor)
    if operation == "ticket":
        ticket_id, _ = await db.get_or_create_ticket(8)
        view = await click(view, "Очередь")
        view = await click(view, "Тикеты")
        view = await click(view, f"№{ticket_id}")
        view = await click(view, "Ответить")
    elif operation == "broadcast":
        view = await click(view, "Чат")
        view = await click(view, "Рассылка")
    else:
        view = await click(view, "Чат")
        view = await click(view, "Сообщение в сообщество")
        view = await click(view, "Мероприятие")
        view = await bridge.input(actor, {"form": view["form"], "version": view["version"], "text": "Собираемся"})
    assert len(session.calls) == 1  # Virtual admin pages must never appear in the Telegram dialog.
    if operation == "upload":
        from io import BytesIO

        from PIL import Image

        output = BytesIO()
        Image.new("RGB", (32, 32)).save(output, "JPEG")
        await bridge.input(actor, {"form": view["form"], "version": view["version"], "text": ""},
                           upload=("photo", output.getvalue()))
        context = await bridge.context(7)
        assert (await context.get_data())["post_file_id"] == "photo-cached"
        assert len(session.calls) == 2 and isinstance(session.calls[-1], EditMessageText)
        await bridge.dispatcher.storage.close()
        return
    await bridge.input(actor, {"form": view["form"], "version": view["version"],
                               "text": "<b>Ответ участнику</b>", "format": "html"})
    sent = [call for call in session.calls if call.chat_id == 8]
    assert sent and all(isinstance(call, (SendRichMessage, EditMessageText)) for call in sent)
    assert "Ответ участнику" in sent[-1].rich_message.model_dump_json()
    assert '"type":"bold"' in sent[-1].rich_message.model_dump_json()
    assert "flow:cancel" not in actions(sent[-1])
    if operation == "ticket":
        assert "Ответ модератора по тикету" in sent[-1].rich_message.model_dump_json()
        assert sum(isinstance(call, SendRichMessage) for call in sent) == 1
    await bridge.dispatcher.storage.close()


@pytest.mark.parametrize('cover', [False, True])
async def test_actual_start_guest_is_one_request_and_repeated_start_edits(setup, monkeypatch, cover):
    from community_bot.routers.private import start

    db, bot, session, state = setup
    bot.community_settings.timezone = 'Europe/Moscow'
    bot.community_settings.welcome_cover = ''
    state.clear = AsyncMock()
    if not cover:
        monkeypatch.setattr('community_bot.menu_art.menu_cover', lambda name: None)

    async def handler(message, data):
        await start(message, state, db, bot.community_settings)

    await turn(setup, handler, incoming(uid=8))
    assert len(session.calls) == 1
    assert isinstance(session.calls[0], SendRichMessage)
    assert session.calls[0].reply_markup is None
    assert 'start:apply' in actions(session.calls[0])
    await turn(setup, handler, incoming(uid=8))
    assert len(session.calls) == 2
    assert isinstance(session.calls[-1], EditMessageText)
    assert session.calls[-1].message_id == 100


async def test_legacy_uneditable_panel_is_deleted_before_one_time_replacement(setup):
    db, bot, session, _ = setup
    await bot.send_message(7, 'Old panel')
    page = json.loads(await db.get_bot_state('private_rich_panel:7'))
    page.pop('version')
    await db.set_bot_state('private_rich_panel:7', json.dumps(page))
    session.uneditable.add((7, 100))
    await bot.send_message(7, 'New page')
    assert [c.__api_method__ for c in session.calls] == [
        'sendRichMessage', 'editMessageText', 'deleteMessage', 'sendRichMessage',
    ]
    assert session.calls[-1].reply_markup is None
    await bot.send_message(7, 'Next page')
    assert isinstance(session.calls[-1], EditMessageText)
    assert session.calls[-1].message_id == 101
    assert json.loads(await db.get_bot_state('private_rich_panel:7'))['version'] == 2


async def test_failed_legacy_deletion_cannot_create_another_panel(setup):
    db, bot, session, _ = setup
    await db.set_bot_state('private_rich_panel:7', json.dumps({'message_id': 100, 'body': []}))
    session.uneditable.add((7, 100))
    original = session.make_request

    async def request(bot, method, **kwargs):
        if method.__api_method__ == 'deleteMessage':
            raise TelegramBadRequest(method=method, message="message can't be deleted")
        return await original(bot, method, **kwargs)

    session.make_request = request
    with pytest.raises(TelegramBadRequest):
        await bot.send_message(7, 'Next page')
    assert not any(isinstance(c, SendRichMessage) for c in session.calls)
