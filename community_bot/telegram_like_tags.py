"""Synchronize profile likes to native member tags in the community group."""

import asyncio
import logging
from time import monotonic

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from community_bot.social_likes import COUNT_PREFIX

TAG_STATE_PREFIX = "telegram_like_tag:"
INTERVAL = 60
BATCH_SIZE = 12
DEFER_SECONDS = 600
logger = logging.getLogger(__name__)


def like_tag(likes: int) -> str:
    if likes <= 0:
        return ""
    # Telegram tags have a 16-character limit. U+2661 is a text symbol.
    count = str(likes) if likes < 10**14 else f"{likes:.2e}"
    return f"♡ {count}"


async def sync_member_tag(db, bot, chat_id: int, user_id: int, key: str, state: str) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    is_member = member.status == ChatMemberStatus.MEMBER or (
        member.status == ChatMemberStatus.RESTRICTED and member.is_member
    )
    if not is_member or member.user.is_bot:
        return False

    current = member.tag or ""
    previous, pending, attempted = state.partition("\n")
    if current != previous and (not pending or current != attempted):
        return False  # The member or an administrator provided their own tag.

    # Check again after the Telegram lookup in case the member hid their profile.
    row = await db.fetchone(
        "SELECT COALESCE(CAST(l.value AS INTEGER),0) likes FROM users u "
        "LEFT JOIN bot_state l ON l.key=(? || u.user_id) WHERE u.user_id=? AND u.profile_private=0",
        (COUNT_PREFIX, user_id),
    )
    desired = like_tag(row["likes"]) if row else ""
    if current != desired:
        # Keep both possible Telegram values so a timeout or restart can be reconciled.
        await db.set_bot_state(key, f"{current}\n{desired}")
        if not await bot.set_chat_member_tag(chat_id, user_id, tag=desired):
            return False
    if desired:
        await db.set_bot_state(key, desired)
    else:
        await db.execute("DELETE FROM bot_state WHERE key=?", (key,))
    return True


async def sync_like_tags(db, bot, chat_id: int, deferred: dict[int, tuple[str, float]]) -> None:
    now = monotonic()
    for uid, (_, until) in list(deferred.items()):
        if until <= now:
            del deferred[uid]
    prefix = f"{TAG_STATE_PREFIX}{chat_id}:"
    rows = await db.fetchall(
        "SELECT u.user_id, COALESCE(t.value,'') tag_state, "
        "CASE WHEN u.profile_private=0 THEN COALESCE(CAST(l.value AS INTEGER),0) ELSE 0 END likes "
        "FROM users u LEFT JOIN bot_state l ON l.key=(? || u.user_id) "
        "LEFT JOIN bot_state t ON t.key=(? || u.user_id) "
        "WHERE u.user_id>0 AND (l.key IS NOT NULL OR t.key IS NOT NULL) "
        "ORDER BY likes=0 DESC, u.user_id",
        (COUNT_PREFIX, prefix),
    )
    pending = []
    for row in rows:
        tag = like_tag(row["likes"])
        retry = deferred.get(row["user_id"])
        if row["tag_state"] != tag and (not retry or retry[0] != tag):
            pending.append((row, tag))
    if not pending:
        return
    bot_member = await bot.get_chat_member(chat_id, bot.id)
    if not getattr(bot_member, "can_manage_tags", False):
        return
    for row, tag in pending[:BATCH_SIZE]:
        uid = row["user_id"]
        try:
            done = await sync_member_tag(db, bot, chat_id, uid, prefix + str(uid), row["tag_state"])
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            logger.debug("Telegram rejected a like tag operation (%s)", type(error).__name__)
            done = False
        if not done:
            deferred[uid] = (tag, now + DEFER_SECONDS)


async def like_tags_job(db, bot, chat_id: int) -> None:
    if not chat_id:
        return
    deferred: dict[int, tuple[str, float]] = {}
    while True:
        delay = INTERVAL
        try:
            await sync_like_tags(db, bot, chat_id, deferred)
        except TelegramRetryAfter as error:
            delay = max(delay, error.retry_after)
        except Exception as error:
            logger.warning("Telegram like tag synchronization deferred (%s)", type(error).__name__)
        await asyncio.sleep(delay)
