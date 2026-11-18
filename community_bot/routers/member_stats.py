from __future__ import annotations

import html
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramNotFound
from aiogram.filters.command import CommandObject
from aiogram.types import (
    InputRichBlockParagraph,
    InputRichBlockTable,
    InputRichMessage,
    Message,
    RichBlockTableCell,
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
    if period == "неделя":
        return today - timedelta(days=today.weekday()), "за неделю"
    if period == "месяц":
        return today.replace(day=1), "за месяц"
    return today, "за сегодня"


async def _send_board(message: Message, bot: Bot, title: str, heading: str, rows: list[tuple[str, str]]) -> None:
    if not rows:
        await message.answer(f"{title}\nПока нет данных.")
        return
    data = [("№", "Участник", heading)]
    data.extend((str(rank), name, amount) for rank, (name, amount) in enumerate(rows, 1))
    cells = [
        [RichBlockTableCell(text=text, align=align, valign="middle", is_header=(row == 0))
         for text, align in zip(values, ("right", "left", "right"), strict=True)]
        for row, values in enumerate(data)
    ]
    try:
        await bot.send_rich_message(
            message.chat.id,
            message_thread_id=message.message_thread_id if message.is_topic_message else None,
            rich_message=InputRichMessage(blocks=[
                InputRichBlockParagraph(text=RichTextBold(text=title)),
                InputRichBlockTable(cells=cells, is_bordered=True, is_striped=True, is_compact=True),
            ]),
        )
    except (TelegramBadRequest, TelegramNotFound):
        lines = [f"{rank}. {html.escape(name)} · <b>{amount}</b>" for rank, name, amount in data[1:]]
        with bot_publication():
            await message.answer(f"<b>{title}</b>\n{heading}\n" + "\n".join(lines), parse_mode="HTML")


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
    today = datetime.now(_MOSCOW).date()
    start, label = _period(today, (command.args or "").casefold())
    rows = await db.daily_message_board(start.isoformat(), message.chat.id, limit=-1, through=today.isoformat())
    leaders = _leader_rows(rows, await marked_bots(db) | {str(bot.id)}, "messages")
    span = today.strftime("%d.%m") if start == today else f"{start:%d.%m}–{today:%d.%m}"
    await _send_board(message, bot, f"📊 Топ сообщений {label} · {span}", "Сообщения", leaders)


@router.message(command_or_alias("millionaires"), _GROUP)
async def cookie_top(message: Message, bot: Bot, db: Database, settings: Settings) -> None:
    if not await _community_chat(message, settings):
        return
    rows = await db.fetchall(
        """
        SELECT u.user_id, u.profile_name, u.telegram_name, u.username, u.cookies
        FROM users u
        WHERE u.user_id > 0 AND u.cookies > 0 AND u.profile_private = 0
          AND (EXISTS (
            SELECT 1 FROM user_activity a WHERE a.user_id = u.user_id AND a.chat_id = ?
          ) OR EXISTS (
            SELECT 1 FROM bot_state s WHERE s.key = ? || u.user_id
          ))
        ORDER BY u.cookies DESC, u.user_id ASC
        """,
        (message.chat.id, f"community_join:{message.chat.id}:"),
    )
    leaders = _leader_rows(rows, await marked_bots(db) | {str(bot.id)}, "cookies")
    await _send_board(message, bot, "🍪 Миллионеры Норы", "Печеньки", leaders)
