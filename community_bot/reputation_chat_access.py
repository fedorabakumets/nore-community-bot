"""Synchronize Telegram chat permissions with the reputation gate.

The gate tags its own restrictions. For older users, a recovery operation can
also release legacy, untagged reputation mutes, while preserving timed/staff
mutes and pending admission checks.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatPermissions

from community_bot.config import Settings
from community_bot.database import Database

logger = logging.getLogger(__name__)


def _key(chat_id: int, user_id: int) -> str:
    return f"reputation_chat_mute:{chat_id}:{user_id}"


async def _release_is_safe(db: Database, chat_id: int, user_id: int) -> bool:
    """Never bypass the captcha, re-application or recorded moderator mutes."""
    from community_bot.access import needs_reapplication

    if await needs_reapplication(db, user_id):
        return False
    if await db.fetchone(
        "SELECT 1 FROM captcha_pending WHERE chat_id=? AND user_id=?",
        (chat_id, user_id),
    ):
        return False

    # Telegram does not indicate *why* an indefinite mute was imposed.
    # Preserve an outstanding moderator mute even if the reputation mute is tagged.
    last_moderation = await db.fetchone(
        "SELECT action FROM admin_audit_log "
        "WHERE target=? AND (action IN ('mute', 'unmute') "
        "OR (action='warn' AND details LIKE '%+ мут%')) "
        "ORDER BY id DESC LIMIT 1",
        (str(user_id),),
    )
    return not last_moderation or last_moderation["action"] == "unmute"


async def sync_reputation_chat_access(
    db: Database,
    settings: Settings,
    bot,
    chat_id: int,
    user_id: int,
    reputation: int,
    *,
    allow_legacy_recovery: bool = False,
) -> str | None:
    """Return 'restricted'/'restored' or None when nothing was safely changed.

    allow_legacy_recovery is for an explicit positive-reputation event or shop
    restoration. Older reputation mutes were not tracked by this mechanism.
    """
    if not bot or not settings.community_chat_id or chat_id != settings.community_chat_id:
        return None
    key = _key(chat_id, user_id)
    restricted = reputation < settings.restricted_reputation_threshold
    owned = await db.get_bot_state(key) == "1"
    if not restricted and not owned and not allow_legacy_recovery:
        return None
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
            return None
        if restricted:
            # Do not take ownership of unrelated restrictions.
            if member.status != ChatMemberStatus.MEMBER:
                return None
            await bot.restrict_chat_member(
                chat_id, user_id,
                permissions=ChatPermissions(can_send_messages=False),
            )
            await db.set_bot_state(key, "1")
            return "restricted"

        if member.status == ChatMemberStatus.RESTRICTED and getattr(member, "is_member", False):
            if not member.can_send_messages:
                until = getattr(member, "until_date", None)
                # A timed moderator mute must never disappear after +реп.
                if isinstance(until, datetime) and until > datetime.now(UTC):
                    if owned:
                        await db.set_bot_state(key, "0")
                    return None
                if not await _release_is_safe(db, chat_id, user_id):
                    return None
                await bot.restrict_chat_member(
                    chat_id, user_id,
                    permissions=ChatPermissions(**dict.fromkeys(ChatPermissions.model_fields, True)),
                    use_independent_chat_permissions=True,
                )
                await db.set_bot_state(key, "0")
                return "restored"
        if owned:
            await db.set_bot_state(key, "0")
    except TelegramAPIError as error:
        logger.warning(
            "Could not sync reputation chat access for %s (%s)",
            user_id, type(error).__name__,
        )
    return None
