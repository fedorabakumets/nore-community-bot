from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot

from community_bot import morning, morning_tvrain_trial
from community_bot.morning_rich import news_block

NOW = datetime(2026, 11, 9, 9, tzinfo=ZoneInfo("Europe/Moscow"))


def test_rain_notice_in_rich_and_fallback_only_for_rain():
    rain = morning.NewsItem("Заголовок", NOW, source=morning.TVRAIN_SOURCE, link="https://tvrain.tv/news/one")
    local = morning.NewsItem("Другая новость", NOW, source="Фонтанка", link="https://example.org/news")
    block = news_block(rain)
    assert "Дождь — иноагент" in block.summary
    assert block.blocks[0].text == morning.TVRAIN_NOTICE
    assert morning.TVRAIN_NOTICE in morning.render_news_line(rain)
    assert morning.TVRAIN_NOTICE in morning.render_brief(morning.MorningBrief(NOW, day_news=[rain, local]))
    assert "иноагент" not in news_block(local).summary
    assert morning.TVRAIN_NOTICE not in morning.render_news_line(local)


def rss_item(title, path, date, extra=""):
    return (
        f"<item><title>{title}</title><link>https://tvrain.tv/{path}</link>"
        f"<pubDate>{date}</pubDate>{extra}</item>"
    )


def test_rss_uses_publication_dates_and_rejects_non_news_and_duplicates():
    rss = "<rss><channel>" + "".join([
        rss_item("Future", "news/future", "Mon, 09 Nov 2026 09:01:00 +0300"),
        rss_item("Broadcast", "teleshow/broadcast", "Mon, 09 Nov 2026 08:59:00 +0300"),
        rss_item("Promo", "news/promo", "Mon, 09 Nov 2026 08:58:00 +0300", "<category>Sponsored</category>"),
        rss_item("Without time zone", "news/unknown", "Mon, 09 Nov 2026 08:57:00 -0000"),
        rss_item("Archive", "news/old", "Sun, 08 Nov 2026 05:59:00 +0000"),
        rss_item("A &amp; B", "news/one/?utm_source=rss", "Mon, 09 Nov 2026 08:01:00 +0300"),
        rss_item("A &amp; B", "news/one/", "Mon, 09 Nov 2026 08:02:00 +0300",
                 "<description><![CDATA[<p>News &amp; details.</p><script>Ignore this.</script>]]></description>"),
        rss_item("Another story", "news/two", "Sun, 08 Nov 2026 06:00:00 +0000"),
    ]) + "</channel></rss>"
    items = morning.parse_tvrain_rss(rss.encode())
    first, second = morning.select_tvrain_news(items, NOW, exclude=[])
    assert first.title == "A & B" and first.lead == "News & details."
    assert first.published == datetime(2026, 11, 9, 5, 2, tzinfo=UTC)
    assert second.title == "Another story" and second.lead == ""
    assert second.published == NOW - timedelta(hours=24)
    assert all(item.source == morning.TVRAIN_SOURCE for item in (first, second))
    assert "<b>A &amp; B</b>" in morning.render_news_line(first)
    assert "News &amp; details." in morning.render_news_line(first)
    assert morning.select_tvrain_news(items, NOW, exclude=[first]) == [second]


def test_rss_rejects_entity_declarations():
    with pytest.raises(ValueError, match="DTD"):
        morning.parse_tvrain_rss(b'<!DOCTYPE rss [<!ENTITY text "untrusted">]><rss><channel/></rss>')


async def test_daily_news_fills_only_missing_slot_from_old_feeds(monkeypatch):
    road = morning.NewsItem("ДТП на КАД Петербурга", NOW, link="https://example.org/road")
    local = morning.NewsItem("В Петербурге открыли музей", NOW, link="https://example.org/museum")
    rain = morning.NewsItem("Новость Дождя", NOW, link="https://tvrain.tv/news/one")

    async def local_feeds(session):
        return [road, local], True

    async def rain_feed(session, now):
        return [rain]

    async def unavailable(*args):
        raise TimeoutError

    monkeypatch.setattr(morning, "collect_news", local_feeds)
    monkeypatch.setattr(morning, "collect_tvrain", rain_feed)
    monkeypatch.setattr(morning, "_get_json", unavailable)
    monkeypatch.setattr(morning, "_get_text", unavailable)
    monkeypatch.setattr("community_bot.day_note.city_event_for", unavailable)
    brief = await morning.collect_brief(NOW)
    assert brief.day_news == [rain, local]
    assert brief.road_incidents == [road]


async def test_trial_serializes_card_and_does_not_retry_after_lost_response(tmp_path, monkeypatch):
    older = morning.NewsItem("Old", NOW - timedelta(hours=2), link="https://tvrain.tv/news/old")
    latest = morning.NewsItem("Latest <&>", NOW, link="https://tvrain.tv/news/latest", source=morning.TVRAIN_SOURCE)
    payload = {
        "current": {"time": "2026-11-09T09:00", "temperature_2m": 2, "apparent_temperature": 0,
                    "weather_code": 3, "wind_speed_10m": 12, "relative_humidity_2m": 87},
        "hourly": {"time": ["2026-11-09T10:00"], "temperature_2m": [3], "weather_code": [61]},
        "daily": {"time": ["2026-11-09"], "temperature_2m_min": [0], "temperature_2m_max": [4],
                  "weather_code": [61]},
    }
    calls = []
    chat = -123
    marker = tmp_path / "claimed"

    async def collect(session, now):
        return [older, latest]

    async def weather(session, url):
        return payload

    async def get_chat(chat_id):
        assert chat_id == chat and not marker.exists()
        calls.append("chat")

    async def send(chat_id, *, rich_message):
        assert chat_id == chat and marker.exists()
        calls.append("send")
        transport = Bot(token="123456:TEST_TOKEN_FOR_LOCAL_SERIALIZATION")
        files = {}
        data = transport.session.prepare_value(rich_message, bot=transport, files=files)
        assert "Latest <&>" in data and "https://tvrain.tv/news/old" not in data
        weather_blocks = rich_message.blocks[1].blocks
        assert [block.type for block in weather_blocks] == ["photo", "paragraph"]
        assert weather_blocks[1].text.startswith("👕 ")
        assert len(files) == 1 and next(iter(files.values())).data.startswith(b"\x89PNG\r\n")
        raise TimeoutError

    monkeypatch.setattr(morning_tvrain_trial, "collect_tvrain", collect)
    monkeypatch.setattr(morning_tvrain_trial, "_get_json", weather)
    bot = SimpleNamespace(get_chat=get_chat, send_rich_message=send)
    with pytest.raises(TimeoutError):
        await morning_tvrain_trial.send_trial(bot, chat, marker, NOW)
    await morning_tvrain_trial.send_trial(bot, chat, marker, NOW)
    assert calls == ["chat", "send"]
