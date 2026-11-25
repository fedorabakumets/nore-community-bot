import asyncio
from unittest.mock import AsyncMock

import pytest

from community_bot import track_disk_cache
from community_bot.track_disk_cache import TrackDiskCache, TrackResponse


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
