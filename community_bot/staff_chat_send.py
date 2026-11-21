"""Staff-only experimental Telegram group composer for the NORA Mini App.

Telegram Bot API always sends as the bot; author attribution is explicit.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import tempfile
from pathlib import Path, PurePath

from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import BufferedInputFile, InputMediaPhoto, ReplyParameters
from aiohttp import web

from community_bot.staff_chat import capture, staff_allowed
from community_bot import staff_chat_delivery as dispatch

logger = logging.getLogger(__name__)
MAX_TEXT = 3000
MAX_CAPTION = 800
MAX_UPLOAD = 12 * 1024 * 1024
MAX_ALBUM_ITEMS = 6
MAX_BATCH_UPLOAD = 30 * 1024 * 1024
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


def _is_photo(filename: str, data: bytes) -> bool:
    suffix = PurePath(filename).suffix.lower()
    return (suffix in {".jpg", ".jpeg"} and data.startswith(b"\xff\xd8\xff")) or (
        suffix == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n")
    )


async def _voice_ogg(filename: str, payload: bytes) -> bytes:
    """Transcode supported browser formats into Telegram-compatible Ogg/Opus.

    FFmpeg is installed in the production image. No shell or caller-controlled
    options are passed to it, and temporary input/output are always deleted.
    """
    if PurePath(filename).suffix.lower() not in {
        ".m4a", ".mp3", ".ogg", ".oga", ".opus", ".webm",
    }:
        raise ValueError("Формат записи не поддерживается")
    with tempfile.TemporaryDirectory(prefix="nora-voice-") as folder:
        source = Path(folder) / ("input" + PurePath(filename).suffix.lower())
        target = Path(folder) / "voice.ogg"
        source.write_bytes(payload)
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-y", "-i", str(source), "-map", "0:a:0", "-vn",
                "-t", "120", "-ac", "1", "-c:a", "libopus", "-b:a", "48k",
                "-f", "ogg", str(target),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            logger.error("Voice encoder unavailable: %s", type(exc).__name__)
            raise ValueError("Запись голосовых временно недоступна") from exc
        try:
            _, errors = await asyncio.wait_for(proc.communicate(), timeout=28)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.communicate()
            raise ValueError("Обработка голосового превысила время ожидания") from exc
        if proc.returncode != 0 or not target.is_file():
            logger.warning("Voice transcoding failed: %s", errors[-350:].decode("utf-8", "replace"))
            raise ValueError("Не удалось обработать голосовое. Попробуй записать ещё раз")
        result = target.read_bytes()
        if not result or len(result) > MAX_UPLOAD:
            raise ValueError("Голосовое слишком большое")
        return result


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
                   files: list[tuple[str, bytes]] | None, kind: str = "file",
                   operation_id: object = None):
    credentials, denied = await _member(request)
    if denied is not None:
        return denied
    db, settings, bot, uid = credentials
    files = files or []
    try:
        content = _validate_text(text, bool(files))
        reply_to = await _reply(db, settings.community_chat_id, reply)
        if kind not in {"file", "voice"} or (kind == "voice" and len(files) != 1):
            raise ValueError("Некорректный тип вложения")
        if len(files) > 1 and (
            kind != "file" or len(files) > MAX_ALBUM_ITEMS
            or not all(_is_photo(name, data) for name, data in files)
        ):
            raise ValueError("Альбом может содержать от 2 до 6 изображений JPG или PNG")
        if sum(len(blob) for _, blob in files) > MAX_BATCH_UPLOAD:
            raise ValueError("Альбом слишком большой")
        operation_id = dispatch.validate_key(operation_id)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    name = _author(await db.get_user(uid), request["actor"])
    attribution = f"💬 {name} · через Mini App Норы"
    body = f"{attribution}\n\n{content}" if content else attribution
    locks = request.app["staff_chat_send_locks"]
    lock = locks.setdefault(uid, asyncio.Lock())
    async with lock:
        if operation_id:
            digest = dispatch.payload_hash(
                settings.community_chat_id, content,
                reply_to.message_id if reply_to else None, kind, files,
            )
            outcome, receipt = await dispatch.claim(db, uid, operation_id, digest)
            if outcome == "conflict":
                return web.json_response(
                    {"error": "Идентификатор используется для другого сообщения"},
                    status=409,
                )
            if outcome == "existing":
                return web.json_response(dispatch.response_data(receipt),
                                         headers={"Cache-Control": "no-store"})
        now = time.monotonic()
        previous = request.app["staff_chat_last_sent"].get(uid, -100.0)
        if now - previous < SEND_INTERVAL:
            if operation_id:
                await dispatch.finish(db, uid, operation_id, "failed", error="Слишком частая отправка")
            return web.json_response(
                {"error": "Отправлять сообщения можно не чаще одного раза в 2 секунды",
                 "state": "failed" if operation_id else None},
                status=429,
            )
        # Reserve the interval before Telegram: a network timeout can still
        # mean that Telegram delivered the message successfully.
        request.app["staff_chat_last_sent"][uid] = now
        try:
            kwargs = {"chat_id": settings.community_chat_id, "reply_parameters": reply_to}
            if kind == "voice":
                filename, payload = files[0]
                gate = request.app.get("staff_chat_voice_gate")
                if gate is not None:
                    async with gate:
                        normalized = await _voice_ogg(filename, payload)
                else:
                    normalized = await _voice_ogg(filename, payload)
                sent = await bot.send_voice(
                    **kwargs, voice=BufferedInputFile(normalized, filename="nora-voice.ogg"),
                    caption=body, parse_mode=None,
                )
            elif len(files) > 1:
                media = [
                    InputMediaPhoto(
                        media=BufferedInputFile(payload, filename=filename),
                        caption=body if index == 0 else None, parse_mode=None,
                    )
                    for index, (filename, payload) in enumerate(files)
                ]
                sent = await bot.send_media_group(**kwargs, media=media)
            elif files:
                filename, content_bytes = files[0]
                upload = BufferedInputFile(content_bytes, filename=filename)
                extension = PurePath(filename).suffix.lower()
                if extension in _PHOTO:
                    sent = await bot.send_photo(**kwargs, photo=upload, caption=body, parse_mode=None)
                elif extension in _VIDEO:
                    sent = await bot.send_video(
                        **kwargs, video=upload, caption=body, parse_mode=None, supports_streaming=True,
                    )
                elif extension == ".gif":
                    sent = await bot.send_animation(**kwargs, animation=upload, caption=body, parse_mode=None)
                elif extension in _AUDIO:
                    sent = await bot.send_audio(**kwargs, audio=upload, caption=body, parse_mode=None)
                else:
                    sent = await bot.send_document(**kwargs, document=upload, caption=body, parse_mode=None)
            else:
                sent = await bot.send_message(**kwargs, text=body, parse_mode=None)
        except ValueError as exc:
            if operation_id:
                await dispatch.finish(db, uid, operation_id, "failed", error=str(exc))
            return web.json_response({"error": str(exc), "state": "failed"}, status=400)
        except TelegramRetryAfter as exc:
            if operation_id:
                await dispatch.finish(db, uid, operation_id, "failed",
                                      error="Telegram ограничил отправку")
            return web.json_response(
                {"error": f"Telegram просит подождать {min(int(exc.retry_after), 60)} сек."},
                status=429,
            )
        except TelegramAPIError:
            logger.exception("Staff chat composer Telegram send failed")
            if operation_id:
                await dispatch.finish(db, uid, operation_id, "uncertain",
                                      error="Неизвестно, принял ли Telegram сообщение")
            return web.json_response(
                {"error": _QUIET_ERRORS, "state": "uncertain" if operation_id else None}, status=502,
            )
        except (OSError, asyncio.TimeoutError):
            logger.exception("Staff chat composer transport failed")
            if operation_id:
                await dispatch.finish(db, uid, operation_id, "uncertain",
                                      error="Ответ Telegram не получен")
            return web.json_response(
                {"error": "Ответ Telegram не получен. Проверь чат, прежде чем повторять отправку.",
                 "state": "uncertain" if operation_id else None},
                status=502,
            )
        messages = sent if isinstance(sent, (list, tuple)) else [sent]
        if not messages:
            if operation_id:
                await dispatch.finish(db, uid, operation_id, "uncertain",
                                      error="Telegram не подтвердил отправку альбома")
            return web.json_response(
                {"error": "Telegram не подтвердил отправку альбома. Проверь чат.",
                 "state": "uncertain" if operation_id else None}, status=502,
            )
        if operation_id:
            await dispatch.finish(
                db, uid, operation_id, "sent", ids=[m.message_id for m in messages],
            )
        try:
            for message in messages:
                # The Bot session middleware already archives successful sends.
                # Only perform the fallback capture if that middleware did not.
                existing = await db.fetchone(
                    "SELECT 1 FROM staff_chat_messages WHERE chat_id=? AND message_id=?",
                    (settings.community_chat_id, message.message_id),
                )
                if not existing:
                    await capture(db, settings, message)
        except Exception:
            logger.exception("Staff chat composer: message sent but archive failed")
        receipt = {
            "ok": True, "message_id": messages[0].message_id,
            "message_ids": [m.message_id for m in messages],
        }
        if operation_id:
            receipt.update(state="sent", operation_id=operation_id)
        return web.json_response(receipt)


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
    if not isinstance(payload, dict) or set(payload) - {"text", "reply_to", "operation_id"}:
        return web.json_response({"error": "Некорректный запрос"}, status=400)
    return await _publish(
        request, text=payload.get("text", ""), reply=payload.get("reply_to"),
        files=None, operation_id=payload.get("operation_id"),
    )


async def send_attachment(request: web.Request) -> web.Response:
    credentials, denied = await _member(request)
    if denied is not None:
        return denied
    if request.content_length is not None and request.content_length > MAX_BATCH_UPLOAD + 96 * 1024:
        return web.json_response({"error": "Вложения превышают 30 МБ"}, status=413)
    if not request.content_type.startswith("multipart/form-data"):
        return web.json_response({"error": "Нужно выбрать файл"}, status=400)
    values: dict[str, str] = {}
    attachments: list[tuple[str, bytes]] = []
    consumed = 0
    try:
        reader = await request.multipart()
        while part := await reader.next():
            if part.name not in {"text", "reply_to", "file", "kind", "operation_id"} or (
                part.name != "file" and part.name in values
            ):
                raise ValueError("Некорректные поля")
            if part.name == "file":
                if len(attachments) >= MAX_ALBUM_ITEMS:
                    raise ValueError("В одном альбоме не больше 6 файлов")
                filename = PurePath(str(part.filename or "").replace("\\", "/")).name[:100]
                extension = PurePath(filename).suffix.lower()
                if not filename or extension not in _ALLOWED_EXTENSIONS:
                    raise ValueError("Этот тип файла пока не поддерживается")
                raw = bytearray()
                while True:
                    chunk = await part.read_chunk(128 * 1024)
                    if not chunk:
                        break
                    consumed += len(chunk)
                    if len(raw) + len(chunk) > MAX_UPLOAD or consumed > MAX_BATCH_UPLOAD:
                        raise ValueError("Один файл до 12 МБ, все вместе до 30 МБ")
                    raw.extend(chunk)
                if not raw:
                    raise ValueError("Файл пуст")
                attachments.append((filename, bytes(raw)))
            else:
                chunk = await part.read(decode=True)
                if len(chunk) > 6000:
                    raise ValueError("Слишком длинное поле")
                values[part.name] = chunk.decode("utf-8")
        if not attachments:
            raise ValueError("Выбери файл")
        raw_reply = values.get("reply_to", "")
        if raw_reply and not (raw_reply.isdecimal() and len(raw_reply) <= 12):
            raise ValueError("Некорректный ответ")
        reply = int(raw_reply) if raw_reply else None
        kind = values.get("kind", "file")
    except (ValueError, UnicodeDecodeError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except web.HTTPRequestEntityTooLarge:
        return web.json_response({"error": "Вложения слишком большие"}, status=413)
    return await _publish(
        request, text=values.get("text", ""), reply=reply,
        files=attachments, kind=kind, operation_id=values.get("operation_id"),
    )
