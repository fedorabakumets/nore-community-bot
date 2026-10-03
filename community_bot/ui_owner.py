from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from community_bot.config import Settings
from community_bot.database import Database
from community_bot.domain import ROLE_LEVELS
from community_bot.helpers import rank_of_user

# Callbacks that drive a personal inline UI in a group chat.
# Join/play actions of shared game lobbies are intentionally absent.
OWNED_PREFIXES = (
    "shop:",
    "pet:",
    "ashop:",
    "menu:",
    "wallet:",
    "p:",
    "ui:close",
    "n:",
    "game:pick:",
    "game:rules:",
    "cg:pick:",
    "cg:home",
    "cg:new:",
    "sg:pick:",
)


def is_owned_callback(data: str | None) -> bool:
    raw = data or ""
    if raw.startswith("profile_action:") or raw.startswith("profile_transfer:"):
        return False
    if raw.startswith("profile:"):
        return True
    return any(raw == prefix or raw.startswith(prefix) for prefix in OWNED_PREFIXES)


async def bind_ui_owner(db: Database, message: Message | None, user_id: int, kind: str = "ui") -> None:
    if message is None or not getattr(message.chat, "type", None):
        return
    if message.chat.type not in {"group", "supergroup"}:
        return
    await db.bind_ui_owner(int(message.chat.id), int(message.message_id), int(user_id), kind)


class UiOwnerMiddleware(BaseMiddleware):
    """In groups, personal UIs (shop/profile/pet/games hub) belong to the opener + staff."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, CallbackQuery) or not event.message:
            return await handler(event, data)
        if event.message.chat.type not in {"group", "supergroup"}:
            return await handler(event, data)
        if not is_owned_callback(event.data):
            return await handler(event, data)
        db: Database | None = data.get("db")
        settings: Settings | None = data.get("settings")
        if db is None or settings is None or not event.from_user:
            return await handler(event, data)
        owner_id = await db.get_ui_owner(int(event.message.chat.id), int(event.message.message_id))
        if owner_id is None:
            return await handler(event, data)
        actor_id = int(event.from_user.id)
        if actor_id == owner_id:
            return await handler(event, data)
        rank = await rank_of_user(db, settings, actor_id)
        if rank >= ROLE_LEVELS["moderator"]:
            return await handler(event, data)
        await event.answer("Это меню открыл другой человек.", show_alert=True)
        return None
