"""Authenticated Mini App catalog search and explicit imports via the existing song delivery."""
from __future__ import annotations

import asyncio
import json
import re
import time
from uuid import uuid4

from aiogram.exceptions import TelegramAPIError
from aiohttp import ClientError, web

from community_bot.music_library import add_resolved_track, get_collection, public_track, track_id
from community_bot.profile_track import MAX_TRACK_BYTES
from community_bot.routers import song_requests as songs
from community_bot.track_disk_cache import TrackResponse

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
         "duration": song.duration, "url": song.url, "cover": song.cover, "saved_id": saved.get(song.id)}
        for song in tracks
    ]})


async def import_track(request):
    return await prepare_track(request, save=True)


async def play_track(request):
    return await prepare_track(request, save=False)


async def prepare_track(request, *, save):
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
            return web.json_response({"track": public_track(key, track), "already_saved": True,
                                      "source": "/api/music-library/" + key})
    for key, record in (await read_history(db, uid)).items():
        track = record["track"]
        if track.get("catalog_id") == song.id:
            if save:
                await add_resolved_track(db, uid, track)
                track = (await get_collection(db, uid))[key]
            source = "/api/music-library/" if save else "/api/music-library/history/"
            return web.json_response({"track": public_track(key, track), "source": source + key})
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
                 "revision": uuid4().hex, "catalog_id": song.id, "cover": song.cover}
        if save:
            result = await add_resolved_track(db, uid, track)
            key = result["id"]
            track = (await get_collection(db, uid))[key]
            source = "/api/music-library/"
        else:
            key = await remember(db, uid, track, listened=False)
            source = "/api/music-library/history/"
        return web.json_response({"track": public_track(key, track), "source": source + key})
    finally:
        _IN_FLIGHT.discard(uid)


HISTORY_LIMIT = 50
HISTORY_PREFIX = "music_history:"
SOCIAL_PREFIX = "music_activity_public:"


async def read_history(db, uid):
    raw = await db.get_bot_state(HISTORY_PREFIX + str(uid))
    return json.loads(raw) if raw else {}


async def remember(db, uid, track, *, listened):
    key = track_id(track)
    state_key = HISTORY_PREFIX + str(uid)
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        row = await (await conn.execute("SELECT value FROM bot_state WHERE key=?", (state_key,))).fetchone()
        records = json.loads(row["value"]) if row else {}
        previous = records.pop(key, {})
        records[key] = {"track": track, "at": time.time() if listened else previous.get("at", 0)}
        while len(records) > HISTORY_LIMIT:
            records.pop(next(iter(records)))
        await conn.execute(
            "INSERT INTO bot_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (state_key, json.dumps(records, ensure_ascii=False)),
        )
        await conn.commit()
    return key


async def history(request):
    db, uid = request.app["db"], request["actor"]["id"]
    records = await read_history(db, uid)
    return web.json_response({"tracks": [
        {**public_track(key, record["track"]), "at": record["at"],
         "source": "/api/music-library/history/" + key}
        for key, record in sorted(records.items(), key=lambda item: item[1]["at"], reverse=True)
        if record["at"]
    ], "public": await db.get_bot_state(SOCIAL_PREFIX + str(uid)) == "1"})


async def activity_visibility(request):
    payload = await request.json()
    if not isinstance(payload, dict) or type(payload.get("public")) is not bool:
        return _error("Некорректная настройка.")
    db, uid = request.app["db"], request["actor"]["id"]
    await db.set_bot_state(SOCIAL_PREFIX + str(uid), "1" if payload["public"] else "0")
    return web.json_response({"public": payload["public"]})


async def activity_rows(db, uid):
    # Include only explicitly shared, currently non-private, non-blocked profiles.
    return await db.fetchall(
        "SELECT h.value, u.user_id, u.telegram_name, "
        "EXISTS(SELECT 1 FROM mini_friendships f WHERE f.status='accepted' "
        "AND ((f.low_id=u.user_id AND f.high_id=?) OR (f.high_id=u.user_id AND f.low_id=?))) AS friend "
        "FROM bot_state h JOIN users u ON h.key='music_history:' || u.user_id "
        "JOIN bot_state p ON p.key='music_activity_public:' || u.user_id AND p.value='1' "
        "WHERE COALESCE(u.profile_private,0)=0 "
        "AND NOT EXISTS(SELECT 1 FROM mini_friend_blocks b WHERE "
        "(b.blocker_id=? AND b.blocked_id=u.user_id) OR (b.blocker_id=u.user_id AND b.blocked_id=?))",
        (uid, uid, uid, uid),
    )


async def social(request):
    uid, db = request["actor"]["id"], request.app["db"]
    period = request.query.get("period", "week")
    if period not in {"day", "week", "all"}:
        return _error("Некорректный период.")
    cutoff = time.time() - {"day": 86400, "week": 604800, "all": 10**12}[period]
    ranked, friends = {}, []
    for row in await activity_rows(db, uid):
        seen = set()
        latest = None
        for key, record in json.loads(row["value"]).items():
            stamp, track = record["at"], record["track"]
            if not stamp:
                continue
            item = {**public_track(key, track), "source": "/api/music-library/social/" + key, "at": stamp}
            if row["friend"] and row["user_id"] != uid and (latest is None or stamp > latest["at"]):
                latest = {**item, "name": row["telegram_name"] or "Участник"}
            if stamp < cutoff:
                continue
            identity = track.get("catalog_id") or key
            entry = ranked.setdefault(identity, {**item, "listeners": 0})
            if identity not in seen:
                entry["listeners"] += 1
                seen.add(identity)
        if latest:
            friends.append(latest)
    return web.json_response({
        "top": sorted(ranked.values(), key=lambda entry: (-entry["listeners"], -entry["at"]))[:20],
        "friends": sorted(friends, key=lambda entry: -entry["at"])[:15],
    })


async def resolve(db, uid, source, revision):
    match = re.fullmatch(r"/api/music-library/(history|social)/([a-f0-9]{64})", source) if isinstance(source, str) else None
    if not match or not isinstance(revision, str):
        return None
    scope, key = match.groups()
    if scope == "history":
        records = [await read_history(db, uid)]
    else:
        records = [json.loads(row["value"]) for row in await activity_rows(db, uid)]
    for entries in records:
        record = entries.get(key)
        if record and (scope == "history" or record["at"]) and record["track"]["revision"] == revision:
            return record["track"]
    return None


async def audio(request):
    db, uid, bot = request.app["db"], request["actor"]["id"], request.app.get("bot")
    revision = request.query.get("v")
    track = await resolve(db, uid, request.path, revision)
    if not bot or not track:
        raise web.HTTPNotFound()
    if request.query.get("check") == "1":
        return web.Response(status=204)
    try:
        lease = await request.app["track_disk_cache"].open(bot, track["file_id"])
    except (TelegramAPIError, ClientError, OSError, ValueError):
        raise web.HTTPBadGateway() from None
    try:
        if not await resolve(db, uid, request.path, revision):
            raise web.HTTPNotFound()
        return TrackResponse(lease, track["mime"])
    except BaseException:
        lease.close()
        raise


async def listened(request):
    from community_bot.social_profiles import _share_track_source

    payload = await request.json()
    if not isinstance(payload, dict):
        return _error("Некорректный запрос.")
    db, uid = request.app["db"], request["actor"]["id"]
    track = await _share_track_source(db, request.app["settings"], uid,
                                      payload.get("source"), payload.get("revision"))
    if not track:
        raise web.HTTPNotFound()
    # A borrowed track must not become a permanent private audio grant after
    # its owner withdraws access. Explicitly saving remains the existing action.
    source = payload.get("source", "")
    if source.startswith("/api/people/") or source.startswith("/api/music-library/social/"):
        return web.json_response({"ok": True, "recorded": False})
    await remember(db, uid, track, listened=True)
    return web.json_response({"ok": True})
