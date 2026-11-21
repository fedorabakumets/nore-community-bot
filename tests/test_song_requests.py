"""Isolated tests for the opt-in Yandex song feature, without network calls."""
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from community_bot.routers import song_requests as songs


def test_song_triggers():
    assert songs.song_query("Нора песня «Кино Группа крови»") == "Кино Группа крови"
    assert songs.song_query("песня M83 Midnight City") == "M83 Midnight City"
    assert songs.song_query("НОРА, ПЕСНЯ: Группа крови") == "Группа крови"
    assert songs.song_query("Нора песня") == ""
    assert songs.song_query("Нора расскажи про песню") is None
    assert songs.song_query("последняя песня") is None
    assert len(songs.song_query("песня " + "x" * 200)) == 120


def test_parse_results_and_urls():
    payload = {"result": {"tracks": {"results": [
        {"id": 100, "title": "Группа крови", "artists": [{"name": "Кино"}],
         "albums": [{"id": 200}], "durationMs": 270000, "available": True},
        {"id": 100, "title": "Повтор", "artists": []},
        {"id": "oops", "title": "Ошибка", "artists": []},
        {"id": 101, "title": "Недоступна", "available": False},
        {"id": 102, "title": "Песня", "artists": [{"name": "A"}, {"name": "B"}],
         "albums": [], "durationMs": None},
    ]}}}
    result = songs.parse_search_results(payload)
    assert len(result) == 2
    assert result[0].url == "https://music.yandex.ru/album/200/track/100"
    assert result[0].duration == 270
    assert result[0].artist == "Кино"
    assert result[1].artist == "A, B"
    assert result[1].duration == 0
    assert result[1].url == "https://music.yandex.ru/track/102"
    assert songs.parse_search_results({"result": False}) == []


def test_preview_guard():
    assert songs.is_full_track(200, 205)
    assert not songs.is_full_track(22, 210)
    assert songs.is_full_track(26, 27)
    assert not songs.is_full_track(0, 120)
    assert not songs.is_full_track(30, 0)
    assert songs.is_full_track(120, 0)


def test_cookie_secret(monkeypatch):
    monkeypatch.delenv("YANDEX_MUSIC_COOKIES_B64", raising=False)
    with pytest.raises(songs.SongError, match="не подключена"):
        songs._cookie_bytes()
    monkeypatch.setenv("YANDEX_MUSIC_COOKIES_B64", "not-base64")
    with pytest.raises(songs.SongError, match="формат"):
        songs._cookie_bytes()
    raw = (b"# Netscape HTTP Cookie File\n"
           b"#HttpOnly_.yandex.ru\tTRUE\t/\tTRUE\t9999999999\tSession_id\tfake-secret\n"
           b".other.tld\tTRUE\t/\tTRUE\t9999999999\tignored\tother\n")
    monkeypatch.setenv("YANDEX_MUSIC_COOKIES_B64", base64.b64encode(raw).decode())
    assert songs._cookie_bytes() == raw
    assert songs._cookie_header(raw) == "Session_id=fake-secret"


@pytest.mark.asyncio
async def test_disabled_request_does_not_search(monkeypatch):
    monkeypatch.delenv("NORA_SONGS_ENABLED", raising=False)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=10, is_bot=False),
        sender_chat=None, forward_origin=None, via_bot=None,
        chat=SimpleNamespace(id=-100, type="supergroup"),
        text="Нора песня Кино", answer=AsyncMock(),
    )
    await songs.request_song(message, SimpleNamespace(community_chat_id=-100))
    message.answer.assert_awaited_once()
    assert "не подключены" in message.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_search_without_cookies_fails_closed(monkeypatch):
    monkeypatch.delenv("YANDEX_MUSIC_COOKIES_B64", raising=False)
    with pytest.raises(songs.SongError, match="не подключена"):
        await songs.find_songs("Кино")


@pytest.mark.asyncio
async def test_unauthorized_callback_does_not_download():
    key = "testchoice"
    songs._CHOICES[key] = songs.Choices(
        user_id=10, chat_id=-100, expires=songs.time.monotonic() + 60,
        tracks=[songs.Song("123", "456", "Title", "Artist", 180)],
    )
    try:
        callback = SimpleNamespace(
            data=f"song:{key}:0", from_user=SimpleNamespace(id=11),
            message=SimpleNamespace(chat=SimpleNamespace(id=-100)),
            answer=AsyncMock(),
        )
        await songs.song_chosen(callback, None)
        callback.answer.assert_awaited_once()
        assert callback.answer.await_args.kwargs["show_alert"] is True
    finally:
        songs._CHOICES.pop(key, None)


@pytest.mark.asyncio
async def test_cooldown_is_persistent(monkeypatch):
    class Db:
        async def get_bot_state(self, key):
            return {"song:last_user:2": "100", "song:last_chat:-100": "110"}.get(key)

    monkeypatch.setattr(songs.time, "time", lambda: 150)
    assert await songs._remaining(Db(), 2, -100) == 260
    assert await songs._remaining(Db(), 3, 4) == 0
