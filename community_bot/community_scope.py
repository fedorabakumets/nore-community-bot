from __future__ import annotations

import logging
from datetime import UTC, datetime

from aiogram import BaseMiddleware
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Update

logger = logging.getLogger(__name__)


MAX_MESSAGE_BACKLOG_SECONDS = 120


class FreshMessageMiddleware(BaseMiddleware):
    """Reject stale Telegram messages before moderation, commands and chat capture.

    A backlog delivered after redeploy or API recovery must never trigger
    old commands, anti-spam mutes, economic operations or notifications.
    """

    async def __call__(self, handler, event: Update, data):
        message = event.edited_message or event.message
        if message is not None:
            value = message.edit_date if event.edited_message and message.edit_date else message.date
            if isinstance(value, datetime):
                sent = value.timestamp()
            elif type(value) in (int, float):
                sent = float(value)
            else:
                sent = None
            if sent is not None:
                age = datetime.now(UTC).timestamp() - sent
                if age > MAX_MESSAGE_BACKLOG_SECONDS:
                    logger.warning(
                        "Skipped stale Telegram message (age=%ds, chat=%s, id=%s)",
                        int(age), message.chat.id, message.message_id,
                    )
                    return None
        return await handler(event, data)


class CommunityScopeMiddleware(BaseMiddleware):
    """Keep non-private chat events outside application handlers unless they come from NORA's group."""

    async def __call__(self, handler, event: Update, data):
        chat = data.get("event_chat")
        if chat is None:
            # Inline callbacks have no chat ID to authorize. Widgets validate their own private chat.
            if event.callback_query is not None:
                return
            return await handler(event, data)
        if chat.type == ChatType.PRIVATE:
            return await handler(event, data)
        settings = data.get("settings")
        community_chat_id = settings.community_chat_id if settings is not None else 0
        if community_chat_id and chat.id == community_chat_id:
            return await handler(event, data)

        membership = event.my_chat_member
        from community_bot.updates_feed import is_updates_chat, run as publish_updates_feed

        if is_updates_chat(chat):
            # Feed is outbound-only; do not forward its events into community logic.
            if membership is not None and membership.new_chat_member.status in {
                ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR,
            } and settings is not None and data.get("db") is not None:
                await publish_updates_feed(data["db"], settings, data["bot"])
            return

        if chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
            return

        if community_chat_id and membership is not None:
            member = membership.new_chat_member
            if member.status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR} or (
                member.status == ChatMemberStatus.RESTRICTED and member.is_member
            ):
                try:
                    await data["bot"].leave_chat(chat.id)
                except TelegramAPIError as error:
                    logger.warning("Could not leave an unconfigured group (%s)", type(error).__name__)
