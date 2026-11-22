"""Regression: a purchased shield absorbs exactly one −реп for at most 24 hours."""
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
    return await db.buy_item(buyer, "rep_shield", 12, target_id=target)


async def test_shield_starts_24_hour_clock_on_purchase(db):
    before = datetime.now(UTC)
    assert await buy_shield(db) == (True, "ok")
    after = datetime.now(UTC)
    assert (await db.get_user(7))["hate_shields"] == 1
    until = datetime.fromisoformat(await db.hate_shield_expiry(7))
    assert before + timedelta(hours=24) <= until <= after + timedelta(hours=24)
    assert await db.active_hate_shields(7) == 1


async def test_single_shield_only_absorbs_one_hit(db):
    await buy_shield(db)
    assert await db.consume_hate_shield(7) is True
    assert await db.consume_hate_shield(7) is False
    assert (await db.get_user(7))["hate_shields"] == 0
    assert await db.hate_shield_expiry(7) is None


async def test_unspent_shield_expires_and_cannot_block_late_hit(db):
    await buy_shield(db)
    await db.execute(
        "UPDATE reputation_shields SET expires_at=? WHERE user_id=?",
        ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), 7),
    )
    assert await db.active_hate_shields(7) == 0
    assert (await db.get_user(7))["hate_shields"] == 0
    assert await db.consume_hate_shield(7) is False
    assert await db.hate_shield_expiry(7) is None


async def test_multiple_shields_have_independent_expiration(db):
    await buy_shield(db)
    first = await db.fetchone("SELECT id FROM reputation_shields WHERE user_id=7")
    await db.execute(
        "UPDATE reputation_shields SET expires_at=? WHERE id=?",
        ((datetime.now(UTC) + timedelta(hours=2)).isoformat(), first["id"]),
    )
    await buy_shield(db)
    assert (await db.get_user(7))["hate_shields"] == 2
    assert await db.consume_hate_shield(7) is True
    assert await db.fetchone("SELECT id FROM reputation_shields WHERE id=?", (first["id"],)) is None
    assert (await db.get_user(7))["hate_shields"] == 1
    assert await db.consume_hate_shield(7) is True
    assert await db.consume_hate_shield(7) is False


async def test_concurrent_negative_hits_can_consume_only_one_shield(db):
    await buy_shield(db)
    used = await asyncio.gather(db.consume_hate_shield(7), db.consume_hate_shield(7))
    assert sorted(used) == [False, True]
    assert await db.active_hate_shields(7) == 0


async def test_gift_credits_recipient_with_own_24_hour_shield(db):
    before = await db.get_user(7)
    assert await buy_shield(db, target=8) == (True, "ok")
    assert (await db.get_user(7))["hate_shields"] == 0
    assert (await db.get_user(8))["hate_shields"] == 1
    assert (await db.get_user(7))["cookies"] == before["cookies"] - 12
    assert await db.hate_shield_expiry(8) is not None


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


async def test_legacy_shields_get_one_time_ttl_migration(tmp_path):
    old = Database(tmp_path / "legacy-shields.db")
    await old.initialize()
    await old.ensure_user(15, telegram_name="Старый")
    await old.execute("UPDATE users SET hate_shields=2 WHERE user_id=15")
    await old.execute("DELETE FROM bot_state WHERE key='reputation_shields_ttl_migration_v1'")
    await old.initialize()
    assert await old.active_hate_shields(15) == 2
    expiry = await old.hate_shield_expiry(15)
    assert expiry is not None
    await old.initialize()
    assert await old.active_hate_shields(15) == 2
    assert await old.hate_shield_expiry(15) == expiry
