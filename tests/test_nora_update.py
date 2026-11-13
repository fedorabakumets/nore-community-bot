from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from community_bot.aliases import parse_trigger
from community_bot.command_registry import explicit_ttl, restore_defaults
from community_bot.daily_chat import due_daily_chat, render_daily_chat
from community_bot.day_note import DayEvent, pick_day_event, render_day_note
from community_bot.ephemeral import _EXPLICIT_TTL, _REPLY_TTL, current_reply_ttl, keep_in_chat
from community_bot.keyboards import admin_system_keyboard
from community_bot.nora import (
    clip_spoken,
    movies_from_itunes,
    render_open_title,
    render_tracks,
    render_watch,
    rule_intent,
    series_from_schedule,
    strip_address,
    wiki_search_title,
)
from community_bot.permissions import DEFAULT_STAFF_ROLES, PERM_COMMANDS
from community_bot.updates import community_announcement, member_details_text, staff_announcement


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
    assert rule_intent("где дюна")["tool"] == "find_title"
    assert rule_intent("где находится эрмитаж") is None


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
    opened = render_open_title(
        "Дюна",
        "2021",
        "Пустыня и семья.",
        "https://example.com/dune",
        series=False,
        platforms_unknown=True,
    )
    assert "Дюна" in opened
    assert "отсюда не видно" in opened
    assert "TMDB" not in opened
    assert "Okko" not in opened
    assert "API" not in opened
    movies = movies_from_itunes(
        {
            "feed": {
                "entry": {
                    "im:name": {"label": "Поймай меня, если сможешь"},
                    "summary": {"label": "Молодой мастер обмана и агент, который идёт следом."},
                    "im:releaseDate": {"label": "2003-02-12T00:00:00-07:00"},
                    "link": [{"attributes": {"rel": "alternate", "href": "https://itunes.apple.com/ru/movie/1"}}],
                }
            }
        }
    )
    assert movies[0]["title"] == "Поймай меня, если сможешь"
    assert movies[0]["year"] == "2003"
    assert "itunes.apple.com" in movies[0]["link"]
    show = series_from_schedule(
        [
            {"show": {"name": "Новости", "type": "News", "summary": "<p>Сводка</p>", "url": "https://tv.example/n"}},
            {"show": {"name": "Невский", "type": "Scripted", "summary": "", "premiered": "2016-04-11", "url": "https://tv.example/s"}},
        ]
    )
    assert show is not None
    assert show["title"] == "Невский"
    assert show["year"] == "2016"
    assert wiki_search_title({"query": {"search": [{"title": "Дюна (фильм, 2021)"}]}}) == "Дюна (фильм, 2021)"
    spoken = clip_spoken("Возьми зонт. <b>не тег</b> " + ("слово " * 200))
    assert "<b>" not in spoken
    assert "не тег" in spoken
    assert len(spoken) <= 700


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
    from community_bot.updates import UPDATES

    item = next(update for update in UPDATES if update.number == 15)
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


async def test_film_without_catalog_key_uses_open_sources(monkeypatch) -> None:
    from community_bot.nora import find_title, suggest_title

    async def movie(genre_asked: bool) -> str:
        assert genre_asked is False
        return "🎬 <b>Поймай меня, если сможешь</b>"

    async def lookup(query: str, kind: str) -> str:
        assert kind == "movie"
        assert "дюна" in query.casefold()
        return "🎬 <b>Дюна</b>\nГде именно это показывают, отсюда не видно."

    monkeypatch.setattr("community_bot.nora._suggest_movie_open", movie)
    monkeypatch.setattr("community_bot.nora._lookup_open", lookup)

    class Settings:
        tmdb_api_key = ""

    suggested = await suggest_title(Settings(), kind="movie", genre="", avoid="")
    found = await find_title(Settings(), "дюна", "movie")
    assert "Поймай" in suggested
    assert "TMDB" not in suggested
    assert "Дюна" in found
    assert "отсюда не видно" in found


async def test_unmatched_nora_phrase_uses_the_model_or_a_hunch(monkeypatch) -> None:
    from community_bot.nora import reply_for, spoken_reply

    prompts: list[str] = []

    async def fake_model(prompt: str, settings: object) -> str:
        del settings
        prompts.append(prompt)
        if "диспетчер" in prompt:
            return '{"tool":"none"}'
        return "Возьми зонт, на Неве ветрено. <b>не тег</b>"

    monkeypatch.setattr("community_bot.nora.ask_model", fake_model)

    class Ready:
        gemini_api_key = "x"
        groq_api_key = ""
        tmdb_api_key = ""

    now = datetime.now(ZoneInfo("Europe/Moscow"))
    text = await reply_for("Нора, что надеть вечером", Ready(), now)
    assert "зонт" in text
    assert "<b>" not in text
    assert len(prompts) == 2

    class Empty:
        gemini_api_key = ""
        groq_api_key = ""
        tmdb_api_key = ""

    hello = await spoken_reply("привет", Empty())
    assert hello.startswith("Привет")

    async def page(query: str):
        assert "эрмитаж" in query.casefold()
        return ("Эрмитаж", "Музей на Дворцовой набережной.", "https://ru.wikipedia.org/wiki/H")

    monkeypatch.setattr("community_bot.nora._wiki_lookup", page)
    fact = await spoken_reply("кто основал эрмитаж", Empty())
    assert fact.startswith("Если коротко:")
    assert "Эрмитаж" in fact
    assert "википед" not in fact.casefold()
    assert "API" not in fact


async def test_group_nora_line_is_deleted_after_the_reply(monkeypatch) -> None:
    from community_bot.routers.nora import nora_address

    async def fake_reply(text: str, settings: object, now: datetime) -> str:
        del text, settings, now
        return "Привет. Я на связи."

    monkeypatch.setattr("community_bot.routers.nora.reply_for", fake_reply)
    deleted: list[tuple[int, int]] = []
    answers: list[str] = []

    class User:
        is_bot = False

    class Chat:
        def __init__(self, kind: str) -> None:
            self.type = kind
            self.id = -100 if kind == "group" else 5

    class Bot:
        async def delete_message(self, chat_id: int, message_id: int) -> None:
            deleted.append((chat_id, message_id))

    class Msg:
        def __init__(self, kind: str) -> None:
            self.text = "Нора, привет"
            self.from_user = User()
            self.chat = Chat(kind)
            self.message_id = 15
            self.bot = Bot()

        async def answer(self, text: str, **kwargs: object) -> None:
            del kwargs
            answers.append(text)

    settings = type("Settings", (), {"timezone": "Europe/Moscow"})()
    await nora_address(Msg("group"), settings)
    assert answers == ["Привет. Я на связи."]
    assert deleted == [(-100, 15)]
    answers.clear()
    await nora_address(Msg("private"), settings)
    assert answers == ["Привет. Я на связи."]
    assert deleted == [(-100, 15)]
