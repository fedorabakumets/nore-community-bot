"""Private Telegram notifications with durable read and cleanup state."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from string import Template
from time import time
from uuid import uuid4

from aiogram.exceptions import (
    ClientDecodeError,
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)

from community_bot.message_widgets import AnswerWidgetQuery, EditMessageWidgetData, SendNotificationWidget

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
SEND_INTERVAL = 30
BLOCKED_INTERVAL = 24 * 60 * 60
TEMPLATE = Path(__file__).with_name("widgets") / "notification.html"
NOTICE_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class Sender:
    kind: str = "nora"
    label: str = "Нора"
    user_id: int | None = None


def snippet(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def document(*, sender: str, title: str, preview: str, details: str, context: str, date: str, url: str) -> str:
    fields = {
        "sender": (sender, 28, 18), "title": (title, 48, 30), "preview": (preview, 75, 48),
        "details": (details or preview, 140, 72), "context": (context, 46, 22),
    }
    values = {"date": date}
    for key, (value, regular, narrow) in fields.items():
        values[key] = snippet(value, regular)
        values[key + "_narrow"] = snippet(value, narrow)
    # The link is derived from getMe and an opaque ID. User text is escaped into text nodes only.
    html = Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
        **{key: escape(value) for key, value in values.items()},
        url=json.dumps(url, ensure_ascii=True).replace("<", "\\u003c"),
        read_request=json.dumps(READ_REQUEST),
    )
    raw = html.encode()
    if not 1 <= len(raw) <= 32768 or len(zlib.compress(raw, 9)) > 4096:
        raise ValueError("Telegram widget exceeds the mini-HTML limits")
    return html


async def send_notification(
    bot, db, recipient_id: int, sender: Sender, title: str, preview: str, details: str, target: str,
    *, category: str, event_key: str, context: str = "", event_at: datetime | None = None,
) -> str:
    """Send a subscribed event at most once. Callers must supply a stable domain event key."""
    if category not in CATEGORIES:
        raise ValueError("Unknown widget notification category")
    return await _send(bot, db, recipient_id, sender, title, preview, details, target, category,
                       event_key, context, event_at)


async def send_admin_test(bot, db, recipient_id: int, event_key: str) -> str:
    return await _send(
        bot, db, recipient_id, Sender(), "Проверка уведомлений", "Это тестовое уведомление от Норы.",
        "Раскрой карточку, открой Нору и нажми «Прочитано». Карточка погасит индикатор и исчезнет через 30 секунд.",
        "notices", TEST_CATEGORY, event_key, "Проверка из админ-панели", None,
    )


async def _send(bot, db, recipient_id, sender, title, preview, details, target, category,
                event_key, context, event_at) -> str:
    if recipient_id <= 0 or target not in TARGETS or not title.strip() or not preview.strip() or not event_key:
        raise ValueError("Invalid widget notification")
    if event_at is not None and event_at.utcoffset() is None:
        raise ValueError("Widget event time must have a timezone")

    me = await bot.me()
    if not me.username or not re.fullmatch(r"[A-Za-z0-9_]+", me.username):
        raise ValueError("A bot username is required for the Mini App link")

    now, notice_id = int(time()), uuid4().hex
    event_date = (event_at or datetime.fromtimestamp(now, UTC)).astimezone(UTC)
    url = f"https://t.me/{me.username}?startapp=nora_notice_{notice_id}"
    html = document(sender=sender.label, title=title, preview=preview, details=details, context=context,
                    date=event_date.strftime("%d.%m.%Y %H:%M UTC"), url=url)
    caption = (f"НОРА | {escape(snippet(title, 110))}\n"
               f"От кого: {escape(snippet(sender.label, 40))}\n{escape(snippet(preview, 250))}\n"
               f'<a href="{url}">Открыть Нору и посмотреть детали</a>')

    # A single write reserves the event across concurrent calls and restarts. sendWidget has no
    # idempotency key. A lost response stays unconfirmed so retrying cannot create a second push.
    async with db.connect() as connection:
        cursor = await connection.execute(
            """INSERT INTO widget_notifications(
                   id,recipient_id,sender_type,sender_id,sender_label,title,preview,details,
                   category,target,context,event_at,event_key,created_at)
               SELECT ?,user_id,?,?,?,?,?,?,?,?,?,?,?,? FROM users
               WHERE user_id=? AND (? OR EXISTS (
                   SELECT 1 FROM notify_prefs WHERE user_id=users.user_id AND channel=? AND enabled=1
               )) AND NOT EXISTS (
                   SELECT 1 FROM widget_notifications WHERE recipient_id=users.user_id AND created_at>?
               ) AND NOT EXISTS (
                   SELECT 1 FROM widget_notifications
                   WHERE recipient_id=users.user_id AND created_at>? AND delivery='blocked'
               )
               ON CONFLICT(recipient_id,category,event_key) DO NOTHING RETURNING id""",
            (notice_id, sender.kind, sender.user_id, sender.label, title, preview, details, category, target,
             context, event_date.isoformat(), event_key, now, recipient_id, category == TEST_CATEGORY,
             category, now - SEND_INTERVAL, now - BLOCKED_INTERVAL),
        )
        reserved = await cursor.fetchone()
        await cursor.close()
        await connection.commit()
    if not reserved:
        return "suppressed"

    try:
        sent = await bot(SendNotificationWidget(
            chat_id=recipient_id, html=html, caption=caption, allow_queries=True, chat_data='{"read":false}',
        ), request_timeout=12)
    except TelegramForbiddenError:
        delivery = "blocked"
    except (TelegramNetworkError, TelegramServerError, ClientDecodeError):
        return "unconfirmed"
    except TelegramAPIError as error:
        logger.info("Widget notification rejected (%s)", type(error).__name__)
        delivery = "failed"
    else:
        if sent.chat.id != recipient_id or sent.message_id <= 0:
            return "unconfirmed"
        await db.execute(
            "UPDATE widget_notifications SET delivery='sent', chat_id=?, message_id=? WHERE id=?",
            (sent.chat.id, sent.message_id, notice_id),
        )
        return "sent"

    await db.execute("UPDATE widget_notifications SET delivery=? WHERE id=?", (delivery, notice_id))
    return delivery


async def handle_widget_query(bot, db, query: dict) -> bool:
    if query.get("data") != READ_REQUEST:
        return False

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
        "WHERE next_action_at<=? ORDER BY next_action_at LIMIT 25",
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
    while True:
        try:
            await settle_read_notifications(bot, db)
        except Exception as error:
            logger.warning("Widget notification cleanup failed (%s)", type(error).__name__)
        await asyncio.sleep(5)
