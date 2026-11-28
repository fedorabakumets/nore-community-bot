"""Bounded, process-local disk cache for authenticated Mini App audio."""
from __future__ import annotations

import asyncio
import hashlib
import io
import re
import shutil
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from weakref import WeakValueDictionary

from aiohttp import payload, web

from community_bot.profile_track import MAX_TRACK_BYTES

CACHE_BYTES = 128 * 1024 * 1024
DOWNLOADS = 2
MAX_PENDING = 8
START_BYTES = 128 * 1024


class _BoundedFile(io.BufferedWriter):
    def write(self, data):
        if self.tell() + len(data) > MAX_TRACK_BYTES:
            raise ValueError("Track exceeds the download limit")
        return super().write(data)


@dataclass
class _Entry:
    path: Path
    size: int
    readers: int = 0
    etag: str = field(default_factory=lambda: f'"{uuid4().hex}"')


class TrackLease:
    """An open file pins its cache entry until the HTTP response finishes."""

    def __init__(self, entry):
        self.file = entry.path.open("rb")
        self._entry = entry
        entry.readers += 1

    def close(self):
        if self._entry is not None:
            try:
                self.file.close()
            finally:
                self._entry.readers -= 1
                self._entry = None


class TrackDiskCache:
    def __init__(self, directory=None, max_bytes=CACHE_BYTES):
        self._directory = Path(directory) if directory is not None else None
        self._temporary = None
        self._max_bytes = max_bytes
        self._bytes = 0
        self._entries = OrderedDict()
        self._locks = WeakValueDictionary()
        self._downloads = asyncio.Semaphore(DOWNLOADS)
        self._pending = 0

    def _root(self):
        if self._directory is None:
            self._temporary = TemporaryDirectory(prefix="nora-tracks-")
            self._directory = Path(self._temporary.name)
        self._directory.mkdir(parents=True, exist_ok=True)
        return self._directory

    def _hit(self, key):
        entry = self._entries.get(key)
        if entry is None:
            return None
        self._entries.move_to_end(key)
        return TrackLease(entry)

    def _make_room(self, size):
        if size > self._max_bytes:
            raise OSError("Track exceeds the disk cache budget")
        for key, entry in list(self._entries.items()):
            if self._bytes + size <= self._max_bytes:
                break
            if entry.readers:
                continue
            entry.path.unlink(missing_ok=True)
            self._bytes -= entry.size
            del self._entries[key]
        if self._bytes + size > self._max_bytes:
            raise OSError("Audio cache is busy")

    async def open(self, bot, file_id):
        async def download(partial):
            with _BoundedFile(partial.open('wb', buffering=0)) as output:
                await bot.download(file_id, destination=output, timeout=25, seek=False)
        return await self._open('telegram:' + file_id, download)

    async def open_track(self, bot, track):
        from community_bot.music_artist import PREFIX, release_paths

        file_id = track['file_id']
        if file_id.startswith(PREFIX):
            path = release_paths().get(file_id)
            if path is None:
                raise ValueError("Unknown artist track")
            stat = path.stat()
            return TrackLease(_Entry(path, stat.st_size))
        if not file_id.startswith('catalog:'):
            return await self.open(bot, file_id)
        from community_bot.routers.song_requests import Song, SongError, download_song, enabled

        async def download(partial):
            if not enabled():
                raise ValueError('Music catalog disabled')
            song = Song(track['catalog_id'], track.get('album_id'), track['title'], track['artist'], track['duration'])
            try:
                with TemporaryDirectory(prefix='nora-catalog-') as temp:
                    path = await download_song(song, temp, max_bytes=MAX_TRACK_BYTES)
                    shutil.move(path, partial)
            except SongError as exc:
                raise ValueError(str(exc)) from exc
            except Exception as exc:
                raise OSError('Catalog audio is unavailable') from exc
        return await self._open(track['file_id'], download)

    async def cached_start(self, track):
        if track["mime"] != "audio/mpeg":
            return web.Response(status=204)
        file_id = track["file_id"]
        identity = file_id if file_id.startswith("catalog:") else "telegram:" + file_id
        lease = self._hit(hashlib.sha256(identity.encode()).hexdigest())
        if lease is None:
            return web.Response(status=204)
        try:
            entry = lease._entry
            if entry.size <= START_BYTES:
                return web.Response(status=204)
            data = await asyncio.to_thread(lease.file.read, START_BYTES)
            if len(data) != START_BYTES:
                return web.Response(status=204)
            return web.Response(
                status=206, body=data, content_type="audio/mpeg",
                headers={"Cache-Control": "no-store", "ETag": entry.etag,
                         "Content-Range": f"bytes 0-{START_BYTES - 1}/{entry.size}"},
            )
        finally:
            lease.close()

    async def _open(self, identity, download):
        key = hashlib.sha256(identity.encode()).hexdigest()
        lease = self._hit(key)
        if lease is not None:
            return lease
        if self._pending >= MAX_PENDING:
            raise OSError("Audio cache is busy")
        self._pending += 1
        try:
            # Deduplicate concurrent downloads of the same Telegram file.
            async with self._locks.setdefault(key, asyncio.Lock()):
                lease = self._hit(key)
                if lease is not None:
                    return lease
                async with self._downloads:
                    root = self._root()
                    partial = root / (key + ".part")
                    final = root / key
                    try:
                        await download(partial)
                        size = partial.stat().st_size
                        if not 0 < size <= MAX_TRACK_BYTES:
                            raise ValueError("Invalid audio file size")
                        self._make_room(size)
                        partial.replace(final)
                        entry = _Entry(final, size)
                        self._entries[key] = entry
                        self._bytes += size
                        return TrackLease(entry)
                    finally:
                        partial.unlink(missing_ok=True)
        finally:
            self._pending -= 1

    def close(self):
        for entry in self._entries.values():
            if not entry.readers:
                entry.path.unlink(missing_ok=True)
        self._entries.clear()
        self._bytes = 0
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None


class TrackResponse(web.Response):
    """Send a file in aiohttp chunks without changing the existing authenticated API."""

    def __init__(self, lease, mime, request_headers=None):
        self.lease = lease
        entry = lease._entry
        headers = {"Cache-Control": "no-store", "Content-Length": str(entry.size), "ETag": entry.etag}
        status = 200
        if request_headers and mime == "audio/mpeg" and request_headers.get("If-Range") == entry.etag:
            match = re.fullmatch(r"bytes=([0-9]{1,6})-", request_headers.get("Range", ""))
            start = int(match[1]) if match else 0
            # The only partial response these routes provide is the rest of a prefetched MP3.
            if start == START_BYTES and start < entry.size:
                lease.file.seek(start)
                headers.update({"Content-Range": f"bytes {start}-{entry.size - 1}/{entry.size}",
                                "Content-Length": str(entry.size - start)})
                status = 206
        super().__init__(
            status=status, body=payload.BufferedReaderPayload(lease.file, content_type=mime, disposition=None),
            headers=headers,
        )

    async def prepare(self, request):
        try:
            return await super().prepare(request)
        except BaseException:
            self.lease.close()
            raise

    async def write_eof(self, data=b""):
        try:
            await super().write_eof(data)
        finally:
            self.lease.close()
