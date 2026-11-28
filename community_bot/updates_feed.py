"""Separate NORA updates feed; never routes activity into the main community."""
from __future__ import annotations

import asyncio
import logging
import os

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InputRichMessage

from community_bot.ephemeral import keep_in_chat
from community_bot.group_message_close import without_group_close

logger = logging.getLogger(__name__)
_lock = asyncio.Lock()

# Only the repository-controlled release list can publish. Keep IDs immutable.
POSTS = (
    {
        "id": "welcome-20261128",
        "revision": "1",
        "pin": True,
        "blocks": [
            {"type": "heading", "text": "НОРА / ОБНОВЛЕНИЯ", "size": 1},
            {"type": "paragraph", "text": "У Норы теперь есть отдельное место для новостей."},
            {"type": "blockquote", "blocks": [
                {"type": "paragraph", "text": "Здесь будут обновления, новые идеи и планы развития Норы."},
            ]},
            {"type": "paragraph", "text": "Добро пожаловать ❤️"},
        ],
    },
)


def target():
    value = os.getenv("UPDATES_CHAT_ID", "@noranoranoranoranora").strip()
    if value.startswith("@") and value[1:].isascii() and value[1:].replace("_", "").isalnum():
        return value
    if value.startswith("-100") and value[1:].isdigit():
        return int(value)
    return None


def is_updates_chat(chat):
    destination = target()
    if chat.type != "supergroup" or destination is None:
        return False
    if isinstance(destination, int):
        return chat.id == destination
    return ("@" + (getattr(chat, "username", None) or "")).casefold() == destination.casefold()


def is_production():
    return (
        os.getenv("RAILWAY_SERVICE_ID") == "dae67cd6-25ee-4710-b11a-7c8f6801e35b"
        and os.getenv("RAILWAY_ENVIRONMENT_ID") == "136c278e-4a0f-4b54-986c-8b64f9d69ad6"
    )


async def publish_post(db, bot, chat_id, post):
    key = f"updates_feed:{chat_id}:{post['id']}"
    message_id = await db.get_bot_state(key)
    revision_key = key + ":revision"
    rich = InputRichMessage(blocks=post["blocks"], skip_entity_detection=True)
    if not message_id:
        if await db.get_bot_state(key + ":sending"):
            logger.warning("Updates feed delivery uncertain; duplicate suppressed: %s", post["id"])
            return
        await db.set_bot_state(key + ":sending", "1")
        try:
            with keep_in_chat(), without_group_close():
                sent = await bot.send_rich_message(chat_id, rich_message=rich)
        except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter):
            await db.execute("DELETE FROM bot_state WHERE key=?", (key + ":sending",))
            raise
        message_id = str(sent.message_id)
        await db.set_bot_state(key, message_id)
        await db.set_bot_state(revision_key, post["revision"])
    elif await db.get_bot_state(revision_key) != post["revision"]:
        try:
            with keep_in_chat(), without_group_close():
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=int(message_id), rich_message=rich, parse_mode=None,
                )
        except TelegramBadRequest as error:
            if "not modified" not in error.message.casefold():
                raise
        await db.set_bot_state(revision_key, post["revision"])
    if post.get("pin") and await db.get_bot_state(key + ":pinned") != "1":
        await bot.pin_chat_message(chat_id, int(message_id), disable_notification=True)
        await db.set_bot_state(key + ":pinned", "1")


async def run(db, settings, bot):
    """Publish configured releases only in the separate, verified production group."""
    destination = target()
    if not is_production() or not destination or not settings.community_chat_id:
        return
    async with _lock:
        try:
            chat = await bot.get_chat(destination)
            if not is_updates_chat(chat) or chat.id == settings.community_chat_id:
                logger.warning("Updates feed target is not a separate configured supergroup")
                return
            for post in POSTS:
                try:
                    await publish_post(db, bot, chat.id, post)
                except Exception:
                    logger.exception("Updates feed post not confirmed: %s", post["id"])
        except Exception:
            logger.exception("Updates feed chat unavailable")
