"""One presentation policy for built-in inline menus; callback actions stay intact."""
from __future__ import annotations

import re

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

_BACK = re.compile(r"\b(назад|закрыть|отмена|отменить|вернуться)\b", re.I)
_NEGATIVE = re.compile(
    r"\b(нет|не надо|отказаться|отклонить|удалить|сбросить|забанить|заблокировать|выключить|отключить|мут)\b", re.I,
)
_POSITIVE = re.compile(
    r"\b(да|подтвердить|одобрить|принять|оплатить|купить|записаться|я буду|участвовать|"
    r"начать|старт|играть|накормить|напоить|получить|забрать|сохранить|включить|"
    r"начислить|перевести|отправить|добавить|создать|проверить|открыть чат)\b", re.I,
)


def button_style(button: InlineKeyboardButton) -> str | None:
    text = button.text.strip()
    if _BACK.search(text) or (text.startswith(("←", "↩")) and len(text) > 2):
        return "danger"
    action = button.callback_data or ""
    if action.startswith(("menu:", "game:pick:", "cg:pick:", "sg:pick:", "shop:cat:")):
        return None
    if "снять мут" in text.casefold() or "заполнить анкету" in text.casefold():
        return "success"
    if _NEGATIVE.search(text) or "−реп" in text or "-реп" in text or text.startswith(("❌", "🗑", "👎")):
        return "danger"
    if _POSITIVE.search(text) or "+реп" in text or text.startswith(("✅", "👍")):
        return "success"
    # Existing green/red toggles express enabled/disabled state rather than navigation.
    if action.startswith(("admin:feature:", "admin:roletog:", "n:ch:", "n:dg:")):
        return getattr(button, "style", None)
    return None


def style_menu(markup: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]
    # User-authored post links and shared RSVP posts keep their explicit publication styling.
    if not callbacks or any(action.startswith(("rsvp:", "evpay:")) for action in callbacks):
        return markup
    rows = [[button.model_copy(update={"style": button_style(button)}) for button in row]
            for row in markup.inline_keyboard]
    return markup.model_copy(update={"inline_keyboard": rows})
