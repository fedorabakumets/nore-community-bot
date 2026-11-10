from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramNotFound, TelegramRetryAfter
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
from community_bot.ephemeral import GroupHousekeepingMiddleware, patch_bot_ephemeral
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
        self.widgets = False

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
        if method.__api_method__ == "sendWidget" and not self.widgets:
            raise TelegramNotFound(method=method, message="Not Found")
        if method.__api_method__ in {"answerCallbackQuery", "answerWidgetQuery", "deleteMessage"}:
            return True
        uid = method.chat_id
        if isinstance(method, EditMessageText) and (uid, method.message_id) in self.uneditable:
            raise TelegramBadRequest(method=method, message="Bad Request: message can't be edited")
        if isinstance(method, SendRichMessage) or method.__api_method__ == "sendWidget":
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
    assert [b["style"] for b in buttons[:3]] == ["link", "success", "danger"]
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
    assert actions(session.calls[1])["menu:home"]["style"] == "link"


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
    assert not any(block["type"] == "photo" for block in content(last))
    assert actions(last)["application:interview:yes"]["style"] == "success"


async def test_guest_and_form_controls_do_not_expose_member_sections(setup):
    _, bot, session, state = setup
    await bot.send_message(8, "Добро пожаловать", reply_markup=main_private_keyboard())
    assert set(actions(session.calls[-1])) == {"start:apply", "menu:question"}
    state.get_state.return_value = "ApplicationForm:name"

    async def handler(message, data):
        await message.answer("Как тебя зовут?", reply_markup=flow_reply_keyboard())

    await turn(setup, handler, incoming(uid=8))
    assert set(actions(session.calls[-1])) == {"flow:cancel", "flow:restart"}
    assert actions(session.calls[-1])["flow:cancel"]["style"] == "link"
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
async def test_actual_start_guest_reopens_panel_and_then_edits(setup, monkeypatch, cover):
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
    assert [c.__api_method__ for c in session.calls] == [
        'sendRichMessage', 'deleteMessage', 'sendRichMessage',
    ]
    assert session.calls[1].message_id == 100
    assert session.calls[-1].reply_markup is None
    await bot.send_message(8, 'Следующая страница')
    assert isinstance(session.calls[-1], EditMessageText)
    assert session.calls[-1].message_id == 101


@pytest.mark.parametrize('deletion_error', [None, "message to delete not found", "message can't be deleted"])
async def test_start_restores_locally_deleted_panel_once_for_multiple_answers(setup, deletion_error):
    from community_bot.private_rich import reopen_private_panel

    db, bot, session, _ = setup
    await bot.send_message(7, 'Hidden locally; Telegram would still accept edits')
    if deletion_error:
        session.fail = TelegramBadRequest(method=session.calls[0], message=deletion_error)

    async def handler(message, data):
        reopen_private_panel()
        await bot.send_message(7, 'Обложка')
        await bot.send_message(7, 'Текст страницы')

    await turn(setup, handler)
    assert [c.__api_method__ for c in session.calls] == [
        'sendRichMessage', 'deleteMessage', 'sendRichMessage', 'editMessageText',
    ]
    assert session.calls[-1].message_id == 101
    assert 'Обложка' in session.calls[-1].rich_message.model_dump_json()
    assert 'Текст страницы' in session.calls[-1].rich_message.model_dump_json()
    assert json.loads(await db.get_bot_state('private_rich_panel:7'))['message_id'] == 101


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


async def test_home_has_only_section_buttons_without_home_or_close(setup):
    from community_bot.keyboards import private_menu_keyboard

    _, bot, session, _ = setup
    await bot.send_message(7, 'Кабинет', reply_markup=private_menu_keyboard(False))
    assert set(actions(session.calls[-1])) == {
        'menu:wallet', 'menu:shop', 'menu:profile', 'menu:pet', 'menu:notices', 'menu:question',
    }
    assert all(b['style'] == 'link' for b in actions(session.calls[-1]).values())


async def test_nested_page_keeps_one_parent_back_and_deduplicates_actions(setup):
    _, bot, session, _ = setup
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [ibtn('История', 'wallet:history'), ibtn('История ещё раз', 'wallet:history')],
        [ibtn('Назад', 'wallet:home'), ibtn('Меню', 'menu:home')],
        [ibtn('Закрыть', 'ui:close')],
    ])
    await bot.send_message(7, 'История', reply_markup=markup)
    buttons = [b for block in content(session.calls[-1]) if block['type'] == 'buttons' for b in block['buttons']]
    assert len([b for b in buttons if b.get('callback_data') == 'wallet:history']) == 1
    assert actions(session.calls[-1])['wallet:home']['text'] == '← Назад'
    assert 'ui:close' not in actions(session.calls[-1])
    assert 'menu:home' not in actions(session.calls[-1])
    await bot.send_message(7, 'Фоновое уведомление')
    assert actions(session.calls[-1])['wallet:home']['text'] == '← Назад'


async def test_profile_input_back_returns_to_profile_without_global_navigation(setup):
    _, _, session, state = setup
    state.get_state.return_value = 'ProfileEdit:name'

    async def handler(message, data):
        await message.answer('Имя?', reply_markup=flow_reply_keyboard())

    await turn(setup, handler)
    assert set(actions(session.calls[-1])) == {'menu:profile'}
    assert actions(session.calls[-1])['menu:profile']['text'] == '← Назад'


async def test_cancel_restores_complete_home_without_footer(setup):
    from community_bot.routers.flows import restore_private_menu

    _, _, session, _ = setup

    async def handler(message, data):
        await restore_private_menu(message, data['db'], data['bot'].community_settings)

    await turn(setup, handler)
    assert {'menu:wallet', 'menu:profile', 'menu:shop'} <= set(actions(session.calls[-1]))
    assert 'menu:home' not in actions(session.calls[-1])


async def test_private_profile_compacts_ornate_style_preserving_fields_and_escaping(setup):
    from community_bot.helpers import render_profile

    db, bot, _, _ = setup
    bot.community_settings.restricted_reputation_threshold = 0
    user = await db.get_user(7)
    user.update(profile_ornate=1, profile_name='<Рома>', hobbies='Чай & игры', profile_bio='<script>')
    compact = await render_profile(db, bot.community_settings, user, compact=True)
    assert '&lt;Рома&gt;' in compact and 'Чай &amp; игры' in compact and '&lt;script&gt;' in compact
    assert 'Репутация:' in compact and 'Варны:' in compact
    assert '━' not in compact and '<code>' not in compact and 'Ｎ Ｏ Ｒ Ａ' not in compact
    assert len(compact.splitlines()) <= 7


def test_compact_text_removes_decoration_but_preserves_code_layout():
    assert text_blocks('Заголовок\n\n━━━━━━━━\nТекст')[0]['text'] == 'Заголовок\nТекст'
    assert text_blocks('<pre>a\n\nb</pre>', 'HTML')[0]['text'] == 'a\n\nb'


@pytest.mark.parametrize('flow', ['ApplicationForm:age', 'ProfileEdit:age', 'FlexiblePurchase:amount'])
async def test_number_widget_replaces_panel_and_keeps_navigation(setup, flow):
    from community_bot.message_widgets import SendWidget

    db, bot, session, state = setup
    first = await bot.send_message(7, 'Кабинет')
    session.widgets = True
    state.get_state.return_value = flow

    async def prompt(message, data):
        await message.answer('Выбери число', reply_markup=flow_reply_keyboard())

    await turn(setup, prompt)
    widget = next(c for c in session.calls if isinstance(c, SendWidget))
    assert widget.allow_queries and not widget.is_shared
    assert widget.reply_markup.inline_keyboard
    assert 'Можно отправить число в чат' in widget.caption
    assert session.calls[-1].__api_method__ == 'deleteMessage'
    assert session.calls[-1].message_id == first.message_id
    page = json.loads(await db.get_bot_state('private_rich_panel:7'))
    assert page['widget']['min'] == (1 if flow.endswith('amount') else 14)
    assert page['message_id'] != first.message_id
    # Notices preserve the picker and its nonce instead of making it stale.
    await bot.send_message(7, 'Уведомление')
    assert json.loads(await db.get_bot_state('private_rich_panel:7')) == page


async def test_widget_unknown_method_falls_back_with_capability_cooldown(setup):
    db, bot, session, state = setup
    state.get_state.return_value = 'ProfileEdit:age'

    async def prompt(message, data):
        await message.answer('Возраст?', reply_markup=flow_reply_keyboard())

    await turn(setup, prompt)
    await turn(setup, prompt)
    assert sum(c.__api_method__ == 'sendWidget' for c in session.calls) == 1
    assert isinstance(session.calls[-1], EditMessageText)
    assert 'widget' not in json.loads(await db.get_bot_state('private_rich_panel:7'))


@pytest.mark.parametrize('native', [True, False])
async def test_real_age_widget_update_uses_actor_fsm_and_rejects_replay(setup, native):
    from community_bot.message_widgets import WidgetUpdateMiddleware
    from community_bot.routers.profile import edit_profile_age
    from community_bot.states import ProfileEdit

    db, bot, session, _ = setup
    session.widgets = native
    dispatcher = Dispatcher()
    dispatcher.update.outer_middleware(WidgetUpdateMiddleware())
    dispatcher.message.outer_middleware(PrivateRichContextMiddleware())
    router = Router()

    @router.message(F.text == '/age')
    async def begin(message, state):
        await state.set_state(ProfileEdit.age)
        await message.answer('Возраст?', reply_markup=flow_reply_keyboard())

    router.message.register(edit_profile_age, ProfileEdit.age)
    dispatcher.include_router(router)
    await dispatcher.feed_update(bot, Update(update_id=1, message=incoming(text='/age')),
                                 db=db, settings=bot.community_settings)
    page = json.loads(await db.get_bot_state('private_rich_panel:7'))
    choice = page['widget' if native else 'number_choice']
    query = {'id': 'query-age', 'from': incoming().from_user.model_dump(),
             'chat': incoming().chat.model_dump(), 'message_id': page['message_id'],
             'data': f"nora:{choice['token']}:25"}
    for update_id in (2, 3):
        update = Update(update_id=update_id, widget_query=query)
        if not native:
            button = CallbackQuery(id='button', from_user=incoming().from_user, chat_instance='private',
                                   message=incoming().model_copy(update={'message_id': page['message_id']}),
                                   data=query['data'])
            update = Update(update_id=update_id, callback_query=button)
        await dispatcher.feed_update(bot, update,
                                     db=db, settings=bot.community_settings)
        answer = session.calls[-1]
        if native:
            assert json.loads(answer.data)['ok'] == (update_id == 2)
        else:
            assert answer.__api_method__ == 'answerCallbackQuery'
            assert (answer.text == 'Готово') == (update_id == 2)
    assert (await db.get_user(7))['age'] == 25
    assert await dispatcher.fsm.get_context(bot, 7, 7).get_state() is None
    assert 'widget' not in json.loads(await db.get_bot_state('private_rich_panel:7'))
    assert sum(c.__api_method__ == 'deleteMessage' for c in session.calls) == int(native)
    await dispatcher.storage.close()


async def test_amount_widget_prepares_discounted_intent_without_spending(setup, monkeypatch):
    from community_bot.message_widgets import WidgetUpdateMiddleware
    from community_bot.routers.group import finish_flexible_purchase
    from community_bot.states import FlexiblePurchase

    db, bot, session, _ = setup
    session.widgets = True
    prepare = AsyncMock(return_value='test-intent')
    monkeypatch.setattr(db, 'create_wallet_intent', prepare)
    before = (await db.get_user(7))['cookies']
    dispatcher = Dispatcher()
    dispatcher.update.outer_middleware(WidgetUpdateMiddleware())
    dispatcher.message.outer_middleware(PrivateRichContextMiddleware())
    router = Router()

    @router.message(F.text == '/amount')
    async def begin(message, state):
        await state.set_state(FlexiblePurchase.amount)
        await state.update_data(flex_item='support', flex_discount=10)
        await message.answer('Сумма?')

    router.message.register(finish_flexible_purchase, FlexiblePurchase.amount)
    dispatcher.include_router(router)
    await dispatcher.feed_update(bot, Update(update_id=1, message=incoming(text='/amount')),
                                 db=db, settings=bot.community_settings)
    page = json.loads(await db.get_bot_state('private_rich_panel:7'))
    query = {'id': 'query-amount', 'from': incoming().from_user.model_dump(),
             'chat': incoming().chat.model_dump(), 'message_id': page['message_id'],
             'data': f"nora:{page['widget']['token']}:500"}
    for idx in (2, 3):
        await dispatcher.feed_update(bot, Update(update_id=idx, widget_query=query),
                                     db=db, settings=bot.community_settings)
    prepare.assert_awaited_once_with(7, 'support', 450, payload={'base_amount': 500, 'discount': 10})
    assert (await db.get_user(7))['cookies'] == before
    rich = next(c for c in reversed(session.calls) if isinstance(c, SendRichMessage))
    assert 'test-intent' in rich.rich_message.model_dump_json()
    assert '450' in rich.rich_message.model_dump_json()
    await dispatcher.storage.close()


@pytest.mark.parametrize('change', ['nonce', 'range', 'actor', 'message', 'state'])
async def test_widget_rejects_forged_and_stale_submissions(setup, change):
    from community_bot.message_widgets import submission

    _, _, _, _ = setup
    page = {'message_id': 5, 'flow': 'ProfileEdit:age',
            'widget': {'token': '0123456789abcdef', 'min': 14, 'max': 120}}
    event = incoming(text='25').model_copy(update={
        'message_id': 5, 'nora_widget': '0123456789abcdef',
    })
    flow = 'ProfileEdit:age'
    if change == 'nonce':
        event = event.model_copy(update={'nora_widget': 'fedcba9876543210'})
    elif change == 'range':
        event = event.model_copy(update={'text': '9999999'})
    elif change == 'actor':
        event = event.model_copy(update={'from_user': incoming(uid=8).from_user})
    elif change == 'message':
        event = event.model_copy(update={'message_id': 4})
    else:
        flow = 'ApplicationForm:age'
    assert not submission(event, page, flow)


async def test_widget_network_error_preserves_current_panel_without_duplicate(setup):
    db, bot, session, state = setup
    await bot.send_message(7, 'Кабинет')
    page = await db.get_bot_state('private_rich_panel:7')
    state.get_state.return_value = 'ProfileEdit:age'
    session.fail = TelegramNetworkError(method=session.calls[0], message='Connection lost')

    async def prompt(message, data):
        await message.answer('Возраст?')

    with pytest.raises(TelegramNetworkError):
        await turn(setup, prompt)
    assert await db.get_bot_state('private_rich_panel:7') == page
    assert not any(c.__api_method__ == 'deleteMessage' for c in session.calls)


async def test_transfer_widget_is_read_only_keeps_confirmation_and_escapes_names(setup):
    from community_bot.message_widgets import document, transfer_card

    _, bot, session, _ = setup
    session.widgets = True
    bot.community_db = None  # This display test must not schedule background DB bookkeeping.
    markup = InlineKeyboardMarkup(inline_keyboard=[[ibtn('Подтвердить', 'transfer:yes:1')]])
    source = incoming().model_copy(update={'chat': Chat(id=-1007, type='supergroup')}).as_(bot)
    target = {'telegram_name': '</script><script>evil()</script>'}
    assert await transfer_card(source, target, 100, 5, 95, markup)
    call = session.calls[-1]
    assert call.reply_markup.inline_keyboard[0][0].callback_data == 'transfer:yes:1'
    assert not call.allow_queries and not call.is_shared
    assert '</script><script>evil()' not in call.html
    import zlib

    assert len(zlib.compress(call.html.encode(), 9)) < 4096
    with pytest.raises(ValueError):
        document({'note': 'x' * 40000})

async def test_widget_transport_selects_beta_and_poll_recovers_on_stable(monkeypatch):
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.methods import ForwardMessage, GetUpdates, SendMessage

    from community_bot.message_widgets import (
        AnswerWidgetQuery,
        EditMessageWidgetData,
        EditSharedWidgetData,
        SendNotificationWidget,
        SendSharedWidget,
        WidgetSession,
    )

    session = WidgetSession()
    calls = []

    async def record(transport, bot, method, timeout=None):  # noqa: ASYNC109
        calls.append((transport.api.base, method.__api_method__))
        if transport is session.widget_api and isinstance(method, GetUpdates):
            raise TelegramNotFound(method=method, message='Not Found')
        return True

    monkeypatch.setattr(AiohttpSession, 'make_request', record)
    try:
        await session.make_request(None, AnswerWidgetQuery(widget_query_id='x', data='ok'))
        await session.make_request(None, EditSharedWidgetData(widget_id='123', public_data='{}'))
        await session.make_request(None, EditMessageWidgetData(chat_id=7, message_id=456, chat_data='{}'))
        await session.make_request(None, SendNotificationWidget(chat_id=7, html='<p>Nora</p>',
                                                                 caption='Test', chat_data='{}'))
        await session.make_request(None, SendSharedWidget(chat_id=-100123, widget_id='123'))
        await session.make_request(None, ForwardMessage(chat_id=-100123, from_chat_id=7, message_id=1))
        await session.make_request(None, SendMessage(chat_id=1, text='test'))
        await session.make_request(None, GetUpdates())
        await session.make_request(None, GetUpdates())
    finally:
        await session.close()
    assert [('/beta/' in base, method) for base, method in calls] == [
        (True, 'answerWidgetQuery'), (True, 'editSharedWidgetData'),
        (True, 'editMessageWidgetData'), (True, 'sendWidget'),
        (True, 'sendSharedWidget'), (False, 'forwardMessage'), (False, 'sendMessage'),
        (True, 'getUpdates'), (False, 'getUpdates'), (False, 'getUpdates'),
    ]


@pytest.mark.parametrize("chat_id,closer", [(7, 7), (-100123, 7), (-100123, 8), (-100123, 9), (-100123, None)])
async def test_commands_card_rich_photo_close_and_expiry(setup, monkeypatch, chat_id, closer):
    from community_bot.commands_guide import CLOSE_COMMANDS_CARD, router
    from community_bot.helpers import delete_later
    from community_bot.routers import group, private

    db, bot, session, _ = setup
    await db.ensure_user(8, telegram_name="Модератор")
    await db.set_role(8, "moderator")
    lookup = AsyncMock(side_effect=lambda _, uid: SimpleNamespace(
        status="administrator" if uid == 9 else "member",
    ))
    monkeypatch.setattr(bot, "get_chat_member", lookup)
    group_timer = AsyncMock()
    monkeypatch.setattr("community_bot.ephemeral.delete_later", group_timer)
    expire = asyncio.Event()
    expired = asyncio.Event()

    async def controlled_timer(message, seconds):
        assert seconds == 60
        await expire.wait()
        await delete_later(message, 0)
        expired.set()

    timer = AsyncMock(side_effect=controlled_timer)
    monkeypatch.setattr("community_bot.commands_guide.delete_later", timer)
    dp = Dispatcher()
    dp.message.outer_middleware(PrivateRichContextMiddleware())
    dp.message.outer_middleware(GroupHousekeepingMiddleware())
    dp.callback_query.outer_middleware(PrivateRichContextMiddleware())
    handlers = Router()
    handlers.message.handlers.extend(
        handler for source, target in ((group.router, group.group_commands), (private.router, private.help_command))
        for handler in source.message.handlers if handler.callback == target
    )
    handlers.callback_query.handlers.extend(router.callback_query.handlers)
    dp.include_router(handlers)
    context = {"db": db, "settings": bot.community_settings}
    if chat_id == 7:
        async def open_panel(event, data):
            await event.answer("Главное меню")

        await turn(setup, open_panel)
    saved_panel = await db.get_bot_state("private_rich_panel:7")
    session.calls.clear()
    event = incoming(text="команды")
    if chat_id < 0:
        event = event.model_copy(update={
            "chat": Chat(id=chat_id, type="supergroup", is_forum=True),
            "is_topic_message": True, "message_thread_id": 42, "text": "Нора команды",
        })

    await dp.feed_update(bot, Update(update_id=1, message=event), **context)
    card = event.model_copy(update={"message_id": session.next_id - 1})
    await asyncio.sleep(0)
    send = session.calls[-1]
    assert isinstance(send, SendRichMessage)
    assert send.reply_markup is None
    assert send.message_thread_id == (42 if chat_id < 0 else None)
    assert [block["type"] for block in content(send)] == ["photo", "buttons"]
    assert send.rich_message.blocks[0].photo.media.path.is_file()
    assert actions(send)[CLOSE_COMMANDS_CARD]["style"] == "danger"
    assert actions(send)[CLOSE_COMMANDS_CARD]["text"] == "Закрыть"
    timer.assert_awaited_once()
    group_timer.assert_not_called()

    async def click(user_id, target):
        query = CallbackQuery(
            id="close", chat_instance="commands", data=CLOSE_COMMANDS_CARD,
            from_user=User(id=user_id, is_bot=False, first_name="Участник"), message=target,
        )
        await dp.feed_update(bot, Update(update_id=2, callback_query=query), **context)

    def card_deletes():
        return [call for call in session.calls
                if call.__api_method__ == "deleteMessage" and call.message_id == card.message_id]

    if chat_id < 0:
        await click(10, card)
        assert session.calls[-1].show_alert
        await click(7, card.model_copy(update={"message_id": card.message_id + 1}))
        assert not card_deletes()
        assert not any(call.__api_method__ == "deleteMessage" and call.message_id == card.message_id + 1
                       for call in session.calls)
    if closer is None:
        expire.set()
        await asyncio.wait_for(expired.wait(), timeout=1)
    else:
        await click(closer, card)
        await asyncio.sleep(0)
        expire.set()
        await asyncio.sleep(0)
        assert not expired.is_set()
    assert len(card_deletes()) == 1
    assert await db.get_bot_state("private_rich_panel:7") == saved_panel
    await dp.storage.close()
