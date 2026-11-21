"""Stage 8: persisted dispatch receipts, no duplicate Telegram sends on retries."""
import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramServerError
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, PhotoSize, User

from community_bot.database import Database
from community_bot.staff_chat_delivery import claim, finish, payload_hash, read, response_data, status, validate_key
from community_bot.staff_chat_send import send_text, _publish

GROUP = -100123456789
OP = "26b12345-aaaa-4bbb-8ccc-123456789abc"


def message(mid, text="💬 Модератор · через Mini App Норы\n\nПривет"):
    return Message(
        message_id=mid, date=datetime.now(UTC),
        chat=Chat(id=GROUP, type="supergroup"),
        from_user=User(id=555, is_bot=True, first_name="Нора"),
        text=text,
    )


async def setup(tmp_path, method=None):
    db = Database(tmp_path / "dispatch.db")
    await db.initialize()
    for uid, role in [(21, "moderator"), (22, "admin"), (23, "member")]:
        await db.ensure_user(uid, telegram_name=f"Пользователь {uid}")
        await db.set_role(uid, role)
    settings = SimpleNamespace(
        community_chat_id=GROUP, moderator_ids=frozenset(),
        is_owner=lambda uid: False,
    )
    bot = SimpleNamespace(send_message=method or AsyncMock(return_value=message(940)))
    app = {
        "db": db, "settings": settings, "bot": bot,
        "staff_chat_send_locks": {}, "staff_chat_last_sent": {},
    }
    return db, settings, bot, app


def request(app, uid=21, text="Привет", operation_id=OP, reply_to=None):
    class Request(dict):
        content_length = 180
        async def json(self):
            return self.payload

    actor = Request(actor={"id": uid})
    actor.app = app
    actor.payload = {"text": text, "reply_to": reply_to, "operation_id": operation_id}
    return actor


def status_request(app, uid=21, op=OP):
    class Request(dict):
        match_info = {"operation_id": op}

    actor = Request(actor={"id": uid})
    actor.app = app
    actor.match_info = {"operation_id": op}
    return actor


@pytest.mark.asyncio
async def test_exactly_one_send_for_same_operation_and_conflicting_payload(tmp_path):
    db, _, bot, app = await setup(tmp_path)
    sent = await send_text(request(app))
    assert sent.status == 200
    assert json.loads(sent.text)["state"] == "sent"

    replay = await send_text(request(app))
    assert replay.status == 200
    assert json.loads(replay.text)["message_ids"] == [940]
    assert bot.send_message.await_count == 1

    conflict = await send_text(request(app, text="Другое сообщение"))
    assert conflict.status == 409
    bot.send_message.assert_awaited_once()

    row = await read(db, 21, OP)
    assert row["status"] == "sent"
    assert "Привет" not in json.dumps(row, ensure_ascii=False)

    report = await status(status_request(app))
    assert report.status == 200
    assert json.loads(report.text)["message_ids"] == [940]

    forbidden = await status(status_request(app, uid=23))
    assert forbidden.status == 403
    unknown = await status(status_request(app, uid=22))
    assert unknown.status == 404


@pytest.mark.asyncio
async def test_ambiguous_telegram_timeout_does_not_send_twice(tmp_path):
    bot_method=AsyncMock(side_effect=TelegramServerError(
        method=SendMessage(chat_id=GROUP, text="X"),
        message="Bad Gateway",
    ))
    db, _, bot, app = await setup(tmp_path, bot_method)
    first = await send_text(request(app))
    assert first.status == 502
    assert json.loads(first.text)["state"] == "uncertain"
    assert (await read(db, 21, OP))["status"] == "uncertain"

    # Same operation must never call Telegram again even after an API error.
    duplicate = await send_text(request(app))
    assert duplicate.status == 200
    assert json.loads(duplicate.text)["state"] == "uncertain"
    bot.send_message.assert_awaited_once()
    report = await status(status_request(app))
    assert json.loads(report.text)["state"] == "uncertain"


@pytest.mark.asyncio
async def test_outstanding_request_survives_restart_and_never_resends(tmp_path):
    db, _, bot, app = await setup(tmp_path)
    digest = payload_hash(GROUP, "Привет", None, "file", [])
    state, _ = await claim(db, 21, OP, digest)
    assert state == "new"

    # A new Database object simulates a new worker after deployment.
    reopened = Database(db.path)
    state, row = await claim(reopened, 21, OP, digest)
    assert state == "existing"
    assert response_data(row)["state"] == "sending"
    held = await send_text(request(app))
    assert json.loads(held.text)["state"] == "sending"
    bot.send_message.assert_not_awaited()

    await db.execute(
        "UPDATE staff_chat_dispatches SET created_at='2020-01-01 00:00:00' WHERE user_id=?",
        (21,),
    )
    assert response_data(await read(db,21,OP))["state"] == "uncertain"
    await finish(db,21,OP,"sent",[555])
    assert response_data(await read(db,21,OP))["message_ids"] == [555]


@pytest.mark.asyncio
async def test_parallel_claim_and_operations_are_separate_by_user(tmp_path):
    db, _, bot, app = await setup(tmp_path)
    digest = payload_hash(GROUP, "One", None, "file", [])
    results = await asyncio.gather(*(claim(db, 21, OP, digest) for _ in range(4)))
    assert sorted(item[0] for item in results) == ["existing"]*3 + ["new"]
    assert (await claim(db,22,OP,digest))[0] == "new"
    assert (await claim(db,21,OP,payload_hash(GROUP,"Two",None,"file",[])))[0] == "conflict"


@pytest.mark.asyncio
async def test_album_digest_prevents_duplicate_group_send(tmp_path):
    photos = [
        Message(
            message_id=mid,date=datetime.now(UTC),
            chat=Chat(id=GROUP,type="supergroup"),
            from_user=User(id=555,is_bot=True,first_name="Нора"),
            media_group_id="album",
            photo=[PhotoSize(file_id=str(mid),file_unique_id=str(mid),width=10,height=10)],
        )
        for mid in (941,942)
    ]
    db, _, bot, app = await setup(tmp_path)
    bot.send_media_group = AsyncMock(return_value=photos)
    fake=request(app)
    files=[("a.jpg",b"\xff\xd8\xff" + b"X"*7),("b.jpg",b"\xff\xd8\xff" + b"Y"*7)]
    result=await _publish(fake,text="Альбом",reply=None,files=files,operation_id=OP)
    assert result.status == 200
    assert json.loads(result.text)["message_ids"] == [941,942]
    result=await _publish(fake,text="Альбом",reply=None,files=files,operation_id=OP)
    assert json.loads(result.text)["message_ids"] == [941,942]
    bot.send_media_group.assert_awaited_once()
    other=await _publish(fake,text="Альбом",reply=None,files=[files[0],("b.jpg",b"\xff\xd8\xff"+b"Z"*7)],operation_id=OP)
    assert other.status==409


@pytest.mark.asyncio
async def test_legacy_client_without_operation_id_still_sends(tmp_path):
    db, _, bot, app = await setup(tmp_path)
    sent = await send_text(request(app, operation_id=None))
    assert sent.status == 200
    assert json.loads(sent.text) == {"ok": True, "message_id": 940, "message_ids": [940]}
    bot.send_message.assert_awaited_once()


def test_reject_malformed_operation_ids():
    for value in (23, "file", "../other", "x"*200, "26b12345-aaaa-0bbb-8ccc-123456789abc"):
        with pytest.raises(ValueError):
            validate_key(value)
    assert validate_key(None) is None
    assert validate_key(OP) == OP



def test_stage8_delivery_script_is_reachable_from_miniapp():
    """All scripts needed before NoraStaffChat initializes must have HTTP routes."""
    from pathlib import Path
    import re

    from community_bot.miniapp import ROOT

    html = (ROOT / "index.html").read_text(encoding="utf-8")
    server = (Path(__file__).resolve().parents[1] / "community_bot" / "miniapp.py").read_text(
        encoding="utf-8"
    )
    required = ("staff-chat-delivery.js", "staff-chat.js")
    # The exact static endpoint was missed by stage-8 checks, despite the
    # script passing Node tests locally. Verify both actual registration
    # and load order.
    entries = re.search(
        r"for name in \((.*?)\):\s*\n\s*app\.router\.add_get\('/'\+name,",
        server,
        re.DOTALL,
    )
    assert entries, "Mini App static route declaration is missing"
    listed = entries.group(1)
    positions = [html.index(f'src="/{name}?') for name in required]
    assert positions == sorted(positions)
    for name in required:
        assert f"'{name}'" in listed
        assert (ROOT / name).is_file()
