import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from community_bot import pet_video, pet_video_worker
from community_bot.database import Database
from community_bot.routers.nora import assistant_access_error, nora_video


async def pet_owner(db):
    await db.ensure_user(7, telegram_name="Test")
    await db.add_cookies(7, 20, "test")
    assert (await db.purchase_pet(7, "cat", "Кот", 10))[0]


async def test_ai_access_explains_pet_level_and_expedition(tmp_path):
    from datetime import UTC, datetime, timedelta

    db = Database(tmp_path / "access.sqlite3")
    await db.initialize()
    assert "заведите питомца" in await assistant_access_error(7, db)
    await pet_owner(db)
    assert "2 уровне" in await assistant_access_error(7, db)
    await db.execute("UPDATE pet_development SET stage=5,level=2 WHERE user_id=7")
    assert await assistant_access_error(7, db) is None
    assert (await db.start_expedition(7))[0]
    assert "в походе" in await assistant_access_error(7, db)
    await db.execute("UPDATE pets SET expedition_until=? WHERE user_id=7", (
        (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
    ))
    assert await assistant_access_error(7, db) is None
    await db.execute("UPDATE feature_flags SET enabled=0 WHERE key='tamagotchi'")
    assert "временно отключены" in await assistant_access_error(7, db)


@pytest.mark.parametrize("url", [
    "https://instagram.com.evil.example/reel/a/",
    "https://instagram.com@127.0.0.1/reel/a/",
    "https://instagram.com:81/reel/a/",
    "https://youtube.com/watch?v=aaaaaaaaaaa",
    "http://vm.tiktok.com/a/",
])
def test_invalid_video_urls(url):
    assert pet_video.canonical_url(url) is None


def test_video_network_boundary(monkeypatch):
    with pytest.raises(ValueError):
        pet_video_worker.SafeRedirect().redirect_request(None, None, 302, "", {}, "https://127.0.0.1/")
    with pytest.raises(ValueError):
        pet_video_worker.check_url("file:///app/data/private")
    monkeypatch.setattr(
        pet_video_worker, "_getaddrinfo", lambda *_: [(2, 1, 6, "", ("169.254.169.254", 443))]
    )
    with pytest.raises(OSError):
        pet_video_worker.public_addresses("www.youtube.com", 443)


async def test_video_queue_gates_size_cache_and_quota(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.sqlite3")
    await db.initialize()
    await pet_owner(db)
    await db.execute("UPDATE pet_development SET stage=5,level=2 WHERE user_id=7")
    queue = pet_video.PetVideoQueue(db)
    gate = asyncio.Event()
    started = asyncio.Event()
    status = 2

    async def download(url, path):
        started.set()
        await gate.wait()
        path.write_bytes(b"test")
        return status

    monkeypatch.setattr(pet_video, "download", download)
    message = SimpleNamespace(
        message_id=123, from_user=SimpleNamespace(id=7, is_bot=False),
        chat=SimpleNamespace(id=7, type="private"),
        reply=AsyncMock(), reply_video=AsyncMock(return_value=SimpleNamespace(video=SimpleNamespace(file_id="id"))),
        date=None, sender_chat=None, forward_origin=None, via_bot=None, text="Нора https://vm.tiktok.com/abc/",
    )
    queue.start()
    try:
        await nora_video(message, SimpleNamespace(), queue)
        assert "3-м уровне" in message.reply.call_args.args[0]
        await db.execute("UPDATE pet_development SET stage=10,level=3 WHERE user_id=7")
        await nora_video(message, SimpleNamespace(), queue)
        await asyncio.wait_for(started.wait(), 1)
        message.reply_video.assert_not_called()
        gate.set()
        await asyncio.wait_for(queue.queue.join(), 1)
        assert "45 МБ" in message.reply.call_args.args[0]

        status = 0
        for index in range(5):
            message.message_id = 200 + index
            await nora_video(message, SimpleNamespace(), queue)
            await asyncio.wait_for(queue.queue.join(), 1)
        assert message.reply_video.await_count == 5
        assert message.reply_video.call_args.args == ("id",)
        message.message_id = 300
        await nora_video(message, SimpleNamespace(), queue)
        assert "5 видео" in message.reply.call_args.args[0]
        assert message.reply_video.await_count == 5
    finally:
        await queue.close()


async def test_video_access_explains_reasons_and_rechecks_during_download(tmp_path, monkeypatch):
    db = Database(tmp_path / "video-access.sqlite3")
    await db.initialize()
    queue = pet_video.PetVideoQueue(db)
    message = SimpleNamespace(
        message_id=123, from_user=SimpleNamespace(id=7, is_bot=False),
        chat=SimpleNamespace(id=7, type="private"), reply=AsyncMock(), reply_video=AsyncMock(),
        date=None, sender_chat=None, forward_origin=None, via_bot=None, text="Нора https://vm.tiktok.com/abc/",
    )
    await nora_video(message, SimpleNamespace(), queue)
    assert "заведи питомца" in message.reply.call_args.args[0]
    assert "3-го уровня" in message.reply.call_args.args[0]
    await pet_owner(db)
    await nora_video(message, SimpleNamespace(), queue)
    assert "3-м уровне" in message.reply.call_args.args[0]
    await db.execute("UPDATE pet_development SET stage=10,level=3 WHERE user_id=7")
    started, finish = asyncio.Event(), asyncio.Event()

    async def download(url, path):
        started.set()
        await finish.wait()
        path.write_bytes(b"video")
        return 0

    monkeypatch.setattr(pet_video, "download", download)
    queue.start()
    try:
        await nora_video(message, SimpleNamespace(), queue)
        await asyncio.wait_for(started.wait(), 1)
        assert (await db.start_expedition(7))[0]
        finish.set()
        await asyncio.wait_for(queue.queue.join(), 1)
        assert "в походе" in message.reply.call_args.args[0]
        message.reply_video.assert_not_awaited()
        await nora_video(message, SimpleNamespace(), queue)
        assert "в походе" in message.reply.call_args.args[0]
        assert await queue._quota(7, pet_video.moscow_now().date().isoformat())
    finally:
        await queue.close()


def test_stream_stops_at_size_limit(tmp_path):
    from contextlib import nullcontext
    from io import BytesIO

    class Response(BytesIO):
        def get_header(self, name):
            return None

    sample = b"\x00\x00\x00\x14ftypisom" + b"X" * 200
    downloader = SimpleNamespace(urlopen=lambda request: nullcontext(Response(sample)))
    destination = tmp_path / "oversized.mp4"
    with pytest.raises(pet_video_worker.VideoTooLarge):
        pet_video_worker.stream(downloader, {"url": "https://www.youtube.com/"}, destination, 50)
    assert destination.stat().st_size <= 50
