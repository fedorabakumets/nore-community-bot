"""Regression tests for the staff-only experimental community mirror."""
import asyncio
import json
from unittest.mock import AsyncMock
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from aiogram.types import Chat, Message, PhotoSize, User

from community_bot.database import Database
from community_bot.staff_chat import StaffChatOutgoingMiddleware, capture, feed, hide, media, staff_allowed
from community_bot.staff_chat_send import MAX_UPLOAD, send_attachment, send_text
from community_bot.staff_chat import discard
from community_bot.staff_chat_live import StaffChatHub, connect

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


@pytest.mark.asyncio
async def test_bot_confirmed_delete_removes_only_community_messages(tmp_path):
    db = Database(tmp_path / "deleted.db")
    await db.initialize()
    settings = SimpleNamespace(community_chat_id=GROUP)
    bot = SimpleNamespace(community_db=db, community_settings=settings)
    middleware = StaffChatOutgoingMiddleware()

    for mid in (10, 11, 12, 13):
        await capture(db, settings, event(mid, f"Сообщение {mid}"))

    async def accepted(_bot, _method):
        return True

    single = SimpleNamespace(__api_method__="deleteMessage", chat_id=GROUP, message_id=10)
    assert await middleware(accepted, bot, single) is True
    assert await db.fetchone(
        "SELECT 1 FROM staff_chat_messages WHERE chat_id=? AND message_id=?", (GROUP, 10),
    ) is None

    async def rejected(_bot, _method):
        return False

    failed = SimpleNamespace(__api_method__="deleteMessage", chat_id=GROUP, message_id=11)
    await middleware(rejected, bot, failed)
    assert await db.fetchone(
        "SELECT 1 FROM staff_chat_messages WHERE chat_id=? AND message_id=?", (GROUP, 11),
    )

    unrelated = SimpleNamespace(__api_method__="deleteMessage", chat_id=-100998877665, message_id=11)
    await middleware(accepted, bot, unrelated)
    assert await db.fetchone(
        "SELECT 1 FROM staff_chat_messages WHERE chat_id=? AND message_id=?", (GROUP, 11),
    )

    batch = SimpleNamespace(__api_method__="deleteMessages", chat_id=GROUP, message_ids=[11, 13])
    await middleware(accepted, bot, batch)
    remaining = await db.fetchall(
        "SELECT message_id FROM staff_chat_messages WHERE chat_id=? ORDER BY message_id", (GROUP,),
    )
    assert [row["message_id"] for row in remaining] == [12]


@pytest.mark.asyncio
async def test_staff_only_mirror_cleanup_does_not_delete_in_telegram(tmp_path):
    db = Database(tmp_path / "hide.db")
    await db.initialize()
    for uid in (8, 20):
        await db.ensure_user(uid)
    await db.set_role(20, "moderator")
    settings = SimpleNamespace(
        community_chat_id=GROUP, moderator_ids=frozenset(), is_owner=lambda uid: False,
    )
    await capture(db, settings, event(31, "Удалили вручную в Telegram"))

    class Request(dict):
        app = {"db": db, "settings": settings}
        async def json(self):
            return {"message_id": 31}

    assert (await hide(Request(actor={"id": 8}))).status == 403
    assert await db.fetchone(
        "SELECT 1 FROM staff_chat_messages WHERE chat_id=? AND message_id=?", (GROUP, 31),
    )
    result = await hide(Request(actor={"id": 20}))
    assert result.status == 200
    assert json.loads(result.text)["ok"] is True
    assert await db.fetchone(
        "SELECT 1 FROM staff_chat_messages WHERE chat_id=? AND message_id=?", (GROUP, 31),
    ) is None



@pytest.mark.asyncio
async def test_staff_chat_composer_role_identity_reply_and_rate_limit(tmp_path):
    db = Database(tmp_path / "compose.db")
    await db.initialize()
    await db.ensure_user(20, telegram_name="Модератор Марина")
    await db.set_role(20, "moderator")
    await db.ensure_user(8, telegram_name="Обычный участник")
    settings = SimpleNamespace(
        community_chat_id=GROUP, moderator_ids=frozenset(),
        is_owner=lambda uid: False,
    )
    await capture(db, settings, event(71, "Исходное сообщение"))

    message = Message(
        message_id=72, date=datetime.now(UTC),
        chat=Chat(id=GROUP, type="supergroup"),
        from_user=User(id=900, is_bot=True, first_name="НОРА"),
        text="💬 Модератор Марина · через Mini App Норы\n\nТест",
    )
    bot = SimpleNamespace(send_message=AsyncMock(return_value=message))
    app_state = {
        "db": db, "settings": settings, "bot": bot,
        "staff_chat_send_locks": {}, "staff_chat_last_sent": {},
    }

    class Request(dict):
        content_length = 68
        app = app_state
        async def json(self):
            return {"text": "Тест", "reply_to": 71}

    denied = await send_text(Request(actor={"id": 8}))
    assert denied.status == 403
    assert not bot.send_message.await_count

    success = await send_text(Request(actor={"id": 20}))
    assert success.status == 200
    assert json.loads(success.text) == {"ok": True, "message_id": 72}
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == GROUP
    assert kwargs["reply_parameters"].message_id == 71
    assert kwargs["parse_mode"] is None
    assert kwargs["text"].startswith("💬 Модератор Марина · через Mini App Норы\n\nТест")
    saved = await db.fetchone(
        "SELECT text FROM staff_chat_messages WHERE chat_id=? AND message_id=?", (GROUP, 72),
    )
    assert saved and saved["text"].endswith("Тест")
    blocked = await send_text(Request(actor={"id": 20}))
    assert blocked.status == 429
    assert bot.send_message.await_count == 1


@pytest.mark.asyncio
async def test_staff_chat_composer_rejects_missing_reply_without_sending(tmp_path):
    db = Database(tmp_path / "invalid-reply.db")
    await db.initialize()
    await db.ensure_user(20)
    await db.set_role(20, "admin")
    settings = SimpleNamespace(
        community_chat_id=GROUP, moderator_ids=frozenset(),
        is_owner=lambda uid: False,
    )
    bot = SimpleNamespace(send_message=AsyncMock())

    class Request(dict):
        content_length = 95
        app = {
            "db": db, "settings": settings, "bot": bot,
            "staff_chat_send_locks": {}, "staff_chat_last_sent": {},
        }
        async def json(self):
            return {"text": "Ответ", "reply_to": 123456}

    response = await send_text(Request(actor={"id": 20}))
    assert response.status == 400
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_staff_chat_attachment_upload_caption_and_validation(tmp_path):
    db = Database(tmp_path / "upload.db")
    await db.initialize()
    await db.ensure_user(20, telegram_name="Тест")
    await db.set_role(20, "admin")
    settings = SimpleNamespace(
        community_chat_id=GROUP, moderator_ids=frozenset(),
        is_owner=lambda uid: False,
    )
    message = Message(
        message_id=140, date=datetime.now(UTC),
        chat=Chat(id=GROUP, type="supergroup"),
        from_user=User(id=900, is_bot=True, first_name="НОРА"),
        caption="💬 Тест · через Mini App Норы\n\nОбложка",
        photo=[PhotoSize(file_id="upload-photo", file_unique_id="u", width=12, height=12)],
    )
    bot = SimpleNamespace(send_photo=AsyncMock(return_value=message))
    app_state = {
        "db": db, "settings": settings, "bot": bot,
        "staff_chat_send_locks": {}, "staff_chat_last_sent": {},
    }

    class Field:
        def __init__(self, name, data: bytes, filename=None):
            self.name, self.data, self.filename = name, data, filename
            self.read_at = 0
        async def read_chunk(self, size):
            chunk=self.data[self.read_at:self.read_at+size]
            self.read_at+=len(chunk)
            return chunk
        async def read(self, decode=False):
            return self.data

    class Reader:
        def __init__(self, fields): self.fields=iter(fields)
        async def next(self): return next(self.fields, None)

    class Request(dict):
        content_type = "multipart/form-data"
        content_length = 140
        app = app_state
        async def multipart(self):
            return Reader([
                Field("text", b"\xd0\x9e\xd0\xb1\xd0\xbb\xd0\xbe\xd0\xb6\xd0\xba\xd0\xb0"),
                Field("file", b"\xff\xd8\xffTEST", filename="nora.jpg"),
            ])

    result = await send_attachment(Request(actor={"id": 20}))
    assert result.status == 200
    assert json.loads(result.text)["message_id"] == 140
    called = bot.send_photo.await_args.kwargs
    assert called["chat_id"] == GROUP
    assert called["photo"].filename == "nora.jpg"
    assert called["photo"].data == b"\xff\xd8\xffTEST"
    assert "Обложка" in called["caption"]
    assert called["parse_mode"] is None

    # Upload inspection denies executable files before Telegram is called.
    class BadRequest(Request):
        app = {**app_state, "staff_chat_last_sent": {}}
        async def multipart(self):
            return Reader([Field("file", b"code", filename="nora.exe")])

    rejected = await send_attachment(BadRequest(actor={"id": 20}))
    assert rejected.status == 400
    assert bot.send_photo.await_count == 1



def _signed_chat_auth(uid, token="test-telegram-token"):
    import hashlib
    import hmac
    import time
    from urllib.parse import urlencode

    values = {
        "user": json.dumps(
            {"id": uid, "first_name": "Сотрудник", "is_bot": False},
            ensure_ascii=False, separators=(",", ":"),
        ),
        "auth_date": str(int(time.time())),
    }
    check = "\n".join(f"{key}={val}" for key, val in sorted(values.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


async def _ws_until(socket, kind, *, matching=None):
    for _ in range(10):
        item = await asyncio.wait_for(socket.receive_json(), timeout=3)
        if item.get("type") == kind and (matching is None or matching(item)):
            return item
    raise AssertionError(f"WebSocket did not deliver {kind}")


@pytest.mark.asyncio
async def test_staff_live_websocket_auth_events_and_typing(tmp_path):
    """Real aiohttp WebSockets, signed Telegram auth, SQLite events and fanout."""
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    db = Database(tmp_path / "live.db")
    await db.initialize()
    for uid in (8, 20, 21):
        await db.ensure_user(uid, telegram_name=f"Сотрудник {uid}")
        await db.execute(
            "UPDATE users SET city=? WHERE user_id=?", ("Санкт-Петербург", uid),
        )
    await db.set_role(20, "moderator")
    await db.set_role(21, "admin")
    settings = SimpleNamespace(
        bot_token="test-telegram-token", community_chat_id=GROUP,
        moderator_ids=frozenset(), is_owner=lambda uid: False,
    )
    hub = StaffChatHub()
    db._staff_chat_hub = hub
    app = web.Application()
    app["db"], app["settings"], app["staff_chat_hub"] = db, settings, hub
    app.router.add_get("/ws/community/chat", connect)

    async def cleanup(_app):
        await hub.shutdown()

    app.on_cleanup.append(cleanup)

    async with TestClient(TestServer(app)) as client:
        unauthorized = await client.ws_connect("/ws/community/chat")
        await unauthorized.send_json({"type": "auth", "init_data": _signed_chat_auth(8)})
        rejected = await _ws_until(unauthorized, "error")
        assert rejected["reason"] == "access"
        assert hub.online == 0
        await unauthorized.close()

        forged = await client.ws_connect("/ws/community/chat")
        await forged.send_json({"type": "auth", "init_data": "fake-signature"})
        denied = await _ws_until(forged, "error")
        assert denied["reason"] == "access"
        await forged.close()

        first = await client.ws_connect("/ws/community/chat")
        await first.send_json({"type": "auth", "init_data": _signed_chat_auth(20)})
        ready1 = await _ws_until(first, "ready")
        assert ready1["online"] == 1

        second = await client.ws_connect("/ws/community/chat")
        await second.send_json({"type": "auth", "init_data": _signed_chat_auth(21)})
        ready2 = await _ws_until(second, "ready")
        assert ready2["online"] == 2
        joined = await _ws_until(first, "presence", matching=lambda e: e["online"] == 2)
        assert joined["online"] == 2

        await capture(db, settings, event(220, "Новое из Telegram"))
        for socket in (first, second):
            update = await _ws_until(socket, "change")
            assert update == {"type": "change", "operation": "message", "ids": [220]}

        await capture(db, settings, event(220, "Исправлено").model_copy(
            update={"edit_date": datetime.now(UTC)},
        ))
        for socket in (first, second):
            update = await _ws_until(socket, "change")
            assert update["operation"] == "edit" and update["ids"] == [220]

        await first.send_json({"type": "typing"})
        typing = await _ws_until(second, "typing")
        assert typing["user_id"] == 20
        assert typing["name"] == "Сотрудник 20"

        await discard(db, settings, GROUP, [220])
        for socket in (first, second):
            update = await _ws_until(socket, "change")
            assert update["operation"] == "delete" and update["ids"] == [220]
        assert await db.fetchone(
            "SELECT 1 FROM staff_chat_messages WHERE chat_id=? AND message_id=?",
            (GROUP, 220),
        ) is None

        await first.close()
        await second.close()
    assert hub.closed


@pytest.mark.asyncio
async def test_staff_live_queue_backpressure_keeps_refresh_signal():
    from community_bot.staff_chat_live import Client

    hub = StaffChatHub()

    class StubSocket:
        closed = False

    stub = StubSocket()
    client = Client(stub, 20, "Модератор", asyncio.Queue(maxsize=2))
    hub.clients[stub] = client
    hub.publish("message", [101])
    hub.publish("edit", [101])
    hub.publish("delete", [101])
    assert client.queue.qsize() == 1
    assert await client.queue.get() == {
        "type": "change", "operation": "sync", "ids": [],
    }
