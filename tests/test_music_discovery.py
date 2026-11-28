import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from community_bot import music_discovery as discovery
from community_bot.database import Database
from community_bot.music_library import get_collection
from community_bot.routers import song_requests as songs


class Request(dict):
    def __init__(self, uid, db, bot, query=None, payload=None):
        super().__init__(actor={"id": uid})
        self.app = {"db": db, "bot": bot}
        self.query = query or {}
        self.payload = payload

    async def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def clear_state():
    discovery._SEARCHES.clear()
    discovery._LAST.clear()
    discovery._IN_FLIGHT.clear()
    yield
    discovery._SEARCHES.clear()
    discovery._LAST.clear()
    discovery._IN_FLIGHT.clear()


async def test_search_and_import_are_private_and_idempotent(tmp_path, monkeypatch):
    db = Database(tmp_path / "discovery.sqlite3")
    await db.initialize()
    await db.ensure_user(1, telegram_name="One")
    await db.ensure_user(2, telegram_name="Two")
    song = songs.Song("123", "456", "Test song", "Artist", 123)
    monkeypatch.setattr(songs, "enabled", lambda: True)
    monkeypatch.setattr(songs, "find_songs", AsyncMock(return_value=[song]))
    monkeypatch.setattr(songs, "song_care_error", AsyncMock(return_value=None))
    monkeypatch.setattr(songs, "_quota_error", AsyncMock(return_value=None))
    monkeypatch.setattr(songs, "_remaining", AsyncMock(return_value=0))
    audio = SimpleNamespace(file_id="private-file", duration=123, file_size=1024)
    deliver = AsyncMock(return_value=audio)
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
    assert (await get_collection(db, 1))[track["id"]]["file_id"] == "private-file"
    assert not await get_collection(db, 2)
    assert deliver.call_args.args[2].chat_id == 1
    again = await discovery.import_track(request)
    assert json.loads(again.body)["already_saved"]
    assert deliver.await_count == 1


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


async def test_failed_or_oversize_import_does_not_add_track(tmp_path, monkeypatch):
    db = Database(tmp_path / "failed.sqlite3")
    await db.initialize()
    await db.ensure_user(1, telegram_name="One")
    song = songs.Song("123", None, "Test", "Artist", 10)
    monkeypatch.setattr(songs, "enabled", lambda: True)
    monkeypatch.setattr(songs, "find_songs", AsyncMock(return_value=[song]))
    monkeypatch.setattr(songs, "song_care_error", AsyncMock(return_value=None))
    monkeypatch.setattr(songs, "_quota_error", AsyncMock(return_value=None))
    monkeypatch.setattr(songs, "_remaining", AsyncMock(return_value=0))
    monkeypatch.setattr(songs, "send_song", AsyncMock(return_value=None))
    bot = object()
    await discovery.search(Request(1, db, bot, {"q": "Test"}))
    request = Request(1, db, bot, payload={"id": "123"})
    assert (await discovery.import_track(request)).status == 409
    monkeypatch.setattr(songs, "send_song", AsyncMock(return_value=SimpleNamespace(
        file_size=discovery.MAX_TRACK_BYTES + 1)))
    assert (await discovery.import_track(request)).status == 413
    assert not await get_collection(db, 1)


async def test_direct_play_does_not_save_and_reuses_private_history(tmp_path, monkeypatch):
    db = Database(tmp_path / "play.sqlite3")
    await db.initialize()
    await db.ensure_user(1, telegram_name="One")
    await db.ensure_user(2, telegram_name="Two")
    song = songs.Song("123", None, "Test", "Artist", 120)
    monkeypatch.setattr(songs, "enabled", lambda: True)
    monkeypatch.setattr(songs, "find_songs", AsyncMock(return_value=[song]))
    monkeypatch.setattr(songs, "song_care_error", AsyncMock(return_value=None))
    monkeypatch.setattr(songs, "_quota_error", AsyncMock(return_value=None))
    monkeypatch.setattr(songs, "_remaining", AsyncMock(return_value=0))
    deliver = AsyncMock(return_value=SimpleNamespace(file_id="test-audio", duration=120, file_size=100))
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
    assert deliver.await_count == 1
    saved = json.loads((await discovery.import_track(request)).body)
    assert saved["source"].startswith("/api/music-library/")
    assert track["id"] in await get_collection(db, 1)
    assert deliver.await_count == 1


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
