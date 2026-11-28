"""Regression: a purchased shield absorbs exactly one −реп and never expires."""
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from community_bot.database import Database
from community_bot.reputation import change_community_reputation


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "shield-ttl.db")
    await database.initialize()
    for uid in (7, 8):
        await database.ensure_user(uid, telegram_name=f"Участник {uid}")
        await database.set_cookies(uid, 500, 7)
    return database


async def buy_shield(db, buyer=7, target=None):
    return await db.buy_item(buyer, "rep_shield", 20, target_id=target)


async def test_shield_has_no_expiry_and_costs_twenty(db):
    before = await db.get_user(7)
    assert (await db.get_shop_item("rep_shield"))["price"] == 20
    assert await db.get_shop_item("immunity_24h") is None
    assert await buy_shield(db) == (True, "ok")
    assert (await db.get_user(7))["cookies"] == before["cookies"] - 20
    assert await db.active_hate_shields(7) == 1
    assert await db.hate_shield_expiry(7) is None


async def test_single_shield_only_absorbs_one_hit(db):
    await buy_shield(db)
    assert await db.consume_hate_shield(7) is True
    assert await db.consume_hate_shield(7) is False
    assert (await db.get_user(7))["hate_shields"] == 0
    assert await db.hate_shield_expiry(7) is None


async def test_unspent_shield_survives_restart(db):
    await buy_shield(db)
    await db.execute("UPDATE users SET updated_at=? WHERE user_id=7",
                     ((datetime.now(UTC) - timedelta(days=30)).isoformat(),))
    await db.initialize()
    assert await db.active_hate_shields(7) == 1
    assert await db.consume_hate_shield(7) is True


async def test_multiple_shields_each_absorb_one_hit(db):
    await buy_shield(db)
    await buy_shield(db)
    assert await db.active_hate_shields(7) == 2
    assert await db.consume_hate_shield(7) is True
    assert await db.consume_hate_shield(7) is True
    assert await db.consume_hate_shield(7) is False


async def test_concurrent_negative_hits_can_consume_only_one_shield(db):
    await buy_shield(db)
    used = await asyncio.gather(db.consume_hate_shield(7), db.consume_hate_shield(7))
    assert sorted(used) == [False, True]
    assert await db.active_hate_shields(7) == 0


async def test_gift_credits_recipient_with_own_one_use_shield(db):
    before = await db.get_user(7)
    assert await buy_shield(db, target=8) == (True, "ok")
    assert (await db.get_user(7))["hate_shields"] == 0
    assert (await db.get_user(8))["hate_shields"] == 1
    assert (await db.get_user(7))["cookies"] == before["cookies"] - 20
    assert await db.hate_shield_expiry(8) is None


async def test_reputation_vote_spends_one_shield_then_deducts_ten(db):
    await db.execute("UPDATE users SET reputation=80 WHERE user_id=7")
    await db.execute("UPDATE users SET reputation=60 WHERE user_id=8")
    await buy_shield(db, target=8)
    settings = SimpleNamespace(restricted_reputation_threshold=50)
    actor = await db.get_user(7)
    target = await db.get_user(8)
    first = await change_community_reputation(db, settings, actor, target, -10, date.today())
    assert first[0] and first[2] == 60
    assert "Щит" in str(first[3])
    assert (await db.get_user(8))["hate_shields"] == 0
    target = await db.get_user(8)
    second = await change_community_reputation(db, settings, actor, target, -10, date.today())
    assert second[0] and second[2] == 50
    assert "−10" in second[1] or "-10" in second[1]


async def test_legacy_shields_and_cloak_reset_once(db):
    await db.execute("UPDATE users SET hate_shields=2, hate_immunity_until='2099-01-01T00:00:00+00:00' WHERE user_id=7")
    await db.execute("INSERT INTO reputation_shields(user_id,granted_at,expires_at) VALUES (7,'2026-01-01','2099-01-01')")
    await db.execute("DELETE FROM bot_state WHERE key='one_use_shield_reset_v2'")
    await db.initialize()
    assert await db.active_hate_shields(7) == 0
    assert (await db.get_user(7))["hate_immunity_until"] is None
    assert await db.fetchone("SELECT id FROM reputation_shields WHERE user_id=7") is None
    assert await buy_shield(db) == (True, "ok")
    await db.initialize()
    assert await db.active_hate_shields(7) == 1
    assert not (await db.buy_item(7, "immunity_24h", 18))[0]
