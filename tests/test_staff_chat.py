"""Regression tests for the staff-only experimental community mirror."""
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from aiogram.types import Chat, Message, User

from community_bot.database import Database
from community_bot.staff_chat import StaffChatOutgoingMiddleware, capture, feed, staff_allowed

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
