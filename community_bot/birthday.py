"""Birthday greetings and once-only cookie gifts through the shared wallet."""

from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputRichBlockBlockQuotation,
    InputRichBlockButtons,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichMessage,
    RichMessageButton,
    RichTextBold,
    RichTextTextMention,
    User,
)

from community_bot.database import Database, utcnow

logger = logging.getLogger(__name__)
router = Router(name="birthday")
GIFT_AMOUNT = 500
GIFT_ART = Path(__file__).parent.parent / "assets" / "birthday" / "gift.png"
SPECIAL_DAY = "2026-11-02"
SPECIAL_USERNAME = "Caramel_kka"
OWNER_GIFT = "2026-11-02-owner"


def gift_key(user_id: int, day: str) -> str:
    return f"birthday_gift:{user_id}:{day}"


async def pending_gift(db: Database, user_id: int) -> str | None:
    row = await db.fetchone(
        "SELECT key FROM bot_state WHERE key LIKE ? AND value='pending' ORDER BY key DESC LIMIT 1",
        (f"birthday_gift:{user_id}:%",),
    )
    return str(row["key"]).rsplit(":", 1)[1] if row else None


async def offer_gift(db: Database, user_id: int, day: str, *, preview: bool = False) -> bool:
    """Record the offer and Mini App notice together; retries cannot create another gift."""
    now = utcnow()
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cursor = await conn.execute(
            "INSERT OR IGNORE INTO bot_state(key,value) VALUES(?, 'pending')",
            (gift_key(user_id, day),),
        )
        if cursor.rowcount != 1:
            await conn.rollback()
            return False
        text = (
            "🎁 Подарок НОРЫ для проверки: 500 🍪. Нажми «Получить подарок» в уведомлениях."
            if preview else
            "🎂 С днём рождения! От НОРЫ тебя ждут 500 🍪. Нажми «Получить подарок» в уведомлениях."
        )
        await conn.execute(
            "INSERT INTO notify_inbox(user_id,channel,text,created_at,read,delivered) "
            "VALUES(?, 'birthday', ?, ?, 0, 0)",
            (user_id, text, now),
        )
        await conn.commit()
    return True


async def claim_gift(db: Database, user_id: int, day: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:-owner)?", day):
        return False
    now = utcnow()
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cursor = await conn.execute(
            "UPDATE bot_state SET value='claimed' WHERE key=? AND value='pending'",
            (gift_key(user_id, day),),
        )
        if cursor.rowcount != 1:
            await conn.rollback()
            return False
        await conn.execute(
            "UPDATE users SET cookies=cookies+?, updated_at=? WHERE user_id=?",
            (GIFT_AMOUNT, now, user_id),
        )
        await conn.execute(
            "INSERT INTO transactions(user_id,amount,kind,details,created_at) VALUES(?,?,?,?,?)",
            (user_id, GIFT_AMOUNT, "birthday_gift", day, now),
        )
        await conn.commit()
    return True


def gift_keyboard(day: str, recipient: str | None = None) -> InlineKeyboardMarkup:
    action = f"birthday:claim:{day}" + (f":{recipient}" if recipient else "")
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎁 Получить подарок · 500 🍪", callback_data=action),
    ]])


def rich_greeting(user: dict, day: str) -> InputRichMessage:
    uid = int(user.get("user_id") or 0)
    name = str(user.get("profile_name") or user.get("telegram_name") or "Именинник")
    recipient = str(uid) if uid else "u" + str(user["username"])
    mention = (RichTextTextMention(text=RichTextBold(text=name),
                                  user=User(id=uid, is_bot=False, first_name=name))
               if uid else RichTextBold(text="@" + str(user["username"])))
    return InputRichMessage(blocks=[
        InputRichBlockPhoto(photo=InputMediaPhoto(media=FSInputFile(GIFT_ART))),
        InputRichBlockParagraph(text=["🎂 ", mention, ", с днём рождения! 🎉"]),
        InputRichBlockParagraph(text=["Поздравляем тебя от всей команды ", RichTextBold(text="НОРЫ"),
                                      " с этим днём! Желаем тебе ", RichTextBold(text="счастья"), ", ",
                                      RichTextBold(text="здоровья"), " и чтобы каждый день радовал тебя! ✨🍪"]),
        InputRichBlockBlockQuotation(blocks=[InputRichBlockParagraph(
            text="Загляни в бота или мини-приложение за подарком — он уже ждёт тебя в уведомлениях! 🎁")]),
        InputRichBlockButtons(buttons=[RichMessageButton(
            text="🎁 Получить подарок · 500 🍪", callback_data=f"birthday:claim:{day}:{recipient}")], align="center"),
    ])


async def send_greeting(bot, chat_id: int, user: dict, day: str) -> None:
    from aiogram.exceptions import TelegramBadRequest, TelegramNotFound

    from community_bot.ephemeral import keep_in_chat

    uid = int(user.get("user_id") or 0)
    recipient = str(uid) if uid else "u" + str(user["username"])
    with keep_in_chat():
        if callable(getattr(bot, "send_rich_message", None)):
            try:
                await bot.send_rich_message(chat_id, rich_message=rich_greeting(user, day))
                return
            except (TelegramBadRequest, TelegramNotFound) as exc:
                reason = str(exc).casefold()
                if not any(s in reason for s in ("method not found", "unknown method", "method is not supported")):
                    raise
        await bot.send_photo(chat_id, FSInputFile(GIFT_ART), caption=greeting(user), parse_mode="HTML",
                             disable_notification=False, reply_markup=gift_keyboard(day, recipient))


def greeting(user: dict) -> str:
    name = html.escape(str(user.get("profile_name") or user.get("telegram_name") or "Именинница"))
    if user.get("user_id"):
        mention = f'<a href="tg://user?id={int(user["user_id"])}"><b>{name}</b></a>'
    else:
        mention = f'<b>@{html.escape(str(user["username"]))}</b>'
    return (
        f"🎂 {mention}, с днём рождения! 🎉\n\n"
        "Поздравляем тебя от всей команды <b>НОРЫ</b> с этим днём! "
        "Желаем тебе <b>счастья</b>, <b>здоровья</b> и чтобы каждый день радовал тебя! ✨🍪\n\n"
        "<blockquote>Загляни в бота или мини-приложение за подарком — "
        "он уже ждёт тебя в уведомлениях! 🎁</blockquote>"
    )


async def _private_offer(bot, user_id: int, day: str, *, preview: bool = False) -> None:
    text = ("🎁 <b>Проверка подарка НОРЫ</b>\n500 🍪 ждут тебя здесь и в уведомлениях Mini App."
            if preview else "🎂 <b>С днём рождения!</b>\nОт НОРЫ тебе 500 🍪. "
            "Забери подарок здесь или в уведомлениях Mini App.")
    try:
        await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=gift_keyboard(day))
    except Exception:
        logger.exception("Birthday DM unavailable for user=%s", user_id)


async def _today_users(db: Database, day: str) -> list[dict]:
    users = await db.fetchall(
        "SELECT u.* FROM users u JOIN bot_state s ON s.key='birthday_date:'||u.user_id "
        "WHERE s.value=?",
        (day[5:],),
    )
    if day == SPECIAL_DAY:
        special = await db.fetchone(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE", (SPECIAL_USERNAME,),
        )
        if special and all(int(row["user_id"]) != int(special["user_id"]) for row in users):
            users.append(special)
        elif not special:
            logger.warning("Birthday user @%s not found in local users table", SPECIAL_USERNAME)
            users.append({"user_id": 0, "username": SPECIAL_USERNAME, "profile_name": "Карамелька"})
    return users


async def offer_special_on_contact(db: Database, telegram_user, day: str) -> bool:
    """Let the named recipient claim even if she had no stored user ID before the post."""
    if day != SPECIAL_DAY or (telegram_user.username or "").casefold() != SPECIAL_USERNAME.casefold():
        return False
    await db.ensure_user(telegram_user.id, telegram_user.username, telegram_user.first_name or "Карамелька")
    return await offer_gift(db, telegram_user.id, day)


async def deliver_today(bot, db: Database, settings, now: datetime | None = None) -> None:
    day = (now or datetime.now(ZoneInfo(settings.timezone))).date().isoformat()
    if day == SPECIAL_DAY and settings.owner_id:
        owner = await db.get_user(settings.owner_id)
        if owner:
            if await offer_gift(db, settings.owner_id, OWNER_GIFT):
                await _private_offer(bot, settings.owner_id, OWNER_GIFT)
            marker = f"birthday_owner_post:{settings.owner_id}:{day}"
            async with db.connect() as conn:
                await conn.execute("BEGIN IMMEDIATE")
                cursor = await conn.execute(
                    "INSERT OR IGNORE INTO bot_state(key,value) VALUES(?, 'attempted')", (marker,),
                )
                await conn.commit()
            if cursor.rowcount == 1 and settings.community_chat_id:
                try:
                    await send_greeting(bot, settings.community_chat_id, owner, OWNER_GIFT)
                    await db.set_bot_state(marker, "sent")
                except Exception:
                    logger.exception("Owner birthday greeting failed")
    for user in await _today_users(db, day):
        uid = int(user["user_id"])
        if uid and await offer_gift(db, uid, day):
            await _private_offer(bot, uid, day)
        if not settings.community_chat_id:
            continue
        special = (user.get("username") or "").casefold() == SPECIAL_USERNAME.casefold() and day == SPECIAL_DAY
        marker = f"birthday_post:{SPECIAL_USERNAME if special else uid}:{day}"
        # Mark before the Telegram call: a lost response must not produce a second public greeting.
        async with db.connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cursor = await conn.execute(
                "INSERT OR IGNORE INTO bot_state(key,value) VALUES(?, 'attempted')", (marker,),
            )
            await conn.commit()
        if cursor.rowcount != 1:
            continue
        try:
            await send_greeting(bot, settings.community_chat_id, user, day)
            await db.set_bot_state(marker, "sent")
        except Exception:
            logger.exception("Birthday greeting failed for user=%s", uid)


async def birthday_job(bot, db: Database, settings) -> None:
    timezone = ZoneInfo(settings.timezone)
    while True:
        try:
            await deliver_today(bot, db, settings)
        except Exception:
            logger.exception("Birthday job failed")
        now = datetime.now(timezone)
        if now.hour < 9:
            target = now.replace(hour=9, minute=0, second=0, microsecond=0)
        elif now.hour < 23:
            target = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            target = now.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
        await asyncio.sleep(max(1, (target - now).total_seconds()))


@router.callback_query(F.data.startswith("birthday:claim:"))
async def claim_callback(callback: CallbackQuery, db: Database) -> None:
    day, _, target = (callback.data or "").removeprefix("birthday:claim:").partition(":")
    is_group = bool(callback.message and callback.message.chat.type != "private")
    username = (callback.from_user.username or "").casefold()
    authorized = (target == str(callback.from_user.id) or
                  target.startswith("u") and target[1:].casefold() == username and bool(username)) if target else (
                      not is_group or day == SPECIAL_DAY and username == SPECIAL_USERNAME.casefold())
    if not authorized:
        await callback.answer("Извини, друг, подарок-то не твой 🎁", show_alert=True)
        return
    await offer_special_on_contact(db, callback.from_user, day)
    if await claim_gift(db, callback.from_user.id, day):
        await callback.answer("Подарок получен: +500 🍪!", show_alert=True)
        if callback.message and callback.message.chat.type == "private":
            await callback.message.answer("🎁 <b>Подарок получен!</b> +500 🍪 уже в кошельке.", parse_mode="HTML")
    else:
        await callback.answer("Подарок уже получен или недоступен.", show_alert=True)
