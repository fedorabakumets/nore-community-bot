"""Explicit, nonce-gated maintenance requests, executed by the existing bot only."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from community_bot.morning import publish_morning_digest

logger = logging.getLogger(__name__)
REQUEST_VARIABLE = "NORA_REBUILD_MORNING_PIN_ONCE"


async def apply_requested_morning_rebuild(bot, db, settings) -> bool:
    request = os.getenv(REQUEST_VARIABLE, "").strip()
    if not request or await db.get_bot_state("morning_rebuild_applied") == request:
        return True
    if not settings.community_chat_id:
        logger.warning("Пересоздание утреннего закрепа: чат сообщества не настроен")
        return False
    today = datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
    prepared = await db.get_bot_state("morning_rebuild_prepared")
    prepared_day = await db.get_bot_state("morning_rebuild_prepared_day")
    message_id = await db.get_bot_state("morning_rebuild_message_id")
    try:
        if prepared != request or prepared_day != today or not message_id:
            # Publish first; old posts remain intact if collecting or sending fails.
            if not await publish_morning_digest(bot, db, settings, force=True):
                return False
            message_id = await db.get_bot_state("morning_pin_message_id")
            if not message_id:
                return False
            await db.set_bot_state("morning_rebuild_message_id", message_id)
            await db.set_bot_state("morning_rebuild_prepared_day", today)
            await db.set_bot_state("morning_rebuild_prepared", request)
        # The fresh post has already been pinned once, proving the pin permission.
        # No messages are deleted. On a failure the prepared ID is reused on retry.
        await bot.unpin_all_chat_messages(settings.community_chat_id)
        await bot.pin_chat_message(settings.community_chat_id, int(message_id), disable_notification=True)
        chat = await bot.get_chat(settings.community_chat_id)
        pinned = getattr(chat, "pinned_message", None)
        if pinned is None or pinned.message_id != int(message_id):
            logger.warning("Не удалось подтвердить новый утренний закреп")
            return False
        await db.set_bot_state("morning_rebuild_applied", request)
    except Exception:
        logger.exception("Не удалось завершить пересоздание утреннего закрепа")
        return False
    logger.info("Новая утренняя сводка опубликована; все старые закрепы сняты; новый закреп подтверждён")
    return True
