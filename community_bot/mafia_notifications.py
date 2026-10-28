"""Actor-bound responses to private Mafia invitation notifications."""

from __future__ import annotations

import hashlib

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from community_bot.access import miniapp_allowed
from community_bot.mafia_api import apply_action

router = Router(name="mini_mafia_invitations")


def invitation_keyboard(room_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Принять", callback_data=f"mfin:y:{room_id}"),
                InlineKeyboardButton(text="Отклонить", callback_data=f"mfin:n:{room_id}"),
            ]
        ]
    )


@router.callback_query(F.data.startswith("mfin:"))
async def respond(callback: CallbackQuery, db, settings):
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer("Ответь на приглашение в личном чате с Норой", show_alert=True)
        return
    if not await miniapp_allowed(db, settings, callback.from_user.id):
        await callback.answer("Сейчас миниапка доступна от роли модератора", show_alert=True)
        return
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3 or parts[1] not in {"y", "n"}:
        await callback.answer("Некорректное приглашение", show_alert=True)
        return
    try:
        _, message, _ = await apply_action(
            db,
            settings,
            callback.from_user.id,
            {
                "action": "respond",
                "room_id": parts[2],
                "accept": parts[1] == "y",
                "request_id": hashlib.sha256(("telegram-" + callback.id).encode()).hexdigest(),
            },
        )
    except ValueError as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer(message, show_alert=True)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass  # A saved response stays successful when the original message is gone.
