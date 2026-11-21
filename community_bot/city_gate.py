"""Require city entry for admitted participants before Telegram commands are available."""
from __future__ import annotations

import html
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from community_bot.access import needs_reapplication, private_allowed
from community_bot.aliases import message_trigger
from community_bot.application_form import validate_city
from community_bot.private_rich import standalone_rich_message
from community_bot.reply_rich import bot_publication

CITY_PROMPT = "📍 Укажи город в ответ на это сообщение. После этого команды Норы снова откроются."
CITY_PROMPT_PREFIX = "Укажи город в ответ на это сообщение."


def _prompt_key(chat_id: int, user_id: int) -> str:
    return f"city_prompt:{chat_id}:{user_id}"


def _is_city_prompt(message: Message) -> bool:
    """Telegram Rich replies do not necessarily populate reply_to_message.text."""
    if CITY_PROMPT_PREFIX in (message.text or message.caption or ""):
        return True
    rich = message.rich_message
    if not rich:
        return False
    # Rich blocks may contain formatted text fragments, not a single text string.
    blocks = rich.model_dump(exclude_none=True).get("blocks", [])
    return CITY_PROMPT_PREFIX in str(blocks)


async def _ask_city(source: Message, db, uid: int) -> None:
    # Use native text for new prompts so Telegram clients reliably attach text in replies.
    # The normal Rich middleware otherwise strips Message.text, making reply recognition fail.
    with standalone_rich_message(), bot_publication():
        sent = await source.reply(CITY_PROMPT)
    if isinstance(sent, Message):
        await db.set_bot_state(_prompt_key(source.chat.id, uid), str(sent.message_id))


async def _can_request_city(db, settings, uid: int, chat_type: str) -> bool:
    if chat_type == "private":
        return await private_allowed(db, settings, uid)
    # Older community members were admitted before applications existed.
    # Their role is "member" (rank 0), so private_allowed() incorrectly excludes them.
    ban = await db.ban_reset_state(uid)
    return not db.ban_is_active(ban) and not await needs_reapplication(db, uid)


class CityGateMiddleware(BaseMiddleware):
    async def __call__(
        self, handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery, data: dict[str, Any],
    ) -> Any:
        actor = event.from_user
        if not actor or actor.is_bot:
            return await handler(event, data)
        db, settings = data.get("db"), data.get("settings")
        if db is None or settings is None:
            return await handler(event, data)
        user = await db.get_user(actor.id)
        if not user or str(user.get("city") or "").strip():
            return await handler(event, data)

        source = event.message if isinstance(event, CallbackQuery) else event
        if not source or not hasattr(source, "chat"):
            return await handler(event, data)
        if not await _can_request_city(db, settings, actor.id, source.chat.type):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            if (event.data or "") in {"ui:close", "flow:cancel"}:
                return await handler(event, data)
            await event.answer("📍 Укажи город в ответ на сообщение Норы.", show_alert=True)
            if isinstance(source, Message):
                await _ask_city(source, db, actor.id)
            return None

        reply = event.reply_to_message
        bot_id = getattr(data.get("bot"), "id", None)
        if (
            event.text and reply and reply.from_user and bot_id is not None
            and reply.from_user.id == bot_id and (
                _is_city_prompt(reply)
                or str(reply.message_id) == await db.get_bot_state(_prompt_key(event.chat.id, actor.id))
            )
        ):
            try:
                city = validate_city(event.text)
            except ValueError as error:
                await event.reply(str(error) + " Ответь на исходное сообщение Норы.")
                return None
            await db.update_profile(actor.id, "city", city)
            await db.set_bot_state(_prompt_key(event.chat.id, actor.id), "")
            await event.reply(
                f"✅ Город сохранён: <b>{html.escape(city)}</b>. Команды Норы снова доступны.",
                parse_mode="HTML",
            )
            return None

        # Let ordinary group conversations continue without repeatedly asking for a city.
        if event.chat.type != "private":
            content = (event.text or "").strip().casefold()
            if not (message_trigger(event) or content.startswith("/") or content.startswith("нора ")):
                return await handler(event, data)
        await _ask_city(event, db, actor.id)
        return None
