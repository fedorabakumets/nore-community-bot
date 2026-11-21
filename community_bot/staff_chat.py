"""Staff-only read-only mirror of the NORA Telegram community chat."""
from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from pathlib import PurePosixPath
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
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
    media_thumb_file_id TEXT NOT NULL DEFAULT '',
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


def message_thumbnail(message: Message) -> str:
    for name in ('video', 'animation', 'video_note', 'sticker', 'document'):
        media = getattr(message, name, None)
        thumbnail = getattr(media, 'thumbnail', None) if media else None
        if thumbnail:
            return str(thumbnail.file_id or '')
    return ''


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
    thumbnail_id = message_thumbnail(message)
    text = str(message.text or message.caption or "")[:4000]
    if not text and not media_type:
        return
    edited = message.edit_date.isoformat() if message.edit_date else None
    await db.execute(
        """
        INSERT INTO staff_chat_messages (
            chat_id, message_id, user_id, author_name, username, text,
            media_type, media_file_id, media_thumb_file_id,
            reply_to_id, sent_at, edited_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, message_id) DO UPDATE SET
            author_name=excluded.author_name, username=excluded.username,
            text=excluded.text, media_type=excluded.media_type,
            media_file_id=excluded.media_file_id,
            media_thumb_file_id=excluded.media_thumb_file_id,
            edited_at=excluded.edited_at
        WHERE excluded.edited_at IS NOT NULL
        """,
        (
            message.chat.id, message.message_id, user_id, author[:120], username[:80],
            text, media_type, media_id, thumbnail_id,
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



_QUERY = """
    SELECT m.message_id id, m.user_id, m.author_name name, m.username,
           m.text, m.media_type, m.reply_to_id, m.sent_at, m.edited_at,
           r.author_name reply_name, r.text reply_text, r.media_type reply_media_type,
           CASE WHEN m.media_file_id != '' THEN 1 ELSE 0 END has_media,
           CASE WHEN m.media_thumb_file_id != '' THEN 1 ELSE 0 END has_thumbnail,
           CASE WHEN u.avatar_file_id IS NOT NULL AND u.avatar_file_id != ''
                THEN 1 ELSE 0 END has_avatar
    FROM staff_chat_messages m
    LEFT JOIN staff_chat_messages r
      ON r.chat_id=m.chat_id AND r.message_id=m.reply_to_id
    LEFT JOIN users u ON u.user_id=m.user_id
"""


def _message_link(chat_id: int, message_id: int | None) -> str:
    chat = str(chat_id)
    return (
        f"https://t.me/c/{chat[4:]}/{message_id}"
        if message_id and chat.startswith("-100") else ""
    )


async def feed(request: web.Request) -> web.Response:
    db, settings = request.app["db"], request.app["settings"]
    if not await staff_allowed(db, settings, request["actor"]["id"]):
        return web.json_response(
            {"error": "Тестовый чат доступен только команде Норы"}, status=403,
        )
    chat_id = int(settings.community_chat_id or 0)
    if not chat_id:
        return web.json_response({"items": [], "enabled": False})

    around_raw = request.query.get("around")
    around = None
    if around_raw is not None:
        if not around_raw.isdecimal() or not 1 <= len(around_raw) <= 12:
            return web.json_response({"error": "Некорректное сообщение"}, status=400)
        around = int(around_raw)
        found = await db.fetchone(
            "SELECT 1 FROM staff_chat_messages WHERE chat_id=? AND message_id=?",
            (chat_id, around),
        )
        if not found:
            return web.json_response(
                {"error": "Сообщение не сохранилось в истории Норы"}, status=404,
            )
    if around is None:
        rows = list(reversed(await db.fetchall(
            _QUERY + "WHERE m.chat_id=? ORDER BY m.message_id DESC LIMIT 80",
            (chat_id,),
        )))
    else:
        before = await db.fetchall(
            _QUERY + "WHERE m.chat_id=? AND m.message_id<=? "
                     "ORDER BY m.message_id DESC LIMIT 40",
            (chat_id, around),
        )
        after = await db.fetchall(
            _QUERY + "WHERE m.chat_id=? AND m.message_id>? "
                     "ORDER BY m.message_id ASC LIMIT 40",
            (chat_id, around),
        )
        rows = list(reversed(before)) + after

    for m in rows:
        m["has_avatar"] = bool(m["has_avatar"])
        m["has_media"] = bool(m["has_media"])
        m["has_thumbnail"] = bool(m["has_thumbnail"])
        m["link"] = _message_link(chat_id, m["id"])
        m["reply_link"] = _message_link(chat_id, m["reply_to_id"])
    return web.json_response({
        "items": rows, "enabled": True,
        "mode": "context" if around is not None else "latest",
        "target": around,
    })


# The hosted Telegram Bot API cannot serve arbitrarily large videos.
# Cap actual allocations as well as the advertised Telegram file size.
MAX_MEDIA_BYTES = 18 * 1024 * 1024
MEDIA_MIMES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif",
    ".mp4": "video/mp4", ".webm": "video/webm",
    ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav",
    ".aac": "audio/aac",
}
MEDIA_TYPES = {"photo", "video", "animation", "sticker", "voice", "audio", "video_note"}


class BoundedMediaBuffer(BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_MEDIA_BYTES:
            raise ValueError("Вложение слишком большое для просмотра")
        return super().write(data)


async def media(request: web.Request) -> web.Response:
    """Authenticated proxy by stored message ID. Never expose Bot API tokens or file IDs."""
    db, settings = request.app["db"], request.app["settings"]
    if not await staff_allowed(db, settings, request["actor"]["id"]):
        return web.json_response(
            {"error": "Просмотр доступен только команде Норы"}, status=403,
        )
    message_id = int(request.match_info["message_id"])
    chat_id = int(settings.community_chat_id or 0)
    row = await db.fetchone(
        "SELECT media_type, media_file_id, media_thumb_file_id "
        "FROM staff_chat_messages WHERE chat_id=? AND message_id=?",
        (chat_id, message_id),
    )
    if not row or row["media_type"] not in MEDIA_TYPES:
        return web.json_response({"error": "Вложение не найдено"}, status=404)
    thumb = request.query.get("thumb") == "1"
    file_id = row["media_thumb_file_id"] if thumb else row["media_file_id"]
    if not file_id:
        return web.json_response({"error": "Превью недоступно"}, status=404)
    bot = request.app.get("bot")
    if bot is None:
        return web.json_response({"error": "Telegram недоступен"}, status=503)
    gate = request.app.get("staff_chat_media_gate")
    if gate is None:
        return web.json_response({"error": "Медиа пока недоступны"}, status=503)
    try:
        async with gate:
            remote = await asyncio.wait_for(bot.get_file(file_id), timeout=15)
            path = str(remote.file_path or "")
            extension = PurePosixPath(path).suffix.lower()
            content_type = MEDIA_MIMES.get(extension)
            if extension == ".tgs":
                return web.json_response(
                    {"error": "Анимированный стикер открывается в Telegram"}, status=415,
                )
            if not content_type or (thumb and not content_type.startswith("image/")):
                return web.json_response(
                    {"error": "Этот формат открывается в Telegram"}, status=415,
                )
            if int(remote.file_size or 0) > MAX_MEDIA_BYTES:
                return web.json_response(
                    {"error": "Файл слишком большой. Открой его в Telegram"}, status=413,
                )
            output = BoundedMediaBuffer()
            try:
                await asyncio.wait_for(
                    bot.download_file(path, destination=output, timeout=20), timeout=25,
                )
            except ValueError:
                return web.json_response(
                    {"error": "Файл слишком большой. Открой его в Telegram"}, status=413,
                )
            payload = output.getvalue()
        return web.Response(
            body=payload, content_type=content_type,
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": "inline",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except (TelegramAPIError, asyncio.TimeoutError, OSError):
        logger.warning("Staff chat media unavailable: chat message %s", message_id)
        return web.json_response(
            {"error": "Файл недоступен. Его можно открыть в Telegram"}, status=502,
        )


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
