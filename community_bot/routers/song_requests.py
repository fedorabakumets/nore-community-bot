"""Text-triggered Yandex Music requests for the community chat.

Disabled by default. Session cookies are read from a deployment secret and
never stored in the database or sent to a user. Only enable chat uploads for
material that the community is allowed to redistribute.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
import re
import secrets
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import aiohttp
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from mutagen.mp3 import MP3

from community_bot.config import Settings
from community_bot.database import Database
from community_bot.ephemeral import delete_user_command

router = Router(name="song_requests")
logger = logging.getLogger(__name__)

_REQUEST = re.compile(r"^\s*(?:нора[\s,:\-]+)?песня(?:[\s,:\-]+|$)(.*)$", re.I | re.S)
_SEND_LOCK = asyncio.Lock()
_CHOICES: dict[str, "Choices"] = {}
MAX_RESULTS = 5
MAX_FILE_BYTES = 48 * 1024 * 1024
COOLDOWN_SECONDS = 300
CHOICE_TTL = 15 * 60
API_URL = "https://api.music.yandex.ru/search"


@dataclass(frozen=True)
class Song:
    id: str
    album_id: str | None
    title: str
    artist: str
    duration: int

    @property
    def url(self) -> str:
        if self.album_id:
            return f"https://music.yandex.ru/album/{self.album_id}/track/{self.id}"
        return f"https://music.yandex.ru/track/{self.id}"


@dataclass
class Choices:
    user_id: int
    chat_id: int
    expires: float
    tracks: list[Song]


class SongError(Exception):
    """Expected configuration or provider failure safe to show in chat."""


def enabled() -> bool:
    return os.getenv("NORA_SONGS_ENABLED", "").lower() in {"1", "true", "yes"}


def song_query(text: str | None) -> str | None:
    match = _REQUEST.fullmatch(text or "")
    if match is None:
        return None
    return match.group(1).strip().strip('«»"“”').strip()[:120]


def is_song_request(text: str | None) -> bool:
    return song_query(text) is not None


def _cookie_bytes() -> bytes:
    encoded = os.getenv("YANDEX_MUSIC_COOKIES_B64", "").strip()
    if not encoded:
        raise SongError("Яндекс Музыка пока не подключена. Нужна авторизованная сессия владельца.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise SongError("Неверный формат YANDEX_MUSIC_COOKIES_B64.") from exc
    if len(raw) > 256_000 or b"\tSession_id\t" not in raw:
        raise SongError("В cookies.txt не найден Session_id от Яндекса. Экспортируй актуальную сессию.")
    return raw


def _cookie_header(raw: bytes) -> str:
    """Forward cookies only to the fixed Yandex Music API host."""
    result = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif line.startswith("#"):
            continue
        cells = line.split("\t", 6)
        if len(cells) != 7:
            continue
        domain, _, _, _, _, name, value = cells
        if domain.lstrip(".").lower() == "yandex.ru" and name:
            result.append(f"{name}={value}")
    return "; ".join(result)


def parse_search_results(data: dict) -> list[Song]:
    result = data.get("result", data)
    if not isinstance(result, dict):
        return []
    tracks = result.get("tracks") or {}
    entries = tracks.get("results", []) if isinstance(tracks, dict) else []
    songs: list[Song] = []
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        track_id = str(item.get("id", ""))
        if not track_id.isdecimal() or track_id in seen or item.get("available") is False:
            continue
        artists = item.get("artists") or []
        artist = ", ".join(
            entry.get("name", "") for entry in artists
            if isinstance(entry, dict) and isinstance(entry.get("name"), str)
        ) or "Неизвестный исполнитель"
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        albums = item.get("albums") or []
        album_id = str(albums[0].get("id")) if albums and isinstance(albums[0], dict) else None
        if album_id and not album_id.isdecimal():
            album_id = None
        duration_ms = item.get("durationMs")
        try:
            duration = max(0, int(duration_ms) // 1000)
        except (TypeError, ValueError):
            duration = 0
        songs.append(Song(track_id, album_id, title[:180], artist[:180], duration))
        seen.add(track_id)
        if len(songs) == MAX_RESULTS:
            break
    return songs


async def find_songs(query: str) -> list[Song]:
    cookies = _cookie_bytes()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "x-yandex-music-client": "YandexMusicWebNext/1.0.0",
        "Cookie": _cookie_header(cookies),
    }
    timeout = aiohttp.ClientTimeout(total=14)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(API_URL, params={"text": query, "type": "track", "page": "0"},
                                   headers=headers, allow_redirects=False) as response:
                if response.status in (401, 403):
                    raise SongError("Яндекс отклонил сессию. Нужно заново войти в аккаунт.")
                if response.status != 200:
                    raise SongError("Яндекс Музыка пока не отвечает на поиск. Попробуй позднее.")
                payload = await response.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise SongError("Не удалось подключиться к Яндекс Музыке.") from exc
    if not isinstance(payload, dict):
        raise SongError("Яндекс вернул неожиданный ответ поиска.")
    return parse_search_results(payload)


def is_full_track(actual: float, expected: int) -> bool:
    """Reject 13–30 second preview files masquerading as full tracks."""
    if actual <= 0:
        return False
    if expected > 0:
        return actual >= max(1, expected * 0.72)
    return actual >= 40


def _download_sync(song: Song, directory: str, cookie_file: str) -> str:
    import yt_dlp

    options = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "noplaylist": True,
        "outtmpl": str(Path(directory) / "%(id)s.%(ext)s"),
        "format": "bestaudio[ext=mp3]",
        "cookiefile": cookie_file,
        "socket_timeout": 20,
        "retries": 2,
        "max_filesize": MAX_FILE_BYTES,
        "cachedir": False,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.extract_info(song.url, download=True)
    files = list(Path(directory).glob("*.mp3"))
    if len(files) != 1:
        raise SongError("Яндекс не отдал MP3. Возможно, доступен только другой формат.")
    audio = files[0]
    if not 0 < audio.stat().st_size <= MAX_FILE_BYTES:
        raise SongError("Файл превышает лимит размера Telegram.")
    try:
        actual = MP3(str(audio)).info.length
    except Exception as exc:
        raise SongError("Не удалось проверить полученный MP3.") from exc
    if not is_full_track(actual, song.duration):
        raise SongError("Яндекс отдал только фрагмент трека. Проверь подписку и сессию.")
    return str(audio)


async def _remaining(db: Database, user_id: int, chat_id: int) -> int:
    now = time.time()
    timestamps = (
        await db.get_bot_state(f"song:last_user:{user_id}"),
        await db.get_bot_state(f"song:last_chat:{chat_id}"),
    )
    return max((max(0, int(float(value) + COOLDOWN_SECONDS - now)) for value in timestamps if value), default=0)


async def send_song(callback: CallbackQuery, db: Database, choice: Choices, song: Song) -> None:
    bot = callback.bot
    if bot is None:
        return
    async with _SEND_LOCK:
        remaining = await _remaining(db, choice.user_id, choice.chat_id)
        if remaining:
            await bot.send_message(choice.chat_id, f"Следующую песню можно запросить через {remaining} сек.")
            return
        cache_key = f"song:file_id:{song.id}"
        cached = await db.get_bot_state(cache_key)
        if cached:
            try:
                await bot.send_audio(choice.chat_id, cached, title=song.title, performer=song.artist,
                                     duration=song.duration or None, caption=song.url)
            except TelegramBadRequest:
                cached = None
            else:
                await _mark_sent(db, choice)
                return

        status = await bot.send_message(choice.chat_id, f"🎧 Загружаю: {song.artist} — {song.title}")
        try:
            with tempfile.TemporaryDirectory(prefix="nora-song-") as temp:
                cookie_file = Path(temp) / "cookies.txt"
                cookie_file.write_bytes(_cookie_bytes())
                cookie_file.chmod(0o600)
                path = await asyncio.wait_for(
                    asyncio.to_thread(_download_sync, song, temp, str(cookie_file)), timeout=100,
                )
                sent = await bot.send_audio(
                    choice.chat_id, FSInputFile(path), title=song.title,
                    performer=song.artist, duration=song.duration or None,
                    caption=song.url,
                )
                if sent.audio and sent.audio.file_id:
                    await db.set_bot_state(cache_key, sent.audio.file_id)
                await _mark_sent(db, choice)
        except (asyncio.TimeoutError, TelegramAPIError):
            logger.warning("Music download/upload failed for track %s", song.id)
            await bot.send_message(choice.chat_id, "Не удалось отправить песню. Повтори запрос позднее.")
        except SongError as exc:
            await bot.send_message(choice.chat_id, str(exc))
        except Exception:
            logger.exception("Song download failed for track %s", song.id)
            await bot.send_message(choice.chat_id, "Ошибка загрузки песни. Проверь сессию или попробуй другой трек.")
        finally:
            try:
                await status.delete()
            except TelegramAPIError:
                pass


async def _mark_sent(db: Database, choice: Choices) -> None:
    now = str(time.time())
    await db.set_bot_state(f"song:last_user:{choice.user_id}", now)
    await db.set_bot_state(f"song:last_chat:{choice.chat_id}", now)


@router.message(F.text.func(is_song_request), F.chat.type.in_({"private", "group", "supergroup"}), StateFilter(None))
async def request_song(message: Message, settings: Settings) -> None:
    if (not message.from_user or message.from_user.is_bot or message.sender_chat
            or message.forward_origin or message.via_bot):
        return
    if message.chat.type != "private" and message.chat.id != settings.community_chat_id:
        return
    query = song_query(message.text)
    if query is None:
        return
    if not enabled():
        await message.answer("Музыкальные запросы пока не подключены. Нужна настройка Яндекса владельцем.")
        return
    if len(query) < 2:
        await message.answer("Напиши: Нора песня Кино Группа крови")
        return
    try:
        tracks = await find_songs(query)
    except SongError as exc:
        await message.answer(str(exc))
        return
    if not tracks:
        await message.answer("Песен по этому запросу не нашла.")
        return
    now = time.monotonic()
    for key in list(_CHOICES):
        if _CHOICES[key].expires <= now:
            _CHOICES.pop(key, None)
    if len(_CHOICES) >= 200:
        _CHOICES.pop(next(iter(_CHOICES)))
    key = secrets.token_urlsafe(6)
    _CHOICES[key] = Choices(message.from_user.id, message.chat.id, now + CHOICE_TTL, tracks)
    buttons = [
        [InlineKeyboardButton(text=f"{i + 1}. {song.artist} — {song.title}"[:64],
                              callback_data=f"song:{key}:{i}")]
        for i, song in enumerate(tracks)
    ]
    await message.answer("🎵 Выбери песню:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    if message.chat.type != "private":
        await delete_user_command(message, message.bot)


@router.callback_query(F.data.startswith("song:"))
async def song_chosen(callback: CallbackQuery, db: Database) -> None:
    try:
        _, key, raw_index = (callback.data or "").split(":", 2)
        index = int(raw_index)
        choice = _CHOICES.get(key)
        if choice is None or choice.expires <= time.monotonic() or not 0 <= index < len(choice.tracks):
            await callback.answer("Поиск устарел. Запроси песню ещё раз.", show_alert=True)
            return
        if (callback.from_user.id != choice.user_id or callback.message is None
                or callback.message.chat.id != choice.chat_id):
            await callback.answer("Выбрать песню может только автор запроса.", show_alert=True)
            return
    except (ValueError, AttributeError):
        await callback.answer("Неверный запрос.", show_alert=True)
        return
    await callback.answer("Загружаю песню…")
    await send_song(callback, db, choice, choice.tracks[index])
