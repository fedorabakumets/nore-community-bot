"""Private Telegram notifications with durable read and cleanup state."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from time import time

from aiogram.exceptions import (
    ClientDecodeError,
    TelegramAPIError,
    TelegramBadRequest,
    TelegramRetryAfter,
)

from community_bot.message_widgets import AnswerWidgetQuery, EditMessageWidgetData

logger = logging.getLogger(__name__)

CATEGORIES = {
    "widget_nora": "Новости Норы",
    "widget_reputation": "Изменения репутации",
    "widget_rewards": "Награды и достижения",
    "widget_events": "События сообщества",
    "widget_shop": "Покупки и магазин",
    "widget_personal": "Персональные уведомления",
}
TARGETS = {
    "notices": "Уведомления",
    "lk": "Профиль",
    "reputation": "Репутация",
    "shop": "Магазин",
    "events": "События",
    "history": "История операций",
}
TEST_CATEGORY = "widget_admin_test"
READ_REQUEST = "nora-notice:read"
DELETE_DELAY = 30
DELETE_WINDOW = 48 * 60 * 60
SEND_INTERVAL = 3
BLOCKED_INTERVAL = 24 * 60 * 60
NOTICE_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class Sender:
    kind: str = "nora"
    label: str = "Нора"
    user_id: int | None = None


def snippet(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


async def send_notification(
    bot, db, recipient_id: int, sender: Sender, title: str, preview: str, details: str, target: str,
    *, category: str, event_key: str, context: str = "", event_at: datetime | None = None,
) -> str:
    """Send a subscribed event at most once. Callers must supply a stable domain event key."""
    if category not in CATEGORIES:
        raise ValueError("Unknown widget notification category")
    from community_bot.widget_inbox import enqueue

    return await enqueue(bot, db, recipient_id, sender, title, preview, details, target, category,
                         event_key, context=context, event_at=event_at)


async def send_admin_test(bot, db, recipient_id: int, event_key: str) -> str:
    from community_bot.widget_inbox import enqueue

    return await enqueue(
        bot, db, recipient_id, Sender(), "Проверка уведомлений", "Это тестовое уведомление от Норы.",
        "Открой Нору, отметь одну карточку прочитанной или прочитай всю пачку и закрой виджет.",
        "notices", TEST_CATEGORY, event_key, context="Проверка из админ-панели", required=True,
    )


async def send_service_notification(
    bot, db, recipient_id: int, sender: Sender, title: str, details: str, target: str,
    *, event_key: str, context: str = "",
) -> str:
    """Deliver a transactional notice using the same inbox, independent of optional subscriptions."""
    from community_bot.widget_inbox import enqueue

    return await enqueue(bot, db, recipient_id, sender, title, details, details, target, "widget_personal",
                         event_key, context=context, required=True)


async def handle_widget_query(bot, db, query: dict) -> bool:
    if query.get("data") != READ_REQUEST:
        from community_bot.widget_inbox import handle_query

        return await handle_query(bot, db, query)

    chat, sender, kind = query.get("chat"), query.get("from"), query.get("type")
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    message_id, query_id = query.get("message_id"), query.get("id")
    if not isinstance(query_id, str) or not query_id:
        return True

    read = False
    if (type(chat_id) is int and chat_id > 0 and chat.get("type") == "private"
            and isinstance(sender, dict) and sender.get("id") == chat_id
            and isinstance(kind, dict) and kind.get("type") == "data"
            and type(message_id) is int and message_id > 0
            and not query.get("inline_message_id") and not query.get("widget_id")):
        now = int(time())
        async with db.connect() as connection:
            cursor = await connection.execute(
                """UPDATE widget_notifications
                   SET read_at=COALESCE(read_at,?), next_action_at=CASE
                       WHEN read_at IS NULL THEN ? ELSE next_action_at END
                   WHERE recipient_id=? AND chat_id=? AND message_id=? AND delivery='sent'
                   RETURNING id""",
                (now, now, sender["id"], chat_id, message_id),
            )
            read = await cursor.fetchone() is not None
            await cursor.close()
            await connection.commit()

    try:
        await bot(AnswerWidgetQuery(widget_query_id=query_id, data=json.dumps({"read": read})), request_timeout=8)
    except (TelegramAPIError, ClientDecodeError) as error:
        # A lost or expired answer must not roll back the saved read status.
        logger.info("Widget query answer failed (%s)", type(error).__name__)
    return True


async def settle_read_notifications(bot, db) -> None:
    now = int(time())
    rows = await db.fetchall(
        "SELECT id, chat_id, message_id, created_at, read_synced FROM widget_notifications "
        "WHERE delivery='sent' AND next_action_at<=? ORDER BY next_action_at LIMIT 25",
        (now,),
    )
    for row in rows:
        now = int(time())
        synced, next_action = row["read_synced"], None
        chat_id, message_id = row["chat_id"], row["message_id"]
        try:
            if not synced:
                try:
                    await bot(EditMessageWidgetData(chat_id=chat_id, message_id=message_id,
                                                    chat_data='{"read":true}'), request_timeout=8)
                except TelegramBadRequest as error:
                    if "message is not modified" not in str(error).casefold():
                        raise
                synced = 1
                if now < row["created_at"] + DELETE_WINDOW:
                    next_action = int(time()) + DELETE_DELAY
            elif now < row["created_at"] + DELETE_WINDOW:
                await bot.delete_message(chat_id, message_id, request_timeout=8)
        except TelegramRetryAfter as error:
            next_action = now + max(5, error.retry_after)
        except TelegramBadRequest as error:
            if not any(reason in str(error).casefold() for reason in (
                "message to delete not found", "message to edit not found", "message not found",
                "message can't be deleted",
            )):
                next_action = now + 60
        except (TelegramAPIError, ClientDecodeError):
            next_action = now + 60

        if next_action is not None and next_action >= row["created_at"] + DELETE_WINDOW:
            next_action = None
        await db.execute(
            "UPDATE widget_notifications SET read_synced=?, next_action_at=? WHERE id=?",
            (synced, next_action, row["id"]),
        )


async def widget_notification_job(bot, db) -> None:
    from community_bot.widget_inbox import settle_due

    while True:
        try:
            await settle_read_notifications(bot, db)
            await settle_due(bot, db)
        except Exception as error:
            logger.warning("Widget notification cleanup failed (%s)", type(error).__name__)
        await asyncio.sleep(5)
