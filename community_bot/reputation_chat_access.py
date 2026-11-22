"""Track Telegram mutes owned by the reputation gate.

A reputation recovery must not silently undo an unrelated moderator mute.
Only mutes applied by this gate are eligible for automatic release.
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


async def sync_reputation_chat_access(
    db: Database,
    settings: Settings,
    bot,
    chat_id: int,
    user_id: int,
    reputation: int,
) -> str | None:
    """Return 'restricted', 'restored', or None; never free an unowned mute."""
    if not settings.community_chat_id or chat_id != settings.community_chat_id:
        return None
    key = _key(chat_id, user_id)
    restricted = reputation < settings.restricted_reputation_threshold
    owned = await db.get_bot_state(key) == "1"
    if not restricted and not owned:
        return None
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
            return None
        if restricted:
            # Existing staff/Telegram mutes are not ours: do not claim them.
            if member.status != ChatMemberStatus.MEMBER:
                return None
            await bot.restrict_chat_member(
                chat_id, user_id,
                permissions=ChatPermissions(can_send_messages=False),
            )
            await db.set_bot_state(key, "1")
            return "restricted"

        # Recovered to bronze. Release only a mute installed by this gate.
        if member.status == ChatMemberStatus.RESTRICTED and getattr(member, "is_member", False):
            if not member.can_send_messages:
                until = getattr(member, "until_date", None)
                # An explicit timed staff mute overrides our former restriction.
                if isinstance(until, datetime) and until > datetime.now(UTC):
                    await db.set_bot_state(key, "0")
                    return None
                await bot.restrict_chat_member(
                    chat_id, user_id,
                    permissions=ChatPermissions(**dict.fromkeys(ChatPermissions.model_fields, True)),
                )
                await db.set_bot_state(key, "0")
                return "restored"
        await db.set_bot_state(key, "0")
    except TelegramAPIError as error:
        logger.warning("Could not sync reputation chat access for %s (%s)", user_id, type(error).__name__)
    return None
