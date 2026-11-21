"""Staff-only read-only mirror of the NORA Telegram community chat."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.types import Message, TelegramObject, Update
from aiohttp import web

from community_bot.helpers import effective_role

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS staff_chat_messages (
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL DEFAULT 0,
    author_name TEXT NOT NULL,
    username TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    media_type TEXT NOT NULL DEFAULT '',
    media_file_id TEXT NOT NULL DEFAULT '',
    reply_to_id INTEGER,
    sent_at TEXT NOT NULL,
    edited_at TEXT,
    PRIMARY KEY (chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_staff_chat_messages_recent
    ON staff_chat_messages(chat_id, message_id DESC);
"""


async def staff_allowed(db, settings, uid: int) -> bool:
    """Check authoritative server-side roles, not a browser-provided flag."""
    return await effective_role(db, settings, uid) in {"owner", "admin", "moderator"}


def message_media(message: Message) -> tuple[str, str]:
    if message.photo:
        return "photo", message.photo[-1].file_id
    for name in ("video", "animation", "voice", "video_note", "audio", "document", "sticker"):
        media = getattr(message, name, None)
        if media:
            return name, str(getattr(media, "file_id", "") or "")
    if message.poll:
        return "poll", ""
    if message.location:
        return "location", ""
    if message.contact:
        return "contact", ""
    return "", ""


async def capture(db, settings, message: Message) -> None:
    if not settings.community_chat_id or message.chat.id != settings.community_chat_id:
        return
    if message.chat.type not in {"group", "supergroup"}:
        return
    user = message.from_user
    sender_chat = message.sender_chat
    if user:
        author = user.full_name or "Участник"
        username = user.username or ""
        user_id = user.id if not sender_chat else 0
    elif sender_chat:
        author, username, user_id = sender_chat.title or "Администратор", "", 0
    else:
        return
    if sender_chat:
        author = sender_chat.title or "Администратор"
    media_type, media_id = message_media(message)
    text = str(message.text or message.caption or "")[:4000]
    if not text and not media_type:
        return
    edited = message.edit_date.isoformat() if message.edit_date else None
    await db.execute(
        """
        INSERT INTO staff_chat_messages (
            chat_id, message_id, user_id, author_name, username, text,
            media_type, media_file_id, reply_to_id, sent_at, edited_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, message_id) DO UPDATE SET
            author_name=excluded.author_name, username=excluded.username,
            text=excluded.text, media_type=excluded.media_type,
            media_file_id=excluded.media_file_id, edited_at=excluded.edited_at
        WHERE excluded.edited_at IS NOT NULL
        """,
        (
            message.chat.id, message.message_id, user_id, author[:120], username[:80],
            text, media_type, media_id,
            message.reply_to_message.message_id if message.reply_to_message else None,
            message.date.isoformat(), edited,
        ),
    )
    # Keep the experimental mirror bounded; Telegram remains the source of truth.
    if not edited and message.message_id % 250 == 0:
        await db.execute(
            """
            DELETE FROM staff_chat_messages
            WHERE chat_id=? AND message_id NOT IN (
                SELECT message_id FROM staff_chat_messages WHERE chat_id=?
                ORDER BY message_id DESC LIMIT 5000
            )
            """,
            (message.chat.id, message.chat.id),
        )


class StaffChatCaptureMiddleware(BaseMiddleware):
    """Capture at update level so other handlers cannot swallow group messages."""

    async def __call__(
        self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject, data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Update):
            message = event.message or event.edited_message
            if message is not None and data.get("db") and data.get("settings"):
                try:
                    await capture(data["db"], data["settings"], message)
                except Exception:
                    logger.exception("Could not archive community message for staff chat")
        return await handler(event, data)


async def feed(request: web.Request) -> web.Response:
    db, settings = request.app["db"], request.app["settings"]
    if not await staff_allowed(db, settings, request["actor"]["id"]):
        return web.json_response(
            {"error": "Тестовый чат доступен только команде Норы"},
            status=403, headers={"Cache-Control": "no-store"},
        )
    if not settings.community_chat_id:
        return web.json_response({"items": [], "enabled": False})
    rows = await db.fetchall(
        """
        SELECT m.message_id id, m.user_id, m.author_name name, m.username,
               m.text, m.media_type, m.reply_to_id, m.sent_at, m.edited_at,
               r.author_name reply_name, r.text reply_text,
               CASE WHEN u.avatar_file_id IS NOT NULL AND u.avatar_file_id != ''
                    THEN 1 ELSE 0 END has_avatar
        FROM staff_chat_messages m
        LEFT JOIN staff_chat_messages r
          ON r.chat_id=m.chat_id AND r.message_id=m.reply_to_id
        LEFT JOIN users u ON u.user_id=m.user_id
        WHERE m.chat_id=?
        ORDER BY m.message_id DESC LIMIT 80
        """,
        (settings.community_chat_id,),
    )
    messages = []
    chat_id = str(settings.community_chat_id)
    public_chat_id = chat_id[4:] if chat_id.startswith("-100") else ""
    for m in reversed(rows):
        m["has_avatar"] = bool(m["has_avatar"])
        m["link"] = (
            f"https://t.me/c/{public_chat_id}/{m['id']}" if public_chat_id else ""
        )
        messages.append(m)
    return web.json_response({"items": messages, "enabled": True})


class StaffChatOutgoingMiddleware(BaseRequestMiddleware):
    """Mirror messages emitted by the bot too; Bot API does not echo its own sends."""

    async def __call__(self, make_request, bot, method):
        result = await make_request(bot, method)
        db = getattr(bot, "community_db", None)
        settings = getattr(bot, "community_settings", None)
        if db is None or settings is None:
            return result
        messages = result if isinstance(result, list) else [result]
        for message in messages:
            if isinstance(message, Message):
                try:
                    await capture(db, settings, message)
                except Exception:
                    logger.exception("Could not archive outgoing community chat message")
        return result
