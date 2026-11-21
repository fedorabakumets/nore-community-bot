"""Require city entry for admitted members before Telegram commands become available."""
from __future__ import annotations

import html
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from community_bot.access import private_allowed
from community_bot.aliases import message_trigger
from community_bot.application_form import validate_city

CITY_PROMPT = "📍 Укажи город в ответ на это сообщение. После этого команды Норы снова откроются."


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
        # Preserve bans and let unapproved users complete their admission forms.
        if not await private_allowed(db, settings, actor.id):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            if (event.data or "") in {"ui:close", "flow:cancel"}:
                return await handler(event, data)
            await event.answer("📍 Укажи город в ответ на сообщение Норы.", show_alert=True)
            if isinstance(event.message, Message):
                await event.message.answer(CITY_PROMPT)
            return None

        reply = event.reply_to_message
        bot_id = getattr(data.get("bot"), "id", None)
        if (
            event.text and reply and reply.from_user and bot_id is not None
            and reply.from_user.id == bot_id and (reply.text or "").startswith(CITY_PROMPT)
        ):
            try:
                city = validate_city(event.text)
            except ValueError as error:
                await event.reply(str(error) + " Ответь на исходное сообщение Норы.")
                return None
            await db.update_profile(actor.id, "city", city)
            await event.reply(
                f"✅ Город сохранён: <b>{html.escape(city)}</b>. Команды Норы снова доступны.",
                parse_mode="HTML",
            )
            return None

        # Avoid flooding group conversations with prompts on ordinary messages.
        if event.chat.type != "private":
            content = (event.text or "").strip().casefold()
            if not (message_trigger(event) or content.startswith("/") or content.startswith("нора ")):
                return await handler(event, data)
        await event.reply(CITY_PROMPT)
        return None
