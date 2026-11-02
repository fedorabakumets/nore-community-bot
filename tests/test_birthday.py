import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from community_bot.birthday import (
    claim_gift,
    deliver_today,
    greeting,
    offer_gift,
    offer_special_on_contact,
    pending_gift,
)
from community_bot.cabinet_api import notices, notices_update
from community_bot.database import Database


@pytest.mark.asyncio
async def test_gift_can_be_claimed_once_across_two_clients(tmp_path):
    db = Database(tmp_path / "birthday.sqlite3")
    await db.initialize()
    await db.ensure_user(71, "birthday_person", "Именинница")
    day = "2026-11-02"

    assert await offer_gift(db, 71, day)
    assert not await offer_gift(db, 71, day)
    assert await pending_gift(db, 71) == day
    assert sum(await asyncio.gather(claim_gift(db, 71, day), claim_gift(db, 71, day))) == 1
    assert await pending_gift(db, 71) is None
    assert (await db.get_user(71))["cookies"] == 500
    assert len(await db.list_transactions(71)) == 1
    assert len(await db.fetchall("SELECT id FROM notify_inbox WHERE user_id=71 AND channel='birthday'")) == 1
    assert not await claim_gift(db, 72, day)


@pytest.mark.asyncio
async def test_today_sends_one_greeting_and_owner_preview(tmp_path):
    db = Database(tmp_path / "birthday.sqlite3")
    await db.initialize()
    await db.ensure_user(71, "Caramel_kka", "Карамелька")
    await db.ensure_user(7, "owner", "Владелец")

    class Bot:
        def __init__(self):
            self.messages = []
            self.photos = []

        async def send_message(self, *args, **kwargs):
            self.messages.append((args, kwargs))

        async def send_photo(self, *args, **kwargs):
            self.photos.append((args, kwargs))

    bot = Bot()
    settings = SimpleNamespace(owner_id=7, community_chat_id=-100123, timezone="Europe/Moscow")
    now = datetime(2026, 11, 2, 12, tzinfo=ZoneInfo("Europe/Moscow"))
    await deliver_today(bot, db, settings, now)
    await deliver_today(bot, db, settings, now)

    assert len(bot.photos) == 1
    assert bot.photos[0][0][0] == -100123
    assert 'tg://user?id=71' in bot.photos[0][1]["caption"]
    assert "<blockquote>" in bot.photos[0][1]["caption"]
    assert "<b>НОРЫ</b>" in bot.photos[0][1]["caption"]
    assert len(bot.messages) == 2
    assert {args[0] for args, _ in bot.messages} == {7, 71}
    assert await pending_gift(db, 7) == "2026-11-02"
    assert await pending_gift(db, 71) == "2026-11-02"


def test_greeting_escapes_profile_name():
    caption = greeting({"user_id": 5, "profile_name": "<Мария>"})
    assert "&lt;Мария&gt;" in caption
    assert "<b><Мария>" not in caption


@pytest.mark.asyncio
async def test_named_guest_can_claim_from_public_greeting(tmp_path):
    db = Database(tmp_path / "guest.sqlite3")
    await db.initialize()
    await db.ensure_user(7, "owner", "Владелец")

    class Bot:
        def __init__(self):
            self.photos = []

        async def send_message(self, *_args, **_kwargs):
            pass

        async def send_photo(self, *_args, **kwargs):
            self.photos.append(kwargs)

    bot = Bot()
    settings = SimpleNamespace(owner_id=7, community_chat_id=-100123, timezone="Europe/Moscow")
    now = datetime(2026, 11, 2, 12, tzinfo=ZoneInfo("Europe/Moscow"))
    await deliver_today(bot, db, settings, now)
    assert len(bot.photos) == 1
    assert "<b>@Caramel_kka</b>" in bot.photos[0]["caption"]

    stranger = SimpleNamespace(id=72, username="somebody", first_name="Other")
    recipient = SimpleNamespace(id=71, username="Caramel_kka", first_name="Карамелька")
    assert not await offer_special_on_contact(db, stranger, "2026-11-02")
    assert await offer_special_on_contact(db, recipient, "2026-11-02")
    assert await claim_gift(db, 71, "2026-11-02")
    assert (await db.get_user(71))["cookies"] == 500
    await deliver_today(bot, db, settings, now)
    assert len(bot.photos) == 1


@pytest.mark.asyncio
async def test_miniapp_notice_claim_uses_same_wallet(tmp_path):
    db = Database(tmp_path / "miniapp.sqlite3")
    await db.initialize()
    await db.ensure_user(7, "owner", "Владелец")
    await offer_gift(db, 7, "2026-11-02", preview=True)

    class Request(dict):
        def __init__(self, body=None):
            super().__init__(actor={"id": 7, "username": "owner", "first_name": "Владелец"})
            self.app = {"db": db}
            self.body = body

        async def json(self):
            return self.body

    visible = json.loads((await notices(Request())).body)
    assert visible["birthday_gift_day"] == "2026-11-02"
    first = json.loads((await notices_update(Request({"action": "claim_birthday", "day": "2026-11-02"}))).body)
    second = json.loads((await notices_update(Request({"action": "claim_birthday", "day": "2026-11-02"}))).body)
    assert first["ok"] and not second["ok"]
    assert (await db.get_user(7))["cookies"] == 500
