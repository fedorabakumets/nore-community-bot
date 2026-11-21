"""Regression tests for the staff-only experimental community mirror."""
import asyncio
import json
from unittest.mock import AsyncMock
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from aiogram.types import Chat, Message, PhotoSize, User

from community_bot.database import Database
from community_bot.staff_chat import StaffChatOutgoingMiddleware, capture, feed, media, staff_allowed

GROUP = -100123456789


def event(mid: int, text: str, *, chat_id: int = GROUP, reply=None) -> Message:
    return Message(
        message_id=mid,
        date=datetime.now(UTC),
        chat=Chat(id=chat_id, type="supergroup"),
        from_user=User(id=8, is_bot=False, first_name="Тест"),
        text=text,
        reply_to_message=reply,
    )


@pytest.mark.asyncio
async def test_staff_chat_access_and_mirroring(tmp_path):
    db = Database(tmp_path / "staff-chat.db")
    await db.initialize()
    for uid in (8, 20, 21):
        await db.ensure_user(uid, telegram_name="Тест")
    await db.set_role(20, "moderator")
    await db.set_role(21, "admin")
    settings = SimpleNamespace(
        community_chat_id=GROUP, moderator_ids=frozenset(),
        is_owner=lambda uid: uid == 22,
    )
    assert not await staff_allowed(db, settings, 8)
    assert await staff_allowed(db, settings, 20)
    assert await staff_allowed(db, settings, 21)
    assert await staff_allowed(db, settings, 22)

    await capture(db, settings, event(10, "Другая группа", chat_id=-100333333333))
    await capture(db, settings, event(11, "Первый"))
    await capture(db, settings, event(12, "Ответ", reply=event(11, "Первый")))
    await capture(db, settings, event(11, "Первый, исправлено").model_copy(
        update={"edit_date": datetime.now(UTC)},
    ))

    class Request(dict):
        app = {"db": db, "settings": settings}
        query = {}

    denied = await feed(Request(actor={"id": 8}))
    assert denied.status == 403
    assert "items" not in json.loads(denied.text)

    allowed = await feed(Request(actor={"id": 20}))
    assert allowed.status == 200
    items = json.loads(allowed.text)["items"]
    assert len(items) == 2
    assert items[0]["text"] == "Первый, исправлено"
    assert items[1]["reply_to_id"] == 11
    assert items[1]["reply_text"] == "Первый, исправлено"
    assert items[0]["link"].startswith("https://t.me/c/")

@pytest.mark.asyncio
async def test_outgoing_bot_message_captured(tmp_path):
    db = Database(tmp_path / "staff-outgoing.db")
    await db.initialize()
    settings = SimpleNamespace(community_chat_id=GROUP)
    bot = SimpleNamespace(community_db=db, community_settings=settings)
    message = Message(
        message_id=33, date=datetime.now(UTC),
        chat=Chat(id=GROUP, type="supergroup"),
        from_user=User(id=9, is_bot=True, first_name="Нора"),
        text="Привет от Норы",
    )
    async def send(_bot, _method):
        return message

    await StaffChatOutgoingMiddleware()(send, bot, object())
    row = await db.fetchone(
        "SELECT text, author_name FROM staff_chat_messages WHERE chat_id=? AND message_id=?",
        (GROUP, 33),
    )
    assert row == {"text": "Привет от Норы", "author_name": "Нора"}



@pytest.mark.asyncio
async def test_staff_chat_photo_media_is_private_and_bounded(tmp_path):
    db = Database(tmp_path / "media.db")
    await db.initialize()
    for uid in (8, 20):
        await db.ensure_user(uid, telegram_name="Участник")
    await db.set_role(20, "moderator")
    settings = SimpleNamespace(
        community_chat_id=GROUP, moderator_ids=frozenset(), is_owner=lambda uid: False,
    )
    photo = Message(
        message_id=61, date=datetime.now(UTC),
        chat=Chat(id=GROUP, type="supergroup"),
        from_user=User(id=8, is_bot=False, first_name="Мария"),
        photo=[PhotoSize(file_id="demo-photo", file_unique_id="unique-photo", width=320, height=320)],
    )
    await capture(db, settings, photo)
    telegram_file = SimpleNamespace(file_path="photos/file_1.jpg", file_size=3)
    async def download(_path, *, destination, timeout):
        destination.write(b"abc")
    bot = SimpleNamespace(
        get_file=AsyncMock(return_value=telegram_file),
        download_file=AsyncMock(side_effect=download),
    )

    class Request(dict):
        app = {
            "db": db, "settings": settings, "bot": bot,
            "staff_chat_media_gate": asyncio.Semaphore(2),
        }
        match_info = {"message_id": "61"}
        query = {}

    denied = await media(Request(actor={"id": 8}))
    assert denied.status == 403
    assert bot.get_file.await_count == 0

    allowed = await media(Request(actor={"id": 20}))
    assert allowed.status == 200
    assert allowed.body == b"abc"
    assert allowed.content_type == "image/jpeg"
    assert bot.download_file.await_count == 1

    telegram_file.file_size = 25 * 1024 * 1024
    large = await media(Request(actor={"id": 20}))
    assert large.status == 413
    assert bot.download_file.await_count == 1


@pytest.mark.asyncio
async def test_staff_chat_context_loads_older_reply(tmp_path):
    db = Database(tmp_path / "context.db")
    await db.initialize()
    await db.ensure_user(20)
    await db.set_role(20, "admin")
    settings = SimpleNamespace(
        community_chat_id=GROUP, moderator_ids=frozenset(), is_owner=lambda uid: False,
    )
    for mid in range(1, 101):
        await capture(db, settings, event(mid, f"Сообщение {mid}"))
    class Request(dict):
        app = {"db": db, "settings": settings}
        query = {"around": "10"}
    result = await feed(Request(actor={"id": 20}))
    assert result.status == 200
    body = json.loads(result.text)
    assert body["mode"] == "context"
    assert body["target"] == 10
    assert any(row["id"] == 10 for row in body["items"])
    assert any(row["id"] == 49 for row in body["items"])
    assert not any(row["id"] == 100 for row in body["items"])

    Request.query = {"around": "404"}
    absent = await feed(Request(actor={"id": 20}))
    assert absent.status == 404



@pytest.mark.asyncio
async def test_rich_playlist_from_bot_is_archived_and_playable(tmp_path):
    """Bot API RichMessage has no ordinary text, caption, or single media field."""
    db = Database(tmp_path / "rich-playlist.db")
    await db.initialize()
    await db.ensure_user(20)
    await db.set_role(20, "moderator")
    settings = SimpleNamespace(
        community_chat_id=GROUP, moderator_ids=frozenset(), is_owner=lambda uid: False,
    )
    rich = SimpleNamespace(model_dump=lambda **_kwargs: {
        "blocks": [
            {"type": "photo", "photo": [
                {"file_id": "photo-small"}, {"file_id": "photo-large"}]},
            {"type": "paragraph", "text": "NORA / MUSIC"},
            {"type": "section_heading", "text": "dedzytwo — музыкальная подборка"},
            {"type": "details", "summary": "Старое ≠ бесполезное", "blocks": [
                {"type": "paragraph", "text": "Автор из Санкт-Петербурга"}]},
            {"type": "audio", "audio": {
                "file_id": "track-one", "title": "Первый", "performer": "dedzytwo", "duration": 163}},
            {"type": "audio", "audio": {
                "file_id": "track-two", "title": "Второй", "performer": "dedzytwo", "duration": 195}},
            {"type": "buttons", "buttons": [
                {"text": "НОРА", "url": "https://t.me/nora_community_bot?startapp"},
                {"text": "Нажми", "callback_data": "secret:callback"}]},
        ],
    })
    msg = event(150, "").model_copy(update={"rich_message": rich, "text": None})
    await StaffChatOutgoingMiddleware()(
        lambda _bot, _method: asyncio.sleep(0, result=msg),
        SimpleNamespace(community_db=db, community_settings=settings), object(),
    )

    class FeedRequest(dict):
        app = {"db": db, "settings": settings}
        query = {}

    response = await feed(FeedRequest(actor={"id": 20}))
    assert response.status == 200
    assert "track-one" not in response.text
    assert "photo-large" not in response.text
    assert "secret:callback" not in response.text
    playlist = json.loads(response.text)["items"][0]
    assert playlist["id"] == 150
    assert len([b for b in playlist["rich"] if b["type"] == "audio"]) == 2
    assert next(b for b in playlist["rich"] if b["type"] == "heading")["text"].startswith("dedzytwo")
    assert next(b for b in playlist["rich"] if b["type"] == "photo")["asset"] == 0

    bot = SimpleNamespace(
        get_file=AsyncMock(return_value=SimpleNamespace(file_path="music/track.mp3", file_size=4)),
        download_file=AsyncMock(side_effect=lambda _path, *, destination, timeout: destination.write(b"song")),
    )
    class MediaRequest(dict):
        app = {"db": db, "settings": settings, "bot": bot,
               "staff_chat_media_gate": asyncio.Semaphore(2)}
        match_info = {"message_id": "150"}
        query = {"part": "2"}

    allowed = await media(MediaRequest(actor={"id": 20}))
    assert allowed.status == 200
    assert allowed.content_type == "audio/mpeg"
    assert allowed.body == b"song"
    bot.get_file.assert_awaited_with("track-two")

    denied = await media(MediaRequest(actor={"id": 404}))
    assert denied.status == 403



@pytest.mark.asyncio
async def test_forwarded_rich_message_captures_without_text(tmp_path):
    db = Database(tmp_path / "rich-forward.db")
    await db.initialize()
    settings = SimpleNamespace(community_chat_id=GROUP)
    forwarded = event(151, "").model_copy(update={
        "text": None,
        "rich_message": SimpleNamespace(model_dump=lambda **_kwargs: {
            "blocks": [{"type": "paragraph", "text": "Пересланный Rich-плейлист"}],
        }),
    })
    await capture(db, settings, forwarded)
    row = await db.fetchone(
        "SELECT rich_json FROM staff_chat_messages WHERE chat_id=? AND message_id=?",
        (GROUP, 151),
    )
    assert "Пересланный Rich-плейлист" in row["rich_json"]
