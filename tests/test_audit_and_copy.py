from types import SimpleNamespace

from community_bot.aliases import CommandOrAlias, command_or_alias, is_command_trigger, parse_trigger
from community_bot.audit import (
    classify_status,
    format_audit_row,
    parse_moderation_args,
    parse_punitive_args,
    parse_warn_args,
)
from community_bot.keyboards import admin_panel_keyboard, admin_system_keyboard, private_menu_keyboard
from community_bot.posting import parse_button_lines, parse_poll_options, render_post
from community_bot.texts import GROUP_COMMANDS_TEXT, STORE_HELP_TEXT
from community_bot.updates import latest_update, updates_text


def test_parse_trigger_slash_and_russian_alias() -> None:
    assert parse_trigger("/commands@bot") == ("commands", "")
    assert parse_trigger("команды") == ("commands", "")
    assert parse_trigger("Профиль") == ("profile", "")
    assert parse_trigger("магазин") == ("shop", "")
    assert parse_trigger("Магазин") == ("shop", "")
    assert parse_trigger("/shop") == ("shop", "")
    assert parse_trigger("/shop extra") == ("shop", "extra")
    assert parse_trigger("Магазин где купить?") is None
    assert parse_trigger("Магазин, привет") is None
    assert parse_trigger("Магазин сегодня работает?") is None
    assert parse_trigger("В магазине...") is None
    assert parse_trigger("кубик 25") == ("dice", "25")
    assert parse_trigger("рейс 10") == ("crash", "10")
    assert parse_trigger("капкан 10") == ("trap", "10")
    assert parse_trigger("налёт 25") == ("trap", "25")
    assert parse_trigger("мафия") == ("mafia", "")
    assert parse_trigger("бункер") == ("bunker", "")
    assert parse_trigger("чистить бота 30 уборка") == ("botsweep", "30 уборка")
    assert parse_trigger("купить печеньки") == ("buycookies", "")
    assert parse_trigger("мут 30m спам") == ("mute", "30m спам")
    assert parse_trigger("баланс") == ("balance", "")
    assert parse_trigger("кошелёк") == ("balance", "")
    assert parse_trigger("розыгрыш итог") == ("lotterydraw", "")
    assert parse_trigger("подарить щит") == ("gift", "щит")
    assert parse_trigger("репорт спам") == ("report", "спам")
    assert parse_trigger("почта") == ("mail", "")
    assert parse_trigger("доска") == ("board", "")
    assert parse_trigger("/команды") == ("commands", "")
    assert parse_trigger("команды!") == ("commands", "")
    assert parse_trigger("Команды") == ("commands", "")
    assert parse_trigger("команды бота") is None
    assert parse_trigger("вопрос") == ("question", "")
    assert parse_trigger("Вопрос") == ("question", "")
    assert parse_trigger("Вопрос?") == ("question", "")
    assert parse_trigger("Вопрос к чату") is None
    assert parse_trigger("вопрос почему удалили") is None
    assert parse_trigger("/question") == ("question", "")
    assert parse_trigger("задать вопрос") == ("question", "")
    assert parse_trigger("задать вопрос по анкете") is None
    assert parse_trigger("закрыть") == ("close", "")
    assert parse_trigger("Закрыть обсуждение") is None
    assert parse_trigger("помощь") == ("help", "")
    assert parse_trigger("Помощь нужна") is None
    assert parse_trigger("погода") == ("pogoda", "")
    assert parse_trigger("Погода!") == ("pogoda", "")
    assert parse_trigger("/pogoda") == ("pogoda", "")
    assert parse_trigger("/погода@bot") == ("pogoda", "")
    assert parse_trigger("какая погода") is None
    assert is_command_trigger("халява")
    assert is_command_trigger("обновления")
    from community_bot.aliases import is_command_message

    assert is_command_message("/неизвестная")
    assert is_command_message("команды")
    assert not is_command_message("привет всем")
    assert not is_command_message("")


def test_media_payloads_are_not_swept_as_group_commands() -> None:
    from community_bot.aliases import is_group_command_to_sweep
    from community_bot.ephemeral import is_game_callback

    def payload(**overrides: object) -> SimpleNamespace:
        base = {
            "sticker": None,
            "photo": None,
            "video": None,
            "video_note": None,
            "voice": None,
            "animation": None,
            "audio": None,
            "document": None,
            "paid_media": None,
            "text": None,
            "caption": None,
        }
        base.update(overrides)
        return SimpleNamespace(**base)

    assert not is_group_command_to_sweep(payload(sticker=object()))
    assert not is_group_command_to_sweep(payload(voice=object()))
    assert not is_group_command_to_sweep(payload(video_note=object()))
    assert not is_group_command_to_sweep(payload(photo=object(), caption="красивый вечер"))
    assert is_group_command_to_sweep(payload(photo=object(), caption="/shop"))
    assert is_group_command_to_sweep(payload(text="баланс"))
    assert not is_group_command_to_sweep(payload(text="Вопрос к чату, почему удалили?"))
    assert not is_group_command_to_sweep(payload(text="вопрос"))
    assert not is_group_command_to_sweep(payload(text="Вопрос"))
    assert not is_group_command_to_sweep(payload(text="закрыть тему"))
    assert not is_group_command_to_sweep(payload(text="/question"))
    assert is_group_command_to_sweep(payload(text="команды"))
    assert is_group_command_to_sweep(payload(text="магазин"))
    assert is_game_callback("cg:join:8")
    assert is_game_callback("game:start:1")
    assert is_game_callback("roulette:accept:2")
    assert is_game_callback("g:hide")
    assert not is_game_callback("shop:home")


def test_moderation_status_red_yellow_green() -> None:
    duration, reason, explicit = parse_moderation_args("/mute 30m спам в чате")
    assert explicit is True
    assert reason == "спам в чате"
    assert duration.total_seconds() == 30 * 60
    assert classify_status("mute", reason=reason, default_duration=not explicit) == "green"
    assert classify_status("mute", reason="", default_duration=True) == "red"
    duration, reason, explicit = parse_moderation_args("мут спам")
    assert explicit is False
    assert reason == "спам"
    assert classify_status("mute", reason=reason, default_duration=not explicit) == "yellow"
    assert classify_status("unban", target="123", target_name="") == "yellow"
    assert classify_status("unmute", target="1", target_name="Анна") == "green"
    assert classify_status("delete_message", reason="фильтр ссылок") == "green"
    assert classify_status("chat_mute") == "yellow"


def test_punitive_args_require_duration_and_reason() -> None:
    duration, reason, error = parse_punitive_args("/mute 30m флуд", need_duration=True)
    assert error is None
    assert duration is not None and duration.total_seconds() == 30 * 60
    assert reason == "флуд"
    _, _, error = parse_punitive_args("мут флуд", need_duration=True)
    assert error
    _, reason, error = parse_punitive_args("/kick реклама", need_duration=False)
    assert error is None
    assert reason == "реклама"
    duration, reason, error = parse_punitive_args("/ban навсегда скам", need_duration=True, allow_permanent=True)
    assert error is None
    assert reason == "скам"
    from community_bot.domain import is_permanent_duration

    assert duration is not None and is_permanent_duration(duration)
    mute_duration, reason, error = parse_warn_args("/warn 2h токсик")
    assert error is None
    assert mute_duration is not None and reason == "токсик"
    _, reason, error = parse_warn_args("варн спам ссылками")
    assert error is None and reason == "спам ссылками"


def test_audit_row_shows_name_not_raw_id() -> None:
    text = format_audit_row(
        {
            "actor_id": 1,
            "actor_name": "Анна",
            "action": "mute",
            "target": "2",
            "target_name": "Борис",
            "reason": "спам",
            "details": "30 мин",
            "status": "green",
            "created_at": "2026-09-08T10:00:00+00:00",
        }
    )
    assert "Анна" in text
    assert "Мут" in text
    assert "Борис" in text
    assert "🟢" in text
    assert "1" not in text.split("Анна")[0]


def test_commands_help_hides_staff_and_has_aliases() -> None:
    lowered = GROUP_COMMANDS_TEXT.casefold()
    assert "«команды»" in GROUP_COMMANDS_TEXT
    assert "«магазин»" in GROUP_COMMANDS_TEXT
    assert "«вопрос»" in GROUP_COMMANDS_TEXT
    assert "🎫 Тикет" in GROUP_COMMANDS_TEXT
    assert "не удаляется" in GROUP_COMMANDS_TEXT
    assert "не стирает" in GROUP_COMMANDS_TEXT
    assert "«обновления»" not in GROUP_COMMANDS_TEXT
    assert "/updates" not in lowered
    for leaked in ("/mute", "/warn", "/kick", "/ban", "/unban", "/givecookies", "/role", "/purge", "/botsweep"):
        assert leaked not in lowered
    assert "контрабанд" not in lowered
    assert "рулетка" in lowered
    assert "кубик" in lowered
    assert "рейс" in lowered
    assert "капкан" in lowered
    assert "тамагочи" in STORE_HELP_TEXT.casefold()
    assert "приватный" in STORE_HELP_TEXT.casefold()
    assert "кастомн" in STORE_HELP_TEXT.casefold()
    for word in ("подарить", "репорт", "почта", "доска", "экспедиция", "витрина", "набор"):
        assert word in lowered
    assert "сезонный набор" in STORE_HELP_TEXT.casefold()


def test_commands_page_is_detailed_and_the_card_is_short() -> None:
    from community_bot.commands_guide import COMMANDS_CARD_TEXT, commands_guide_nodes, commands_keyboard

    assert len(COMMANDS_CARD_TEXT) <= 1024
    assert "не удаляется" in COMMANDS_CARD_TEXT
    page = "\n".join(
        "".join(str(child) for child in node.get("children", []))
        for node in commands_guide_nodes()
    )
    lowered = page.casefold()
    assert "Пример. кубик 25" in page
    assert "Пример. Нора, какой фильм посмотреть" in page
    assert "пример." in lowered
    for word in (
        "магазин",
        "вопрос",
        "тикет",
        "рулетка",
        "рейс",
        "капкан",
        "подарить",
        "репорт",
        "почта",
        "доска",
        "экспедиц",
        "витрин",
        "набор",
        "погода",
    ):
        assert word in lowered
    for leaked in ("/mute", "/warn", "/kick", "/ban", "/purge", "tmdb", "api"):
        assert leaked not in lowered
    button = commands_keyboard("https://telegra.ph/Komandy").inline_keyboard[0][0]
    assert button.text == "Читать команды"
    assert button.url == "https://telegra.ph/Komandy"


async def test_commands_card_sends_one_photo_with_a_page_button(monkeypatch) -> None:
    from community_bot.commands_guide import send_commands_card

    async def publish(_db):
        return "https://telegra.ph/Komandy"

    monkeypatch.setattr("community_bot.telegraph.publish_commands_guide", publish)
    sent: list[dict] = []

    class Message:
        async def answer_photo(self, photo, **kwargs):
            sent.append({"photo": photo, **kwargs})
            return self

        async def answer(self, text, **kwargs):
            sent.append({"text": text, **kwargs})
            return self

    await send_commands_card(Message(), db=None)
    assert len(sent) == 1
    assert len(sent[0]["caption"]) <= 1024
    assert sent[0]["reply_markup"].inline_keyboard[0][0].url == "https://telegra.ph/Komandy"


async def test_commands_page_is_published_once(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from community_bot.database import Database
    from community_bot.telegraph import publish_commands_guide

    db = Database(Path(tmp_path) / "commands.db")
    await db.initialize()
    calls: list[str] = []

    async def token(_db):
        return "token"

    async def call(method, payload):
        calls.append(method)
        assert payload["title"] == "Команды НОРЫ"
        assert any(node.get("tag") == "blockquote" for node in payload["content"])
        return {"url": "https://telegra.ph/Komandy", "path": "Komandy"}

    monkeypatch.setattr("community_bot.telegraph.ensure_token", token)
    monkeypatch.setattr("community_bot.telegraph._call", call)
    assert await publish_commands_guide(db) == "https://telegra.ph/Komandy"
    assert await publish_commands_guide(db) == "https://telegra.ph/Komandy"
    assert calls == ["createPage"]


def test_post_templates_and_buttons() -> None:
    html = render_post("announce", "Собрание в субботу")
    assert "Объявление" in html
    assert "Собрание в субботу" in html
    assert "<blockquote>" in html
    formatted = render_post("announce", "<b>Жирный</b> и <i>курсив</i>")
    assert "<b>Жирный</b>" in formatted
    assert "&lt;b&gt;" not in formatted
    buttons, error = parse_button_lines("Магазин | https://t.me/nore | green\nПравила | https://example.com | blue")
    assert error is None
    assert len(buttons) == 2
    assert buttons[0]["style"] == "success"
    bad, err = parse_button_lines("без ссылки")
    assert not bad
    assert err
    options, poll_error = parse_poll_options("Да\nНет\nВоздержусь")
    assert poll_error is None
    assert options == ["Да", "Нет", "Воздержусь"]
    assert parse_poll_options("только один")[1]


def test_updates_are_admin_only_and_numbered() -> None:
    latest = latest_update()
    assert latest.number == 20
    text = updates_text()
    assert "№15" in text
    assert "№14" in text
    assert "№13" in text
    assert "№12" in text
    assert "№11" in text
    assert "админ" in text.casefold()
    assert "Написать боту" not in text
    member_menu = private_menu_keyboard()
    member_labels = [button.text for row in member_menu.inline_keyboard for button in row]
    member_data = [button.callback_data for row in member_menu.inline_keyboard for button in row]
    assert "✨ Обновления" not in member_labels
    assert "admin:updates" not in member_data
    assert "menu:updates" not in member_data
    admin_menu = admin_panel_keyboard(["*"])
    admin_buttons = [button for row in admin_menu.inline_keyboard for button in row]
    assert any(button.callback_data == "admin:system" for button in admin_buttons)
    system_menu = admin_system_keyboard(["*"])
    system_buttons = [button for row in system_menu.inline_keyboard for button in row]
    assert any(button.callback_data == "admin:updates" for button in system_buttons)
    assert any(button.callback_data == "admin:staffguide" for button in system_buttons)
    assert any(button.text == "✨ Обновления" for button in system_buttons)
    assert all(button.callback_data != "admin:restart" for button in system_buttons)
    owner_system = admin_system_keyboard(["*"], is_owner=True)
    owner_buttons = [button for row in owner_system.inline_keyboard for button in row]
    assert any(button.callback_data == "admin:restart" for button in owner_buttons)
    from community_bot.keyboards import games_menu_keyboard
    from community_bot.staff_guide import staff_guide_text
    from community_bot.updates import community_announcement, member_details_text, staff_announcement

    pin = community_announcement(latest)
    assert "Админ" not in pin
    assert "очередь" not in pin.casefold()
    assert "Обновление №20" in pin
    details = member_details_text(latest)
    assert "ОБНОВА" in details
    assert "стикер" in details.casefold()
    assert "админка" not in details.casefold()
    staff = staff_announcement(latest)
    assert "Служебные стикеры" in staff
    assert "Админка" not in details
    labels = " ".join(button.text for row in games_menu_keyboard().inline_keyboard for button in row).casefold()
    assert "рулетка" in labels
    assert "кубик" in labels
    assert "рейс" in labels
    assert "капкан" in labels
    assert "мафия" in labels
    assert "бункер" in labels
    assert "контрабанд" not in labels
    guide = staff_guide_text()
    assert "/mute 30m" in guide
    assert "/purge 50" in guide
    assert "/botsweep" in guide
    assert "Перезапустить бота" in guide
    assert "Конкурс на печеньки" in guide
    assert "Капкан" in guide
    assert "Мафия" in guide
    assert "Бункер" in guide
    assert "сильнейший" in guide.casefold()
    assert "аварийный выключатель" in guide.casefold()
    from community_bot.texts import GAMES_HELP_TEXT

    assert "капкан" in GAMES_HELP_TEXT.casefold()
    assert "мафия" in GAMES_HELP_TEXT.casefold()
    assert "бункер" in GAMES_HELP_TEXT.casefold()
    assert "комиссии репутации" not in GAMES_HELP_TEXT
    assert "банк минус комиссия" not in GAMES_HELP_TEXT


async def test_command_or_alias_matches_bare_russian_words() -> None:
    filt = command_or_alias("commands", "profile", "shop", "pet")
    assert isinstance(filt, CommandOrAlias)
    for text, expected in (
        ("команды", "commands"),
        ("Профиль", "profile"),
        ("магазин", "shop"),
        ("тамагочи", "pet"),
        ("/profile@nore_community_bot", "profile"),
    ):
        message = SimpleNamespace(text=text, caption=None)
        result = await filt(message)  # type: ignore[arg-type]
        assert result is not False
        assert result["command"].command == expected
    miss = await filt(SimpleNamespace(text="привет", caption=None))  # type: ignore[arg-type]
    assert miss is False


async def test_housekeeping_deletes_command_before_handler() -> None:
    from aiogram.types import Message

    from community_bot.ephemeral import GroupHousekeepingMiddleware

    deleted: list[tuple[int, int]] = []

    class FakeBot:
        async def delete_message(self, chat_id: int, message_id: int) -> bool:
            deleted.append((chat_id, message_id))
            return True

    event = Message.model_validate(
        {
            "message_id": 77,
            "date": 1_725_000_000,
            "chat": {"id": -1004331642093, "type": "supergroup", "title": "Nora"},
            "from": {"id": 1, "is_bot": False, "first_name": "Анна"},
            "text": "команды",
        }
    )
    seen_before_handler = False

    async def handler(_event, _data):
        nonlocal seen_before_handler
        seen_before_handler = bool(deleted)
        return "ok"

    result = await GroupHousekeepingMiddleware()(handler, event, {"bot": FakeBot()})
    assert result == "ok"
    assert seen_before_handler is True
    assert deleted == [(-1004331642093, 77)]


async def test_housekeeping_keeps_messages_that_start_with_vopros() -> None:
    from aiogram.types import Message

    from community_bot.ephemeral import GroupHousekeepingMiddleware

    deleted: list[tuple[int, int]] = []

    class FakeBot:
        async def delete_message(self, chat_id: int, message_id: int) -> bool:
            deleted.append((chat_id, message_id))
            return True

    event = Message.model_validate(
        {
            "message_id": 88,
            "date": 1_725_000_000,
            "chat": {"id": -1004331642093, "type": "supergroup", "title": "Nora"},
            "from": {"id": 1, "is_bot": False, "first_name": "Анна"},
            "text": "Вопрос к чату: почему сообщение пропало?",
        }
    )

    async def handler(_event, _data):
        return "ok"

    result = await GroupHousekeepingMiddleware()(handler, event, {"bot": FakeBot()})
    assert result == "ok"
    assert deleted == []


async def test_housekeeping_does_not_sweep_media_stickers_voice_or_circles() -> None:
    from aiogram.types import Message

    from community_bot.ephemeral import GroupHousekeepingMiddleware

    deleted: list[tuple[int, int]] = []

    class FakeBot:
        async def delete_message(self, chat_id: int, message_id: int) -> bool:
            deleted.append((chat_id, message_id))
            return True

    async def handler(_event, _data):
        return "ok"

    payloads = [
        {
            "message_id": 101,
            "sticker": {
                "file_id": "sticker-file",
                "file_unique_id": "sticker-unique",
                "type": "regular",
                "width": 100,
                "height": 100,
                "is_animated": False,
                "is_video": False,
            },
        },
        {
            "message_id": 102,
            "voice": {
                "file_id": "voice-file",
                "file_unique_id": "voice-unique",
                "duration": 3,
            },
        },
        {
            "message_id": 103,
            "video_note": {
                "file_id": "circle-file",
                "file_unique_id": "circle-unique",
                "length": 200,
                "duration": 4,
            },
        },
        {
            "message_id": 104,
            "photo": [
                {
                    "file_id": "photo-file",
                    "file_unique_id": "photo-unique",
                    "width": 800,
                    "height": 600,
                }
            ],
            "caption": "вечер в норе",
        },
    ]
    for extra in payloads:
        event = Message.model_validate(
            {
                "date": 1_725_000_000,
                "chat": {"id": -1004331642093, "type": "supergroup", "title": "Nora"},
                "from": {"id": 1, "is_bot": False, "first_name": "Анна"},
                **extra,
            }
        )
        result = await GroupHousekeepingMiddleware()(handler, event, {"bot": FakeBot()})
        assert result == "ok"
    assert deleted == []


def _group_message(message_id: int = 88, chat_type: str = "supergroup"):
    from aiogram.types import Message

    return Message.model_validate(
        {
            "message_id": message_id,
            "date": 1_725_000_000,
            "chat": {"id": -1004331642093, "type": chat_type, "title": "Nora"},
            "from": {"id": 8992215311, "is_bot": True, "first_name": "Nore Community"},
            "text": "📚 Команды",
        }
    )


async def test_bot_group_replies_are_scheduled_via_session_middleware(monkeypatch) -> None:
    import asyncio

    from community_bot.ephemeral import (
        _REPLY_TTL,
        BOT_REPLY_TTL,
        EphemeralSendMiddleware,
        keep_in_chat,
        patch_bot_ephemeral,
    )
    from community_bot.helpers import BOT_REPLY_TTL as TTL

    seen: list[tuple[int, float]] = []

    async def fake_delete_later(message, delay: float = TTL) -> None:
        seen.append((message.message_id, delay))

    monkeypatch.setattr("community_bot.ephemeral.delete_later", fake_delete_later)

    async def make_request(_bot, _method):
        return _group_message()

    middleware = EphemeralSendMiddleware()
    token = _REPLY_TTL.set(BOT_REPLY_TTL)
    try:
        await middleware(make_request, None, None)
        await asyncio.sleep(0)
    finally:
        _REPLY_TTL.reset(token)
    assert seen == [(88, 30.0)]

    seen.clear()
    token = _REPLY_TTL.set(BOT_REPLY_TTL)
    try:
        with keep_in_chat():
            await middleware(make_request, None, None)
            await asyncio.sleep(0)
    finally:
        _REPLY_TTL.reset(token)
    assert seen == []

    from aiogram import Bot
    from aiogram.client.session.aiohttp import AiohttpSession

    bot = Bot(token="123:abc", session=AiohttpSession())
    patch_bot_ephemeral(bot)
    assert any(isinstance(item, EphemeralSendMiddleware) for item in bot.session.middleware)
    await bot.session.close()


async def test_game_callbacks_do_not_expire_replies_in_thirty_seconds(monkeypatch) -> None:
    import asyncio

    from aiogram.types import CallbackQuery

    from community_bot.ephemeral import (
        _REPLY_TTL,
        GAME_RESULT_TTL,
        GroupCallbackEphemeralMiddleware,
        expire_game_result,
    )

    seen_ttl: list[float | None] = []

    async def handler(_event, _data):
        seen_ttl.append(_REPLY_TTL.get())
        return "ok"

    callback = CallbackQuery.model_validate(
        {
            "id": "1",
            "from": {"id": 1, "is_bot": False, "first_name": "Анна"},
            "chat_instance": "x",
            "data": "cg:join:8",
            "message": {
                "message_id": 90,
                "date": 1_725_000_000,
                "chat": {"id": -1004331642093, "type": "supergroup", "title": "Nora"},
                "from": {"id": 8992215311, "is_bot": True, "first_name": "Nore Community"},
                "text": "🍪 лобби",
            },
        }
    )
    result = await GroupCallbackEphemeralMiddleware()(handler, callback, {})
    assert result == "ok"
    assert seen_ttl == [None]

    scheduled: list[tuple[int, float]] = []

    async def fake_delete_later(message, delay: float = 30.0) -> None:
        scheduled.append((message.message_id, delay))

    monkeypatch.setattr("community_bot.ephemeral.delete_later", fake_delete_later)
    expire_game_result(_group_message(91))
    await asyncio.sleep(0)
    assert scheduled == [(91, GAME_RESULT_TTL)]


async def test_audit_log_persists_names_and_status(tmp_path) -> None:
    from pathlib import Path

    from community_bot.database import Database

    db = Database(Path(tmp_path) / "audit.db")
    await db.initialize()
    await db.ensure_user(10, telegram_name="Анна")
    await db.ensure_user(20, telegram_name="Борис")
    await db.log_admin_action(10, "mute", "20", "30 мин", reason="спам", actor_name="Анна", target_name="Борис")
    await db.log_admin_action(10, "warn", "20", reason="")
    rows = await db.recent_admin_actions()
    mute = next(row for row in rows if row["action"] == "mute")
    warn = next(row for row in rows if row["action"] == "warn")
    assert mute["actor_name"] == "Анна"
    assert mute["target_name"] == "Борис"
    assert mute["status"] == "green"
    assert warn["status"] == "red"


async def test_get_pet_still_returns_row_if_settle_fails(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from community_bot.database import Database

    db = Database(Path(tmp_path) / "pet.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Хозяин")
    await db.add_cookies(1, 80, "test")
    assert (await db.purchase_pet(1, "cat", "Булочка", 50))[0] is True

    async def boom(_user_id: int):
        raise RuntimeError("settle failed")

    monkeypatch.setattr(db, "settle_pet", boom)
    pet = await db.get_pet(1)
    assert pet is not None
    assert pet["name"] == "Булочка"
