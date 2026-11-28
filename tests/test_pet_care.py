"""Pet hunger and thirst should gate abilities, never the recovery path."""

from datetime import UTC, datetime, timedelta

import pytest
from test_nora_game import content, request

from community_bot import cabinet_api, pet_video
from community_bot.database import Database
from community_bot.pet_care import HUNGER_DECAY_PER_HOUR, THIRST_DECAY_PER_HOUR, care_error, needs_care
from community_bot.routers.nora import assistant_access_error


@pytest.mark.asyncio
async def test_pet_care_decays_twice_as_fast(tmp_path):
    db = Database(tmp_path / "pet-decay.sqlite3")
    await db.initialize()
    await db.ensure_user(1)
    await db.add_cookies(1, 10, "test")
    assert (await db.purchase_pet(1, "cat", "Кот", 1))[0]
    past = (datetime.now(UTC) - timedelta(hours=2, minutes=2)).isoformat()
    await db.execute(
        "UPDATE pets SET hunger=80,thirst=80,last_tick_at=? WHERE user_id=1", (past,),
    )
    pet = await db.get_pet(1)
    assert (HUNGER_DECAY_PER_HOUR, THIRST_DECAY_PER_HOUR) == (4, 6)
    assert (pet["hunger"], pet["thirst"]) == (72, 68)


@pytest.mark.asyncio
async def test_low_either_stat_locks_level_abilities_and_recovers_with_supplies(tmp_path):
    db = Database(tmp_path / "pet-care.sqlite3")
    await db.initialize()
    await db.ensure_user(1)
    await db.add_cookies(1, 10, "test")
    assert (await db.purchase_pet(1, "cat", "Кот", 1))[0]
    await db.execute("UPDATE pet_development SET stage=10,level=3 WHERE user_id=1")
    queue = pet_video.PetVideoQueue(db)
    for hunger, thirst in [(49, 100), (100, 49)]:
        await db.execute(
            "UPDATE pets SET hunger=?,thirst=?,mood=20 WHERE user_id=1",
            (hunger, thirst),
        )
        pet = await db.get_pet(1)
        assert needs_care(pet)
        assert "50" in care_error(pet)
        assert "50" in await assistant_access_error(1, db)
        assert "50" in await queue._access_error(1)
        ok, message = await db.stroke_pet(1)
        assert not ok and "50" in message
        assert not (await db.rename_pet(1, "Новое имя"))
        with pytest.raises(ValueError, match="50"):
            await cabinet_api.pet_prepare(request(db, 1, {"action": "rename", "name": "Имя"}))

    await db.execute(
        "UPDATE pets SET hunger=40,thirst=30,food_units=1,water_units=1 WHERE user_id=1",
    )
    assert (await db.use_pet_supply(1, "food"))[0]
    assert "50" in await assistant_access_error(1, db)
    assert (await db.use_pet_supply(1, "water"))[0]
    pet = await db.get_pet(1)
    assert (pet["hunger"], pet["thirst"]) == (60, 50)
    assert not needs_care(pet)
    assert await assistant_access_error(1, db) is None
    assert await queue._access_error(1) is None
    assert content(await cabinet_api.pet_prepare(
        request(db, 1, {"action": "rename", "name": "Котик"}),
    ))["token"]


@pytest.mark.asyncio
async def test_old_pet_intent_cannot_bypass_care_threshold(tmp_path):
    db = Database(tmp_path / "pet-intent.sqlite3")
    await db.initialize()
    await db.ensure_user(1)
    await db.add_cookies(1, 10, "test")
    assert (await db.purchase_pet(1, "cat", "Кот", 1))[0]
    token = content(await cabinet_api.pet_prepare(
        request(db, 1, {"action": "rename", "name": "Друг"}),
    ))["token"]
    await db.execute("UPDATE pets SET hunger=49 WHERE user_id=1")
    reply = await cabinet_api.pet_action(request(db, 1, {"token": token}))
    assert reply.status == 409
    assert "50" in content(reply)["message"]
    assert (await db.get_pet(1, settle=False))["name"] == "Кот"
