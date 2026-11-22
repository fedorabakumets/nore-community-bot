"""Require a verified city for admitted members, with Rich inline selection."""
from __future__ import annotations

import html
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from community_bot.access import needs_reapplication, private_allowed
from community_bot.aliases import message_trigger
from community_bot.city_lookup import popular_cities, resolve_city_id, search_cities

CITY_PROMPT_PREFIX = "Укажи город в ответ на это сообщение."
CITY_PROMPT = (
    "📍 " + CITY_PROMPT_PREFIX + "\n"
    "Ниже можно сразу выбрать популярный город. "
    "Для другого города напиши его название в ответ: Нора предложит реальные варианты."
)


def _prompt_key(chat_id: int, user_id: int) -> str:
    return f"city_prompt:{chat_id}:{user_id}"


def _is_city_prompt(message: Message) -> bool:
    """Telegram Rich replies do not necessarily populate reply_to_message.text."""
    if CITY_PROMPT_PREFIX in (message.text or message.caption or ""):
        return True
    rich = message.rich_message
    if not rich:
        return False
    blocks = rich.model_dump(exclude_none=True).get("blocks", [])
    return CITY_PROMPT_PREFIX in str(blocks)


def city_keyboard(user_id: int, *, page: int = 0, suggestions: list[dict] | None = None,
                  prefix: str = 'city'):
    if suggestions is None:
        options, pages = popular_cities(page)
        page = min(max(0, page), pages - 1)
    else:
        options, pages = suggestions[:12], 0
    rows = [
        [InlineKeyboardButton(
            text="📍 " + item["name"] + ((" · " + item["region"]) if item.get("region") else ""),
            callback_data=f'{prefix}:pick:{user_id}:{item["id"]}',
        )]
        for item in options
    ]
    if pages:
        rows.append([
            InlineKeyboardButton(text="◀", callback_data=f"{prefix}:page:{user_id}:{(page - 1) % pages}"),
            InlineKeyboardButton(text=f"🌍 Все города · {page + 1}/{pages}",
                                 callback_data=f"{prefix}:page:{user_id}:{(page + 1) % pages}"),
            InlineKeyboardButton(text="▶", callback_data=f"{prefix}:page:{user_id}:{(page + 1) % pages}"),
        ])
    else:
        rows.append([InlineKeyboardButton(text="🌍 Все популярные города",
                                          callback_data=f"{prefix}:page:{user_id}:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _ask_city(source: Message, db, uid: int) -> None:
    # A reply to this Rich message can be located through its blocks or stored ID.
    sent = await source.reply(CITY_PROMPT, reply_markup=city_keyboard(uid))
    if isinstance(sent, Message):
        await db.set_bot_state(_prompt_key(source.chat.id, uid), str(sent.message_id))


async def _can_request_city(db, settings, uid: int, chat_type: str) -> bool:
    if chat_type == "private":
        return await private_allowed(db, settings, uid)
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
        action = (event.data or "") if isinstance(event, CallbackQuery) else ""

        if user and str(user.get("city") or "").strip():
            if action.startswith("city:"):
                await event.answer("Город уже указан.")
                return None
            return await handler(event, data)
        if not user:
            return await handler(event, data)
        if action.startswith('appcity:'):
            return await handler(event, data)

        source = event.message if isinstance(event, CallbackQuery) else event
        if not isinstance(source, Message):
            return await handler(event, data)
        if not await _can_request_city(db, settings, actor.id, source.chat.type):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            if action in {"ui:close", "flow:cancel"}:
                return await handler(event, data)
            if action.startswith("city:"):
                parts = action.split(":")
                try:
                    if len(parts) < 4 or int(parts[2]) != actor.id:
                        raise ValueError
                except ValueError:
                    await event.answer("Выбрать город может только владелец профиля.", show_alert=True)
                    return None
                latest = await db.get_bot_state(_prompt_key(source.chat.id, actor.id))
                if str(source.message_id) != str(latest):
                    await event.answer("Выбери город из последнего сообщения Норы.", show_alert=True)
                    return None
                if parts[1] == "page" and len(parts) == 4:
                    try:
                        page = int(parts[3])
                    except ValueError:
                        page = 0
                    await source.edit_text(CITY_PROMPT, reply_markup=city_keyboard(actor.id, page=page))
                    await event.answer()
                    return None
                if parts[1] == "pick" and len(parts) == 5:
                    token = parts[3] + ":" + parts[4]
                    try:
                        city = await resolve_city_id(token)
                    except ValueError as error:
                        await event.answer(str(error), show_alert=True)
                        return None
                    await db.update_profile(actor.id, "city", city)
                    await db.set_bot_state(_prompt_key(source.chat.id, actor.id), "")
                    await source.edit_text(
                        f"✅ Город сохранён: <b>{html.escape(city)}</b>. Команды Норы доступны.",
                        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[]),
                    )
                    await event.answer("Город сохранён")
                    return None
                await event.answer("Устаревшая кнопка.", show_alert=True)
                return None
            await event.answer("📍 Сначала выбери город.", show_alert=True)
            await _ask_city(source, db, actor.id)
            return None

        reply = event.reply_to_message
        bot_id = getattr(data.get("bot"), "id", None)
        if (
            event.text and reply and reply.from_user and bot_id is not None
            and reply.from_user.id == bot_id and (
                _is_city_prompt(reply)
                or str(reply.message_id) == str(await db.get_bot_state(_prompt_key(event.chat.id, actor.id)))
            )
        ):
            try:
                suggestions = await search_cities(event.text)
            except ValueError as error:
                await event.reply(str(error) + " Ответь на исходное сообщение Норы.")
                return None
            if not suggestions:
                await event.reply("Город не найден. Попробуй другое название в ответ.")
                return None
            text = CITY_PROMPT + "\n\nВыбери найденный город (регион указан, если названия совпадают):"
            sent = await event.reply(text, reply_markup=city_keyboard(actor.id, suggestions=suggestions))
            if isinstance(sent, Message):
                await db.set_bot_state(_prompt_key(event.chat.id, actor.id), str(sent.message_id))
            return None

        # Don't interrupt ordinary conversation, only commands and bot mentions.
        if source.chat.type != "private":
            content = (event.text or "").strip().casefold()
            if not (message_trigger(event) or content.startswith("/") or content.startswith("нора ")):
                return await handler(event, data)
        await _ask_city(event, db, actor.id)
        return None
