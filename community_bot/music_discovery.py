"""Authenticated Mini App catalog search and explicit imports via the existing song delivery."""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
from collections import Counter
from uuid import uuid4

from aiogram.exceptions import TelegramAPIError
from aiohttp import ClientError, web

from community_bot.music_library import add_resolved_track, get_collection, public_track, track_id
from community_bot.routers import song_requests as songs
from community_bot.track_disk_cache import START_BYTES, TrackResponse

_SEARCHES = {}
_LAST = {}
_IN_FLIGHT = set()
_SEARCH_SLOTS = asyncio.Semaphore(3)
_PRELOAD_SLOTS = asyncio.Semaphore(1)
_MAX_USERS = 256
_WAVES = {}
_WAVE_LAST = {}
_WAVE_METADATA = {}
_WAVE_LOOKUPS = {}
_WAVE_TTL = 2 * 60 * 60
_WAVE_CACHE_TTL = 30 * 60
_WAVE_CACHE_LIMIT = 128
_WAVE_SEEDS = (
    'The Weeknd', 'Daft Punk', 'Billie Eilish', 'Disclosure', 'M83', 'Bicep',
    'ODESZA', 'Arctic Monkeys', 'Kendrick Lamar', 'Adele', 'Bonobo', 'Nirvana',
    'Молчат Дома', 'Кино', 'Земфира', 'Моя Мишель', 'Баста', 'Cream Soda',
    'Imagine Dragons', 'Dua Lipa', 'Tame Impala', 'Gorillaz', 'Radiohead', 'The xx',
)

_WAVE_GENRES = {
    "pop": ("Dua Lipa", "Ariana Grande", "Adele", "Sabrina Carpenter", "Lady Gaga"),
    "hiphop": ("Kendrick Lamar", "Nas", "J. Cole", "Баста", "Kanye West"),
    "house": ("Disclosure", "Kerri Chandler", "Bicep", "Peggy Gou", "Fred again.."),
    "electronic": ("Daft Punk", "M83", "ODESZA", "Justice", "The Chemical Brothers"),
    "rock": ("Nirvana", "Foo Fighters", "Queens of the Stone Age", "Кино", "Arctic Monkeys"),
    "indie": ("The xx", "Tame Impala", "Beach House", "Alvvays", "Молчат Дома"),
    "rnb": ("SZA", "Frank Ocean", "H.E.R.", "Daniel Caesar", "Summer Walker"),
    "chill": ("Bonobo", "Tycho", "Khruangbin", "Emancipator", "Ólafur Arnalds"),
}

# Catalog station IDs. Keep the editorial seeds for provider outages or empty genre feeds.
_WAVE_RADIO = {
    "pop": "pop", "hiphop": "rap", "house": "house", "electronic": "electronic",
    "rock": "rock", "indie": "indie", "rnb": "rnb", "chill": "ambient",
}


def _catalog_id(track):
    value = track.get("catalog_id")
    return value if isinstance(value, str) and re.fullmatch(r"[0-9]{1,20}", value) else None


def _wave_taste(collection, history):
    weights, artists = Counter(), Counter()
    for track, weight in [
        *((track, 4) for track in collection.values()),
        *((record["track"], 1) for record in history.values() if record["at"]),
    ]:
        if key := _catalog_id(track):
            weights[key] += weight
            for name in (track.get("artist") or "").split(", "):
                if name and name != "Неизвестный исполнитель":
                    artists[name[:120]] += weight
    return weights, [name for name, _ in artists.most_common(8)]


def _diverse_wave(batches, avoid, limit=15):
    # Round-robin catalog sources so one seed cannot dominate the first tracks.
    pools = [batch for batch in batches if isinstance(batch, list)]
    seen, artists, picked, deferred = set(), Counter(), [], []
    for index in range(max(map(len, pools), default=0)):
        for pool in pools:
            if index >= len(pool) or (song := pool[index]).id in seen:
                continue
            seen.add(song.id)
            artist = _artist_key(song.artist.split(", ", 1)[0])
            if song.id in avoid or artists[artist] >= 2:
                deferred.append(song)
                continue
            picked.append(song)
            artists[artist] += 1
            if len(picked) == limit:
                return picked
    return (picked + deferred)[:limit]


def _artist_key(artist):
    return " ".join(artist.casefold().split())


def _matches_artist(song, artist):
    return artist == _artist_key(song.artist) or any(
        artist == _artist_key(name) for name in song.artist.split(", ")
    )


def _error(message, status=400):
    return web.json_response({"error": message}, status=status)


def _catalog_track(song):
    return {"file_id": "catalog:" + song.id, "mime": "audio/mpeg", "title": song.title,
            "artist": song.artist, "duration": song.duration, "catalog_id": song.id,
            "album_id": song.album_id, "cover": song.cover}


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
    db = request.app["db"]
    payload = await request.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
        return _error("Некорректный трек.")
    entry = (_WAVES if payload.get("wave") is True else _SEARCHES).get(uid)
    if not entry or entry[0] <= time.monotonic() or payload["id"] not in entry[1]:
        return _error("Поиск устарел. Найди трек снова.", 409)
    if not songs.enabled():
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
        problem = await songs.song_care_error(db, uid)
        if problem:
            return _error(problem, 403)
        # The durable reference can reuse audio already fetched by the shared cache.
        track = {**_catalog_track(song), "revision": uuid4().hex}
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
_LIVE = {}


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
    if not payload["public"]:
        _LIVE.pop(uid, None)
    return web.json_response({"public": payload["public"]})


async def activity_rows(db, uid, view="all"):
    # Include only explicitly shared, currently non-private, non-blocked profiles.
    friendship = (
        "EXISTS(SELECT 1 FROM mini_friendships f WHERE f.status='accepted' "
        "AND ((f.low_id=u.user_id AND f.high_id=?) OR (f.high_id=u.user_id AND f.low_id=?)))"
    )
    projection = ", " + friendship + " AS friend" if view == "all" else ""
    source = (
        "FROM (SELECT high_id AS user_id FROM mini_friendships WHERE low_id=? AND status='accepted' "
        "UNION ALL SELECT low_id FROM mini_friendships WHERE high_id=? AND status='accepted') f "
        "JOIN users u ON f.user_id=u.user_id "
        if view == "friends" else "FROM users u "
    )
    return await db.fetchall(
        "SELECT h.value, u.user_id, u.telegram_name" + projection + " " + source
        + "JOIN bot_state p ON p.key='music_activity_public:' || u.user_id AND p.value='1' "
        "JOIN bot_state h ON h.key='music_history:' || u.user_id "
        "WHERE COALESCE(u.profile_private,0)=0 "
        "AND NOT EXISTS(SELECT 1 FROM mini_friend_blocks b WHERE "
        "(b.blocker_id=? AND b.blocked_id=u.user_id) OR (b.blocker_id=u.user_id AND b.blocked_id=?))",
        (uid, uid) if view == "top" else (uid, uid, uid, uid),
    )


async def social(request):
    uid, db = request["actor"]["id"], request.app["db"]
    period = request.query.get("period", "week")
    view = request.query.get("view", "all")
    if period not in {"day", "week", "all"} or view not in {"top", "friends", "all"}:
        return _error("Некорректный раздел или период.")
    cutoff = time.time() - {"day": 86400, "week": 604800, "all": 10**12}[period]
    ranked, friends = {}, []
    live_now = time.monotonic()
    for row in await activity_rows(db, uid, view):
        seen = set()
        latest = None
        live = _LIVE.get(row["user_id"])
        friend = view == "friends" or (view == "all" and row["friend"] and row["user_id"] != uid)
        for key, record in json.loads(row["value"]).items():
            stamp, track = record["at"], record["track"]
            if not stamp:
                continue
            if friend:
                playing = bool(live and live[0] > live_now and live[1] == key)
                if playing or latest is None or (not latest["playing"] and stamp > latest["at"]):
                    latest = {**public_track(key, track), "source": "/api/music-library/social/" + key,
                              "at": stamp, "name": row["telegram_name"] or "Участник", "playing": playing}
            if view == "friends" or stamp < cutoff:
                continue
            identity = track.get("catalog_id") or key
            entry = ranked.get(identity)
            if entry is None:
                entry = ranked[identity] = {**public_track(key, track),
                                            "source": "/api/music-library/social/" + key,
                                            "at": stamp, "listeners": 0}
            if identity not in seen:
                entry["listeners"] += 1
                seen.add(identity)
        if latest:
            friends.append(latest)
    return web.json_response({
        "top": sorted(ranked.values(), key=lambda entry: (-entry["listeners"], -entry["at"]))[:20],
        "friends": sorted(friends, key=lambda entry: (not entry["playing"], -entry["at"]))[:15],
    })


async def resolve(db, uid, source, revision):
    match = (
        re.fullmatch(r"/api/music-library/(history|social)/([a-f0-9]{64})", source)
        if isinstance(source, str) else None
    )
    if not match or not isinstance(revision, str):
        return None
    scope, key = match.groups()
    if scope == "history":
        records = [await read_history(db, uid)]
    else:
        records = (json.loads(row["value"]) for row in await activity_rows(db, uid, "top"))
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
        lease = await request.app["track_disk_cache"].open_track(bot, track)
    except (TelegramAPIError, ClientError, OSError, ValueError):
        raise web.HTTPBadGateway() from None
    try:
        if not await resolve(db, uid, request.path, revision):
            raise web.HTTPNotFound()
        return TrackResponse(lease, track["mime"], request.headers)
    except BaseException:
        lease.close()
        raise


async def buffer_start(request):
    """Serve only an already cached MP3 prefix for an authorized track or Wave choice."""
    from community_bot.social_profiles import _share_track_source

    if request.headers.get("Range") != f"bytes=0-{START_BYTES - 1}":
        raise web.HTTPBadRequest()
    uid, db = request["actor"]["id"], request.app["db"]
    catalog_id = request.query.get("wave")
    if catalog_id is not None:
        entry = _WAVES.get(uid)
        if not entry or time.monotonic() >= entry[0] or catalog_id not in entry[1]:
            raise web.HTTPNotFound()
        if not songs.enabled() or await songs.song_care_error(db, uid):
            raise web.HTTPNotFound()
        track = {"file_id": "catalog:" + catalog_id, "mime": "audio/mpeg"}
    else:
        source = request.query.get("source")
        revision = request.query.get("revision")
        if source and source.startswith("/api/music-library/social/"):
            return web.Response(status=204)
        track = await _share_track_source(db, request.app["settings"], uid, source, revision)
        if not track:
            raise web.HTTPNotFound()

    return await request.app["track_disk_cache"].cached_start(track)


async def preload(request):
    """Load one authorized upcoming track without writing history or presence."""
    from community_bot.social_profiles import _share_track_source

    uid, db = request["actor"]["id"], request.app["db"]
    catalog_id = request.query.get("wave")
    bot = request.app.get("bot")
    if not bot:
        raise web.HTTPNotFound()

    async def resolve_track():
        if catalog_id is None:
            source = request.query.get("source", "")
            if not source.startswith("/api/music-library/"):
                return None
            return await _share_track_source(
                db, request.app["settings"], uid, source, request.query.get("revision"),
            )
        entry = _WAVES.get(uid)
        song = entry[1].get(catalog_id) if entry and time.monotonic() < entry[0] else None
        if not song or not songs.enabled() or await songs.song_care_error(db, uid):
            return None
        return _catalog_track(song)

    track = await resolve_track()
    if track is None:
        raise web.HTTPNotFound()
    # Keep a download slot free for foreground playback and avoid a speculative queue.
    if _PRELOAD_SLOTS.locked():
        return web.Response(status=204, headers={"Cache-Control": "no-store"})
    try:
        async with _PRELOAD_SLOTS:
            lease = await request.app["track_disk_cache"].open_track(bot, track)
    except (TelegramAPIError, ClientError, OSError, ValueError):
        raise web.HTTPBadGateway() from None
    try:
        if await resolve_track() != track:
            raise web.HTTPNotFound()
        response = TrackResponse(lease, track["mime"])
        response.headers["X-Music-Track-Id"] = track_id(track)
        return response
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


async def playing(request):
    from community_bot.social_profiles import _share_track_source

    db, uid = request.app["db"], request["actor"]["id"]
    body = await request.json()
    if not isinstance(body, dict) or type(body.get("playing")) is not bool:
        return _error("Некорректный запрос.")
    if not body["playing"]:
        _LIVE.pop(uid, None)
        return web.json_response({"ok": True})
    if await db.get_bot_state(SOCIAL_PREFIX + str(uid)) != "1":
        _LIVE.pop(uid, None)
        return web.json_response({"ok": True, "public": False})
    source = body.get("source")
    if not isinstance(source, str) or not source.startswith(("/api/music-library/", "/api/profile/track")):
        return _error("Некорректный трек.")
    track = await _share_track_source(db, request.app["settings"], uid, source, body.get("revision"))
    if not track:
        raise web.HTTPNotFound()
    if len(_LIVE) >= 512 and uid not in _LIVE:
        _LIVE.pop(next(iter(_LIVE)), None)
    _LIVE[uid] = (time.monotonic() + 40, track_id(track))
    return web.json_response({"ok": True, "public": True})


def _wave_prune(now):
    for cache in (_WAVES, _WAVE_METADATA):
        for key, entry in list(cache.items()):
            if entry[0] <= now:
                cache.pop(key, None)
    for uid, (stamp, _) in list(_WAVE_LAST.items()):
        if stamp + 60 <= now:
            _WAVE_LAST.pop(uid, None)


async def _wave_search(query, kind="search"):
    key = (kind, query.casefold())
    cached = _WAVE_METADATA.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    existing = _WAVE_LOOKUPS.get(key)
    if existing is not None:
        return await asyncio.shield(existing)
    if _SEARCH_SLOTS.locked() or len(_WAVE_LOOKUPS) >= 3:
        raise songs.SongError("Волна пока недоступна. Попробуй обновить позже.")

    async def lookup():
        try:
            async with _SEARCH_SLOTS:
                tracks = await (songs.find_songs(query) if kind == "search" else songs.wave_catalog(kind, query))
                if len(_WAVE_METADATA) >= _WAVE_CACHE_LIMIT:
                    _WAVE_METADATA.pop(next(iter(_WAVE_METADATA)))
                _WAVE_METADATA[key] = (time.monotonic() + _WAVE_CACHE_TTL, tracks)
                return tracks
        finally:
            _WAVE_LOOKUPS.pop(key, None)

    task = asyncio.create_task(lookup())
    _WAVE_LOOKUPS[key] = task
    return await asyncio.shield(task)


async def wave(request):
    uid, db = request["actor"]["id"], request.app["db"]
    genre = request.query.get("genre", "")
    artist = " ".join(request.query.get("artist", "").split())
    chart = request.query.get("chart", "")
    if (sum(map(bool, (genre, artist, chart))) > 1 or (genre and genre not in _WAVE_GENRES)
            or (chart and chart != "russia") or (artist and not 2 <= len(artist) <= 120)):
        return _error("Некорректная настройка.")
    if not songs.enabled():
        return _error("Музыкальный каталог пока не подключён.", 503)
    problem = await songs.song_care_error(db, uid)
    if problem:
        return _error(problem, 403)
    now = time.monotonic()
    _wave_prune(now)
    station = (genre, _artist_key(artist), chart)
    last, previous_station = _WAVE_LAST.get(uid, (-100, None))
    cooldown = 4 if station == previous_station else 1
    if uid in _IN_FLIGHT or now - last < cooldown:
        return _error("Подожди немного перед обновлением волны.", 429)
    if len(_WAVE_LAST) >= _MAX_USERS and uid not in _WAVE_LAST:
        _WAVE_LAST.pop(next(iter(_WAVE_LAST)))
    _WAVE_LAST[uid] = (now, station)
    _IN_FLIGHT.add(uid)
    try:
        collection = await get_collection(db, uid)
        history = await read_history(db, uid)
        weights, favorites = _wave_taste(collection, history)
        personalized = False
        if artist:
            try:
                batch = await _wave_search(artist, "artist")
            except songs.SongError:
                batch = []
            if not batch:
                batch = [song for song in await _wave_search(artist) if _matches_artist(song, _artist_key(artist))]
            batches = [batch]
        elif chart:
            batches = [await _wave_search(chart, "chart")]
        elif genre:
            batches = await asyncio.gather(_wave_search(_WAVE_RADIO[genre], "genre"), return_exceptions=True)
        else:
            pool = dict(weights)
            seeds = []
            for _ in range(min(2, len(pool))):
                key = random.choices(list(pool), weights=list(pool.values()))[0]
                seeds.append(key)
                del pool[key]
            feeds = [*(_wave_search(key, "similar") for key in seeds), _wave_search("russia", "chart")]
            if not seeds:
                feeds.append(_wave_search(random.choice(tuple(_WAVE_RADIO.values())), "genre"))
            batches = await asyncio.gather(*feeds, return_exceptions=True)
            personalized = bool(seeds and any(isinstance(batch, list) and batch for batch in batches[:len(seeds)]))
        if not (artist or chart) and not any(isinstance(batch, list) and batch for batch in batches):
            queries = random.sample(_WAVE_GENRES[genre] if genre else _WAVE_SEEDS, 3)
            fallback = await asyncio.gather(*(_wave_search(q) for q in queries), return_exceptions=True)
            batches = [
                [song for song in batch if _matches_artist(song, _artist_key(query))]
                for query, batch in zip(queries, fallback, strict=True) if isinstance(batch, list)
            ]
        existing = _WAVES.get(uid)
        previous = existing[1] if existing else {}
        selected = batches[0][:20] if chart else _diverse_wave(batches, set(weights) | previous.keys())
        if not selected and not artist:
            return _error("Волна пока недоступна. Попробуй обновить позже.", 503)
        # Retain prior choices so a search or refresh cannot invalidate the active queue.
        authorized = {**previous, **{song.id: song for song in selected}}
        while len(authorized) > 90:
            authorized.pop(next(iter(authorized)))
        if len(_WAVES) >= _MAX_USERS and uid not in _WAVES:
            _WAVES.pop(next(iter(_WAVES)))
        _WAVES[uid] = (time.monotonic() + _WAVE_TTL, authorized)
        saved = {track.get("catalog_id"): key for key, track in collection.items() if track.get("catalog_id")}
        return web.json_response({"tracks": [
            {"id": song.id, "title": song.title, "artist": song.artist,
             "duration": song.duration, "cover": song.cover, "saved_id": saved.get(song.id)}
            for song in selected
        ], "personalized": personalized, "artists": favorites})
    except songs.SongError as exc:
        return _error(str(exc), 502)
    finally:
        _IN_FLIGHT.discard(uid)
