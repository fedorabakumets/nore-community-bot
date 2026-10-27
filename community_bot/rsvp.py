"""Persistent event posts and serialized, retryable updates to their participant counters."""
from __future__ import annotations

import asyncio
import json
import logging
from weakref import WeakValueDictionary

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from community_bot.database import Database
from community_bot.ephemeral import keep_in_chat
from community_bot.posting import compose_post_markup, post_title

logger = logging.getLogger(__name__)
_LOCKS: WeakValueDictionary[tuple[str, str], asyncio.Lock] = WeakValueDictionary()


def event_lock(db: Database, event_id: str) -> asyncio.Lock:
    key = (str(db.path), event_id)
    lock = _LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[key] = lock
    return lock


async def published_event(callback: CallbackQuery, db: Database, community_chat_id: int):
    event_id = (callback.data or "").split(":", 1)[-1]
    message = callback.message
    if not message or message.chat.id != community_chat_id:
        return None
    event = await db.get_studio_event(event_id)
    if event:
        if int(event["chat_id"]) != message.chat.id or int(event["message_id"]) != message.message_id:
            return None
        return event if event["rsvp_enabled"] and event["status"] == "active" else None
    # Old published posts had no registry. Bind only the original shared button in the community.
    markup = getattr(message, "reply_markup", None)
    if not markup or not any(b.callback_data == callback.data for row in markup.inline_keyboard for b in row):
        return None
    raw = await db.get_bot_state("rsvp_stake") or "0"
    buttons = [
        {"text": b.text, "url": b.url, "style": getattr(b, "style", None) or ""}
        for row in markup.inline_keyboard for b in row if b.url
    ]
    await db.save_studio_event(
        event_id, message.chat.id, message.message_id,
        post_title(message.text or message.caption or "Мероприятие"), buttons,
        int(raw) if raw.isdigit() else 0, 0,
    )
    return await db.get_studio_event(event_id)


async def refresh_event_markup(bot, db: Database, event_id: str) -> bool:
    """Caller holds event_lock. Dirty state survives API errors and process restarts."""
    event = await db.get_studio_event(event_id)
    if not event:
        return False
    from community_bot.event_manager import sync_content

    content_synced = await sync_content(bot, db, event_id)
    offer = await db.get_event_offer(event_id)
    markup = compose_post_markup(
        json.loads(event["buttons_json"]), event_id if event["rsvp_enabled"] else None,
        pay=(offer["button_text"], event_id) if offer else None,
        rsvp_count=await db.event_participant_count(event_id),
    ) if event["status"] == "active" else None
    try:
        # Edits also return Message; group callback TTL must never delete the original event post.
        with keep_in_chat():
            await bot.edit_message_reply_markup(
                chat_id=int(event["chat_id"]), message_id=int(event["message_id"]), reply_markup=markup,
            )
    except TelegramBadRequest as error:
        if "message is not modified" not in error.message.casefold():
            if any(text in error.message.casefold() for text in (
                "message to edit not found", "message can't be edited", "message_id_invalid",
            )):
                await db.execute("UPDATE studio_events SET markup_dirty = -1 WHERE event_id = ?", (event_id,))
            logger.warning("Event counter update deferred: %s (%s)", event_id, type(error).__name__)
            return False
    except TelegramAPIError as error:
        logger.warning("Event counter update deferred: %s (%s)", event_id, type(error).__name__)
        return False
    if content_synced:
        await db.execute("UPDATE studio_events SET markup_dirty = 0 WHERE event_id = ?", (event_id,))
    return content_synced


async def sync_event_counters(bot, db: Database) -> None:
    rows = await db.fetchall("SELECT event_id FROM studio_events WHERE markup_dirty = 1 LIMIT 50")
    for row in rows:
        event_id = str(row["event_id"])
        async with event_lock(db, event_id):
            await refresh_event_markup(bot, db, event_id)


async def event_counters_job(bot, db: Database) -> None:
    while True:
        try:
            await sync_event_counters(bot, db)
        except Exception:
            logger.exception("Event counter synchronization failed")
        await asyncio.sleep(30)


def attendance_action(event_id: str, user_id: int, *, cancel: bool, stake: int = 0) -> InlineKeyboardMarkup:
    from community_bot.keyboards import STYLE_CLOSE, STYLE_GO, ibtn

    prefix = "rsvpc" if cancel else "rsvpj"
    text = "Отменить участие" if cancel else f"Записаться · залог {stake} 🍪"
    return InlineKeyboardMarkup(inline_keyboard=[[
        ibtn(text, f"{prefix}:{event_id}:{user_id}", STYLE_CLOSE if cancel else STYLE_GO),
    ]])
