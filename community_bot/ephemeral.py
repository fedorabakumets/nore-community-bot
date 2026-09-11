from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from aiogram import BaseMiddleware, Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods.base import TelegramMethod, TelegramType
from aiogram.types import CallbackQuery, Message, TelegramObject

from community_bot.aliases import is_group_command_to_sweep
from community_bot.helpers import BOT_REPLY_TTL, delete_later

GAME_RESULT_TTL = 60.0
_GAME_CALLBACK_PREFIXES = ("game:", "cg:", "roulette:", "g:hide", "crash:")

logger = logging.getLogger(__name__)

_REPLY_TTL: ContextVar[float | None] = ContextVar("group_reply_ttl", default=None)
_PENDING: set[asyncio.Task[Any]] = set()

_HARMLESS_DELETE = (
    "message to delete not found",
    "message identifier is not specified",
    "message can't be found",
)


@contextmanager
def keep_in_chat() -> Iterator[None]:
    """Do not auto-delete bot messages sent inside this block."""
    token = _REPLY_TTL.set(None)
    try:
        yield
    finally:
        _REPLY_TTL.reset(token)


def is_game_callback(data: str | None) -> bool:
    raw = data or ""
    return raw.startswith(_GAME_CALLBACK_PREFIXES)


def expire_game_result(message: Any, ttl: float = GAME_RESULT_TTL) -> None:
    """Keep a finished-game message for a while, then remove it."""
    schedule_group_reply(message, ttl)


def _track(task: asyncio.Task[Any]) -> None:
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)


def schedule_group_reply(result: Any, ttl: float | None = None) -> None:
    delay = BOT_REPLY_TTL if ttl is None else ttl
    if not delay:
        return
    messages: list[Message] = []
    if isinstance(result, Message):
        messages.append(result)
    elif isinstance(result, list):
        messages.extend(item for item in result if isinstance(item, Message))
    for sent in messages:
        if sent.chat.type in {"group", "supergroup"}:
            _track(asyncio.create_task(delete_later(sent, delay)))


def _schedule(result: Any) -> None:
    ttl = _REPLY_TTL.get()
    if not ttl:
        return
    schedule_group_reply(result, ttl)


class EphemeralSendMiddleware(BaseRequestMiddleware):
    """Catch every outgoing Telegram method, including message.answer()/reply() shortcuts."""

    async def __call__(
        self,
        make_request: Callable[[Bot, TelegramMethod[TelegramType]], Awaitable[TelegramType]],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> TelegramType:
        result = await make_request(bot, method)
        _schedule(result)
        if isinstance(result, Message) and result.chat.type in {"group", "supergroup"}:
            db = getattr(bot, "community_db", None)
            if db is not None:
                _track(asyncio.create_task(db.remember_bot_message(result.chat.id, result.message_id)))
        return result


def patch_bot_ephemeral(bot: Bot) -> None:
    if getattr(bot.session, "_nore_ephemeral", False):
        return
    bot.session.middleware.register(EphemeralSendMiddleware())
    bot.session._nore_ephemeral = True  # type: ignore[attr-defined]


async def delete_user_command(event: Message, bot: Any) -> bool:
    """Delete a group command using the live Bot, not Message.bot."""
    try:
        if bot is not None and hasattr(bot, "delete_message"):
            await bot.delete_message(event.chat.id, event.message_id)
        else:
            await event.delete()
        return True
    except (TelegramBadRequest, TelegramForbiddenError) as error:
        detail = str(error).casefold()
        if any(item in detail for item in _HARMLESS_DELETE):
            return True
        logger.warning(
            "Не удалось удалить команду %s в чате %s: %s",
            event.message_id,
            event.chat.id,
            error,
        )
        return False


class GroupHousekeepingMiddleware(BaseMiddleware):
    """Delete user commands in groups immediately, then expire bot replies."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Any],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.chat.type not in {"group", "supergroup"}:
            return await handler(event, data)
        is_cmd = is_group_command_to_sweep(event)
        bot = data.get("bot")
        deleted = False
        if is_cmd:
            deleted = await delete_user_command(event, bot)
        token = _REPLY_TTL.set(BOT_REPLY_TTL if is_cmd else None)
        try:
            return await handler(event, data)
        finally:
            _REPLY_TTL.reset(token)
            if is_cmd and not deleted:
                await delete_user_command(event, bot)


class GroupCallbackEphemeralMiddleware(BaseMiddleware):
    """Expire bot replies that come from inline buttons in the group chat."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Any],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        message = event.message if isinstance(event, CallbackQuery) else None
        if message is None or message.chat.type not in {"group", "supergroup"}:
            return await handler(event, data)
        ttl = None if isinstance(event, CallbackQuery) and is_game_callback(event.data) else BOT_REPLY_TTL
        token = _REPLY_TTL.set(ttl)
        try:
            return await handler(event, data)
        finally:
            _REPLY_TTL.reset(token)
