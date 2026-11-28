"""One Telegram audio file per community profile."""
from __future__ import annotations

import json
import re
from asyncio import Lock, Semaphore
from io import BytesIO
from pathlib import PurePath
from uuid import uuid4
from weakref import WeakValueDictionary

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, InputMediaAudio, InputRichBlockAudio, InputRichBlockParagraph

MAX_TRACK_MB = 20
MAX_TRACK_BYTES = MAX_TRACK_MB * 1024 * 1024
COMMAND = re.compile(r"(?:нора[ ,:]+)?добавить|\+", re.IGNORECASE)
FORMATS = {".mp3": "audio/mpeg", ".m4a": "audio/mp4"}
_LOCKS: WeakValueDictionary[int, Lock] = WeakValueDictionary()
_DOWNLOADS = Semaphore(3)


def track_key(uid):
    return f"profile_track:{uid}"


async def get_track(db, uid):
    raw = await db.get_bot_state(track_key(uid))
    return json.loads(raw) if raw else None


def track_summary(track):
    if not track:
        return None
    summary = {name: track[name] for name in ("title", "artist", "duration", "revision")}
    if track.get("cover"):
        summary["cover"] = track["cover"]
    return summary


def audio_block(track):
    if track["file_id"].startswith("catalog:"):
        return InputRichBlockParagraph(text=f"🎧 {track['artist']} · {track['title']} (Mini App)")
    return InputRichBlockAudio(audio=InputMediaAudio(
        media=track["file_id"], title=track["title"], performer=track["artist"] or None,
    ))


def _attachment(message):
    if not message:
        return None, None
    if message.audio or message.document:
        return message.audio, message.document
    if message.rich_message:
        tracks = [block.audio for block in message.rich_message.blocks if block.type == "audio"]
        if len(tracks) == 1:
            return tracks[0], None
    return None, None


def track_command(message):
    body = (message.text or message.caption or "").strip()
    if not COMMAND.fullmatch(body):
        return False
    return any(_attachment(message)) or any(_attachment(message.reply_to_message)) or body.casefold().startswith("нора")


class TrackBuffer(BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_TRACK_BYTES:
            raise ValueError(f"Трек должен быть не больше {MAX_TRACK_MB} МБ.")
        return super().write(data)


async def download_track(bot, file_id):
    async with _DOWNLOADS:
        with TrackBuffer() as output:
            await bot.download(file_id, destination=output, timeout=25)
            return output.getvalue()


async def save_from_message(message, db, settings):
    from community_bot.access import private_allowed
    from community_bot.ephemeral import reply_ttl
    from community_bot.helpers import register_telegram_user
    from community_bot.private_rich import standalone_rich_message
    from community_bot.reply_rich import bot_publication

    user = message.from_user
    if (not user or user.is_bot or message.sender_chat
            or (message.chat.type != "private" and message.chat.id != settings.community_chat_id)):
        return
    audio, document = _attachment(message)
    if not audio and not document:
        audio, document = _attachment(message.reply_to_message)
    with standalone_rich_message(), bot_publication(), reply_ttl(None):
        async with _LOCKS.setdefault(user.id, Lock()):
            ban = await db.ban_reset_state(user.id)
            if (message.chat.type == "private" or ban) and not await private_allowed(db, settings, user.id, ban=ban):
                return
            if message.chat.type != "private":
                await register_telegram_user(db, user)
            try:
                track = await _build_track(message, audio, document)
            except ValueError as error:
                await message.reply(str(error), allow_sending_without_reply=True)
                return
            except (TelegramAPIError, TimeoutError, OSError):
                await message.reply(
                    "Не удалось открыть аудиофайл. Попробуй отправить его ещё раз.", allow_sending_without_reply=True,
                )
                return
            async with db.connect() as conn:
                await conn.execute("BEGIN IMMEDIATE")
                row = await (await conn.execute(
                    "SELECT value FROM bot_state WHERE key=?", (f"ban_reset:{user.id}",),
                )).fetchone()
                if (json.loads(row["value"]) if row else {}) != ban:
                    return
                await conn.execute(
                    "INSERT INTO bot_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (track_key(user.id), json.dumps(track, ensure_ascii=False)),
                )
                await conn.commit()
            await message.reply("🎵 Трек в профиле обновлён.", allow_sending_without_reply=True)


async def _build_track(message, audio, document):
    media = audio or document
    if not media:
        raise ValueError("Ответь «добавить» или «+» на аудиофайл MP3 или M4A.")
    if media.file_size and media.file_size > MAX_TRACK_BYTES:
        raise ValueError(f"Трек должен быть не больше {MAX_TRACK_MB} МБ.")
    filename = media.file_name or ""
    ext = PurePath(filename).suffix.lower()
    mime = FORMATS.get(ext)
    if audio and not mime:
        mime = {"audio/mpeg": "audio/mpeg", "audio/mp3": "audio/mpeg", "audio/mp4": "audio/mp4",
                "audio/x-m4a": "audio/mp4", "audio/m4a": "audio/mp4"}.get(audio.mime_type)
        if not audio.mime_type:
            mime = "audio/mpeg"
    if not mime:
        raise ValueError("Для профиля подойдёт файл MP3 или M4A.")
    fallback_title = PurePath(filename).stem or "Трек профиля"
    if document:
        data = await download_track(message.bot, document.file_id)
        if mime == "audio/mpeg":
            valid = len(data) >= 12 and (data.startswith(b"ID3") or data[0] == 255 and data[1] & 224 == 224)
        else:
            valid = len(data) >= 12 and data[4:8] == b"ftyp"
        if not valid:
            raise ValueError("Файл не удалось распознать как MP3 или M4A.")
        sent = await message.reply_audio(
            BufferedInputFile(data, filename="track" + ext), allow_sending_without_reply=True,
        )
        audio = sent.audio
        if not audio:
            raise ValueError("Telegram не распознал аудио в этом файле.")
    title = " ".join((audio.title or fallback_title).split())[:160] or "Трек профиля"
    return {"file_id": audio.file_id, "mime": mime, "title": title,
            "artist": " ".join((audio.performer or "").split())[:160],
            "duration": audio.duration, "revision": uuid4().hex}
