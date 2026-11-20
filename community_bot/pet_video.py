"""Bounded asynchronous delivery of public video and music files via Telegram."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from community_bot.nora import strip_address
from community_bot.pet_progress import VIDEO_DAILY_LIMIT, VIDEO_MAX_MB, level, moscow_now
from community_bot.private_rich import standalone_rich_message
from community_bot.profile_track import MAX_TRACK_MB
from community_bot.reply_rich import bot_publication

logger = logging.getLogger(__name__)
WORKERS = 2
QUEUE_SIZE = 6
DOWNLOAD_SECONDS = 75
SEND_SECONDS = 45
MUSIC_UNAVAILABLE = 3
CACHE_SIZE = 1000
COMMAND = re.compile(r"https?://\S+", re.IGNORECASE)
PLATFORMS = {
    "vm.tiktok.com": r"/[\w-]+/?",
    "vt.tiktok.com": r"/[\w-]+/?",
    "tiktok.com": r"/(?:@[\w.\-]+/video/\d+|t/[\w-]+)/?",
    "instagram.com": r"/reel/[\w-]+/?",
    "youtube.com": r"/shorts/[\w-]{11}/?",
    "music.yandex.ru": r"/(?:album/[0-9]{1,16}/)?track/[0-9]{1,16}/?",
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS pet_video_deliveries (
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    PRIMARY KEY (chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS pet_video_deliveries_user_day ON pet_video_deliveries(user_id, day);
CREATE TABLE IF NOT EXISTS pet_video_cache (
    url TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def video_command(text):
    body = strip_address(text or "")
    return body if body and COMMAND.fullmatch(body) else None


def canonical_url(raw):
    if not raw or len(raw) > 1500:
        return None
    try:
        parts = urlsplit(raw)
        host = parts.hostname or ""
        if (parts.scheme != "https" or parts.username is not None
                or parts.password is not None or parts.port not in (None, 443)):
            return None
    except ValueError:
        return None
    domain = host.removeprefix("www.").removeprefix("m.")
    pattern = PLATFORMS.get(domain)
    if not pattern or not re.fullmatch(pattern, parts.path, re.ASCII):
        return None
    canonical_host = "www.tiktok.com" if domain == "tiktok.com" else domain
    return f"https://{canonical_host}{parts.path.rstrip('/')}/"


def music_alternative():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть @yndxapp", url="https://t.me/yndxapp"),
    ]])


async def music_failure(message, text):
    with standalone_rich_message(), bot_publication():
        await message.reply(text, reply_markup=music_alternative())


async def send_media(message, music, media, **options):
    if music:
        with standalone_rich_message(), bot_publication():
            return await asyncio.wait_for(message.reply_audio(media, **options), SEND_SECONDS)
    return await asyncio.wait_for(message.reply_video(media), SEND_SECONDS)


async def download(url, path):
    env = {"PATH": os.defpath, "PYTHONIOENCODING": "utf-8"}
    if os.name == "nt":
        env["SystemRoot"] = os.environ["SystemRoot"]
        env["PATH"] = os.environ.get("PATH", os.defpath)
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "community_bot.pet_video_worker", url, str(path), env=env,
        start_new_session=os.name == "posix",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        return await asyncio.wait_for(process.wait(), DOWNLOAD_SECONDS)
    finally:
        if process.returncode is None:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            await process.wait()


@dataclass(frozen=True)
class VideoJob:
    message: Message
    url: str
    user_id: int


class PetVideoQueue:
    def __init__(self, db):
        self.db = db
        self.queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.tasks = []
        self.active_users = set()

    def start(self):
        self.tasks = [asyncio.create_task(self._worker()) for _ in range(WORKERS)]

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def _quota(self, user_id, day):
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS total FROM pet_video_deliveries WHERE user_id=? AND day=?", (user_id, day),
        )
        return row["total"] < VIDEO_DAILY_LIMIT

    async def _access_error(self, user_id, kind="видео"):
        if not await self.db.feature_enabled("tamagotchi"):
            return f"Скачивание {kind} недоступно: питомцы временно отключены."
        pet = await self.db.get_pet(user_id)
        if not pet:
            return f"Чтобы скачивать {kind}, сначала заведи питомца и достигни 3-го уровня."
        if await level(self.db, user_id) < 3:
            return f"Скачивание {kind} открывается на 3-м уровне питомца."
        if pet.get("expedition_until"):
            return f"Пока питомец в походе, скачивание {kind} недоступно. Его можно вернуть через «Питомец»."
        return None

    async def _delivery_error(self, user_id, kind="видео"):
        error = await self._access_error(user_id, kind)
        if error:
            return error
        if not await self._quota(user_id, moscow_now().date().isoformat()):
            return f"Сегодня уже получено {VIDEO_DAILY_LIMIT} видео или треков. Лимит обновится в 00:00 МСК."
        return None

    async def enqueue(self, message, raw_url):
        url = canonical_url(raw_url)
        if not url:
            await message.reply("Пришли ссылку на TikTok, Instagram Reels, YouTube Shorts или трек Яндекс Музыки.")
            return
        user_id = message.from_user.id
        kind = "музыки" if url.startswith("https://music.yandex.ru/") else "видео"
        error = await self._access_error(user_id, kind)
        if error:
            await message.reply(error)
            return
        day = moscow_now().date().isoformat()
        if message.date and message.date.astimezone(moscow_now().tzinfo).date().isoformat() != day:
            return
        if not await self._quota(user_id, day):
            await message.reply(
                f"Сегодня уже получено {VIDEO_DAILY_LIMIT} видео или треков. Лимит обновится в 00:00 МСК.",
            )
            return
        if await self.db.fetchone(
            "SELECT 1 FROM pet_video_deliveries WHERE chat_id=? AND message_id=?",
            (message.chat.id, message.message_id),
        ):
            return
        if user_id in self.active_users:
            await message.reply("Предыдущий запрос ещё обрабатывается.")
            return
        if self.queue.full():
            await message.reply("Очередь скачивания заполнена. Попробуй чуть позже.")
            return
        self.active_users.add(user_id)
        self.queue.put_nowait(VideoJob(message, url, user_id))

    async def _worker(self):
        while True:
            job = await self.queue.get()
            try:
                await self._deliver(job)
            except (TelegramAPIError, OSError, TimeoutError):
                logger.info("Pet video delivery unavailable")
            except Exception:
                logger.warning("Pet video worker failed")
            finally:
                self.active_users.discard(job.user_id)
                self.queue.task_done()

    async def _deliver(self, job):
        music = job.url.startswith("https://music.yandex.ru/")
        kind = "музыки" if music else "видео"
        day = moscow_now().date().isoformat()
        error = await self._delivery_error(job.user_id, kind)
        if error:
            await job.message.reply(error)
            return
        cached = await self.db.fetchone("SELECT file_id FROM pet_video_cache WHERE url=?", (job.url,))
        sent = None
        preview = False
        if cached:
            try:
                sent = await send_media(job.message, music, cached["file_id"])
            except TelegramBadRequest:
                await self.db.execute("DELETE FROM pet_video_cache WHERE url=?", (job.url,))
        if sent is None:
            with tempfile.TemporaryDirectory(prefix="nora-video-") as directory:
                path = Path(directory) / ("track.mp3" if music else "video.mp4")
                max_mb = MAX_TRACK_MB if music else VIDEO_MAX_MB
                try:
                    status = await download(job.url, path)
                except TimeoutError:
                    if music:
                        logger.info("Yandex Music download timed out")
                        await music_failure(job.message, "Яндекс Музыка не ответила вовремя. Попробуй чуть позже.")
                    else:
                        await job.message.reply("Источник отвечает слишком долго. Попробуй чуть позже.")
                    return
                if status == 2 or (path.is_file() and path.stat().st_size > max_mb * 1024 * 1024):
                    await job.message.reply(f"Файл превышает {max_mb} МБ.")
                    return
                if status or not path.is_file() or not path.stat().st_size:
                    if music:
                        logger.info("Yandex Music download ended without audio (worker status %d)", status)
                        reason = (
                            "Яндекс Музыка не предоставила доступный MP3 для этого трека."
                            if status == MUSIC_UNAVAILABLE else
                            "Не удалось загрузить файл с Яндекс Музыки. Попробуй чуть позже."
                        )
                        await music_failure(job.message, reason)
                    else:
                        await job.message.reply(
                            "Источник не отдал доступное видео в MP4. Проверь, открыта ли публикация.",
                        )
                    return
                error = await self._delivery_error(job.user_id, kind)
                if error:
                    await job.message.reply(error)
                    return
                options = {}
                if music:
                    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
                    preview = meta["preview"]
                    title = meta["title"]
                    options = {"title": f"{title} (фрагмент)" if preview else title, "performer": meta["artist"]}
                    if preview:
                        options["caption"] = "Яндекс Музыка предоставила только фрагмент трека."
                        options["reply_markup"] = music_alternative()
                try:
                    sent = await send_media(job.message, music, FSInputFile(path), **options)
                except (TelegramBadRequest, TimeoutError):
                    await job.message.reply("Не удалось отправить файл. Попробуй чуть позже.")
                    return
        async with self.db.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "INSERT OR IGNORE INTO pet_video_deliveries VALUES (?,?,?,?)",
                (job.message.chat.id, job.message.message_id, job.user_id, day),
            )
            await db.execute("DELETE FROM pet_video_deliveries WHERE day < date(?, '-2 days')", (day,))
            media = sent.audio if music else sent.video
            if media and not preview:
                await db.execute(
                    "INSERT INTO pet_video_cache VALUES (?,?,?) "
                    "ON CONFLICT(url) DO UPDATE SET file_id=excluded.file_id,updated_at=excluded.updated_at",
                    (job.url, media.file_id, moscow_now().isoformat()),
                )
                await db.execute(
                    "DELETE FROM pet_video_cache WHERE url IN "
                    "(SELECT url FROM pet_video_cache ORDER BY updated_at DESC LIMIT -1 OFFSET ?)", (CACHE_SIZE,),
                )
            await db.commit()
