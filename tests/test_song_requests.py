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
    await songs.request_song(message, SimpleNamespace(community_chat_id=-100), None)
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
    assert await songs._remaining(Db(), 2, -100) == 20
    assert await songs._remaining(Db(), 3, 4) == 0


@pytest.mark.parametrize("text,expected", [
    ("https://music.yandex.ru/track/987?utm_medium=copy_link", "987"),
    ("Нора https://music.yandex.ru/album/321/track/987?utm_medium=copy_link", "987"),
    ("Нора песня https://music.yandex.ru/album/321/track/987", "987"),
    ("песня https://music.yandex.ru/track/987", "987"),
    ("https://music.yandex.kz/track/987", "987"),
])
def test_yandex_link_command_variants(text, expected):
    assert songs.is_song_request(text)
    link = songs.song_link_request(text)
    assert link is not None
    assert songs.parse_track_link(link)[0] == expected


def test_yandex_track_links_ignore_query_and_keep_album():
    assert songs.parse_track_link("https://music.yandex.ru/album/123/track/456?utm_source=share") == ("456", "123")
    assert songs.parse_track_link("https://music.yandex.ru/track/456/") == ("456", None)


@pytest.mark.parametrize("url", [
    "https://music.yandex.ru/album/123",
    "https://music.yandex.ru/artist/123",
    "https://music.yandex.ru/album/123/track/456/other",
    "https://music.yandex.ru/album/123/track/../../1",
    "https://music.yandex.ru.evil.test/track/123",
    "https://evil.test/track/123",
    "https://music.yandex.ru:9443/track/123",
    "http://music.yandex.ru/track/123",
])
def test_invalid_yandex_track_links_are_rejected(url):
    with pytest.raises(songs.SongError):
        songs.parse_track_link(url)


@pytest.mark.asyncio
async def test_direct_yandex_link_uses_exact_track_without_search(monkeypatch):
    monkeypatch.setenv("NORA_SONGS_ENABLED", "1")
    song = songs.Song("987", "321", "Песня", "Исполнитель", 213)
    find_by_link = AsyncMock(return_value=song)
    search_by_name = AsyncMock()
    send = AsyncMock()
    monkeypatch.setattr(songs, "find_song_by_link", find_by_link)
    monkeypatch.setattr(songs, "find_songs", search_by_name)
    monkeypatch.setattr(songs, "send_song", send)
    bot = SimpleNamespace()
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=10, is_bot=False),
        sender_chat=None, forward_origin=None, via_bot=None,
        chat=SimpleNamespace(id=20, type="private"),
        text="Нора https://music.yandex.ru/album/321/track/987?utm_source=copy_link",
        answer=AsyncMock(),
        bot=bot,
    )
    db = SimpleNamespace()
    await songs.request_song(message, SimpleNamespace(community_chat_id=-100), db)
    find_by_link.assert_awaited_once()
    search_by_name.assert_not_awaited()
    send.assert_awaited_once()
    assert send.await_args.args[0] is bot
    assert send.await_args.args[1] is db
    assert send.await_args.args[3] == song
    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_yandex_link_metadata_api_resolves_exact_track(monkeypatch):
    raw = (b"# Netscape HTTP Cookie File\n"
           b".yandex.ru\tTRUE\t/\tTRUE\t9999999999\tSession_id\tfake-secret\n")
    monkeypatch.setenv("YANDEX_MUSIC_COOKIES_B64", base64.b64encode(raw).decode())
    requested = []

    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def json(self, **_):
            return [{
                "id": "987", "title": "Песня", "available": True,
                "artists": [{"name": "Исполнитель"}],
                "albums": [{"id": "321"}], "durationMs": 200000,
            }]

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def post(self, url, **kwargs):
            requested.append((url, kwargs))
            return Response()

    monkeypatch.setattr(songs.aiohttp, "ClientSession", lambda **_: Session())
    result = await songs.find_song_by_link("https://music.yandex.ru/album/321/track/987?utm=1")
    assert result == songs.Song("987", "321", "Песня", "Исполнитель", 200)
    assert requested[0][0] == "https://api.music.yandex.ru/tracks"
    assert requested[0][1]["allow_redirects"] is False
    assert requested[0][1]["data"]._fields[0][2] == "987:321"



@pytest.mark.asyncio
async def test_successful_cached_songs_have_60_second_cooldown_and_five_daily_deliveries(tmp_path, monkeypatch):
    from community_bot.database import Database

    db = Database(tmp_path / "songs.db")
    await db.initialize()
    song = songs.Song("987", "321", "Песня", "Исполнитель", 200)
    choice = songs.Choices(user_id=17, chat_id=-100, expires=999999, tracks=[song])
    await db.set_bot_state("song:file_id:987", "already_uploaded_audio")
    bot = SimpleNamespace(
        send_audio=AsyncMock(return_value=SimpleNamespace(audio=SimpleNamespace(file_id="cached"))),
        send_message=AsyncMock(),
    )

    monkeypatch.setattr(songs.time, "time", lambda: 1000.0)
    await songs.send_song(bot, db, choice, song)
    assert await songs._daily_used(db, 17) == 1

    monkeypatch.setattr(songs.time, "time", lambda: 1000.1)
    assert await songs._remaining(db, 17, -100) == 60
    await songs.send_song(bot, db, choice, song)
    assert bot.send_audio.await_count == 1
    assert await songs._daily_used(db, 17) == 1
    assert "через 60 сек" in bot.send_message.await_args.args[1]

    for index in range(1, 5):
        monkeypatch.setattr(songs.time, "time", lambda index=index: 1000 + index * 61)
        await songs.send_song(bot, db, choice, song)
        assert await songs._daily_used(db, 17) == index + 1

    assert bot.send_audio.await_count == 5
    monkeypatch.setattr(songs.time, "time", lambda: 2000)
    await songs.send_song(bot, db, choice, song)
    assert bot.send_audio.await_count == 5
    assert await songs._daily_used(db, 17) == 5
    assert "00:00 МСК" in bot.send_message.await_args.args[1]
    assert await songs._daily_used(db, 18) == 0


@pytest.mark.asyncio
async def test_failed_song_does_not_use_daily_quota_or_cooldown(tmp_path, monkeypatch):
    from community_bot.database import Database

    db = Database(tmp_path / "failed_songs.db")
    await db.initialize()
    monkeypatch.delenv("YANDEX_MUSIC_COOKIES_B64", raising=False)
    song = songs.Song("123", None, "Не загружается", "Artist", 180)
    choice = songs.Choices(user_id=42, chat_id=100, expires=99999, tracks=[song])
    status = SimpleNamespace(delete=AsyncMock())
    bot = SimpleNamespace(send_audio=AsyncMock(), send_message=AsyncMock(return_value=status))
    await songs.send_song(bot, db, choice, song)
    assert bot.send_audio.await_count == 0
    assert await songs._daily_used(db, 42) == 0
    assert await db.get_bot_state("song:last_user:42") is None
    assert await db.get_bot_state("song:last_chat:100") is None
    status.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_daily_song_counter_uses_moscow_calendar_day(tmp_path, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from community_bot.database import Database

    db = Database(tmp_path / "midnight_songs.db")
    await db.initialize()
    msk = ZoneInfo("Europe/Moscow")
    choice = songs.Choices(user_id=42, chat_id=100, expires=123, tracks=[])
    monkeypatch.setattr(songs, "moscow_now", lambda: datetime(2026, 11, 21, 23, 59, tzinfo=msk))
    await songs._mark_sent(db, choice)
    assert await songs._daily_used(db, 42) == 1
    monkeypatch.setattr(songs, "moscow_now", lambda: datetime(2026, 11, 22, 0, 1, tzinfo=msk))
    assert await songs._daily_used(db, 42) == 0
    await songs._mark_sent(db, choice)
    assert await songs._daily_used(db, 42) == 1
    assert await db.get_bot_state("song:daily:42:2026-11-21") == "1"
    assert await db.get_bot_state("song:daily:42:2026-11-22") == "1"
