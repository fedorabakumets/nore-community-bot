"""Automatic onboarding and one-time invitation to the NORA community chat."""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)
BROADCAST_MARKER = "invite_chat_20261121_v1:"


def _telegram_link(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    return parsed.scheme == "https" and parsed.hostname == "t.me" and bool(parsed.path.strip("/"))


def entry_keyboard(settings, *, bot_username: str = "") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if _telegram_link(settings.community_invite_url):
        rows.append([InlineKeyboardButton(text="🚪 Войти в чат НОРЫ", url=settings.community_invite_url)])
    if bot_username:
        rows.append([InlineKeyboardButton(
            text="🎮 Открыть приложение NORA",
            url=f"https://t.me/{bot_username}?startapp",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def entry_text(*, new_member: bool = False) -> str:
    if new_member:
        return (
            "❤️ <b>Добро пожаловать в НОРУ!</b>\n\n"
            "✅ Твоя анкета принята автоматически. Можно сразу присоединиться к сообществу.\n\n"
            "💬 <b>Общий чат</b> — общение, новые знакомства и события.\n"
            "🎮 <b>Приложение</b> — игры, друзья, питомец и печеньки 🍪\n\n"
            "Нажми на кнопку ниже, чтобы войти."
        )
    return (
        "🕳 <b>НОРА · СОБИРАЕМСЯ ВМЕСТЕ</b>\n\n"
        "Главный чат НОРЫ открыт для тебя.\n\n"
        "💬 Общение и новые знакомства\n"
        "🎮 Игры и совместные партии\n"
        "🍪 События, достижения и жизнь сообщества\n\n"
        "<b>Присоединяйся по кнопке ниже.</b> ❤️"
    )


async def send_entry(bot, settings, user_id: int, *, new_member: bool = False) -> None:
    me = await bot.me()
    await bot.send_message(
        user_id,
        entry_text(new_member=new_member),
        parse_mode="HTML",
        reply_markup=entry_keyboard(settings, bot_username=me.username or ""),
    )


async def accept_waiting_applications(bot, db, settings) -> int:
    """Clear legacy pending applications; respect active bans and avoid duplicate decisions."""
    from community_bot.routers.private import _notify_application_decision

    approved = 0
    pending = await db.fetchall(
        "SELECT id, user_id FROM applications WHERE status = 'pending' ORDER BY created_at",
    )
    for row in pending:
        uid = int(row["user_id"])
        if db.ban_is_active(await db.ban_reset_state(uid)):
            continue
        application_id = int(row["id"])
        if not await db.decide_application(application_id, settings.owner_id, "approved", None):
            continue
        approved += 1
        try:
            await _notify_application_decision(
                bot, db, settings, application_id, settings.owner_id, "approved", None,
                automatic=True,
            )
            # The same person already got their admission and chat-link card.
            await db.set_bot_state(f"{BROADCAST_MARKER}{uid}", "sent")
        except TelegramAPIError as error:
            logger.warning("Auto-approved application %s; DM failed: %s", application_id, type(error).__name__)
    return approved

async def broadcast_entry_once(bot, db, settings) -> tuple[int, int]:
    """Persist per-recipient completion to avoid a repeated blast after a restart."""
    if not _telegram_link(settings.community_invite_url):
        logger.warning("Chat invitation broadcast skipped: no valid t.me link")
        return 0, 0
    sent, blocked = 0, 0
    for row in await db.list_all_users():
        uid = int(row["user_id"])
        if uid <= 0 or await db.get_bot_state(f"{BROADCAST_MARKER}{uid}"):
            continue
        for attempt in range(2):
            try:
                await send_entry(bot, settings, uid)
            except TelegramRetryAfter as error:
                await asyncio.sleep(error.retry_after + 0.1)
                if attempt == 0:
                    continue
                logger.warning("Chat invitation rate limited for %s", uid)
            except TelegramForbiddenError:
                blocked += 1
                await db.set_bot_state(f"{BROADCAST_MARKER}{uid}", "blocked")
            except TelegramAPIError as error:
                logger.warning("Chat invitation to %s failed (%s)", uid, type(error).__name__)
            else:
                sent += 1
                await db.set_bot_state(f"{BROADCAST_MARKER}{uid}", "sent")
            break
        await asyncio.sleep(0.075)
    logger.info("Chat invitation: sent=%s blocked=%s", sent, blocked)
    return sent, blocked


async def run_entry_release(bot, db, settings) -> None:
    try:
        await accept_waiting_applications(bot, db, settings)
        await broadcast_entry_once(bot, db, settings)
    except Exception:
        logger.exception("Automatic onboarding and invitation release failed")
