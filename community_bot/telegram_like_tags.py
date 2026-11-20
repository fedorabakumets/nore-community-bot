"""Synchronize profile likes to native member tags in the community group."""

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from time import monotonic

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from community_bot.social_likes import COUNT_PREFIX

TAG_STATE_PREFIX = "telegram_like_tag:"
DEFAULT_ADMIN_TITLE = "Админ"
INTERVAL = 60
BATCH_SIZE = 12
DEFER_SECONDS = 600
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TagState:
    base: str = ""
    applied: str = ""
    pending: str | None = None
    administrator: bool = False

    @classmethod
    def read(cls, value: str):
        if value.startswith("{"):
            return cls(**json.loads(value))
        # Earlier releases stored only the tag, or two possible tags separated by a newline.
        applied, separator, pending = value.partition("\n")
        return cls(applied=applied, pending=pending if separator else None)

    def base_for(self, current: str, administrator: bool) -> str:
        if self.administrator != administrator:
            return current
        if current in (self.applied, self.pending):
            return self.base
        # An admin can edit the role text while leaving our previous suffix in place.
        display_base = self.base or (DEFAULT_ADMIN_TITLE if administrator else "")
        for tag in (self.applied, self.pending):
            if tag and tag.startswith(display_base):
                suffix = tag.removeprefix(display_base)
                if suffix and current.endswith(suffix):
                    return current.removesuffix(suffix).rstrip()
        return current


def like_tag(likes: int, base: str, *, administrator: bool) -> str:
    if likes <= 0:
        return base
    # Telegram tags have a 16-character limit. U+2661 is a text symbol.
    count = str(likes) if likes < 10**14 else f"{likes:.2e}"
    title = base or (DEFAULT_ADMIN_TITLE if administrator else "")
    if not title:
        return f"♡ {count}"
    for suffix in (f" ♡ {count}", f" ♡{count}", f"♡{count}"):
        if len(title + suffix) <= 16:
            return title + suffix
    return base


async def sync_member_tag(db, bot, chat_id: int, user_id: int, key: str, saved: str, *, can_manage_tags: bool) -> None:
    member = await bot.get_chat_member(chat_id, user_id)
    administrator = member.status == ChatMemberStatus.ADMINISTRATOR
    is_regular = member.status == ChatMemberStatus.MEMBER or (
        member.status == ChatMemberStatus.RESTRICTED and member.is_member
    )
    can_edit = member.can_be_edited if administrator else is_regular and can_manage_tags
    if not can_edit or member.user.is_bot:
        return

    current = (member.custom_title if administrator else member.tag) or ""
    state = TagState.read(saved)
    base = state.base_for(current, administrator)

    # Check again after the Telegram lookup in case the member hid their profile.
    row = await db.fetchone(
        "SELECT COALESCE(CAST(l.value AS INTEGER),0) likes FROM users u "
        "LEFT JOIN bot_state l ON l.key=(? || u.user_id) WHERE u.user_id=? AND u.profile_private=0",
        (COUNT_PREFIX, user_id),
    )
    desired = like_tag(row["likes"] if row else 0, base, administrator=administrator)
    if current != desired:
        # Keep both possible Telegram values so a timeout or restart can be reconciled.
        pending = TagState(base=base, applied=current, pending=desired, administrator=administrator)
        await db.set_bot_state(key, json.dumps(asdict(pending), ensure_ascii=False))
        if administrator:
            updated = await bot.set_chat_administrator_custom_title(chat_id, user_id, custom_title=desired)
        else:
            updated = await bot.set_chat_member_tag(chat_id, user_id, tag=desired)
        if not updated:
            return
    if desired != base:
        finished = TagState(base=base, applied=desired, administrator=administrator)
        if current != desired or state != finished:
            await db.set_bot_state(key, json.dumps(asdict(finished), ensure_ascii=False))
    elif saved:
        await db.execute("DELETE FROM bot_state WHERE key=?", (key,))


async def sync_like_tags(db, bot, chat_id: int, checked: dict[int, tuple[int, float]]) -> None:
    now = monotonic()
    prefix = f"{TAG_STATE_PREFIX}{chat_id}:"
    rows = await db.fetchall(
        "SELECT u.user_id, COALESCE(t.value,'') tag_state, "
        "CASE WHEN u.profile_private=0 THEN COALESCE(CAST(l.value AS INTEGER),0) ELSE 0 END likes "
        "FROM users u LEFT JOIN bot_state l ON l.key=(? || u.user_id) "
        "LEFT JOIN bot_state t ON t.key=(? || u.user_id) "
        "WHERE u.user_id>0 AND (t.key IS NOT NULL OR (u.profile_private=0 AND CAST(l.value AS INTEGER)>0)) "
        "ORDER BY u.user_id",
        (COUNT_PREFIX, prefix),
    )
    pending = []
    active_ids = {row["user_id"] for row in rows}
    for uid in checked.keys() - active_ids:
        del checked[uid]
    for row in rows:
        likes = row["likes"]
        previous_likes, last_checked = checked.get(row["user_id"], (None, 0.0))
        if previous_likes != likes or now - last_checked >= DEFER_SECONDS:
            pending.append((likes > 0, previous_likes == likes, last_checked, row))
    if not pending:
        return
    bot_member = await bot.get_chat_member(chat_id, bot.id)
    if bot_member.status != ChatMemberStatus.ADMINISTRATOR:
        return
    can_manage_tags = bool(bot_member.can_manage_tags)
    # Clear hidden counts first and recheck old tags fairly when there is room in the batch.
    pending.sort(key=lambda item: item[:3])
    for _, _, _, row in pending[:BATCH_SIZE]:
        uid = row["user_id"]
        try:
            await sync_member_tag(
                db, bot, chat_id, uid, prefix + str(uid), row["tag_state"], can_manage_tags=can_manage_tags,
            )
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            logger.debug("Telegram rejected a like tag operation (%s)", type(error).__name__)
        checked[uid] = (row["likes"], now)


async def like_tags_job(db, bot, chat_id: int) -> None:
    if not chat_id:
        return
    checked: dict[int, tuple[int, float]] = {}
    while True:
        delay = INTERVAL
        try:
            await sync_like_tags(db, bot, chat_id, checked)
        except TelegramRetryAfter as error:
            delay = max(delay, error.retry_after)
        except Exception as error:
            logger.warning("Telegram like tag synchronization deferred (%s)", type(error).__name__)
        await asyncio.sleep(delay)
