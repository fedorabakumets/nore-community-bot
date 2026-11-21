"""Single-issue invite competition for NORA, independent of random cookie raffles."""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery, ChatJoinRequest, ChatMemberUpdated, InlineKeyboardButton,
    InlineKeyboardMarkup, InputRichMessage, Message,
)

from community_bot.group_message_close import without_group_close
from community_bot.private_rich import standalone_rich_message, text_blocks

logger = logging.getLogger(__name__)
router = Router(name="referral_cookie_campaign")
CAMPAIGN = "cookies-invites-2026"
ZONE = ZoneInfo("Europe/Moscow")
START = datetime(2026, 11, 22, 0, 0, tzinfo=ZONE)
END = datetime(2026, 12, 22, 0, 0, tzinfo=ZONE)
PRIZES = (1000, 500, 100)
POST_KEY = "referral_campaign:2026:post"
AWARD_KEY = "referral_campaign:2026:awarded"

SCHEMA = """
CREATE TABLE IF NOT EXISTS referral_campaign_links (
    campaign TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    invite_link TEXT NOT NULL UNIQUE,
    invite_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(campaign, user_id)
);
CREATE TABLE IF NOT EXISTS referral_campaign_pending (
    campaign TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    inviter_id INTEGER NOT NULL,
    requested_at TEXT NOT NULL,
    PRIMARY KEY(campaign, user_id)
);
CREATE TABLE IF NOT EXISTS referral_campaign_joins (
    campaign TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    inviter_id INTEGER NOT NULL,
    joined_at TEXT NOT NULL,
    PRIMARY KEY(campaign, user_id)
);
CREATE INDEX IF NOT EXISTS idx_referral_campaign_joins_inviter
    ON referral_campaign_joins(campaign, inviter_id);
"""

POST_HTML = (
    "🍪 <b>КОНКУРС НА ПЕЧЕНЬКИ</b>\n"
    "Позови больше всех новых участников по своей личной ссылке и получи "
    "<b>настоящие печеньки Норы</b>: для мини-игр, кастомизации и возможностей приложения.\n\n"
    "🏆 <b>Призовые места</b>\n"
    "🥇 1 место — <b>1 000 🍪</b>\n"
    "🥈 2 место — <b>500 🍪</b>\n"
    "🥉 3 место — <b>100 🍪</b>\n\n"
    "<blockquote>Победят три участника, которые пригласят больше всего "
    "новых людей. Рейтинг обновляется в Mini App: Коммьюнити → ТОП → 🏆.</blockquote>\n\n"
    "<b>Условия</b>\n"
    "🗓 22 ноября 00:00 – 21 декабря 23:59, МСК (один месяц).\n"
    "🔗 Нажми «Получить ссылку» в этом сообщении. "
    "Персональная ссылка выдаётся <b>один раз</b>, повторно не создаётся. "
    "Ею можно пригласить сколько угодно людей.\n"
    "✅ Засчитываются только новые участники, реально вступившие в чат. "
    "Повторные вступления и боты не учитываются.\n"
    "🏅 При равенстве приглашений выше тот, кто пригласил первого раньше.\n"
    "Итоги и начисление призов — после завершения конкурса."
)


def within_window(when: datetime | None = None) -> bool:
    when = (when or datetime.now(UTC)).astimezone(ZONE)
    return START <= when < END


async def link_owner(db, invite_url: str | None) -> int | None:
    if not invite_url:
        return None
    row = await db.fetchone(
        "SELECT user_id FROM referral_campaign_links WHERE campaign=? AND invite_link=?",
        (CAMPAIGN, invite_url),
    )
    return int(row["user_id"]) if row else None


_link_locks: dict[int, asyncio.Lock] = {}


async def get_or_create_link(bot: Bot, db, settings, user_id: int) -> str:
    """One permanent personalized link per Telegram user; no replacement on repeat clicks."""
    lock = _link_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        row = await db.fetchone(
            "SELECT invite_link FROM referral_campaign_links WHERE campaign=? AND user_id=?",
            (CAMPAIGN, user_id),
        )
        if row:
            return str(row["invite_link"])
        if datetime.now(ZONE) >= END:
            raise ValueError("Конкурс уже завершён.")
        name = f"NORA26-{user_id}"[:32]
        invite = await bot.create_chat_invite_link(
            settings.community_chat_id, name=name, creates_join_request=True,
            expire_date=END,
        )
        url = invite.invite_link
        try:
            await db.execute(
                "INSERT INTO referral_campaign_links(campaign,user_id,invite_link,invite_name,created_at) "
                "VALUES(?,?,?,?,?)",
                (CAMPAIGN, user_id, url, name, datetime.now(UTC).isoformat()),
            )
        except Exception:
            # If a durable write fails, invalidate the orphan instead of silently issuing two.
            try:
                await bot.revoke_chat_invite_link(settings.community_chat_id, url)
            except TelegramAPIError:
                logger.warning("Could not revoke orphaned referral link for user %s", user_id)
            raise
        return url


async def remember_request(db, event: ChatJoinRequest) -> None:
    """Telegram may omit invite_link from a later approved ChatMemberUpdated event."""
    if not within_window(event.date):
        return
    inviter = await link_owner(db, getattr(getattr(event, "invite_link", None), "invite_link", None))
    if not inviter or inviter == event.from_user.id or event.from_user.is_bot:
        return
    await db.execute(
        "INSERT INTO referral_campaign_pending(campaign,user_id,inviter_id,requested_at) "
        "VALUES(?,?,?,?) ON CONFLICT(campaign,user_id) DO UPDATE SET "
        "inviter_id=excluded.inviter_id, requested_at=excluded.requested_at",
        (CAMPAIGN, event.from_user.id, inviter, event.date.isoformat()),
    )


async def record_join(db, event: ChatMemberUpdated) -> bool:
    """Count a verified first-time membership, once, regardless of future rejoins."""
    user = event.new_chat_member.user
    if user.is_bot or not within_window(event.date):
        return False
    event_link = getattr(getattr(event, "invite_link", None), "invite_link", None)
    inviter = await link_owner(db, event_link)
    if not inviter and not event_link:
        pending = await db.fetchone(
            "SELECT inviter_id,requested_at FROM referral_campaign_pending "
            "WHERE campaign=? AND user_id=?", (CAMPAIGN, user.id),
        )
        if pending:
            try:
                requested = datetime.fromisoformat(pending["requested_at"])
                if event.date - requested <= timedelta(days=7) and event.date >= requested:
                    inviter = int(pending["inviter_id"])
            except (TypeError, ValueError):
                pass
    if not inviter or inviter == user.id:
        return False
    # Prior membership (even before this campaign) does not earn an invitation.
    if await db.get_bot_state(f"community_join:{event.chat.id}:{user.id}"):
        return False
    prior = await db.fetchone(
        "SELECT 1 AS seen FROM user_activity WHERE user_id=? AND chat_id=? "
        "UNION SELECT 1 AS seen FROM daily_scores "
        "WHERE user_id=? AND chat_id=? AND day<? LIMIT 1",
        (user.id, event.chat.id, user.id, event.chat.id, START.date().isoformat()),
    )
    if prior:
        return False
    async with db.connect() as connection:
        await connection.execute("BEGIN IMMEDIATE")
        current = await (await connection.execute(
            "INSERT OR IGNORE INTO referral_campaign_joins "
            "(campaign,user_id,inviter_id,joined_at) VALUES(?,?,?,?)",
            (CAMPAIGN, user.id, inviter, event.date.isoformat()),
        ))
        await connection.execute(
            "DELETE FROM referral_campaign_pending WHERE campaign=? AND user_id=?",
            (CAMPAIGN, user.id),
        )
        await connection.commit()
        return bool(current.rowcount)


async def leaderboard(db, limit: int = 3) -> list[dict]:
    """Rank by unique first joins; timestamp and user id give deterministic tie breaks."""
    return await db.fetchall(
        "SELECT l.user_id, COUNT(j.user_id) AS invites, MIN(j.joined_at) AS first_join "
        "FROM referral_campaign_links l "
        "LEFT JOIN referral_campaign_joins j ON j.campaign=l.campaign AND j.inviter_id=l.user_id "
        "WHERE l.campaign=? GROUP BY l.user_id HAVING COUNT(j.user_id)>0 "
        "ORDER BY invites DESC, (first_join IS NULL) ASC, first_join ASC, l.created_at ASC, l.user_id ASC "
        "LIMIT ?",
        (CAMPAIGN, limit),
    )


@router.callback_query(F.data == "referral:link:2026")
async def issue_personal_link(callback: CallbackQuery, bot: Bot, db, settings) -> None:
    if not callback.from_user or not settings.community_chat_id:
        await callback.answer("Ссылки сейчас недоступны.", show_alert=True)
        return
    from community_bot.access import private_allowed

    user_id = callback.from_user.id
    if not await private_allowed(db, settings, user_id):
        await callback.answer("Сначала заверши анкету в личке Норы.", show_alert=True)
        return
    try:
        url = await get_or_create_link(bot, db, settings, user_id)
    except ValueError as error:
        await callback.answer(str(error), show_alert=True)
        return
    except TelegramAPIError:
        logger.exception("Telegram could not create a campaign invite")
        await callback.answer("Не удалось получить ссылку. Проверь права бота на приглашения.", show_alert=True)
        return
    except Exception:
        logger.exception("Could not store an invite")
        await callback.answer("Ссылка пока недоступна, обратитесь к администрации.", show_alert=True)
        return
    try:
        with standalone_rich_message():
            await bot.send_message(
                user_id,
                "🏆 <b>Твоя ссылка конкурса НОРЫ</b>\n\n"
                f"<code>{html.escape(url)}</code>\n\n"
                "Ссылка персональная и уже закреплена за тобой. "
                "Новых ссылок не выдаём, но этой можешь приглашать сколько угодно людей.\n"
                "Рейтинг: Коммьюнити → ТОП → 🏆",
                parse_mode="HTML",
            )
    except (TelegramBadRequest, TelegramForbiddenError):
        await callback.answer(
            "⚠️ Ссылка закреплена за тобой, но ЛС закрыты. Открой личный чат с ботом НОРЫ и нажми кнопку ещё раз.",
            show_alert=True,
        )
    else:
        await callback.answer(
            "⚠️ Ссылка уже закреплена за тобой и продублирована в личные сообщения Норы.",
            show_alert=True,
        )


async def publish_poster(bot: Bot, db, settings, file_id: str) -> int:
    """Post the supplied photo as Rich, then pin it; never publish twice."""
    existing = await db.get_bot_state(POST_KEY)
    if not settings.community_chat_id:
        raise ValueError("Не задан чат сообщества.")
    if datetime.now(ZONE) >= END and not existing:
        raise ValueError("Срок конкурса истёк, публиковать его нельзя.")
    if existing:
        await bot.pin_chat_message(settings.community_chat_id, int(existing), disable_notification=True)
        return int(existing)
    username = (await bot.me()).username
    if not username:
        raise ValueError("У бота нет имени Telegram.")
    rich = InputRichMessage(blocks=[
        {"type": "photo", "photo": {"type": "photo", "media": file_id}},
        *text_blocks(POST_HTML, "HTML", compact=False),
        {"type": "buttons", "align": "center", "buttons": [
            {"text": "🔗 Получить ссылку", "callback_data": "referral:link:2026", "style": "success"},
        ]},
    ])
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="НОРА", url=f"https://t.me/{username}?startapp")
    ]])
    with without_group_close():
        sent = await bot.send_rich_message(
            chat_id=settings.community_chat_id, rich_message=rich, reply_markup=markup,
        )
    await db.set_bot_state(POST_KEY, str(sent.message_id))
    try:
        await bot.pin_chat_message(settings.community_chat_id, sent.message_id, disable_notification=True)
    except TelegramAPIError:
        logger.exception("Contest posted, but bot could not pin message %s", sent.message_id)
        raise
    return sent.message_id


@router.message(F.chat.type == "private", F.photo, Command("refcontest"))
async def admin_publish_poster(message: Message, bot: Bot, db, settings) -> None:
    """One-time upload path: admin sends the exact artwork to the bot with /refcontest caption."""
    if not message.from_user or not settings.is_owner(message.from_user.id):
        return
    try:
        post_id = await publish_poster(bot, db, settings, message.photo[-1].file_id)
    except (TelegramAPIError, ValueError) as error:
        logger.exception("Could not publish referral competition")
        await message.answer(f"Не удалось опубликовать конкурс: {html.escape(str(error))}", parse_mode="HTML")
        return
    await message.answer(f"🏆 Конкурс опубликован. Сообщение №{post_id}; закреп проверяй в чате.")


async def award_finished_contest(bot: Bot, db) -> list[tuple[int, int]]:
    """Atomic, idempotent payout. No reward for a zero-invite participant."""
    if datetime.now(ZONE) < END or not await db.get_bot_state(POST_KEY):
        return []
    async with db.connect() as connection:
        await connection.execute("BEGIN IMMEDIATE")
        exists = await (await connection.execute("SELECT 1 FROM bot_state WHERE key=?", (AWARD_KEY,))).fetchone()
        if exists:
            await connection.rollback()
            return []
        standings = await (await connection.execute(
            "SELECT inviter_id, COUNT(*) AS total, MIN(joined_at) AS first_join "
            "FROM referral_campaign_joins WHERE campaign=? GROUP BY inviter_id "
            "ORDER BY total DESC, first_join ASC, inviter_id ASC LIMIT 3",
            (CAMPAIGN,),
        )).fetchall()
        now = datetime.now(UTC).isoformat()
        awarded = []
        for rank, row in enumerate(standings):
            uid, prize = int(row["inviter_id"]), PRIZES[rank]
            await connection.execute(
                "UPDATE users SET cookies=cookies+?, updated_at=? WHERE user_id=?",
                (prize, now, uid),
            )
            await connection.execute(
                "INSERT INTO transactions(user_id,amount,kind,details,created_at) "
                "VALUES(?,?,?,?,?)",
                (uid, prize, "referral_campaign", CAMPAIGN, now),
            )
            awarded.append((uid, prize))
        await connection.execute("INSERT INTO bot_state(key,value) VALUES(?,?)", (AWARD_KEY, now))
        await connection.commit()
    for uid, prize in awarded:
        try:
            with standalone_rich_message():
                await bot.send_message(uid, f"🏆 Конкурс НОРЫ завершён! Тебе начислено {prize} 🍪.")
        except TelegramAPIError:
            logger.warning("Could not DM referral winner %s", uid)
    return awarded


async def reward_scheduler(bot: Bot, db) -> None:
    while not await db.get_bot_state(AWARD_KEY):
        if datetime.now(ZONE) >= END and await db.get_bot_state(POST_KEY):
            await award_finished_contest(bot, db)
            return
        await asyncio.sleep(300)
