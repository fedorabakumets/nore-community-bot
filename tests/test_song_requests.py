"""Isolated tests for the opt-in Yandex song feature, without network calls."""
import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from community_bot import song_worker
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
    assert song_worker.is_full_track(200, 205)
    assert not song_worker.is_full_track(22, 210)
    assert song_worker.is_full_track(26, 27)
    assert not song_worker.is_full_track(0, 120)
    assert not song_worker.is_full_track(30, 0)
    assert song_worker.is_full_track(120, 0)


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
    db = SimpleNamespace(get_pet=AsyncMock(return_value=None))
    await songs.request_song(message, SimpleNamespace(community_chat_id=-100), db)
    find_by_link.assert_awaited_once()
    search_by_name.assert_not_awaited()
    send.assert_awaited_once()
    assert send.await_args.args[0] is bot
    assert send.await_args.args[1] is db
    assert send.await_args.args[3] == song
    message.answer.assert_not_awaited()


def test_yandex_link_uses_same_extractor_as_song_download(monkeypatch, tmp_path):
    import yt_dlp

    raw = (b"# Netscape HTTP Cookie File\n"
           b".yandex.ru\tTRUE\t/\tTRUE\t9999999999\tSession_id\tfake-secret\n")
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_bytes(raw)
    seen = []

    class FakeYDL:
        def __init__(self, options):
            self.options = options
            seen.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def extract_info(self, url, download):
            assert self.options["skip_download"] is True
            assert self.options["cookiefile"]
            assert Path(self.options["cookiefile"]).read_bytes() == raw
            assert download is False
            assert url == "https://music.yandex.ru/album/321/track/987"
            return {
                "id": "987", "title": "Песня", "artist": "Исполнитель",
                "album_id": "321", "duration": 200.5,
            }

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    result = song_worker.resolve_metadata("987", "321", str(cookie_file))
    assert result == songs.Song("987", "321", "Песня", "Исполнитель", 200)
    assert len(seen) == 1


def test_yandex_link_extractor_rejects_missing_or_wrong_track(monkeypatch, tmp_path):
    import yt_dlp

    raw = (b"# Netscape HTTP Cookie File\n"
           b".yandex.ru\tTRUE\t/\tTRUE\t9999999999\tSession_id\tfake-secret\n")
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_bytes(raw)

    class FakeYDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def extract_info(self, _url, download):
            return {"id": "999", "title": "Не тот трек"}

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    with pytest.raises(songs.SongError, match="нужной песни"):
        song_worker.resolve_metadata("987", None, str(cookie_file))


def test_yandex_link_extractor_returns_helpful_error_not_secrets(monkeypatch, tmp_path):
    import yt_dlp

    raw = (b"# Netscape HTTP Cookie File\n"
           b".yandex.ru\tTRUE\t/\tTRUE\t9999999999\tSession_id\tfake-secret\n")
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_bytes(raw)

    class FakeYDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def extract_info(self, _url, download):
            raise RuntimeError("fake-secret")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    with pytest.raises(songs.SongError) as error:
        song_worker.resolve_metadata("987", None, str(cookie_file))
    assert "fake-secret" not in str(error.value)


async def test_yandex_worker_resolves_track_in_separate_process(monkeypatch):
    spawn = asyncio.create_subprocess_exec
    process = None
    stub = """
import os, runpy, sys, types
from pathlib import Path
class FakeYDL:
    def __init__(self, options):
        path = Path(options["cookiefile"])
        assert path.read_bytes() == b"fake cookie"
        if os.name == "posix":
            assert path.stat().st_mode & 0o777 == 0o600
        assert "YANDEX_MUSIC_COOKIES_B64" not in os.environ
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass
    def extract_info(self, url, download):
        assert url == "https://music.yandex.ru/album/321/track/987"
        assert not download
        return {"id": "987", "title": "Песня", "artist": "Имя", "duration": 200}
sys.modules["yt_dlp"] = types.SimpleNamespace(YoutubeDL=FakeYDL)
runpy.run_module("community_bot.song_worker", run_name="__main__")
"""

    async def launch(executable, *args, **kwargs):
        nonlocal process
        assert args == ("-m", "community_bot.song_worker")
        process = await spawn(executable, "-c", stub, **kwargs)
        return process

    monkeypatch.setattr(songs, "_cookie_bytes", lambda: b"fake cookie")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    assert await songs.find_song_by_link("https://music.yandex.ru/album/321/track/987") == songs.Song(
        "987", "321", "Песня", "Имя", 200,
    )
    assert process.returncode == 0


async def test_cancelled_yandex_worker_is_reaped(monkeypatch, tmp_path):
    spawn = asyncio.create_subprocess_exec
    started = asyncio.Event()
    process = None

    async def launch(executable, *_args, **kwargs):
        nonlocal process
        process = await spawn(executable, "-c", "import time; time.sleep(30)", **kwargs)
        started.set()
        return process

    monkeypatch.setattr(songs, "_cookie_bytes", lambda: b"fake cookie")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    task = asyncio.create_task(songs.download_song(songs.Song("987", None, "X", "Y", 200), str(tmp_path)))
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)
    assert process.returncode is not None


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



@pytest.mark.asyncio
@pytest.mark.parametrize("hunger,thirst", [(49, 100), (100, 49), (49, 49)])
@pytest.mark.parametrize("text", ["Нора песня Кино", "https://music.yandex.ru/album/321/track/987"])
async def test_low_pet_needs_block_song_query_and_direct_links(tmp_path, monkeypatch, hunger, thirst, text):
    from community_bot.database import Database

    db = Database(tmp_path / "blocked-song.db")
    await db.initialize()
    await db.ensure_user(10)
    await db.add_cookies(10, 10, "test")
    assert (await db.purchase_pet(10, "cat", "Кот", 1))[0]
    await db.execute("UPDATE pets SET hunger=?,thirst=? WHERE user_id=10", (hunger, thirst))
    monkeypatch.setenv("NORA_SONGS_ENABLED", "1")
    search = AsyncMock()
    by_link = AsyncMock()
    monkeypatch.setattr(songs, "find_songs", search)
    monkeypatch.setattr(songs, "find_song_by_link", by_link)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=10, is_bot=False),
        sender_chat=None, forward_origin=None, via_bot=None,
        chat=SimpleNamespace(id=10, type="private"),
        text=text, answer=AsyncMock(), bot=SimpleNamespace(),
    )
    await songs.request_song(message, SimpleNamespace(community_chat_id=-100), db)
    assert "50" in message.answer.await_args.args[0]
    search.assert_not_awaited()
    by_link.assert_not_awaited()


@pytest.mark.asyncio
async def test_song_query_recovers_at_50_and_old_choice_cannot_bypass_gate(tmp_path, monkeypatch):
    from community_bot.database import Database

    db = Database(tmp_path / "song-choice.db")
    await db.initialize()
    await db.ensure_user(10)
    await db.add_cookies(10, 10, "test")
    assert (await db.purchase_pet(10, "cat", "Кот", 1))[0]
    monkeypatch.setenv("NORA_SONGS_ENABLED", "1")
    song = songs.Song("987", "321", "Песня", "Артист", 90)
    find = AsyncMock(return_value=[song])
    monkeypatch.setattr(songs, "find_songs", find)
    await db.execute("UPDATE pets SET hunger=50,thirst=50 WHERE user_id=10")
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=10, is_bot=False),
        sender_chat=None, forward_origin=None, via_bot=None,
        chat=SimpleNamespace(id=10, type="private"),
        text="Нора песня Кино", answer=AsyncMock(), bot=SimpleNamespace(),
    )
    await songs.request_song(message, SimpleNamespace(community_chat_id=-100), db)
    find.assert_awaited_once_with("Кино")
    assert "Выбери песню" in message.answer.await_args.args[0]
    key = message.answer.await_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data.split(":")[1]
    bot = SimpleNamespace(send_audio=AsyncMock(), send_message=AsyncMock())
    callback = SimpleNamespace(
        data=f"song:{key}:0", from_user=SimpleNamespace(id=10),
        message=SimpleNamespace(chat=SimpleNamespace(id=10)), answer=AsyncMock(), bot=bot,
    )
    await db.set_bot_state("song:file_id:987", "cached-audio")
    try:
        await db.execute("UPDATE pets SET hunger=49,thirst=100 WHERE user_id=10")
        await songs.song_chosen(callback, db)
        assert "50" in callback.answer.await_args.args[0]
        assert callback.answer.await_args.kwargs["show_alert"] is True
        bot.send_audio.assert_not_awaited()
        await songs.send_song(bot, db, songs._CHOICES[key], song)
        assert "50" in bot.send_message.await_args.args[1]
        assert await songs._daily_used(db, 10) == 0
        assert await db.get_bot_state("song:last_user:10") is None

        await db.execute("UPDATE pets SET hunger=50,thirst=50 WHERE user_id=10")
        assert await songs.song_care_error(db, 10) is None
        await songs.song_chosen(callback, db)
        bot.send_audio.assert_awaited_once()
        assert await songs._daily_used(db, 10) == 1
    finally:
        songs._CHOICES.pop(key, None)
