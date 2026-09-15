from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from community_bot.blocks import replace_block
from community_bot.database import Database
from community_bot.helpers import register_telegram_user
from community_bot.notify import CHANNELS, notices_keyboard, notices_text

router = Router(name="notices")


async def show_notices(callback: CallbackQuery, db: Database) -> None:
    assert callback.message
    user = await register_telegram_user(db, callback.from_user)
    user_id = int(user["user_id"])
    prefs = await db.notify_prefs_map(user_id)
    unread = await db.notify_list_unread(user_id)
    count = await db.notify_unread_count(user_id)
    await replace_block(
        callback.message,
        "notify",
        notices_text(prefs, unread, count),
        parse_mode="HTML",
        reply_markup=notices_keyboard(prefs),
    )


@router.callback_query(F.data == "menu:notices")
async def menu_notices(callback: CallbackQuery, db: Database) -> None:
    if not callback.message:
        return
    await callback.answer()
    await show_notices(callback, db)


@router.callback_query(F.data.startswith("n:ch:"))
async def toggle_channel(callback: CallbackQuery, db: Database) -> None:
    if not callback.message or not callback.data:
        return
    channel = callback.data.rsplit(":", 1)[1]
    if channel not in CHANNELS:
        await callback.answer()
        return
    enabled = await db.notify_toggle_enabled(callback.from_user.id, channel)
    await callback.answer("Включено" if enabled else "Выключено")
    await show_notices(callback, db)


@router.callback_query(F.data.startswith("n:dg:"))
async def toggle_digest(callback: CallbackQuery, db: Database) -> None:
    if not callback.message or not callback.data:
        return
    channel = callback.data.rsplit(":", 1)[1]
    if channel not in CHANNELS:
        await callback.answer()
        return
    digest = await db.notify_toggle_digest(callback.from_user.id, channel)
    await callback.answer("Раз в день" if digest else "Сразу")
    await show_notices(callback, db)


@router.callback_query(F.data == "n:read")
async def mark_read(callback: CallbackQuery, db: Database) -> None:
    if not callback.message:
        return
    await db.notify_mark_read_all(callback.from_user.id)
    await callback.answer("Лента очищена")
    await show_notices(callback, db)
