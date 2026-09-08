from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message, TelegramObject

from community_bot.aliases import is_command_message
from community_bot.helpers import BOT_REPLY_TTL, delete_later

logger = logging.getLogger(__name__)

_REPLY_TTL: ContextVar[float | None] = ContextVar("group_reply_ttl", default=None)

_SEND_METHODS = (
    "send_message",
    "send_photo",
    "send_video",
    "send_animation",
    "send_document",
    "send_audio",
    "send_voice",
    "send_video_note",
    "send_sticker",
    "send_dice",
    "send_media_group",
    "copy_message",
)


@contextmanager
def keep_in_chat() -> Iterator[None]:
    """Do not auto-delete bot messages sent inside this block."""
    token = _REPLY_TTL.set(None)
    try:
        yield
    finally:
        _REPLY_TTL.reset(token)


def _schedule(result: Any) -> None:
    ttl = _REPLY_TTL.get()
    if not ttl:
        return
    messages: list[Message] = []
    if isinstance(result, Message):
        messages.append(result)
    elif isinstance(result, list):
        messages.extend(item for item in result if isinstance(item, Message))
    for sent in messages:
        if sent.chat.type in {"group", "supergroup"}:
            asyncio.create_task(delete_later(sent, ttl))


def patch_bot_ephemeral(bot: Bot) -> None:
    for name in _SEND_METHODS:
        original: Callable[..., Any] = getattr(bot, name)

        async def wrapped(*args: Any, __orig: Callable[..., Any] = original, **kwargs: Any) -> Any:
            result = await __orig(*args, **kwargs)
            _schedule(result)
            return result

        setattr(bot, name, wrapped)


class GroupHousekeepingMiddleware(BaseMiddleware):
    """Delete user commands in groups and expire bot replies to those commands."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Any],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.chat.type not in {"group", "supergroup"}:
            return await handler(event, data)
        text = event.text or event.caption or ""
        is_cmd = is_command_message(text)
        token = _REPLY_TTL.set(BOT_REPLY_TTL if is_cmd else None)
        try:
            return await handler(event, data)
        finally:
            _REPLY_TTL.reset(token)
            if is_cmd:
                try:
                    await event.delete()
                except (TelegramBadRequest, TelegramForbiddenError) as error:
                    logger.warning("Не удалось удалить команду в чате %s: %s", event.chat.id, error)
