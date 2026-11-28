"""Links to the NORA community chat and Mini App."""
from __future__ import annotations

from urllib.parse import urlparse

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _telegram_link(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    return parsed.scheme == "https" and parsed.hostname == "t.me" and bool(parsed.path.strip("/"))


def entry_keyboard(settings, *, bot_username: str = "") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    url = getattr(settings, "community_invite_url", "")
    if _telegram_link(url):
        rows.append([InlineKeyboardButton(text="🚪 Войти в чат НОРЫ", url=url)])
    if bot_username:
        rows.append([InlineKeyboardButton(
            text="🎮 Открыть приложение NORA",
            url=f"https://t.me/{bot_username}?startapp",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_entry(bot, settings, user_id: int) -> None:
    me = await bot.me()
    await bot.send_message(
        user_id,
        "✅ Админ одобрил твою анкету.\n\n"
        "Открой общий чат или вернись в приложение Норы.",
        reply_markup=entry_keyboard(settings, bot_username=me.username or ""),
    )
