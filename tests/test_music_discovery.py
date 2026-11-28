import json
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from community_bot import music_discovery as discovery
from community_bot.database import Database
from community_bot.music_library import get_collection
from community_bot.routers import song_requests as songs
from community_bot.track_disk_cache import START_BYTES


class Request(dict):
    def __init__(self, uid, db, bot, query=None, payload=None):
        super().__init__(actor={"id": uid})
        self.app = {"db": db, "bot": bot}
        self.query = query or {}
        self.headers = {}
        self.payload = payload

    async def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def clear_state():
    discovery._SEARCHES.clear()
    discovery._LAST.clear()
    discovery._IN_FLIGHT.clear()
    discovery._WAVES.clear()
    discovery._WAVE_LAST.clear()
    discovery._WAVE_METADATA.clear()
    yield
    discovery._SEARCHES.clear()
    discovery._LAST.clear()
    discovery._IN_FLIGHT.clear()
    discovery._WAVES.clear()
    discovery._WAVE_LAST.clear()
    discovery._WAVE_METADATA.clear()


async def test_search_and_import_are_private_and_idempotent(tmp_path, monkeypatch):
    db = Database(tmp_path / "discovery.sqlite3")
    await db.initialize()
    await db.ensure_user(1, telegram_name="One")
    await db.ensure_user(2, telegram_name="Two")
    song = songs.Song("123", "456", "Test song", "Artist", 123)
    monkeypatch.setattr(songs, "enabled", lambda: True)
    monkeypatch.setattr(songs, "find_songs", AsyncMock(return_value=[song]))
    monkeypatch.setattr(songs, "song_care_error", AsyncMock(return_value=None))
    monkeypatch.setattr(songs, "_quota_error", AsyncMock(side_effect=AssertionError("chat quota must not be used")))
    monkeypatch.setattr(songs, "_remaining", AsyncMock(side_effect=AssertionError("chat cooldown must not be used")))
    deliver = AsyncMock(side_effect=AssertionError("must not send Telegram audio"))
    monkeypatch.setattr(songs, "send_song", deliver)
    bot = object()
    response = await discovery.search(Request(1, db, bot, {"q": "Artist"}))
    result = json.loads(response.body)
    assert response.status == 200
    assert result["tracks"][0]["id"] == "123"
    assert "file_id" not in result["tracks"][0]
    denied = await discovery.import_track(Request(2, db, bot, payload={"id": "123"}))
    assert denied.status == 409
    assert deliver.await_count == 0
    request = Request(1, db, bot, payload={"id": "123"})
    imported = await discovery.import_track(request)
    assert imported.status == 200
    track = json.loads(imported.body)["track"]
    assert "file_id" not in track
    assert (await get_collection(db, 1))[track["id"]]["file_id"] == "catalog:123"
    assert not await get_collection(db, 2)
    again = await discovery.import_track(request)
    assert json.loads(again.body)["already_saved"]
    assert deliver.await_count == 0


async def test_search_disabled_and_pet_gate(tmp_path, monkeypatch):
    db = Database(tmp_path / "gates.sqlite3")
    await db.initialize()
    await db.ensure_user(1, telegram_name="One")
    find = AsyncMock()
    monkeypatch.setattr(songs, "find_songs", find)
    monkeypatch.setattr(songs, "enabled", lambda: False)
    request = Request(1, db, object(), {"q": "Artist"})
    assert (await discovery.search(request)).status == 503
    monkeypatch.setattr(songs, "enabled", lambda: True)
    monkeypatch.setattr(songs, "song_care_error", AsyncMock(return_value="Pet gate"))
    assert (await discovery.search(request)).status == 403
    find.assert_not_awaited()


async def test_many_catalog_tracks_without_chat_quota(tmp_path, monkeypatch):
    db = Database(tmp_path / "unlimited.sqlite3")
    await db.initialize()
    await db.ensure_user(1, telegram_name="One")
    tracks = [songs.Song(str(i), None, "Test", "Artist", 120) for i in range(1, 9)]
    monkeypatch.setattr(songs, "enabled", lambda: True)
    monkeypatch.setattr(songs, "find_songs", AsyncMock(return_value=tracks))
    monkeypatch.setattr(songs, "song_care_error", AsyncMock(return_value=None))
    monkeypatch.setattr(songs, "_quota_error", AsyncMock(side_effect=AssertionError("chat quota")))
    monkeypatch.setattr(songs, "_remaining", AsyncMock(side_effect=AssertionError("chat cooldown")))
    monkeypatch.setattr(songs, "send_song", AsyncMock(side_effect=AssertionError("Telegram delivery")))
    await discovery.search(Request(1, db, None, {"q": "Test"}))
    for track in tracks:
        request = Request(1, db, None, payload={"id": track.id})
        assert (await discovery.import_track(request)).status == 200
    assert len(await get_collection(db, 1)) == 8


async def test_direct_play_does_not_save_and_reuses_private_history(tmp_path, monkeypatch):
    db = Database(tmp_path / "play.sqlite3")
    await db.initialize()
    await db.ensure_user(1, telegram_name="One")
    await db.ensure_user(2, telegram_name="Two")
    song = songs.Song("123", None, "Test", "Artist", 120)
    monkeypatch.setattr(songs, "enabled", lambda: True)
    monkeypatch.setattr(songs, "find_songs", AsyncMock(return_value=[song]))
    monkeypatch.setattr(songs, "song_care_error", AsyncMock(return_value=None))
    monkeypatch.setattr(songs, "_quota_error", AsyncMock(side_effect=AssertionError("chat quota must not be used")))
    monkeypatch.setattr(songs, "_remaining", AsyncMock(side_effect=AssertionError("chat cooldown must not be used")))
    deliver = AsyncMock(side_effect=AssertionError("must not send Telegram audio"))
    monkeypatch.setattr(songs, "send_song", deliver)
    bot = object()
    await discovery.search(Request(1, db, bot, {"q": "Test"}))
    request = Request(1, db, bot, payload={"id": "123"})
    response = json.loads((await discovery.play_track(request)).body)
    track, source = response["track"], response["source"]
    assert source.startswith("/api/music-library/history/")
    assert not await get_collection(db, 1)
    assert await discovery.resolve(db, 1, source, track["revision"])
    assert not await discovery.resolve(db, 2, source, track["revision"])
    assert not await discovery.resolve(db, 1, source, "bad")
    assert not json.loads((await discovery.history(Request(1, db, bot))).body)["tracks"]
    again = json.loads((await discovery.play_track(request)).body)
    assert again == response
    assert deliver.await_count == 0
    saved = json.loads((await discovery.import_track(request)).body)
    assert saved["source"].startswith("/api/music-library/")
    assert track["id"] in await get_collection(db, 1)
    assert deliver.await_count == 0


async def test_chart_is_opt_in_and_counts_unique_listeners(tmp_path):
    db = Database(tmp_path / "social.sqlite3")
    await db.initialize()
    for uid in (1, 2, 3):
        await db.ensure_user(uid, telegram_name=str(uid))
    sample = {"file_id": "a", "revision": "a" * 32, "title": "Track", "artist": "Artist",
              "duration": 90, "mime": "audio/mpeg", "catalog_id": "123"}
    key = await discovery.remember(db, 1, sample, listened=True)
    await discovery.remember(db, 1, sample, listened=True)
    await discovery.remember(db, 2, {**sample, "file_id": "b", "revision": "b" * 32}, listened=True)
    req = Request(3, db, None)
    assert not json.loads((await discovery.social(req)).body)["top"]
    for uid in (1, 2):
        await discovery.activity_visibility(Request(uid, db, None, payload={"public": True}))
    top = json.loads((await discovery.social(req)).body)["top"]
    assert len(top) == 1 and top[0]["listeners"] == 2
    assert "file_id" not in top[0]
    assert await discovery.resolve(db, 3, "/api/music-library/social/" + key, sample["revision"])
    await discovery.activity_visibility(Request(1, db, None, payload={"public": False}))
    assert not await discovery.resolve(db, 3, "/api/music-library/social/" + key, sample["revision"])
    assert json.loads((await discovery.social(req)).body)["top"][0]["listeners"] == 1
    await db.reset_banned_user(2, None)
    assert not await discovery.read_history(db, 2)
    assert not json.loads((await discovery.social(req)).body)["top"]


async def test_friend_feed_uses_friends_only_and_keeps_privacy_checks(tmp_path):
    db = Database(tmp_path / "friends.sqlite3")
    await db.initialize()
    for uid in (1, 2, 3):
        await db.ensure_user(uid, telegram_name=str(uid))
    await db.execute("INSERT INTO mini_friendships VALUES(1,2,1,'accepted','test','now','now',0,0)")
    for uid in (2, 3):
        await discovery.remember(db, uid, {
            "file_id": str(uid), "revision": "a" * 32, "title": "Track",
            "artist": "Artist", "duration": 90, "mime": "audio/mpeg",
        }, listened=True)
        await discovery.activity_visibility(Request(uid, db, None, payload={"public": True}))
    request = Request(1, db, None, {"view": "friends"})
    result = json.loads((await discovery.social(request)).body)
    assert not result["top"]
    assert [row["name"] for row in result["friends"]] == ["2"]
    top = json.loads((await discovery.social(Request(1, db, None, {"view": "top"}))).body)
    assert len(top["top"]) == 2 and not top["friends"]
    await db.execute("INSERT INTO mini_friend_blocks VALUES(2,1,'test','now')")
    assert not json.loads((await discovery.social(request)).body)["friends"]


async def test_wave_uses_external_metadata_and_personal_taste_without_audio(tmp_path, monkeypatch):
    db = Database(tmp_path / "wave.sqlite3")
    await db.initialize()
    for uid in (1, 2, 3):
        await db.ensure_user(uid, telegram_name=str(uid))
    monkeypatch.setattr(songs, "enabled", lambda: True)
    monkeypatch.setattr(songs, "song_care_error", AsyncMock(return_value=None))
    monkeypatch.setattr(discovery, "_WAVE_SEEDS", ("Seed A", "Seed B", "Seed C", "Seed D"))
    monkeypatch.setattr(discovery.random, "sample", lambda values, k: list(values)[:k])
    async def lookup(query):
        index = {"Seed A": 1, "Seed B": 2, "Seed C": 3, "Seed D": 4, "Favorite": 5}[query]
        return [songs.Song(str(index), None, "Song " + query, query, 120)]
    find = AsyncMock(side_effect=lookup)
    monkeypatch.setattr(songs, "find_songs", find)
    delivery = AsyncMock(side_effect=AssertionError("must not send Telegram audio"))
    monkeypatch.setattr(songs, "send_song", delivery)
    response = json.loads((await discovery.wave(Request(1, db, None))).body)
    assert not response["personalized"]
    assert len(response["tracks"]) == 3
    assert not await get_collection(db, 1)
    assert not await discovery.read_history(db, 1)
    assert find.await_count == 3
    await discovery.wave(Request(2, db, None))
    assert find.await_count == 3
    denied = await discovery.play_track(Request(3, db, None, payload={"id": "1", "wave": True}))
    assert denied.status == 409
    play = await discovery.play_track(Request(1, db, None, payload={"id": "1", "wave": True}))
    assert play.status == 200
    await discovery.remember(db, 1, {"file_id": "catalog:9", "catalog_id": "9",
        "title": "Favorite song", "artist": "Favorite", "mime": "audio/mpeg",
        "duration": 120, "revision": "a"*32}, listened=True)
    discovery._WAVE_LAST.clear()
    response = json.loads((await discovery.wave(Request(1, db, None))).body)
    assert response["personalized"]
    assert any(track["artist"] == "Favorite" for track in response["tracks"])
    assert find.await_count == 4
    delivery.assert_not_awaited()


async def test_wave_prefix_checks_offer_and_pet_without_preparing_or_downloading(tmp_path, monkeypatch):
    db = Database(tmp_path / "wave-prefix.sqlite3")
    await db.initialize()
    await db.ensure_user(1, telegram_name="One")
    cache = AsyncMock()
    cache.cached_start.return_value = web.Response(status=204)
    gate = AsyncMock(return_value=None)
    monkeypatch.setattr(songs, "enabled", lambda: True)
    monkeypatch.setattr(songs, "song_care_error", gate)
    offer = {"123": songs.Song("123", None, "Test", "Artist", 120)}
    discovery._WAVES[1] = (discovery.time.monotonic() + 30, offer)

    async def buffer_for(uid):
        request = Request(uid, db, None, {"wave": "123"})
        request.app["track_disk_cache"] = cache
        request.headers["Range"] = f"bytes=0-{START_BYTES - 1}"
        return await discovery.buffer_start(request)

    with pytest.raises(web.HTTPNotFound):
        await buffer_for(2)
    cache.cached_start.assert_not_called()
    assert (await buffer_for(1)).status == 204
    cache.cached_start.assert_awaited_once_with({"file_id": "catalog:123", "mime": "audio/mpeg"})
    assert not await discovery.read_history(db, 1)
    assert not await get_collection(db, 1)
    gate.return_value = "Pet gate"
    with pytest.raises(web.HTTPNotFound):
        await buffer_for(1)
    assert cache.cached_start.await_count == 1


async def test_wave_stations_filter_provider_matches_and_keep_previous_choices(tmp_path, monkeypatch):
    db = Database(tmp_path / "stations.sqlite3")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Listener")
    monkeypatch.setattr(songs, "enabled", lambda: True)
    monkeypatch.setattr(songs, "song_care_error", AsyncMock(return_value=None))
    monkeypatch.setattr(discovery.random, "sample", lambda values, count: list(values)[:count])
    monkeypatch.setattr(discovery, "_WAVE_GENRES", {"house": ("First", "Second", "Third")})
    names = ["First", "Second", "Third", "Chosen"]

    async def lookup(query):
        index = names.index(query) + 1
        return [
            songs.Song(str(index), None, query, query + ", Guest", 120),
            songs.Song(str(index + 10), None, query, "Unrelated", 120),
        ]

    monkeypatch.setattr(songs, "find_songs", lookup)
    genre = await discovery.wave(Request(1, db, None, {"genre": "house"}))
    assert {track["id"] for track in json.loads(genre.body)["tracks"]} == {"1", "2", "3"}
    discovery._WAVE_LAST.clear()
    artist = await discovery.wave(Request(1, db, None, {"artist": " Chosen "}))
    assert [track["id"] for track in json.loads(artist.body)["tracks"]] == ["4"]
    assert set(discovery._WAVES[1][1]) == {"1", "2", "3", "4"}
    invalid = await discovery.wave(Request(1, db, None, {"genre": "house", "artist": "Chosen"}))
    assert invalid.status == 400
