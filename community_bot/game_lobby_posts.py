"""Retire Telegram lobby posts without changing the room or its stakes."""
from __future__ import annotations

import asyncio
import json
import logging
import time

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

TTL = 120
PREFIX = "game-lobby-post:"
logger = logging.getLogger(__name__)

_DUE = """
    WITH posts AS (
        SELECT key,json_extract(value,'$[0]') AS game,json_extract(value,'$[1]') AS room,
               json_extract(value,'$[2]') AS chat,json_extract(value,'$[3]') AS message,
               json_extract(value,'$[4]') AS expires,json_extract(value,'$[5]') AS retry
        FROM bot_state WHERE key BETWEEN 'game-lobby-post:' AND 'game-lobby-post;' AND json_valid(value)
    )
    SELECT * FROM posts WHERE retry<=? AND (expires<=? OR CASE
        WHEN game IN ('barricade','durak') THEN NOT EXISTS (
            SELECT 1 FROM durak_rooms r WHERE r.id=posts.room AND r.status='waiting')
        WHEN game='mafia' THEN NOT EXISTS (
            SELECT 1 FROM mini_mafia_rooms r WHERE r.id=posts.room AND r.status='lobby')
        WHEN game='sea' THEN NOT EXISTS (
            SELECT 1 FROM mini_sea_rooms r WHERE r.id=posts.room AND r.status='lobby')
        WHEN game='roulette' THEN NOT EXISTS (
            SELECT 1 FROM roulette_games r WHERE r.id=posts.room AND r.status='pending')
        ELSE 0 END) ORDER BY expires LIMIT 20
"""


async def remember(db, game, room, chat, sent, *, now=None, announcement=False):
    message_id = getattr(sent, "message_id", None)
    if type(message_id) is not int or message_id <= 0:
        return
    try:
        await db.set_bot_state(
            f"{PREFIX}{chat}:{message_id}",
            json.dumps([game, room, chat, message_id, (time.time() if now is None else now) + TTL, 0, announcement]),
        )
    except Exception:
        logger.exception("Could not track the Telegram lobby post for cleanup")


async def has_live_announcement(db, game, room, chat):
    prefix = f"{PREFIX}{chat}:"
    return await db.fetchone("""
        SELECT 1 FROM bot_state WHERE key GLOB ? AND json_valid(value)
          AND json_extract(value,'$[0]')=? AND json_extract(value,'$[1]')=?
          AND json_extract(value,'$[4]')>? AND json_extract(value,'$[6]')=1 LIMIT 1
    """, (prefix + "*", game, room, time.time())) is not None


async def cleanup(db, bot, *, now=None):
    if not bot:
        return
    now = time.time() if now is None else now
    for row in await db.fetchall(_DUE, (now, now)):
        retry = 0
        try:
            async with asyncio.timeout(4):
                await bot.delete_message(row["chat"], row["message"])
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            if "not found" not in str(error).lower():
                logger.warning("Telegram declined lobby post removal (%s)", type(error).__name__)
        except TelegramRetryAfter as error:
            retry = now + error.retry_after
        except (TelegramAPIError, OSError, TimeoutError):
            retry = now + 15
        if retry:
            await db.execute("UPDATE bot_state SET value=json_set(value,'$[5]',?) WHERE key=?", (retry, row["key"]))
        else:
            await db.execute("DELETE FROM bot_state WHERE key=?", (row["key"],))
