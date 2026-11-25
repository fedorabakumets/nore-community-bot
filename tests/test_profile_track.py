import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.types import Audio, Chat, Message, User
from aiohttp import web
from yt_dlp.networking.exceptions import HTTPError, TransportError

from community_bot import pet_video, pet_video_worker
from community_bot.database import Database
from community_bot.group_profile import send_group_profile
from community_bot.profile_track import get_track, save_from_message, track_command
from community_bot.social_profiles import track_audio
from community_bot.track_disk_cache import TrackDiskCache


async def test_reply_replaces_profile_audio_and_uses_same_file_in_both_profiles(tmp_path, monkeypatch):
    db = Database(tmp_path / "track.sqlite3")
    await db.initialize()
    await db.ensure_user(7, telegram_name="Ник")
    await db.update_profile(7, "birth_date", "2000-01-01")
    chat = Chat(id=-1001, type="supergroup")
    user = User(id=7, first_name="Ник", is_bot=False)
    settings = SimpleNamespace(
        community_chat_id=chat.id, is_owner=lambda uid: False, moderator_ids=set(),
        restricted_reputation_threshold=0,
    )
    when = datetime.now(UTC)
    bot = SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(username="nora_bot")))

    def telegram_file(file_id, command, message_id):
        source = Message(chat=chat, message_id=1, date=when,
                         audio=Audio(file_id=file_id, file_unique_id=file_id, duration=7, title="Темп"))
        return Message(chat=chat, message_id=message_id, date=when, from_user=user,
                       text=command, reply_to_message=source).as_(bot)

    replies = AsyncMock()
    monkeypatch.setattr(Message, "reply", replies)
    for i, command in enumerate(("Нора добавить", "добавить", "+"), 2):
        message = telegram_file(f"audio_{i}", command, i)
        assert track_command(message)
        await save_from_message(message, db, settings)
    assert not track_command(message.model_copy(update={"reply_to_message": None}))
    track = await get_track(db, user.id)
    assert track["file_id"] == "audio_4"
    assert replies.await_count == 3

    bot.send_rich_message = AsyncMock(return_value=message)
    await send_group_profile(message, db, settings, await db.get_user(user.id), user.id)
    blocks = bot.send_rich_message.await_args.kwargs["rich_message"].blocks
    age_pos = next(i for i, block in enumerate(blocks) if block.type == "paragraph" and "Возраст" in block.text)
    assert blocks[age_pos + 1].audio.media == track["file_id"]

    async def telegram_download(file_id, *, destination, **options):
        assert file_id == track["file_id"]
        destination.write(b"mp3")

    bot.download = telegram_download
    cache = TrackDiskCache(directory=tmp_path / "audio")
    request = SimpleNamespace(
        app={"db": db, "bot": bot, "settings": settings, "track_disk_cache": cache}, path="/api/people/7/track",
        match_info={"user_id": "7"}, query={"v": track["revision"]},
    )

    class Request(dict):
        def __getattr__(self, name):
            return getattr(request, name)

    visitor = Request(actor={"id": 8})
    request.query["check"] = "1"
    assert (await track_audio(visitor)).status == 204
    assert not cache._entries
    del request.query["check"]
    response = await track_audio(visitor)
    assert response.lease.file.read() == b"mp3"
    response.lease.close()
    await db.update_profile(user.id, "profile_private", 1)
    with pytest.raises(web.HTTPNotFound):
        await track_audio(visitor)
    request.query["check"] = "1"
    with pytest.raises(web.HTTPNotFound):
        await track_audio(visitor)
    del request.query["check"]
    request.path = "/api/profile/track"
    request.query["v"] = "expired-revision"
    with pytest.raises(web.HTTPNotFound):
        await track_audio(Request(actor={"id": user.id}))
    request.query["v"] = track["revision"]
    response = await track_audio(Request(actor={"id": user.id}))
    assert response.content_type == "audio/mpeg"
    response.lease.close()
    cache.close()
    await db.reset_banned_user(user.id, None)
    assert await get_track(db, user.id) is None


async def test_music_shares_download_queue_and_labels_preview(tmp_path, monkeypatch):
    db = Database(tmp_path / "music.sqlite3")
    await db.initialize()
    queue = pet_video.PetVideoQueue(db)
    queue._access_error = AsyncMock(return_value=None)
    url = pet_video.canonical_url("https://music.yandex.ru/album/123/track/456?utm_medium=copy")
    assert url == "https://music.yandex.ru/album/123/track/456/"
    assert pet_video.canonical_url("https://music.yandex.ru.evil.example/album/123/track/456") is None
    assert pet_video.canonical_url("https://music.yandex.ru/album/123") is None

    async def download(source, path):
        assert source == url and path.suffix == ".mp3"
        path.write_bytes(b"mp3")
        path.with_suffix(".json").write_text(json.dumps({"title": "Темп", "artist": "Нора", "preview": True}))
        return 0

    monkeypatch.setattr(pet_video, "download", download)
    message = SimpleNamespace(
        chat=SimpleNamespace(id=-1001), message_id=7, from_user=SimpleNamespace(id=8), date=None,
        reply_audio=AsyncMock(return_value=SimpleNamespace(audio=SimpleNamespace(file_id="preview"))),
    )
    await queue.enqueue(message, url)
    await queue._deliver(queue.queue.get_nowait())
    assert message.reply_audio.await_args.kwargs["title"] == "Темп (фрагмент)"
    assert "только фрагмент" in message.reply_audio.await_args.kwargs["caption"]
    keyboard = message.reply_audio.await_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].url == "https://t.me/yndxapp"
    assert await db.fetchone("SELECT 1 FROM pet_video_deliveries WHERE user_id=8")
    assert not await db.fetchone("SELECT 1 FROM pet_video_cache WHERE url=?", (url,))



def test_music_retries_other_api_host_and_keeps_audio_without_catalog_metadata(tmp_path, monkeypatch):
    track_id = "150607144"
    primary, alternate = pet_video_worker.MUSIC_APIS
    info = "https://storage.mds.yandex.net/download-info/fixture?format=json"
    media = b"ID3" + b"a" * 16
    urls = []

    def json_response(_, url):
        urls.append(url)
        if f"https://{primary}/" in url or url == f"https://{alternate}/tracks/{track_id}":
            raise TransportError("test timeout")
        if url == f"https://{alternate}/tracks/{track_id}/download-info":
            return {"result": [{"codec": "mp3", "preview": True, "downloadInfoUrl": info}]}
        assert url == info
        return {"host": "mds.storage.yandex.net", "path": "/rmusic/fixture", "ts": "ab12", "s": "test"}

    def save_media(_, source, path, limit, *, mp3=False):
        assert source["url"].startswith("https://mds.storage.yandex.net/get-mp3/")
        assert source["url"].endswith(f"?track-id={track_id}")
        assert mp3 and len(media) <= limit
        path.write_bytes(media)

    monkeypatch.setattr(pet_video_worker, "music_json", json_response)
    monkeypatch.setattr(pet_video_worker, "stream", save_media)
    path = tmp_path / "track.mp3"
    pet_video_worker.download_music(f"https://music.yandex.ru/album/41732563/track/{track_id}/", path)
    assert urls[:2] == [f"https://{host}/tracks/{track_id}/download-info" for host in (primary, alternate)]
    assert path.read_bytes() == media
    assert json.loads(path.with_suffix(".json").read_text(encoding="utf-8")) == {
        "title": "Трек Яндекс Музыки", "artist": "", "preview": True,
    }


def test_music_stops_on_explicit_access_denial(monkeypatch):
    response = SimpleNamespace(status=403, reason="Forbidden", close=Mock())
    read = Mock(side_effect=HTTPError(response))
    monkeypatch.setattr(pet_video_worker, "music_json", read)
    with pytest.raises(pet_video_worker.MusicUnavailable):
        pet_video_worker.music_variants(object(), "150607144")
    read.assert_called_once()
    response.close.assert_called_once()
