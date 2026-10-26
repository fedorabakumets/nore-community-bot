"""Context stickers follow successful posts; their failure never blocks publication."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from weakref import WeakValueDictionary

from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from community_bot.ephemeral import keep_in_chat

STICKER_PACK_NAME = "vstickere"
STICKER_PACK_URL = f"https://t.me/addstickers/{STICKER_PACK_NAME}"
_ASSETS = Path(__file__).resolve().parent.parent / "assets" / "stickers"
_KINDS = frozenset({"update", "event", "morning"})
_LOCKS: WeakValueDictionary[tuple[str, str], asyncio.Lock] = WeakValueDictionary()
logger = logging.getLogger(__name__)


async def verify_sticker_pack(bot) -> bool:
    try:
        pack = await bot.get_sticker_set(name=STICKER_PACK_NAME)
        logger.info("Sticker pack connected: name=%s stickers=%s", STICKER_PACK_NAME, len(pack.stickers))
        return bool(pack.stickers)
    except Exception as error:
        logger.warning("Sticker pack check unavailable: %s", type(error).__name__)
        return False


def _lock(db, key: str) -> asyncio.Lock:
    lock_key = (str(getattr(db, "path", id(db))), key)
    lock = _LOCKS.get(lock_key)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[lock_key] = lock
    return lock


async def send_context_sticker(bot, db, chat_id: int, kind: str, source_message_id: int) -> bool:
    """Return True when delivered/already delivered; False means a later retry is safe.

    Deduplication survives restarts and serializes concurrent handlers in the bot's
    single process. Telegram has no idempotency key: a crash after Telegram accepts
    the sticker but before SQLite records it can still produce a duplicate on retry.
    """
    if kind not in _KINDS or not chat_id or source_message_id <= 0:
        return False
    key = f"context_sticker:{kind}:{chat_id}:{source_message_id}"
    pending_key = f"context_sticker_pending:{kind}:{chat_id}:{source_message_id}"
    try:
        async with _lock(db, key):
            if await db.get_bot_state(key):
                if await db.get_bot_state(pending_key):
                    await db.set_bot_state(pending_key, "")
                return True
            await db.set_bot_state(pending_key, json.dumps({
                "kind": kind, "chat_id": chat_id, "source_message_id": source_message_id, "attempted_at": time.time(),
            }))
            path = _ASSETS / f"{kind}.webp"
            if not path.is_file():
                logger.warning("Context sticker missing: %s", kind)
                return False
            with keep_in_chat():
                sent = await bot.send_sticker(
                    chat_id=chat_id, sticker=FSInputFile(path), disable_notification=True,
                )
            await db.set_bot_state(key, str(sent.message_id))
            await db.set_bot_state(pending_key, "")
            logger.info("Context sticker delivered: kind=%s source=%s", kind, source_message_id)
            return True
    except Exception as error:
        # Do not print Telegram request objects or credentials in errors.
        logger.warning("Context sticker deferred: kind=%s cause=%s", kind, type(error).__name__)
        return False


async def retry_pending_stickers(bot, db) -> None:
    """Retry oldest attempts first so one permanently failing post cannot starve others."""
    rows = await db.fetchall(
        """SELECT key, value FROM bot_state
        WHERE key LIKE 'context_sticker_pending:%' AND value != '' AND json_valid(value)
        ORDER BY COALESCE(json_extract(value, '$.attempted_at'), 0), key LIMIT 20""",
    )
    for row in rows:
        try:
            data = json.loads(row["value"])
            kind = data["kind"]
            chat_id = int(data["chat_id"])
            source_message_id = int(data["source_message_id"])
            expected_key = f"context_sticker_pending:{kind}:{chat_id}:{source_message_id}"
            if row["key"] != expected_key or kind not in _KINDS or not chat_id or source_message_id <= 0:
                raise ValueError("invalid queued sticker metadata")
        except (KeyError, TypeError, ValueError):
            logger.warning("Invalid pending sticker discarded")
            await db.set_bot_state(row["key"], "")
            continue
        await send_context_sticker(bot, db, chat_id, kind, source_message_id)


async def sticker_delivery_job(bot, db) -> None:
    while True:
        try:
            await retry_pending_stickers(bot, db)
        except Exception as error:
            logger.warning("Sticker retry temporarily unavailable: %s", type(error).__name__)
        await asyncio.sleep(30)


async def send_pack_invitation(message, bot) -> bool:
    """An explicit user request opens the existing pack and shows one of its stickers."""
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Добавить стикеры Норы", url=STICKER_PACK_URL),
    ]])
    try:
        with keep_in_chat():
            await message.answer(
                "😎 <b>Бабушка теперь и в стикерах</b>\n\n"
                "Когда слов уже мало: «Ну погоди», «Я всё» или просто «Это база». "
                "Забирайте набор и отправляйте бабушку в свои чаты.",
                parse_mode="HTML", reply_markup=markup,
            )
    except Exception as error:
        logger.warning("Sticker invitation failed: %s", type(error).__name__)
        return False
    try:
        pack = await bot.get_sticker_set(name=STICKER_PACK_NAME)
        if pack.stickers:
            with keep_in_chat():
                await bot.send_sticker(
                    chat_id=message.chat.id, sticker=pack.stickers[0].file_id, disable_notification=True,
                )
    except Exception as error:
        logger.warning("Sticker pack preview unavailable: %s", type(error).__name__)
    return True
