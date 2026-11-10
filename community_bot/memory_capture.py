from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from community_bot.chat_memory import clean_author_name, clean_stored_text
from community_bot.config import Settings
from community_bot.database import Database

logger = logging.getLogger(__name__)
_CLEANUP_INTERVAL = 3600.0


def _eligible(message: Message, settings: Settings) -> bool:
    return bool(
        settings.community_chat_id
        and message.chat.id == settings.community_chat_id
        and message.chat.type in {"group", "supergroup"}
        and message.from_user and not message.from_user.is_bot
        and not message.sender_chat and not message.forward_origin and not message.via_bot
        and clean_stored_text(message.text)
    )


class CommunityMemoryMiddleware(BaseMiddleware):
    """Save community text locally; never calls DeepSeek and never logs message text."""

    def __init__(self) -> None:
        self._last_cleanup = 0.0

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        db = data.get("db")
        settings = data.get("settings")
        if isinstance(event, Message) and isinstance(db, Database) and isinstance(settings, Settings):
            try:
                if getattr(event, "edit_date", None):
                    if settings.community_chat_id and event.chat.id == settings.community_chat_id and event.text:
                        await db.update_community_message(event.chat.id, event.message_id, event.text)
                elif _eligible(event, settings):
                    assert event.from_user is not None
                    await db.save_community_message(
                        event.chat.id, event.message_id, event.from_user.id,
                        clean_author_name(event.from_user.full_name), event.text or "",
                        event.date.isoformat(),
                        event.message_thread_id if event.is_topic_message else None,
                    )
                    await self._maybe_cleanup(db)
            except Exception:
                logger.warning("Не удалось сохранить сообщение в память сообщества")
        return await handler(event, data)

    async def _maybe_cleanup(self, db: Database) -> None:
        now = time.monotonic()
        if now - self._last_cleanup < _CLEANUP_INTERVAL:
            return
        self._last_cleanup = now
        await db.cleanup_community_messages()
