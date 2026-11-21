"""Staff-only experimental Telegram group composer for the NORA Mini App.

Telegram Bot API always sends as the bot; author attribution is explicit.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import PurePath

from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import BufferedInputFile, ReplyParameters
from aiohttp import web

from community_bot.staff_chat import capture, staff_allowed

logger = logging.getLogger(__name__)
MAX_TEXT = 3000
MAX_CAPTION = 800
MAX_UPLOAD = 12 * 1024 * 1024
SEND_INTERVAL = 2.0
_ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif",
    ".mp4", ".mov", ".webm", ".mp3", ".m4a", ".ogg", ".oga",
    ".opus", ".aac", ".wav", ".pdf", ".txt",
}
_PHOTO = {".jpg", ".jpeg", ".png"}
_VIDEO = {".mp4"}
_AUDIO = {".mp3", ".m4a"}
_QUIET_ERRORS = "Не удалось отправить в Telegram. Проверь доступность чата и попробуй снова."


async def _member(request: web.Request):
    db, settings = request.app["db"], request.app["settings"]
    uid = request["actor"]["id"]
    if not await staff_allowed(db, settings, uid):
        return None, web.json_response(
            {"error": "Писать в тестовом чате могут только администраторы и модераторы"},
            status=403,
        )
    bot = request.app.get("bot")
    if bot is None or not settings.community_chat_id:
        return None, web.json_response({"error": "Чат Норы пока недоступен"}, status=503)
    return (db, settings, bot, uid), None


def _validate_text(raw: object, has_file: bool) -> str:
    if not isinstance(raw, str):
        raise ValueError("Некорректный текст")
    text = raw.strip()
    if not text and not has_file:
        raise ValueError("Напиши сообщение или прикрепи файл")
    limit = MAX_CAPTION if has_file else MAX_TEXT
    if len(text) > limit:
        raise ValueError(f"Слишком длинный текст (не более {limit} символов)")
    return text


async def _reply(db, chat_id: int, raw: object) -> ReplyParameters | None:
    if raw in (None, "", 0):
        return None
    if type(raw) is not int or raw <= 0:
        raise ValueError("Некорректный ответ")
    found = await db.fetchone(
        "SELECT 1 FROM staff_chat_messages WHERE chat_id=? AND message_id=?",
        (chat_id, raw),
    )
    if not found:
        raise ValueError("Исходное сообщение отсутствует в зеркале")
    return ReplyParameters(message_id=raw, allow_sending_without_reply=False)


def _author(db_user: dict | None, actor: dict) -> str:
    user = db_user or {}
    identity = (
        user.get("profile_name") or user.get("telegram_name")
        or actor.get("first_name") or "Участник"
    )
    return re.sub(r"\s+", " ", str(identity)).strip()[:48] or "Участник"


async def _publish(request: web.Request, *, text: str, reply: object,
                   file: tuple[str, bytes] | None):
    credentials, denied = await _member(request)
    if denied is not None:
        return denied
    db, settings, bot, uid = credentials
    try:
        content = _validate_text(text, file is not None)
        reply_to = await _reply(db, settings.community_chat_id, reply)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    name = _author(await db.get_user(uid), request["actor"])
    attribution = f"💬 {name} · через Mini App Норы"
    body = f"{attribution}\n\n{content}" if content else attribution
    locks = request.app["staff_chat_send_locks"]
    lock = locks.setdefault(uid, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        previous = request.app["staff_chat_last_sent"].get(uid, -100.0)
        if now - previous < SEND_INTERVAL:
            return web.json_response(
                {"error": "Отправлять сообщения можно не чаще одного раза в 2 секунды"},
                status=429,
            )
        # Reserve before calling Telegram: a retry during a network timeout
        # must not immediately produce another message.
        request.app["staff_chat_last_sent"][uid] = now
        try:
            kwargs = {"chat_id": settings.community_chat_id,
                      "reply_parameters": reply_to}
            if file:
                filename, content_bytes = file
                upload = BufferedInputFile(content_bytes, filename=filename)
                extension = PurePath(filename).suffix.lower()
                if extension in _PHOTO:
                    sent = await bot.send_photo(**kwargs, photo=upload, caption=body,
                                                parse_mode=None)
                elif extension in _VIDEO:
                    sent = await bot.send_video(**kwargs, video=upload, caption=body,
                                                parse_mode=None, supports_streaming=True)
                elif extension == ".gif":
                    sent = await bot.send_animation(**kwargs, animation=upload, caption=body,
                                                    parse_mode=None)
                elif extension in _AUDIO:
                    sent = await bot.send_audio(**kwargs, audio=upload, caption=body,
                                                parse_mode=None)
                else:
                    sent = await bot.send_document(**kwargs, document=upload, caption=body,
                                                   parse_mode=None)
            else:
                sent = await bot.send_message(**kwargs, text=body, parse_mode=None)
        except TelegramRetryAfter as exc:
            return web.json_response(
                {"error": f"Telegram просит подождать {min(int(exc.retry_after), 60)} сек."},
                status=429,
            )
        except TelegramAPIError:
            logger.exception("Staff chat composer Telegram send failed")
            return web.json_response({"error": _QUIET_ERRORS}, status=502)
        except (OSError, asyncio.TimeoutError):
            logger.exception("Staff chat composer transport failed")
            return web.json_response(
                {"error": "Ответ Telegram не получен. Проверь чат, прежде чем повторять отправку."},
                status=502,
            )
        # The outgoing middleware normally captures this. Explicit capture also
        # covers endpoints called with a non-middleware bot in tests.
        try:
            await capture(db, settings, sent)
        except Exception:
            logger.exception("Staff chat composer: message sent but archive failed")
        return web.json_response({"ok": True, "message_id": sent.message_id})


async def send_text(request: web.Request) -> web.Response:
    credentials, denied = await _member(request)
    if denied is not None:
        return denied
    if request.content_length and request.content_length > 16 * 1024:
        return web.json_response({"error": "Слишком большой запрос"}, status=413)
    try:
        payload = await request.json()
    except (ValueError, TypeError):
        return web.json_response({"error": "Некорректный запрос"}, status=400)
    if not isinstance(payload, dict) or set(payload) - {"text", "reply_to"}:
        return web.json_response({"error": "Некорректный запрос"}, status=400)
    return await _publish(
        request, text=payload.get("text", ""), reply=payload.get("reply_to"),
        file=None,
    )


async def send_attachment(request: web.Request) -> web.Response:
    credentials, denied = await _member(request)
    if denied is not None:
        return denied
    if request.content_length is not None and request.content_length > MAX_UPLOAD + 64 * 1024:
        return web.json_response({"error": "Размер файла не должен превышать 12 МБ"}, status=413)
    if not request.content_type.startswith("multipart/form-data"):
        return web.json_response({"error": "Нужно выбрать файл"}, status=400)
    values = {}
    attachment = None
    try:
        reader = await request.multipart()
        while part := await reader.next():
            if part.name not in {"text", "reply_to", "file"} or part.name in values:
                raise ValueError("Некорректные поля")
            if part.name == "file":
                if attachment is not None:
                    raise ValueError("Можно прикрепить только один файл")
                filename = PurePath(str(part.filename or "").replace("\\", "/")).name[:100]
                extension = PurePath(filename).suffix.lower()
                if not filename or extension not in _ALLOWED_EXTENSIONS:
                    raise ValueError("Этот тип файла пока не поддерживается")
                raw = bytearray()
                while True:
                    chunk = await part.read_chunk(128 * 1024)
                    if not chunk:
                        break
                    if len(raw) + len(chunk) > MAX_UPLOAD:
                        raise ValueError("Размер файла не должен превышать 12 МБ")
                    raw.extend(chunk)
                if not raw:
                    raise ValueError("Файл пуст")
                attachment = (filename, bytes(raw))
            else:
                chunk = await part.read(decode=True)
                if len(chunk) > 6000:
                    raise ValueError("Слишком длинное поле")
                values[part.name] = chunk.decode("utf-8")
        if attachment is None:
            raise ValueError("Выбери файл")
        raw_reply = values.get("reply_to", "")
        if raw_reply and not (raw_reply.isdecimal() and len(raw_reply) <= 12):
            raise ValueError("Некорректный ответ")
        reply = int(raw_reply) if raw_reply else None
    except (ValueError, UnicodeDecodeError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except web.HTTPRequestEntityTooLarge:
        return web.json_response({"error": "Размер файла не должен превышать 12 МБ"}, status=413)
    return await _publish(request, text=values.get("text", ""), reply=reply, file=attachment)
