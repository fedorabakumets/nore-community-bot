import asyncio
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from community_bot import track_disk_cache
from community_bot.track_disk_cache import START_BYTES, TrackDiskCache, TrackResponse


async def test_shared_download_and_lru(tmp_path):
    async def download(file_id, *, destination, **kwargs):
        await asyncio.sleep(0)
        destination.write(file_id.encode() * 4)

    bot = AsyncMock()
    bot.download.side_effect = download
    cache = TrackDiskCache(tmp_path, max_bytes=8)
    first, second = await asyncio.gather(cache.open(bot, "a"), cache.open(bot, "a"))
    assert bot.download.await_count == 1
    assert first.file.read() == second.file.read() == b"aaaa"
    second.close()
    b = await cache.open(bot, "b")
    b.close()
    c = await cache.open(bot, "c")
    c.close()
    assert len(list(tmp_path.iterdir())) == 2
    assert first.file.seek(0) == 0
    assert first.file.read() == b"aaaa"
    first.close()
    again = await cache.open(bot, "a")
    again.close()
    assert bot.download.await_count == 3
    cache.close()
    assert not list(tmp_path.iterdir())


async def test_failure_does_not_cache_partial_files(tmp_path, monkeypatch):
    monkeypatch.setattr(track_disk_cache, "MAX_TRACK_BYTES", 4)

    async def download(file_id, *, destination, **kwargs):
        destination.write(b"123")
        destination.write(b"45")

    bot = AsyncMock()
    bot.download.side_effect = download
    cache = TrackDiskCache(tmp_path)
    with pytest.raises(ValueError):
        await cache.open(bot, "track")
    assert not list(tmp_path.iterdir())
    cache.close()


async def test_pinned_cache_cannot_grow_and_response_keeps_mime(tmp_path):
    async def download(file_id, *, destination, **kwargs):
        destination.write(b"1234")

    bot = AsyncMock()
    bot.download.side_effect = download
    cache = TrackDiskCache(tmp_path, max_bytes=4)
    lease = await cache.open(bot, "a")
    response = TrackResponse(lease, "audio/mpeg")
    assert response.content_type == "audio/mpeg"
    assert response.content_length == 4
    assert response.headers["Cache-Control"] == "no-store"
    with pytest.raises(OSError):
        await cache.open(bot, "b")
    assert len(list(tmp_path.iterdir())) == 1
    lease.close()
    other = await cache.open(bot, "b")
    other.close()
    cache.close()


async def test_http_response_sends_complete_audio_and_releases_lease(tmp_path):
    audio = b"audio" * 40_000

    async def download(file_id, *, destination, **kwargs):
        for start in range(0, len(audio), 8192):
            destination.write(audio[start:start + 8192])

    bot = AsyncMock()
    bot.download.side_effect = download
    cache = TrackDiskCache(tmp_path)
    leases = []

    async def handler(request):
        lease = await cache.open(bot, "track")
        leases.append(lease)
        return TrackResponse(lease, "audio/mpeg")

    app = web.Application()
    app.router.add_get("/track", handler)
    async with TestClient(TestServer(app)) as client:
        for _ in range(2):
            response = await client.get("/track")
            assert response.content_type == "audio/mpeg"
            assert await response.read() == audio
            assert leases[-1].file.closed
    assert bot.download.await_count == 1
    cache.close()


async def test_cached_start_and_resume_do_not_download_or_reuse_stale_bytes(tmp_path):
    audio = b"A" * START_BYTES + b"end"

    async def download(file_id, *, destination, **kwargs):
        destination.write(audio)

    bot = AsyncMock()
    bot.download.side_effect = download
    cache = TrackDiskCache(tmp_path, max_bytes=len(audio))
    track = {"file_id": "track", "mime": "audio/mpeg"}

    async def handler(request):
        lease = await cache.open_track(bot, track)
        return TrackResponse(lease, track["mime"], request.headers)

    assert (await cache.cached_start(track)).status == 204
    bot.download.assert_not_awaited()

    app = web.Application()
    app.router.add_get("/track", handler)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/track")
        assert await response.read() == audio
        prefix = await cache.cached_start(track)
        assert prefix.status == 206
        assert prefix.body == audio[:START_BYTES]
        assert prefix.headers["Content-Range"] == f"bytes 0-{START_BYTES - 1}/{len(audio)}"
        resume = {"Range": f"bytes={START_BYTES}-", "If-Range": prefix.headers["ETag"]}
        response = await client.get("/track", headers=resume)
        assert response.status == 206
        assert response.headers["Content-Range"] == f"bytes {START_BYTES}-{len(audio) - 1}/{len(audio)}"
        assert await response.read() == audio[START_BYTES:]
        assert bot.download.await_count == 1

        other = await cache.open(bot, "another")
        other.close()
        response = await client.get("/track", headers=resume)
        assert response.status == 200
        assert response.headers["ETag"] != resume["If-Range"]
        assert await response.read() == audio
        assert bot.download.await_count == 3
    cache.close()


async def test_catalog_download_is_shared_and_does_not_use_telegram(tmp_path, monkeypatch):
    from pathlib import Path

    from community_bot.routers import song_requests

    calls = []
    monkeypatch.setattr(song_requests, "enabled", lambda: True)

    async def download(song, directory, *, max_bytes):
        calls.append((song.id, max_bytes))
        output = Path(directory) / "song.mp3"
        output.write_bytes(b"test audio")
        return output

    monkeypatch.setattr(song_requests, "download_song", download)
    cache = TrackDiskCache(tmp_path)
    bot = AsyncMock()
    track = {"file_id": "catalog:123", "catalog_id": "123", "title": "Song", "artist": "Artist", "duration": 120}
    a, b = await asyncio.gather(cache.open_track(bot, track), cache.open_track(bot, {**track, "revision": "other"}))
    assert a.file.read() == b.file.read() == b"test audio"
    assert calls == [("123", track_disk_cache.MAX_TRACK_BYTES)]
    bot.download.assert_not_awaited()
    a.close()
    b.close()
    cache.close()


async def test_catalog_download_limit_rejects_excess_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(track_disk_cache, "MAX_PENDING", 2)
    entered = asyncio.Event()
    release = asyncio.Event()
    async def download(file_id, *, destination, **kwargs):
        entered.set()
        await release.wait()
        destination.write(b"x")
    bot = AsyncMock()
    bot.download.side_effect = download
    cache = TrackDiskCache(tmp_path)
    one = asyncio.create_task(cache.open(bot, "one"))
    await entered.wait()
    two = asyncio.create_task(cache.open(bot, "two"))
    await asyncio.sleep(0)
    with pytest.raises(OSError, match="busy"):
        await cache.open(bot, "three")
    release.set()
    for lease in await asyncio.gather(one, two):
        lease.close()
    assert cache._pending == 0
    cache.close()
