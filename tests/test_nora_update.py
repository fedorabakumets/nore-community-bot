from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from community_bot.aliases import parse_trigger
from community_bot.command_registry import explicit_ttl, restore_defaults
from community_bot.daily_chat import due_daily_chat, render_daily_chat
from community_bot.day_note import DayEvent, pick_day_event, render_day_note
from community_bot.ephemeral import _EXPLICIT_TTL, _REPLY_TTL, current_reply_ttl, keep_in_chat
from community_bot.keyboards import admin_system_keyboard
from community_bot.nora import render_tracks, render_watch, rule_intent, strip_address
from community_bot.permissions import DEFAULT_STAFF_ROLES, PERM_COMMANDS
from community_bot.updates import community_announcement, latest_update, member_details_text, staff_announcement


def test_nora_routes_plain_phrases() -> None:
    assert strip_address("Нора, какой фильм посмотреть?") == "какой фильм посмотреть?"
    assert strip_address("просто фильм") is None
    assert rule_intent("какой фильм посмотреть?")["tool"] == "suggest_title"
    assert rule_intent("где сериал медведь")["tool"] == "find_title"
    assert rule_intent("где сериал медведь")["kind"] == "tv"
    assert rule_intent("топ чартов музыки")["tool"] == "music_chart"
    assert rule_intent("найди песню jungle")["tool"] == "music_search"
    assert "jungle" in rule_intent("найди песню jungle")["query"]
    assert rule_intent("какая погода")["tool"] == "weather"
    assert rule_intent("новости")["tool"] == "news"
    assert rule_intent("коротко расскажи основные команды бота")["tool"] == "help"


def test_watch_and_chart_do_not_invent_places() -> None:
    empty = render_watch("Дюна", "2021", "Пустыня и семья.", [], "", series=False)
    assert "В каталоге для России площадок не видно." in empty
    assert "Okko" not in empty
    filled = render_watch("Дюна", "2021", "Пустыня.", ["Старт"], "https://example.com/w", series=False)
    assert "Старт" in filled
    assert "example.com/w" in filled
    chart = render_tracks("🎵 <b>Сейчас в топе</b>", [("А", "Б", "https://music.example/a")])
    assert "А — Б" in chart
    assert "music.example/a" in chart


def test_day_note_prefers_calm_petersburg() -> None:
    events = [
        DayEvent(1941, "Началась война и блокада города.", "Блокада", ""),
        DayEvent(1714, "В Петербурге открылась Кунсткамера, первый музей России.", "Кунсткамера", "https://ru.wikipedia.org/wiki/K"),
        DayEvent(2001, "Где-то открыли парк.", "Парк", ""),
    ]
    picked = pick_day_event(events, date(2026, 10, 8))
    assert picked is not None
    assert picked.year == 1714
    text = render_day_note(date(2026, 10, 8), picked)
    assert "Кунсткамера" in text
    assert "API" not in text
    assert "войн" not in text.casefold()


def test_daily_board_names_only_the_leader_for_the_cookie() -> None:
    rows = [
        {"profile_name": "Аня", "messages": 12, "user_id": 1},
        {"profile_name": "Боря", "messages": 4, "user_id": 2},
    ]
    text = render_daily_chat(date(2026, 10, 7), rows, awarded=True)
    assert "Аня — 12" in text
    assert "Боря — 4" in text
    assert "Лидер суток — Аня. На баланс +1 🍪." in text
    assert "tg://user" not in text
    quiet = render_daily_chat(date(2026, 10, 7), [], awarded=False)
    assert "тихо" in quiet
    moment = datetime(2026, 10, 8, 1, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    assert due_daily_chat(moment, None) == date(2026, 10, 7)
    assert due_daily_chat(moment, "2026-10-07") is None
    later = datetime(2026, 10, 8, 11, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    assert due_daily_chat(later, None) is None


def test_weather_reply_expires_in_a_minute_and_explicit_ttl_wins() -> None:
    assert explicit_ttl("pogoda") == 60
    assert explicit_ttl("shop") is None
    explicit = _EXPLICIT_TTL.set(60)
    reply = _REPLY_TTL.set(60)
    try:
        with keep_in_chat():
            assert current_reply_ttl() == 60
    finally:
        _REPLY_TTL.reset(reply)
        _EXPLICIT_TTL.reset(explicit)


async def test_daily_leader_gets_one_cookie_once(tmp_path: Path) -> None:
    from community_bot.daily_chat import publish_daily_chat
    from community_bot.database import Database

    db = Database(tmp_path / "day.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Аня")
    await db.ensure_user(2, telegram_name="Боря")
    for _ in range(3):
        await db.record_activity(1, -100)
    await db.record_activity(2, -100)
    sent: list[str] = []

    class Bot:
        async def send_message(self, chat_id, text, **kwargs):
            assert kwargs.get("disable_notification") is True
            sent.append(text)
            return None

    class Settings:
        community_chat_id = -100

    day = datetime.now(ZoneInfo("Europe/Moscow")).date()
    assert await publish_daily_chat(Bot(), db, Settings(), day) is True
    assert await publish_daily_chat(Bot(), db, Settings(), day) is False
    user = await db.get_user(1)
    other = await db.get_user(2)
    assert int(user["cookies"]) == 1
    assert int(other["cookies"]) == 0
    assert len(sent) == 1
    assert "Аня" in sent[0]
    assert "Лидер суток — Аня" in sent[0]


def test_custom_command_and_removed_alias(tmp_path: Path) -> None:
    del tmp_path
    from community_bot.command_registry import CommandView, apply_rows

    try:
        apply_rows(
            [
                {
                    "slug": "pogoda",
                    "kind": "builtin",
                    "enabled": 1,
                    "title": "Погода",
                    "description": "Погода",
                    "aliases_json": "[]",
                    "ttl_seconds": 60,
                    "scope": "both",
                    "reply_text": "",
                    "options_json": "{}",
                },
                {
                    "slug": "c_hi",
                    "kind": "custom",
                    "enabled": 1,
                    "title": "Привет",
                    "description": "Короткое приветствие",
                    "aliases_json": "[\"приветnora\"]",
                    "ttl_seconds": None,
                    "scope": "both",
                    "reply_text": "Здравствуй",
                    "options_json": "{}",
                }
            ]
        )
        assert parse_trigger("погода") == ("pogoda", "")
        assert parse_trigger("приветnora") == ("c_hi", "")
        assert parse_trigger("приветnora всем") is None
        view = CommandView(
            slug="c_hi",
            title="Привет",
            description="",
            aliases=("приветnora",),
            kind="custom",
            reply_text="Здравствуй",
        )
        assert view.allows("private")
    finally:
        restore_defaults()
        assert parse_trigger("погода") == ("pogoda", "")


def test_public_update_hides_the_command_tool() -> None:
    item = latest_update()
    pin = community_announcement(item)
    details = member_details_text(item)
    staff = staff_announcement(item)
    public = f"{pin}\n{details}".casefold()
    assert item.number == 15
    assert item.telegraph_title == "НОРА и ИИ"
    assert "команды бота" not in public
    assert "tmdb" not in public
    assert "api" not in public
    assert "википед" not in public
    assert "погод" in public
    assert "петербург" in details.casefold()
    assert "00:00" in staff
    assert "TMDB_API_KEY" in staff
    assert "команды бота" not in staff.casefold()
    admin_rows = admin_system_keyboard(["admin.panel"]).inline_keyboard
    admin_buttons = [button.callback_data for row in admin_rows for button in row]
    assert "admin:cmds" not in admin_buttons
    owner_rows = admin_system_keyboard(["*"], is_owner=True).inline_keyboard
    owner_buttons = [button.callback_data for row in owner_rows for button in row]
    assert "admin:cmds" in owner_buttons
    assert PERM_COMMANDS == "commands.studio"
    admin_role = next(role for role in DEFAULT_STAFF_ROLES if role[0] == "admin")
    moderator_role = next(role for role in DEFAULT_STAFF_ROLES if role[0] == "moderator")
    assert PERM_COMMANDS in admin_role[3]
    assert PERM_COMMANDS not in moderator_role[3]
