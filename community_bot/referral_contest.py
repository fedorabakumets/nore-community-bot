"""NORA's one-month, invitation-counted cookie contest.

Separate from the legacy random-draw cookie contest. Every participant receives
one reusable, individually named Telegram invite link for the whole campaign.
"""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramAPIError
from aiogram.types import InputRichMessage, RichMessageButton, InputRichBlockButtons

from community_bot.private_rich import standalone_rich_message, text_blocks
from community_bot.reply_rich import bot_publication
from community_bot.group_message_close import without_group_close

logger = logging.getLogger(__name__)
MOSCOW = ZoneInfo("Europe/Moscow")
CAMPAIGN = "cookies-20261121"
START = datetime(2026, 11, 21, 22, 0, tzinfo=MOSCOW)
END = datetime(2026, 12, 21, 22, 0, tzinfo=MOSCOW)
PRIZES = (1000, 500, 100)
POST_KEY = "referral-contest:20261121:post"
FINISHED_KEY = "referral-contest:20261121:finished"
_LINK_LOCK = asyncio.Lock()
_FINISH_LOCK = asyncio.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS nora_referral_links (
    campaign TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    invite_link TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    PRIMARY KEY(campaign, user_id)
);
CREATE TABLE IF NOT EXISTS nora_referral_pending (
    campaign TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    inviter_id INTEGER NOT NULL REFERENCES users(user_id),
    requested_at TEXT NOT NULL,
    PRIMARY KEY(campaign, user_id)
);
CREATE TABLE IF NOT EXISTS nora_referral_joins (
    campaign TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    inviter_id INTEGER NOT NULL REFERENCES users(user_id),
    joined_at TEXT NOT NULL,
    PRIMARY KEY(campaign, user_id)
);
CREATE INDEX IF NOT EXISTS idx_nora_referral_joins_leader
ON nora_referral_joins(campaign, inviter_id, joined_at);
"""


def within_campaign(value: datetime | None = None) -> bool:
    when = value or datetime.now(MOSCOW)
    if when.tzinfo is None:
        when = when.replace(tzinfo=MOSCOW)
    return START <= when.astimezone(MOSCOW) < END


async def published(db) -> bool:
    return bool(await db.get_bot_state(POST_KEY))


async def ensure_personal_link(db, bot, settings, user) -> str:
    """Exactly one link per Telegram ID; a repeat click never creates a new link."""
    if not await published(db) or not within_campaign():
        raise ValueError("Конкурс ещё не начался или уже завершён.")
    if not settings.community_chat_id:
        raise ValueError("Чат сообщества пока не настроен.")
    uid = int(user.id)
    async with _LINK_LOCK:
        existing = await db.fetchone(
            "SELECT invite_link FROM nora_referral_links WHERE campaign=? AND user_id=?",
            (CAMPAIGN, uid),
        )
        if existing:
            return existing["invite_link"]
        username = (user.username or str(uid)).replace(" ", "")[:17]
        title = f"NORA CUP | {username}"[:32]
        invitation = await bot.create_chat_invite_link(
            settings.community_chat_id,
            name=title,
            expire_date=END,
            creates_join_request=True,
        )
        link = invitation.invite_link
        try:
            await db.execute(
                "INSERT INTO nora_referral_links(campaign,user_id,invite_link,created_at) "
                "VALUES (?,?,?,?)",
                (CAMPAIGN, uid, link, datetime.now(MOSCOW).isoformat()),
            )
        except Exception:
            try:
                await bot.revoke_chat_invite_link(settings.community_chat_id, link)
            except TelegramAPIError:
                logger.exception("Could not revoke an untracked contest link")
            raise
        return link


async def record_request(db, chat_id: int, settings, user_id: int, telegram_link: str | None) -> None:
    """Record the attribution before auto-approval (approval may happen after the form)."""
    if chat_id != settings.community_chat_id or not await published(db) or not within_campaign():
        return
    row = await db.fetchone(
        "SELECT user_id FROM nora_referral_links WHERE campaign=? AND invite_link=?",
        (CAMPAIGN, telegram_link or ""),
    )
    if not row or int(row["user_id"]) == user_id:
        return
    await db.execute(
        "INSERT INTO nora_referral_pending(campaign,user_id,inviter_id,requested_at) "
        "VALUES (?,?,?,?) ON CONFLICT(campaign,user_id) DO UPDATE SET "
        "inviter_id=excluded.inviter_id,requested_at=excluded.requested_at",
        (CAMPAIGN, user_id, row["user_id"], datetime.now(MOSCOW).isoformat()),
    )


async def record_join(db, chat_id: int, settings, user_id: int,
                      telegram_link: str | None, joined_at: datetime) -> bool:
    """Credit a first genuine chat join, never a request, click or rejoin."""
    if chat_id != settings.community_chat_id or not await published(db) or not within_campaign(joined_at):
        return False
    previous = await db.get_bot_state(f"community_join:{chat_id}:{user_id}")
    if previous:
        return False
    active_before = await db.fetchone(
        "SELECT 1 AS existing FROM user_activity WHERE chat_id=? AND user_id=? LIMIT 1",
        (chat_id, user_id),
    )
    if active_before:
        return False
    inviter = None
    if telegram_link:
        row = await db.fetchone(
            "SELECT user_id FROM nora_referral_links WHERE campaign=? AND invite_link=?",
            (CAMPAIGN, telegram_link),
        )
        inviter = row["user_id"] if row else None
    else:
        row = await db.fetchone(
            "SELECT inviter_id FROM nora_referral_pending WHERE campaign=? AND user_id=?",
            (CAMPAIGN, user_id),
        )
        inviter = row["inviter_id"] if row else None
    if not inviter or int(inviter) == user_id:
        return False
    # The primary key protects against concurrent duplicate updates and repeated rejoining.
    async with db.connect() as connection:
        cursor = await connection.execute(
            "INSERT OR IGNORE INTO nora_referral_joins(campaign,user_id,inviter_id,joined_at) "
            "VALUES (?,?,?,?)",
            (CAMPAIGN, user_id, inviter, joined_at.astimezone(MOSCOW).isoformat()),
        )
        await connection.commit()
        return cursor.rowcount == 1


async def leaders(db, *, limit: int = 3) -> list[dict]:
    return await db.fetchall(
        "SELECT l.user_id, COUNT(j.user_id) AS invitations, "
        "MIN(j.joined_at) AS first_join_at FROM nora_referral_links l "
        "LEFT JOIN nora_referral_joins j ON j.campaign=l.campaign AND j.inviter_id=l.user_id "
        "WHERE l.campaign=? GROUP BY l.user_id "
        "ORDER BY invitations DESC, CASE WHEN first_join_at IS NULL THEN 1 ELSE 0 END, "
        "first_join_at ASC, l.created_at ASC, l.user_id ASC LIMIT ?",
        (CAMPAIGN, limit),
    )


def announcement_text() -> str:
    return (
        "🏆 <b>КОНКУРС НА ПЕЧЕНЬКИ</b>\n\n"
        "🥇 <b>1 место: 1 000 🍪</b>\n"
        "🥈 <b>2 место: 500 🍪</b>\n"
        "🥉 <b>3 место: 100 🍪</b>\n\n"
        "<blockquote>Пригласи больше всех новых участников по своей личной ссылке "
        "и забери настоящие печеньки Норы! Трать их на мини-игры, кастомизацию "
        "и возможности нашего приложения.</blockquote>\n\n"
        "📅 <b>Срок:</b> с 21 ноября 2026, 22:00 по 21 декабря 2026, 22:00 (МСК).\n"
        "🔗 <b>Как участвовать:</b> нажми «Получить ссылку» ниже. "
        "Ссылка создаётся для тебя <b>один раз</b> на весь конкурс, "
        "новая выдаваться не будет. Её можно отправлять сколь угодно многим друзьям.\n"
        "✅ Засчитываются только новые участники, <b>вступившие в чат</b> по ссылке. "
        "Повторные входы и приглашение самого себя очков не дают.\n"
        "🏆 Актуальная тройка лидеров: <b>Коммьюнити → ТОП → 🏆</b> в Mini App.\n"
        "При равенстве результатов выше участник, чьё первое приглашение произошло раньше."
    )


async def publish(db, settings, bot, image_file_id: str) -> int:
    """Publish the submitted Telegram photo inside Rich; pin adds NORA as sole native button."""
    if not image_file_id:
        raise ValueError("Нужна картинка конкурса.")
    if datetime.now(MOSCOW) >= END:
        raise ValueError("Дата окончания конкурса уже прошла.")
    if not settings.community_chat_id:
        raise ValueError("Не настроен чат Норы.")
    if existing := await db.get_bot_state(POST_KEY):
        return int(existing)
    buttons = InputRichBlockButtons(
        align="center",
        buttons=[
            RichMessageButton(text="🔗 Получить ссылку", callback_data="refcontest:link", style="success"),
            RichMessageButton(text="🏆 Топ конкурса", callback_data="refcontest:top", style="link"),
        ],
    )
    rich = InputRichMessage(blocks=[
        {"type": "photo", "photo": {"type": "photo", "media": image_file_id}},
        *text_blocks(announcement_text(), "HTML", compact=False),
        buttons,
    ])
    with without_group_close(), bot_publication():
        sent = await bot.send_rich_message(settings.community_chat_id, rich_message=rich)
    await db.set_bot_state(POST_KEY, str(sent.message_id))
    try:
        await bot.pin_chat_message(settings.community_chat_id, sent.message_id, disable_notification=True)
    except TelegramAPIError:
        logger.exception("Contest published but pin failed; check Telegram bot admin rights")
    return sent.message_id


async def send_link_dm(bot, user_id: int, link: str) -> None:
    body = (
        "🍪 <b>ТВОЯ ССЫЛКА НА КОНКУРС</b>\n\n"
        "Это личная ссылка для приглашений в Нору. Она выдана один раз и "
        "останется неизменной до конца конкурса.\n\n"
        f"<code>{html.escape(link)}</code>\n\n"
        "Каждый новый участник, вступивший по ней в чат, добавит тебе +1 в рейтинге 🏆."
    )
    rich = InputRichMessage(blocks=[
        *text_blocks(body, "HTML", compact=False),
        InputRichBlockButtons(align="center", buttons=[
            RichMessageButton(text="🔗 Открыть ссылку", url=link, style="primary"),
        ]),
    ])
    with standalone_rich_message(), bot_publication():
        await bot.send_rich_message(user_id, rich_message=rich)


async def finish(db) -> list[dict] | None:
    """Pay winners once, atomically, after the deadline. No random-draw mechanics."""
    if datetime.now(MOSCOW) < END or not await published(db):
        return None
    async with _FINISH_LOCK:
        async with db.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            old = await (await connection.execute(
                "SELECT value FROM bot_state WHERE key=?", (FINISHED_KEY,),
            )).fetchone()
            if old:
                await connection.rollback()
                return None
            entries = await (await connection.execute(
                "SELECT l.user_id, COUNT(j.user_id) AS invitations, "
                "MIN(j.joined_at) AS first_join_at FROM nora_referral_links l "
                "LEFT JOIN nora_referral_joins j ON j.campaign=l.campaign AND j.inviter_id=l.user_id "
                "WHERE l.campaign=? GROUP BY l.user_id HAVING invitations > 0 "
                "ORDER BY invitations DESC, first_join_at ASC, l.created_at ASC, l.user_id ASC LIMIT 3",
                (CAMPAIGN,),
            )).fetchall()
            awarded = []
            now = datetime.now(MOSCOW).isoformat()
            for place, row in enumerate(entries, 1):
                prize = PRIZES[place - 1]
                await connection.execute(
                    "UPDATE users SET cookies=cookies+?,updated_at=? WHERE user_id=?",
                    (prize, now, row["user_id"]),
                )
                await connection.execute(
                    "INSERT INTO transactions(user_id,amount,kind,details,created_at) VALUES(?,?,?,?,?)",
                    (row["user_id"], prize, "referral_contest", f"{CAMPAIGN}:place:{place}", now),
                )
                awarded.append({"user_id": row["user_id"], "invitations": row["invitations"], "prize": prize})
            await connection.execute(
                "INSERT INTO bot_state(key,value) VALUES(?,?) ON CONFLICT(key) "
                "DO UPDATE SET value=excluded.value",
                (FINISHED_KEY, now),
            )
            await connection.commit()
            return awarded
