from __future__ import annotations

import logging

from aiogram import BaseMiddleware
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Update

logger = logging.getLogger(__name__)


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
        if chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
            return

        settings = data.get("settings")
        community_chat_id = settings.community_chat_id if settings is not None else 0
        if community_chat_id and chat.id == community_chat_id:
            return await handler(event, data)

        membership = event.my_chat_member
        if community_chat_id and membership is not None:
            member = membership.new_chat_member
            if member.status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR} or (
                member.status == ChatMemberStatus.RESTRICTED and member.is_member
            ):
                try:
                    await data["bot"].leave_chat(chat.id)
                except TelegramAPIError as error:
                    logger.warning("Could not leave an unconfigured group (%s)", type(error).__name__)
