from __future__ import annotations

import html
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramNotFound
from aiogram.filters.command import CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichBlockButtons,
    InputRichBlockParagraph,
    InputRichBlockTable,
    InputRichMessage,
    Message,
    RichBlockTableCell,
    RichMessageButton,
    RichTextBold,
)

from community_bot.aliases import command_or_alias
from community_bot.bot_identity import is_bot, likely_bot, marked_bots
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.helpers import display_name, resolve_command_target
from community_bot.pet_progress import level
from community_bot.reply_rich import bot_publication

router = Router(name="member_stats")
_GROUP = F.chat.type.in_({"group", "supergroup"})
_MOSCOW = ZoneInfo("Europe/Moscow")
_LIMIT = 10
_METRICS = {"likes": ("❤️", "Лайки"), "messages": ("💬", "Сообщения"), "cookies": ("🍪", "Печеньки")}
_PERIODS = {"неделя": "week", "месяц": "month"}


def _number(value: int) -> str:
    return f"{value:,}".replace(",", " ")


async def _community_chat(message: Message, settings: Settings) -> bool:
    if not settings.community_chat_id or message.chat.id == settings.community_chat_id:
        return True
    await message.answer("Эта команда работает в основном чате Норы.")
    return False


@router.message(command_or_alias("stats"), _GROUP)
async def member_stats(message: Message, db: Database, settings: Settings) -> None:
    if not await _community_chat(message, settings):
        return
    target, args, _ = await resolve_command_target(message, db)
    if not target or args or await is_bot(db, target):
        await message.answer("Ответьте «Нора стата» участнику или напишите «Нора стата @имя».")
        return
    if target.get("profile_private"):
        await message.answer("🔒 Статистика скрыта настройками профиля.")
        return
    uid = int(target["user_id"])
    chat_id = message.chat.id
    history = await db.fetchone(
        """
        SELECT
            (SELECT value FROM bot_state WHERE key = ?) AS joined,
            (SELECT MIN(day) FROM daily_scores WHERE user_id = ? AND chat_id = ?) AS first_message,
            (SELECT message_count FROM user_activity WHERE user_id = ? AND chat_id = ?) AS messages
        """,
        (f"community_join:{chat_id}:{uid}", uid, chat_id, uid, chat_id),
    )
    assert history is not None
    joined, first_message = history["joined"], history["first_message"]
    since = min(day for day in (joined, first_message) if day) if joined or first_message else None
    tenure = "нет данных"
    if since:
        days = max(0, (datetime.now(_MOSCOW).date() - date.fromisoformat(since)).days)
        tenure = f"{_number(days)} дн."
        if since != joined:
            tenure += " с первого учтённого сообщения"
    pet = await db.get_pet(uid, settle=False)
    pet_status = f"{html.escape(str(pet['name']))} · уровень {await level(db, uid) or 1}" if pet else "нет"
    await message.answer(
        f"📊 <b>{html.escape(display_name(target))}</b>\n"
        f"Сообщений в чате · <b>{_number(history['messages'] or 0)}</b>\n"
        f"В сообществе · <b>{tenure}</b>\n"
        f"Питомец · <b>{pet_status}</b>",
        parse_mode="HTML",
    )


def _period(today: date, period: str) -> tuple[date, str]:
    if period == "week":
        return today - timedelta(days=today.weekday()), "за неделю"
    if period == "month":
        return today.replace(day=1), "за месяц"
    return today, "за сегодня"


async def _show_board(message: Message, bot: Bot, db: Database, metric: str, period: str, *, edit=False) -> None:
    icon, heading = _METRICS[metric]
    if metric == "messages":
        today = datetime.now(_MOSCOW).date()
        start, label = _period(today, period)
        span = today.strftime("%d.%m") if start == today else f"{start:%d.%m}–{today:%d.%m}"
        title = f"{icon} Топ сообщений {label} · {span}"
        rows = await db.daily_message_board(start.isoformat(), message.chat.id, limit=-1, through=today.isoformat())
    else:
        title = f"{icon} Топ по {'лайкам' if metric == 'likes' else 'печенькам'}"
        rows = await db.public_profile_board(message.chat.id, metric)
    leaders = _leader_rows(rows, await marked_bots(db) | {str(bot.id)}, metric)
    data = [("№", "Участник", heading)]
    data.extend((str(rank), name, amount) for rank, (name, amount) in enumerate(leaders, 1))
    cells = [
        [RichBlockTableCell(text=text, align=align, valign="middle", is_header=(row == 0))
         for text, align in zip(values, ("right", "left", "right"), strict=True)]
        for row, values in enumerate(data)
    ]
    options = [
        (key, f"{emoji} {label}", f"nora_top:{key}:{period}") for key, (emoji, label) in _METRICS.items()
    ]
    buttons = InputRichBlockButtons(buttons=[
        RichMessageButton(text=label, style="primary" if key == metric else "link", callback_data=callback)
        for key, label, callback in options
    ], align="center")
    content = (InputRichBlockTable(cells=cells, is_bordered=True, is_striped=True, is_compact=True)
               if leaders else InputRichBlockParagraph(text="Пока нет данных."))
    rich = InputRichMessage(blocks=[InputRichBlockParagraph(text=RichTextBold(text=title)), content, buttons],
                            skip_entity_detection=True)
    try:
        if edit and message.rich_message:
            await message.edit_text(parse_mode=None, rich_message=rich)
            return
        if not edit:
            await bot.send_rich_message(
                message.chat.id, rich_message=rich,
                message_thread_id=message.message_thread_id if message.is_topic_message else None,
            )
            return
    except (TelegramBadRequest, TelegramNotFound):
        if edit and message.rich_message:
            raise
    lines = [f"{rank}. {html.escape(name)} · <b>{amount}</b>" for rank, name, amount in data[1:]]
    text = f"<b>{title}</b>\n" + ("\n".join(lines) or "Пока нет данных.")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, style="primary" if key == metric else None, callback_data=callback)
        for key, label, callback in options
    ]])
    with bot_publication():
        if edit:
            await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        else:
            await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


def _leader_rows(rows, known_bots, value):
    public_rows = (row for row in rows if not likely_bot(row) and str(row["user_id"]) not in known_bots)
    result = []
    for row in public_rows:
        name = " ".join(display_name(row).split())
        result.append((name[:47] + "…" if len(name) > 48 else name, _number(row[value])))
        if len(result) == _LIMIT:
            break
    return result


@router.message(command_or_alias("top"), _GROUP)
async def message_top(message: Message, command: CommandObject, bot: Bot, db: Database, settings: Settings) -> None:
    if not await _community_chat(message, settings):
        return
    await _show_board(message, bot, db, "messages", _PERIODS.get((command.args or "").casefold(), "day"))


@router.callback_query(F.data.regexp(r"^nora_top:(likes|messages|cookies):(day|week|month)$"),
                       F.message.chat.type.in_({"group", "supergroup"}))
async def change_top(callback: CallbackQuery, bot: Bot, db: Database, settings: Settings) -> None:
    message = callback.message
    if not isinstance(message, Message) or not callback.data:
        await callback.answer("Таблица больше недоступна.")
        return
    if settings.community_chat_id and message.chat.id != settings.community_chat_id:
        await callback.answer("Таблица доступна в основном чате Норы.")
        return
    _, metric, period = callback.data.split(":")
    try:
        await _show_board(message, bot, db, metric, period, edit=True)
    except (TelegramBadRequest, TelegramNotFound) as error:
        if "message is not modified" not in str(error).casefold():
            await callback.answer("Таблица больше недоступна. Напиши «Нора топ».", show_alert=True)
            return
    await callback.answer()
