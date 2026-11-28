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
