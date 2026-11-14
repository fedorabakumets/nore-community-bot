"""Bounded asynchronous delivery of public short videos via Telegram."""
from __future__ import annotations

import asyncio
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
from aiogram.types import FSInputFile, Message

from community_bot.nora import strip_address
from community_bot.pet_progress import VIDEO_DAILY_LIMIT, VIDEO_MAX_MB, level, moscow_now

logger = logging.getLogger(__name__)
WORKERS = 2
QUEUE_SIZE = 6
DOWNLOAD_SECONDS = 75
SEND_SECONDS = 45
CACHE_SIZE = 1000
COMMAND = re.compile(r"https?://\S+", re.IGNORECASE)
PLATFORMS = {
    "vm.tiktok.com": r"/[\w-]+/?",
    "vt.tiktok.com": r"/[\w-]+/?",
    "tiktok.com": r"/(?:@[\w.\-]+/video/\d+|t/[\w-]+)/?",
    "instagram.com": r"/reel/[\w-]+/?",
    "youtube.com": r"/shorts/[\w-]{11}/?",
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

    async def _access(self, user_id):
        return await level(self.db, user_id) >= 3 and await self.db.feature_enabled("tamagotchi")

    async def enqueue(self, message, raw_url):
        url = canonical_url(raw_url)
        if not url:
            await message.reply("Пришли ссылку на TikTok, Instagram Reels или YouTube Shorts.")
            return
        user_id = message.from_user.id
        if not await self._access(user_id):
            await message.reply("Загрузка видео открывается на 10-м этапе развития питомца.")
            return
        day = moscow_now().date().isoformat()
        if message.date and message.date.astimezone(moscow_now().tzinfo).date().isoformat() != day:
            return
        if not await self._quota(user_id, day):
            await message.reply(f"Сегодня уже получено {VIDEO_DAILY_LIMIT} видео. Лимит обновится в 00:00 МСК.")
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
            await message.reply("Очередь видео заполнена. Попробуй чуть позже.")
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
        day = moscow_now().date().isoformat()
        if not await self._access(job.user_id) or not await self._quota(job.user_id, day):
            await job.message.reply("Доступ или дневной лимит видео изменился. Проверь вкладку питомца.")
            return
        cached = await self.db.fetchone("SELECT file_id FROM pet_video_cache WHERE url=?", (job.url,))
        sent = None
        if cached:
            try:
                sent = await asyncio.wait_for(job.message.reply_video(cached["file_id"]), SEND_SECONDS)
            except TelegramBadRequest:
                await self.db.execute("DELETE FROM pet_video_cache WHERE url=?", (job.url,))
        if sent is None:
            with tempfile.TemporaryDirectory(prefix="nora-video-") as directory:
                path = Path(directory) / "video.mp4"
                try:
                    status = await download(job.url, path)
                except TimeoutError:
                    await job.message.reply("Источник отвечает слишком долго. Попробуй чуть позже.")
                    return
                if status == 2 or (path.is_file() and path.stat().st_size > VIDEO_MAX_MB * 1024 * 1024):
                    await job.message.reply(f"Файл превышает {VIDEO_MAX_MB} МБ.")
                    return
                if status or not path.is_file() or not path.stat().st_size:
                    await job.message.reply("Источник не отдал доступное видео в MP4. Проверь, открыта ли публикация.")
                    return
                try:
                    sent = await asyncio.wait_for(job.message.reply_video(FSInputFile(path)), SEND_SECONDS)
                except (TelegramBadRequest, TimeoutError):
                    await job.message.reply("Не удалось отправить видео. Попробуй чуть позже.")
                    return
        async with self.db.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "INSERT OR IGNORE INTO pet_video_deliveries VALUES (?,?,?,?)",
                (job.message.chat.id, job.message.message_id, job.user_id, day),
            )
            await db.execute("DELETE FROM pet_video_deliveries WHERE day < date(?, '-2 days')", (day,))
            if sent.video:
                await db.execute(
                    "INSERT INTO pet_video_cache VALUES (?,?,?) "
                    "ON CONFLICT(url) DO UPDATE SET file_id=excluded.file_id,updated_at=excluded.updated_at",
                    (job.url, sent.video.file_id, moscow_now().isoformat()),
                )
                await db.execute(
                    "DELETE FROM pet_video_cache WHERE url IN "
                    "(SELECT url FROM pet_video_cache ORDER BY updated_at DESC LIMIT -1 OFFSET ?)", (CACHE_SIZE,),
                )
            await db.commit()
