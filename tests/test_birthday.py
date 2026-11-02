import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from community_bot.birthday import (
    claim_callback,
    claim_gift,
    deliver_today,
    greeting,
    offer_gift,
    offer_special_on_contact,
    pending_gift,
    rich_greeting,
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
    await offer_gift(db, 7, "2026-11-02-owner")
    await db.set_bot_state("birthday_owner_post:7:2026-11-02", "sent")

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

    assert len(bot.photos) == 2
    assert bot.photos[0][0][0] == -100123
    assert 'tg://user?id=71' in bot.photos[1][1]["caption"]
    assert "<blockquote>" in bot.photos[1][1]["caption"]
    assert "<b>НОРЫ</b>" in bot.photos[1][1]["caption"]
    assert len(bot.messages) == 2
    assert {args[0] for args, _ in bot.messages} == {7, 71}
    assert await pending_gift(db, 7) == "2026-11-02-owner2"
    assert await pending_gift(db, 71) == "2026-11-02"
    assert await claim_gift(db, 7, "2026-11-02-owner2")
    assert not await claim_gift(db, 7, "2026-11-02-owner2")
    assert await claim_gift(db, 7, "2026-11-02-owner")


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
    assert len(bot.photos) == 2
    assert "<b>@Caramel_kka</b>" in bot.photos[1]["caption"]

    stranger = SimpleNamespace(id=72, username="somebody", first_name="Other")
    recipient = SimpleNamespace(id=71, username="Caramel_kka", first_name="Карамелька")
    assert not await offer_special_on_contact(db, stranger, "2026-11-02")
    assert await offer_special_on_contact(db, recipient, "2026-11-02")
    assert await claim_gift(db, 71, "2026-11-02")
    assert (await db.get_user(71))["cookies"] == 500
    await deliver_today(bot, db, settings, now)
    assert len(bot.photos) == 2


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


@pytest.mark.asyncio
async def test_group_button_is_bound_to_recipient_even_when_other_has_gift(tmp_path):
    db = Database(tmp_path / "access.sqlite3")
    await db.initialize()
    await db.ensure_user(7, "owner", "Owner")
    await db.ensure_user(8, "other", "Other")
    await offer_gift(db, 7, "2026-11-02-owner")
    await offer_gift(db, 8, "2026-11-02-owner")
    callback = SimpleNamespace(data="birthday:claim:2026-11-02-owner:7",
                               from_user=SimpleNamespace(id=8, username="other"),
                               message=SimpleNamespace(chat=SimpleNamespace(type="supergroup")),
                               answer=AsyncMock())
    await claim_callback(callback, db)
    assert "подарок-то не твой" in callback.answer.await_args.args[0]
    assert (await db.get_user(8))["cookies"] == 0
    assert await pending_gift(db, 8) == "2026-11-02-owner"


def test_rich_greeting_embeds_bound_button_and_image():
    rich = rich_greeting({"user_id": 7, "profile_name": "Рома"}, "2026-11-02-owner")
    assert rich.blocks[0].type == "paragraph"
    assert rich.blocks[1].type == "photo"
    assert rich.blocks[2].type == "paragraph"
    assert rich.blocks[3].blocks[0].text == "Забери свой подарок по кнопке ниже или в мини-приложении"
    assert rich.blocks[-1].buttons[0].style == "primary"
    assert rich.blocks[-1].buttons[0].callback_data == "birthday:claim:2026-11-02-owner:7"
