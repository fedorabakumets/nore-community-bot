from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

NAVIGATION_ACTIONS = {"wallet:home", "wallet:back", "shop:home", "shop:close", "ui:close", "flow:cancel"}


class CabinetNavigationMiddleware(BaseMiddleware):
    """Leaving a personal flow also cancels its pending purchase authorization."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)
        action = event.data or ""
        if not action.startswith("menu:") and action not in NAVIGATION_ACTIONS:
            return await handler(event, data)
        db, state = data.get("db"), data.get("state")
        if db is None or state is None:
            return await handler(event, data)
        current = await state.get_data()
        tokens = {current["purchase_intent"]} if current.get("purchase_intent") else set()
        markup = getattr(event.message, "reply_markup", None)
        if markup:
            for row in markup.inline_keyboard:
                for button in row:
                    callback_data = button.callback_data or ""
                    for prefix in ("shop:pay:", "wallet:loan:yes:", "wallet:repay:yes:"):
                        if callback_data.startswith(prefix):
                            tokens.add(callback_data.removeprefix(prefix))
        for token in tokens:
            await db.cancel_wallet_intent(event.from_user.id, token)
        if action == "flow:cancel":
            # Existing flow handlers clear state and restore the reply keyboard themselves.
            return await handler(event, data)
        ticket_id = current.get("ticket_id")
        if ticket_id and action != "menu:question":
            ticket = await db.fetchone("SELECT user_id FROM tickets WHERE id = ?", (ticket_id,))
            if ticket and int(ticket["user_id"]) == event.from_user.id:
                await db.close_ticket(int(ticket_id))
        await state.clear()
        return await handler(event, data)
