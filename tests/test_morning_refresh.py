import asyncio
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from community_bot.database import Database
from community_bot.day_note import VERIFIED_EVENTS, DayEvent, parse_onthisday, pick_day_event, years_ago
from community_bot.morning import (
    CAPTION_LIMIT,
    MORNING_LAYOUT,
    MorningBrief,
    NewsItem,
    WeatherNow,
    clean_link,
    collect_brief,
    collect_news,
    news_region,
    parse_rss,
    publish_morning_digest,
    render_brief,
    select_day_news,
    telegram_length,
)

NOW = datetime(2026, 10, 26, 6, tzinfo=UTC)


def article(title, *, age=1, link="https://www.fontanka.ru/story/1/", lead="", source="Фонтанка"):
    return NewsItem(title, NOW - timedelta(hours=age), link=link, lead=lead, source=source)


def test_geography_takes_priority_over_recency_and_does_not_pad():
    city = article("В Петербурге открыли музей", age=20)
    region = article("В Ленобласти открыли школу", age=2, link="https://47news.ru/story/2/")
    russia = article("В России изменились правила проезда", age=1, link="https://tass.ru/story/3/")
    world = article("Во Франции открыли музей", link="https://tass.ru/story/4/")
    assert select_day_news([world, russia, region, city], NOW) == [city]
    assert select_day_news([world, russia, region], NOW) == [region]
    assert select_day_news([world, russia], NOW) == [russia]
    assert select_day_news([world], NOW) == []
    assert news_region(article("На станции открыли павильон")) is None


def test_date_window_duplicate_stories_and_two_item_limit():
    a = article("В Петербурге открыли новый музей транспорта", age=24)
    duplicate = article("В Петербурге открыли новый музей транспорта!", age=1, link="https://47news.ru/same/")
    b = article("В Петербурге изменили маршруты автобусов", link="https://www.fontanka.ru/story/2/")
    c = article("В Петербурге заработала новая библиотека", age=3, link="https://www.fontanka.ru/story/3/")
    old = article("В Петербурге открыли парк", age=24.01, link="https://www.fontanka.ru/old/")
    future = article("В Петербурге построили школу", age=-0.01, link="https://www.fontanka.ru/future/")
    selected = select_day_news([a, duplicate, b, c, old, future], NOW, 99)
    assert len(selected) == 2
    assert old not in selected and future not in selected
    assert not (a in selected and duplicate in selected)
    assert select_day_news([a], NOW) == [a]
    museum = article("В Петербурге открыли новый музей")
    school = article("В Петербурге открыли новую школу", link="https://47news.ru/school/")
    assert len(select_day_news([museum, school], NOW)) == 2
    traffic = [article("Водители встали в пробку на КАД Петербурга из-за ремонта"),
               article("Пробка парализовала КАД из-за ремонта моста в Петербурге 26 октября",
                       link="https://example.org/kad-followup")]
    assert len(select_day_news(traffic, NOW)) == 1


def test_recent_archive_reprint_is_not_current_news_and_useful_news_beats_weather():
    archive = article("Работницы вышли на митинг в Петрограде в 1917 году", age=0.1)
    weather = article("Погода в Петербурге демонстрирует аномалии", age=0.2, link="https://example.org/w")
    useful = article("В Петербурге изменили маршруты автобусов", age=2, link="https://example.org/b")
    exhibit = article("В Петербурге откроют выставку о жизни в 1917 году", age=3, link="https://example.org/e")
    assert select_day_news([archive, weather, useful, exhibit], NOW) == [useful, exhibit]
    crime = article("Петербурженка спаслась от сожителя и попала в больницу", link="https://example.org/crime")
    assert select_day_news([crime, useful, weather], NOW) == [useful]
    incident = article("В Петербурге подросток попал в больницу после ДТП", link="https://example.org/dtp")
    assert select_day_news([incident, useful], NOW) == [useful]


def test_rss_requires_timezone_and_keeps_real_query_parameters():
    rss = '''<rss><channel><item><title>В Петербурге открыли музей</title>
      <pubDate>Mon, 26 Oct 2026 08:00:00 +0300</pubDate>
      <link>https://example.org/read?id=7&amp;utm_source=rss</link>
      <description>&lt;p&gt;Подробности публикации.&lt;/p&gt;</description></item>
      <item><title>Без часового пояса</title><pubDate>Mon, 26 Oct 2026 08:00:00</pubDate></item>
      </channel></rss>'''
    items = parse_rss(rss, "Издание")
    assert len(items) == 1
    assert items[0].published == datetime(2026, 10, 26, 5, tzinfo=UTC)
    assert items[0].link == "https://example.org/read?id=7"
    assert items[0].source == "Издание"
    assert clean_link("javascript:alert(1)") == ""
    assert clean_link("https://name:password@example.org/") == ""


class CheckHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.quotes = 0

    def handle_starttag(self, tag, attrs):
        assert tag in {"b", "a", "blockquote"}
        if tag == "blockquote":
            assert "blockquote" not in self.stack
            assert ("expandable", None) in attrs
            self.quotes += 1
        self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack.pop() == tag


def test_caption_is_balanced_collapsible_bounded_and_does_not_mutate():
    news = [article("В Петербурге <открыли> & музей " * 30, lead="Детали 👩🏽‍🚀 & <текст> " * 100),
            article("В Петербурге новая библиотека " * 30, link="https://47news.ru/2/", lead="Ещё детали " * 200)]
    brief = MorningBrief(
        NOW, weather=WeatherNow(8, 5, 3, 14, 0, "", ""), day_news=news,
        history=DayEvent(1930, "В Петербурге произошло событие & <детали> " * 40,
                         "Заголовок", "https://example.org/history", "Последствия 👩🏽‍🚀 " * 100, 10, 26),
    )
    first = render_brief(brief)
    assert render_brief(brief) == first
    assert brief.day_news == news and len(brief.day_news) == 2
    assert telegram_length(first) <= CAPTION_LIMIT
    assert "1930" in first and "96 лет назад" in first
    assert "Этот день в Петербурге" in first
    assert "&lt;" in first and "&amp;" in first
    parser = CheckHTML()
    parser.feed(first)
    assert not parser.stack and parser.quotes == 3


def test_missing_sources_never_claim_no_news_or_fabricate_metro_or_history():
    brief = MorningBrief(NOW, news_available=False, metro_available=False,
                         closed_stations=["Парк Победы", "Фрунзенская"],
                         history=DayEvent(1930, "Другой день", "", "", "", 10, 25))
    text = render_brief(brief)
    assert "Новости пока не загрузились" in text
    assert "нет новых материалов" not in text
    assert "Парк Победы" not in text and "Другой день" not in text
    assert "Подтверждённого события" in text


def test_history_is_calendar_bound_city_specific_and_not_a_year_article():
    payload = {"events": [{"year": 1900, "text": "В Петербурге открыли учебный музей.", "pages": [
        {"title": "1900_год", "extract": "Обычный год", "content_urls": {"desktop": {"page": "https://example.org/y"}}},
        {"title": "Санкт-Петербург", "extract": "Город России"},
        {"title": "Учебный_музей", "extract": "Музей стал площадкой для занятий студентов.",
         "content_urls": {"desktop": {"page": "https://example.org/museum"}}},
    ]}]}
    events = parse_onthisday(payload, date(2026, 10, 26))
    picked = pick_day_event(events, date(2026, 10, 26))
    assert picked and picked.context == "Музей стал площадкой для занятий студентов."
    assert picked.url == "https://example.org/museum"
    assert pick_day_event(events, date(2026, 10, 27)) is None
    assert pick_day_event([DayEvent(1900, "В Москве открыли музей.", "", "")], date(2026, 10, 26)) is None
    verified = VERIFIED_EVENTS[(10, 26)]
    assert verified.month == 10 and verified.day == 26 and verified.context
    assert "mariinsky.ru" in verified.url
    assert [years_ago(n) for n in (1, 2, 5, 11, 21, 22)] == [
        "1 год назад", "2 года назад", "5 лет назад", "11 лет назад", "21 год назад", "22 года назад",
    ]


async def test_collector_keeps_working_feed_and_distinguishes_failures(monkeypatch):
    async def get_text(session, url):
        if "fontanka" in url:
            return '<rss><channel><item><title>В Петербурге открыли музей</title><pubDate>' \
                   'Mon, 26 Oct 2026 08:00:00 +0300</pubDate><link>https://example.org/a</link></item></channel></rss>'
        if "47news" in url:
            return "<html>Bad gateway</html>"
        raise TimeoutError()

    monkeypatch.setattr("community_bot.morning._get_text", get_text)
    items, available = await collect_news(None)
    assert available and len(items) == 1 and items[0].source == "Фонтанка"

    async def unavailable(*args):
        raise TimeoutError()

    monkeypatch.setattr("community_bot.morning._get_text", unavailable)
    items, available = await collect_news(None)
    assert items == [] and not available
    monkeypatch.setattr("community_bot.morning._get_json", unavailable)
    monkeypatch.setattr("community_bot.day_note.city_event_for", unavailable)
    brief = await collect_brief(NOW)
    assert brief.closed_stations == [] and not brief.metro_available
    assert brief.history is None and not brief.news_available


async def test_pin_failure_preserves_previous_pin_and_retry_does_not_resend(tmp_path: Path, monkeypatch):
    db = Database(tmp_path / "pin.db")
    await db.initialize()
    await db.set_bot_state("morning_pin_message_id", "7")
    now = datetime.now(UTC)
    brief = MorningBrief(now)
    calls = []

    async def collect(now):
        return brief

    monkeypatch.setattr("community_bot.morning.collect_brief", collect)

    class Bot:
        fail_pin = True

        async def send_photo(self, *args, **kwargs):
            calls.append("send")
            return SimpleNamespace(message_id=8)

        async def pin_chat_message(self, chat, message_id, **kwargs):
            calls.append(("pin", message_id))
            if self.fail_pin:
                raise RuntimeError("no pin permission")

        async def unpin_chat_message(self, chat, message_id):
            calls.append(("unpin", message_id))

    bot = Bot()
    settings = SimpleNamespace(community_chat_id=-100, timezone="Europe/Moscow")
    assert not await publish_morning_digest(bot, db, settings, force=True)
    assert ("unpin", 7) not in calls
    assert await db.get_bot_state("morning_pin_message_id") == "7"
    bot.fail_pin = False
    assert await publish_morning_digest(bot, db, settings, force=True)
    assert calls.count("send") == 1
    assert calls[-2:] == [("pin", 8), ("unpin", 7)]
    assert await db.get_bot_state("morning_pending_day") == ""
    assert await db.get_bot_state("morning_pin_message_id") == "8"
    # A regular scheduler pass after a completed publication is a no-op.
    before = list(calls)
    assert await publish_morning_digest(bot, db, settings)
    assert calls == before


async def test_send_failure_does_not_unpin_or_mark_sent(tmp_path: Path, monkeypatch):
    db = Database(tmp_path / "send.db")
    await db.initialize()
    await db.set_bot_state("morning_pin_message_id", "7")

    async def collect(now):
        return MorningBrief(now)

    class Bot:
        async def send_photo(self, *args, **kwargs):
            raise RuntimeError("send failed")

        async def unpin_chat_message(self, *args):
            pytest.fail("old pin removed")

    monkeypatch.setattr("community_bot.morning.collect_brief", collect)
    settings = SimpleNamespace(community_chat_id=-100, timezone="Europe/Moscow")
    with pytest.raises(RuntimeError, match="send failed"):
        await publish_morning_digest(Bot(), db, settings, force=True)
    assert await db.get_bot_state("morning_digest_day") is None
    assert await db.get_bot_state("morning_pin_message_id") == "7"


async def test_concurrent_scheduler_passes_send_only_once(tmp_path: Path, monkeypatch):
    db = Database(tmp_path / "concurrent.db")
    await db.initialize()
    sent = []

    class Clock(datetime):
        @classmethod
        def now(cls, tz):
            return datetime(2026, 10, 26, 9, 0, tzinfo=tz)

    async def collect(now):
        await asyncio.sleep(0)
        return MorningBrief(now)

    class Bot:
        async def send_photo(self, *args, **kwargs):
            sent.append(kwargs["caption"])
            return SimpleNamespace(message_id=8)

        async def pin_chat_message(self, *args, **kwargs):
            pass

    monkeypatch.setattr("community_bot.morning.datetime", Clock)
    monkeypatch.setattr("community_bot.morning.collect_brief", collect)
    bot = Bot()
    settings = SimpleNamespace(community_chat_id=-100, timezone="Europe/Moscow")
    assert await asyncio.gather(*(publish_morning_digest(bot, db, settings) for _ in range(2))) == [True, True]
    assert len(sent) == 1


async def test_release_announcement_preserves_unrelated_and_morning_pins():
    from community_bot.main import _pin_announcement

    pins = {6, 42, 99}

    class DB:
        async def get_bot_state(self, key):
            return "6" if key == "last_announcement_message_id" else None

    class Bot:
        fail = False

        async def pin_chat_message(self, chat, message_id, **kwargs):
            if self.fail:
                raise RuntimeError("pin failed")
            pins.add(message_id)

        async def unpin_chat_message(self, chat, message_id):
            pins.remove(message_id)

        async def unpin_all_chat_messages(self, chat):
            pytest.fail("unrelated pins must never be removed")

    bot = Bot()
    settings = SimpleNamespace(community_chat_id=-100)
    bot.fail = True
    await _pin_announcement(bot, DB(), settings, 8)
    assert pins == {6, 42, 99}
    bot.fail = False
    await _pin_announcement(bot, DB(), settings, 8)
    assert pins == {8, 42, 99}


async def test_today_is_refreshed_in_place_once_without_resending_photo(tmp_path: Path, monkeypatch):
    db = Database(tmp_path / "refresh.db")
    await db.initialize()
    today = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    await db.set_bot_state("morning_digest_day", today)
    await db.set_bot_state("morning_pin_message_id", "42")
    edits = []

    async def collect(now):
        return MorningBrief(now)

    class Bot:
        async def edit_message_caption(self, **kwargs):
            edits.append(kwargs)

        async def send_photo(self, *args, **kwargs):
            pytest.fail("migration must preserve the existing photo")

        async def pin_chat_message(self, *args, **kwargs):
            pytest.fail("migration must preserve the existing pin")

    monkeypatch.setattr("community_bot.morning.collect_brief", collect)
    bot = Bot()
    settings = SimpleNamespace(community_chat_id=-100, timezone="Europe/Moscow")
    assert await publish_morning_digest(bot, db, settings)
    assert len(edits) == 1 and edits[0]["message_id"] == 42
    assert await db.get_bot_state("morning_layout_version") == MORNING_LAYOUT
    assert await publish_morning_digest(bot, db, settings)
    assert len(edits) == 1


async def test_failed_caption_refresh_keeps_old_pin_and_retry_state(tmp_path: Path, monkeypatch):
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import EditMessageCaption
    db = Database(tmp_path / "refresh-fail.db")
    await db.initialize()
    today = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    await db.set_bot_state("morning_digest_day", today)
    await db.set_bot_state("morning_pin_message_id", "42")

    async def collect(now):
        return MorningBrief(now)

    class Bot:
        async def edit_message_caption(self, **kwargs):
            raise TelegramBadRequest(method=EditMessageCaption(**kwargs), message="message can't be edited")

    monkeypatch.setattr("community_bot.morning.collect_brief", collect)
    settings = SimpleNamespace(community_chat_id=-100, timezone="Europe/Moscow")
    assert not await publish_morning_digest(Bot(), db, settings)
    assert await db.get_bot_state("morning_pin_message_id") == "42"
    assert await db.get_bot_state("morning_layout_version") is None
