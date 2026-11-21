"""Retire Telegram lobby posts without changing the room or its stakes."""
from __future__ import annotations

import asyncio
import json
import logging
import time

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)
from aiogram.types import InputRichBlockParagraph, InputRichMessage

from community_bot.group_message_close import RECORD, without_group_close

TTL = 120
PREFIX = "game-lobby-post:"
ACCEPTED_PREFIX = "game-lobby-accepted:"
ACCEPTED_TEXT = "Игра принята ✅"
ACCEPTED_SECONDS = 2
logger = logging.getLogger(__name__)

# Lobby posts and their confirmation deadlines survive a bot restart in the existing bot_state table.
_DUE = f"""
    WITH posts AS (
        SELECT key,json_extract(value,'$[0]') AS game,json_extract(value,'$[1]') AS room,
               json_extract(value,'$[2]') AS chat,json_extract(value,'$[3]') AS message,
               json_extract(value,'$[4]') AS expires,json_extract(value,'$[5]') AS retry,
               json_extract(value,'$[6]') AS announcement,json_extract(value,'$[7]') AS recipient,
               COALESCE(json_extract(value,'$[8]'),json_extract(value,'$[4]')-{TTL}) AS sent_since,
               json_extract(value,'$[9]') AS delete_after,
               json_extract(value,'$[10]') AS edit_pending,
               '{ACCEPTED_PREFIX}'||json_extract(value,'$[0]')||':'||json_extract(value,'$[1]')||':' AS acceptance_key
        FROM bot_state WHERE key BETWEEN 'game-lobby-post:' AND 'game-lobby-post;' AND json_valid(value)
    ), resolved AS (
        SELECT posts.*,CASE WHEN chat>=0 OR delete_after IS NOT NULL THEN 0
            WHEN edit_pending=1 THEN 1
            WHEN game='roulette' THEN EXISTS (
                SELECT 1 FROM roulette_games WHERE id=posts.room AND status='completed')
            ELSE EXISTS (SELECT 1 FROM bot_state AS accepted
                WHERE accepted.key>acceptance_key AND accepted.key<acceptance_key||';'
                  AND CAST(accepted.value AS REAL) BETWEEN sent_since AND expires
                  AND (announcement=1 OR accepted.key=acceptance_key||recipient OR (
                      recipient IS NULL AND EXISTS (SELECT 1 FROM bot_state AS owner
                          WHERE owner.key='{RECORD}'||chat||':'||message
                            AND owner.value GLOB '* nora:close:*:' ||
                                substr(accepted.key,length(acceptance_key)+1) || ' *'))))
        END AS accepted
        FROM posts WHERE retry<=?
    )
    SELECT * FROM resolved AS posts WHERE CASE WHEN delete_after IS NOT NULL THEN delete_after<=?
        ELSE accepted OR expires<=? OR CASE
        WHEN game IN ('barricade','durak') THEN NOT EXISTS (
            SELECT 1 FROM durak_rooms r WHERE r.id=posts.room AND r.status='waiting')
        WHEN game='mafia' THEN NOT EXISTS (
            SELECT 1 FROM mini_mafia_rooms r WHERE r.id=posts.room AND r.status='lobby')
        WHEN game='sea' THEN NOT EXISTS (
            SELECT 1 FROM mini_sea_rooms r WHERE r.id=posts.room AND r.status='lobby')
        WHEN game='roulette' THEN NOT EXISTS (
            SELECT 1 FROM roulette_games r WHERE r.id=posts.room AND r.status='pending')
        ELSE 0 END END ORDER BY COALESCE(delete_after,expires) LIMIT 20
"""
_UPDATE_POST = """
    UPDATE bot_state SET value=json_set(
        json_insert(value,'$[6]',0,'$[7]',NULL,'$[8]',NULL,'$[9]',NULL,'$[10]',0),
        '$[5]',?,'$[9]',?,'$[10]',?) WHERE key=?
"""


async def remember(db, game, room, chat, sent, *, now=None, announcement=False, recipient=None, sent_since=None):
    message_id = getattr(sent, "message_id", None)
    if type(message_id) is not int or message_id <= 0:
        return
    now = time.time() if now is None else now
    try:
        await db.set_bot_state(
            f"{PREFIX}{chat}:{message_id}",
            json.dumps([game, room, chat, message_id, now + TTL, 0, announcement, recipient, sent_since, None]),
        )
    except Exception:
        logger.exception("Could not track the Telegram lobby post for cleanup")


async def record_acceptance(conn, game, room, uid, now):
    # Record the successful join in its transaction, even if the corresponding send is still in flight.
    await conn.execute("""
        INSERT INTO bot_state(key,value) VALUES(?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (f"{ACCEPTED_PREFIX}{game}:{room}:{uid}", str(now)))


async def purge_acceptances(db, now):
    await db.execute("DELETE FROM bot_state WHERE key BETWEEN ? AND ? AND CAST(value AS REAL)<?",
                     (ACCEPTED_PREFIX, ACCEPTED_PREFIX[:-1] + ";", now - TTL - 30))


async def has_live_announcement(db, game, room, chat):
    prefix = f"{PREFIX}{chat}:"
    return await db.fetchone("""
        SELECT 1 FROM bot_state WHERE key GLOB ? AND json_valid(value)
          AND json_extract(value,'$[0]')=? AND json_extract(value,'$[1]')=?
          AND json_extract(value,'$[4]')>? AND json_extract(value,'$[6]')=1 LIMIT 1
    """, (prefix + "*", game, room, time.time())) is not None


async def _show_acceptance(bot, chat, message):
    try:
        with without_group_close():
            await bot.edit_message_text(chat_id=chat, message_id=message, rich_message=InputRichMessage(
                blocks=[InputRichBlockParagraph(text=ACCEPTED_TEXT)],
            ))
    except TelegramBadRequest as error:
        if "not modified" in str(error).lower():
            return
        with without_group_close():
            try:
                await bot.edit_message_text(chat_id=chat, message_id=message, text=ACCEPTED_TEXT)
            except TelegramBadRequest as fallback:
                if "not modified" not in str(fallback).lower():
                    raise


async def cleanup(db, bot, *, now=None):
    if not bot:
        return
    clock = time.time if now is None else lambda: now
    now = clock()
    for row in await db.fetchall(_DUE, (now, now, now)):
        retry = 0
        try:
            async with asyncio.timeout(4):
                if row["accepted"]:
                    await _show_acceptance(bot, row["chat"], row["message"])
                else:
                    await bot.delete_message(row["chat"], row["message"])
        except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound) as error:
            if "not found" not in str(error).lower():
                logger.warning("Telegram declined a lobby post update (%s)", type(error).__name__)
                if row["accepted"]:
                    await db.execute(_UPDATE_POST, (0, clock(), 0, row["key"]))
                    continue
        except TelegramRetryAfter as error:
            retry = now + error.retry_after
        except (TelegramAPIError, OSError, TimeoutError):
            retry = now + 15
        else:
            if row["accepted"]:
                await db.execute(_UPDATE_POST, (0, clock() + ACCEPTED_SECONDS, 0, row["key"]))
                continue
        if retry:
            await db.execute(_UPDATE_POST, (retry, row["delete_after"], row["accepted"], row["key"]))
        else:
            await db.execute("DELETE FROM bot_state WHERE key=?", (row["key"],))
