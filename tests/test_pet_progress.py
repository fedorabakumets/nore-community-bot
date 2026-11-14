from datetime import UTC, datetime, timedelta

import pytest

from community_bot import pet_progress
from community_bot.database import Database


async def new_pet(db):
    await db.ensure_user(1, telegram_name="Test")
    await db.add_cookies(1, 100, "test")
    assert (await db.purchase_pet(1, "cat", "Барс", 10))[0]


async def test_existing_pet_is_preserved(tmp_path):
    db = Database(tmp_path / "pets.sqlite3")
    await db.initialize()
    await new_pet(db)
    await db.execute("UPDATE pets SET hunger=36,thirst=42,mood=78,food_units=4")
    original = await db.get_pet(1, settle=False)
    async with db.connect() as conn:
        for table in ("pet_quest_events", "pet_quests", "pet_quest_days", "pet_stage_rewards", "pet_development"):
            await conn.execute(f"DROP TABLE {table}")
        await conn.commit()
    await db.initialize()
    assert await db.get_pet(1, settle=False) == original
    state = await pet_progress.dashboard(db, 1)
    assert (state["level"], state["stage"], state["xp"]) == (1, 1, 0)


async def test_nine_days_and_rewards(tmp_path):
    db = Database(tmp_path / "pets.sqlite3")
    await db.initialize()
    await new_pet(db)
    await db.execute("UPDATE users SET reputation=50 WHERE user_id=1")
    for offset in range(9):
        now = datetime(2026, 11, 1, 12, tzinfo=UTC) + timedelta(days=offset)
        async with db.connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            for _ in range(3):
                for event in ("food", "water", "stroke", "expedition", "plus", *pet_progress.MEDIA_LABELS):
                    await pet_progress.record(conn, 1, event, now=now)
            for index in range(10):
                sent = now + timedelta(seconds=index * 10)
                message = (-1, index + offset * 10, sent, f"hello {index}")
                await pet_progress.record(conn, 1, "text", now=sent, message=message)
                await pet_progress.record(conn, 1, "text", now=sent, message=message)
            await conn.commit()
        day = await db.fetchone("SELECT xp FROM pet_quest_days WHERE day=?", (now.date().isoformat(),))
        state = await db.fetchone("SELECT level,stage,messages FROM pet_development")
        assert day["xp"] == 100
        assert state["stage"] == offset + 2
        assert state["level"] == (1 if offset < 3 else 2 if offset < 8 else 3)
        assert state["messages"] == (offset + 1) * 10

    rewards = await db.fetchall("SELECT * FROM pet_stage_rewards ORDER BY stage")
    assert len(rewards) == 10
    assert (await db.get_user(1))["cookies"] == 115
    assert sum(row["amount"] for row in rewards if row["kind"] == "reputation") == 10
    for kind, stat in pet_progress.CONSUMABLES.items():
        await db.execute(f"UPDATE pets SET {stat}=100 WHERE user_id=1")
        token = await db.create_wallet_intent(1, "pet_action", 1)
        assert not (await pet_progress.redeem(db, 1, kind, token))[0]
        await db.execute(f"UPDATE pets SET {stat}=25 WHERE user_id=1")
        assert (await pet_progress.redeem(db, 1, kind, token))[0]
        another = await db.create_wallet_intent(1, "pet_action", 1)
        assert not (await pet_progress.redeem(db, 1, kind, another))[0]
    pet = await db.get_pet(1, settle=False)
    assert (pet["hunger"], pet["thirst"], pet["mood"]) == (65, 75, 100)


@pytest.mark.asyncio
async def test_progress_rolls_over_at_moscow_midnight(tmp_path):
    db = Database(tmp_path / "pets.sqlite3")
    await db.initialize()
    await new_pet(db)
    start = datetime(2026, 11, 1, 20, 58, tzinfo=UTC)
    for now in (start, start + timedelta(minutes=2)):
        async with db.connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            for event in ("food", "stroke"):
                await pet_progress.record(conn, 1, event, now=now)
            await conn.commit()
    days = await db.fetchall("SELECT day FROM pet_quest_days ORDER BY day")
    assert [day["day"] for day in days] == ["2026-11-01", "2026-11-02"]
