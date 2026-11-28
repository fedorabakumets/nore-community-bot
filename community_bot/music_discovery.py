"""Authenticated Mini App catalog search and explicit imports via the existing song delivery."""
from __future__ import annotations

import asyncio
import time
from uuid import uuid4

from aiogram.exceptions import TelegramAPIError
from aiohttp import web

from community_bot.music_library import add_resolved_track, get_collection, public_track
from community_bot.profile_track import MAX_TRACK_BYTES
from community_bot.routers import song_requests as songs

_SEARCHES = {}
_LAST = {}
_IN_FLIGHT = set()
_SEARCH_SLOTS = asyncio.Semaphore(3)
_MAX_USERS = 256


def _error(message, status=400):
    return web.json_response({"error": message}, status=status)


def _prune(now):
    for uid, entry in list(_SEARCHES.items()):
        if entry[0] <= now:
            _SEARCHES.pop(uid, None)
    for uid, stamp in list(_LAST.items()):
        if stamp + 60 <= now:
            _LAST.pop(uid, None)
    while len(_SEARCHES) >= _MAX_USERS:
        _SEARCHES.pop(next(iter(_SEARCHES)))
    while len(_LAST) >= _MAX_USERS:
        _LAST.pop(next(iter(_LAST)))


async def search(request):
    uid = request["actor"]["id"]
    query = " ".join(request.query.get("q", "").split())
    if not 2 <= len(query) <= 120:
        return _error("Введи от 2 до 120 символов.")
    if not songs.enabled():
        return _error("Музыкальный каталог пока не подключён.", 503)
    problem = await songs.song_care_error(request.app["db"], uid)
    if problem:
        return _error(problem, 403)
    now = time.monotonic()
    _prune(now)
    if uid in _IN_FLIGHT or now - _LAST.get(uid, -100) < 2 or _SEARCH_SLOTS.locked():
        return _error("Подожди немного перед следующим поиском.", 429)
    _LAST[uid] = now
    _IN_FLIGHT.add(uid)
    try:
        async with _SEARCH_SLOTS:
            tracks = await songs.find_songs(query)
    except songs.SongError as exc:
        return _error(str(exc), 502)
    finally:
        _IN_FLIGHT.discard(uid)
    _SEARCHES[uid] = (time.monotonic() + songs.CHOICE_TTL, {song.id: song for song in tracks})
    existing = await get_collection(request.app["db"], uid)
    saved = {track.get("catalog_id"): key for key, track in existing.items() if track.get("catalog_id")}
    return web.json_response({"tracks": [
        {"id": song.id, "title": song.title, "artist": song.artist,
         "duration": song.duration, "url": song.url, "saved_id": saved.get(song.id)}
        for song in tracks
    ]})


async def import_track(request):
    uid = request["actor"]["id"]
    db, bot = request.app["db"], request.app.get("bot")
    payload = await request.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
        return _error("Некорректный трек.")
    entry = _SEARCHES.get(uid)
    if not entry or entry[0] <= time.monotonic() or payload["id"] not in entry[1]:
        return _error("Поиск устарел. Найди трек снова.", 409)
    if not songs.enabled() or bot is None:
        return _error("Музыкальный каталог пока не подключён.", 503)
    song = entry[1][payload["id"]]
    existing = await get_collection(db, uid)
    for key, track in existing.items():
        if track.get("catalog_id") == song.id:
            return web.json_response({"track": public_track(key, track), "already_saved": True})
    if uid in _IN_FLIGHT:
        return _error("Дождись завершения предыдущего запроса.", 429)
    _IN_FLIGHT.add(uid)
    try:
        problem = await songs.song_care_error(db, uid) or await songs._quota_error(db, uid)
        if problem:
            return _error(problem, 403)
        if await songs._remaining(db, uid, uid):
            return _error("Следующую песню можно запросить после окончания паузы.", 429)
        ban = await db.ban_reset_state(uid)
        choice = songs.Choices(uid, uid, entry[0], [song])
        try:
            audio = await songs.send_song(bot, db, choice, song)
        except TelegramAPIError:
            return _error("Не удалось отправить песню в личку Норы.", 502)
        if not audio:
            return _error("Трек не добавлен. Проверь сообщение от Норы в личке.", 409)
        if audio.file_size and audio.file_size > MAX_TRACK_BYTES:
            return _error("Трек отправлен в личку, но слишком большой для плеера.", 413)
        if await db.ban_reset_state(uid) != ban:
            return _error("Доступ изменился. Открой приложение снова.", 403)
        track = {"file_id": audio.file_id, "mime": "audio/mpeg",
                 "title": song.title, "artist": song.artist, "duration": audio.duration,
                 "revision": uuid4().hex, "catalog_id": song.id}
        result = await add_resolved_track(db, uid, track)
        entries = await get_collection(db, uid)
        return web.json_response({"track": public_track(result["id"], entries[result["id"]])})
    finally:
        _IN_FLIGHT.discard(uid)
