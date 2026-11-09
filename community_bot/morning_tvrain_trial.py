"""One production-only trial for the 2026-11-09 digest release."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import aiohttp
from aiogram.types import InputRichBlockSectionHeading, InputRichMessage

from community_bot.ephemeral import keep_in_chat
from community_bot.morning import MorningBrief, _get_json, collect_tvrain, parse_weather, select_tvrain_news
from community_bot.morning_rich import news_block, weather_block
from community_bot.morning_weather import MORNING_WEATHER_URL, render_weather_card

logger = logging.getLogger(__name__)
EXPIRES_AT = datetime(2026, 11, 9, 9, tzinfo=UTC)


async def apply_tvrain_trial(bot, settings) -> None:
    now = datetime.now(UTC)
    if (
        now >= EXPIRES_AT
        or not settings.community_chat_id
        or os.getenv("RAILWAY_ENVIRONMENT_NAME") != "production"
        or os.getenv("RAILWAY_GIT_BRANCH") != "cursor/nora-2-update-d133"
    ):
        return
    mount = Path("/app/data")
    marker = mount / ".nora-tvrain-trial-2026-11-09"
    try:
        mountinfo = await asyncio.to_thread(Path("/proc/self/mountinfo").read_text, encoding="utf-8")
        if not any(line.split()[4] == mount.as_posix() for line in mountinfo.splitlines()):
            logger.warning("Пробная сводка пропущена: постоянный том Railway не смонтирован")
            return
        await send_trial(bot, settings.community_chat_id, marker, now)
    except Exception as exc:
        logger.warning("Пробная сводка «Дождя»: отправка не подтверждена (%s)", type(exc).__name__)


async def send_trial(bot, chat_id: int, marker: Path, now: datetime) -> None:
    if await asyncio.to_thread(marker.exists):
        return
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=12), headers={"User-Agent": "NoraMorning/1.0"}, trust_env=True,
    ) as session:
        items, weather_raw = await asyncio.gather(
            collect_tvrain(session, now), _get_json(session, MORNING_WEATHER_URL),
        )
    selected = select_tvrain_news(items, now, exclude=[], limit=1)
    weather = parse_weather(weather_raw)
    if not selected or weather is None:
        logger.warning("Пробная сводка пропущена: нет свежей новости «Дождя» или погоды")
        return
    card = render_weather_card(weather_raw, weather, now)
    if card is None:
        return
    brief = MorningBrief(now, weather=weather, weather_card=card)
    rich_message = InputRichMessage(blocks=[
        InputRichBlockSectionHeading(text="NORA DAILY · пробный выпуск", size=1),
        weather_block(brief),
        InputRichBlockSectionHeading(text="📰 Свежая новость", size=2),
        news_block(selected[0]),
    ])
    await bot.get_chat(chat_id)
    if not await asyncio.to_thread(_claim_trial, marker, now):
        return
    with keep_in_chat():
        sent = await bot.send_rich_message(chat_id, rich_message=rich_message)
    logger.info("Пробная сводка «Дождя» отправлена, message_id=%d", sent.message_id)


def _claim_trial(marker: Path, now: datetime) -> bool:
    # A lost Telegram response must not result in another send after restart.
    try:
        with marker.open("x", encoding="ascii") as claim:
            claim.write(now.isoformat())
            claim.flush()
            os.fsync(claim.fileno())
    except FileExistsError:
        return False
    return True
