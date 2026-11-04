from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendRichMessage
from aiogram.types import InputRichBlockDetails, InputRichBlockPhoto

from community_bot.database import Database
from community_bot.day_note import DayEvent
from community_bot.morning import MorningBrief, NewsItem, WeatherNow, publish_morning_digest
from community_bot.morning_rich import render_rich_brief

NOW = datetime(2026, 10, 26, 9, tzinfo=UTC)


def test_rich_blocks_keep_complete_headlines_and_embedded_photo():
    title = "В Петербурге открыли новый музей " * 8
    brief = MorningBrief(
        NOW, weather=WeatherNow(8, 5, 3, 14, 0, "", ""), traffic_level=4,
        metro_available=False, closed_stations=["Неизвестная станция"],
        road_incidents=[NewsItem("ДТП на КАД Петербурга", NOW, link="https://example.org/road", source="Источник")],
        day_news=[NewsItem(title, NOW, link="https://example.org/news", lead="Детали", source="Источник")],
        history=DayEvent(1930, "История", "Событие", "https://example.org/history", "Контекст", 10, 26),
    )
    rich = render_rich_brief(brief, "test_bot")
    assert rich.blocks and any(isinstance(block, InputRichBlockPhoto) for block in rich.blocks)
    details = [block for block in rich.blocks if isinstance(block, InputRichBlockDetails)]
    assert details[2].summary == title and len(details) == 4
    assert details[1].summary == "🚦 Пробки · 4 из 10 баллов"
    assert "ДТП на КАД" in details[1].blocks[1].text
    assert "Петербург" in details[0].summary
    assert rich.blocks[1].text == "📆 Понедельник • 26 октября"
    assert rich.blocks.index(details[1]) == rich.blocks.index(details[0]) + 1
    bot = Bot(token="123456:TEST_TOKEN_FOR_LOCAL_SERIALIZATION")
    files = {}
    data = bot.session.prepare_value(rich, bot=bot, files=files)
    assert len(files) == 1 and "attach://" in data
    assert "https://example.org/news" in data and "https://example.org/history" in data
    assert "https://example.org/road" in data
    assert "start=private" not in data
    assert '"text": "BOT"' not in data
    assert "Неизвестная станция" not in data


@pytest.mark.asyncio
async def test_rich_send_pin_retry_without_duplicate(tmp_path, monkeypatch):
    db = Database(tmp_path / "rich.db")
    await db.initialize()
    await db.set_bot_state("morning_pin_message_id", "7")
    async def collect(now):
        return MorningBrief(now)
    monkeypatch.setattr("community_bot.morning.collect_brief", collect)
    class Bot:
        calls = []
        fail = True
        async def me(self):
            return SimpleNamespace(username="test_bot")
        async def send_rich_message(self, chat, *, rich_message, reply_markup):
            assert reply_markup.inline_keyboard[0][0].text == "НОРА"
            assert reply_markup.inline_keyboard[0][0].url == "https://t.me/test_bot?startapp"
            self.calls.append(rich_message)
            return SimpleNamespace(message_id=8)
        async def pin_chat_message(self, *args, **kwargs):
            if self.fail:
                raise RuntimeError("pin failed")
        async def unpin_chat_message(self, *args):
            pass
    bot = Bot()
    settings = SimpleNamespace(community_chat_id=-100, timezone="Europe/Moscow")
    assert not await publish_morning_digest(bot, db, settings, force=True)
    assert await db.get_bot_state("morning_pin_message_id") == "7"
    bot.fail = False
    assert await publish_morning_digest(bot, db, settings, force=True)
    assert len(bot.calls) == 1
    assert await db.get_bot_state("morning_pin_message_id") == "8"


@pytest.mark.asyncio
@pytest.mark.parametrize("error,should_fallback", [("method not found", True), ("invalid content", False)])
async def test_only_definitive_unsupported_errors_fallback(tmp_path, monkeypatch, error, should_fallback):
    db = Database(tmp_path / "fallback.db")
    await db.initialize()
    async def collect(now):
        return MorningBrief(now)
    monkeypatch.setattr("community_bot.morning.collect_brief", collect)
    class Bot:
        legacy_calls = 0
        async def send_rich_message(self, chat, *, rich_message, reply_markup):
            raise TelegramBadRequest(method=SendRichMessage(chat_id=chat, rich_message=rich_message), message=error)
        async def send_photo(self, *args, **kwargs):
            self.legacy_calls += 1
            return SimpleNamespace(message_id=8)
        async def pin_chat_message(self, *args, **kwargs):
            pass
    bot = Bot()
    settings = SimpleNamespace(community_chat_id=-100, timezone="Europe/Moscow")
    if should_fallback:
        assert await publish_morning_digest(bot, db, settings, force=True)
        assert bot.legacy_calls == 1
    else:
        with pytest.raises(TelegramBadRequest):
            await publish_morning_digest(bot, db, settings, force=True)
        assert bot.legacy_calls == 0


@pytest.mark.asyncio
async def test_uncertain_send_never_falls_back(tmp_path, monkeypatch):
    db = Database(tmp_path / "timeout.db")
    await db.initialize()
    async def collect(now):
        return MorningBrief(now)
    monkeypatch.setattr("community_bot.morning.collect_brief", collect)
    class Bot:
        async def send_rich_message(self, *args, **kwargs):
            raise TimeoutError("uncertain send")
        async def send_photo(self, *args, **kwargs):
            pytest.fail("ambiguous send must not fall back")
    settings = SimpleNamespace(community_chat_id=-100, timezone="Europe/Moscow")
    bot = Bot()
    with pytest.raises(TimeoutError):
        await publish_morning_digest(bot, db, settings, force=True)
    assert not await publish_morning_digest(bot, db, settings, force=True)


def test_rich_traffic_explains_missing_sources():
    empty = render_rich_brief(MorningBrief(NOW))
    traffic = next(block for block in empty.blocks if isinstance(block, InputRichBlockDetails))
    assert "данные недоступны" in traffic.summary
    assert "не найдено" in traffic.blocks[0].text
    unavailable = render_rich_brief(MorningBrief(NOW, news_available=False))
    traffic = next(block for block in unavailable.blocks if isinstance(block, InputRichBlockDetails))
    assert "не загрузились" in traffic.blocks[0].text
