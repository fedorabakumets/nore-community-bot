import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from test_nora_game import content, request

from community_bot import expedition, nora_game_api
from community_bot.database import Database
from community_bot.helpers import pet_guard_reputation


@pytest.mark.asyncio
async def test_expedition_requires_both_stats_and_saves_departure_result(tmp_path, monkeypatch):
    db = Database(tmp_path / 'pet.db')
    await db.initialize()
    await db.ensure_user(1)
    await db.add_cookies(1, 10, 'test')
    await db.purchase_pet(1, 'cat', 'Кот', 1)
    for hunger, thirst in [(49, 50), (50, 49)]:
        await db.execute('UPDATE pets SET hunger=?, thirst=? WHERE user_id=1', (hunger, thirst))
        ok, message, _ = await db.start_expedition(1)
        assert not ok and '50' in message
    await db.execute('UPDATE pets SET hunger=50, thirst=50, mood=42 WHERE user_id=1')
    observed = []
    def roll(mood):
        observed.append(mood)
        return expedition.ExpeditionLoot(kind='cookies', amount=0)
    monkeypatch.setattr(expedition, 'roll_expedition_loot', roll)
    assert (await db.start_expedition(1))[0]
    await db.execute('UPDATE pets SET mood=100, expedition_until=? WHERE user_id=1',
                     ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),))
    before = (await db.get_user(1))['cookies']
    result = await db.settle_pet(1)
    assert observed == [42]
    assert result['expedition_loot']['amount'] == 0
    assert (await db.get_user(1))['cookies'] == before
    assert 'находок нет' in expedition.result_text(pet_name='Кот', species_words={},
                                                   loot=expedition.ExpeditionLoot(kind='cookies', amount=0))


@pytest.mark.asyncio
async def test_stroking_is_private_hourly_and_mood_is_not_overwritten(tmp_path):
    db = Database(tmp_path / 'pet.db')
    await db.initialize()
    for uid in (1, 2):
        await db.ensure_user(uid)
        await db.add_cookies(uid, 10, 'test')
        await db.purchase_pet(uid, 'cat', 'Кот', 1)
    await db.execute('UPDATE pets SET hunger=80, thirst=80, mood=10 WHERE user_id=1')
    assert content(await nora_game_api.stroke_companion(request(db, 1)))['ok']
    assert (await db.get_pet(1))['mood'] == 60
    assert (await db.get_pet(2))['mood'] == 80
    assert not content(await nora_game_api.stroke_companion(request(db, 1)))['ok']
    past = (datetime.now(UTC) - timedelta(hours=1, minutes=1)).isoformat()
    await db.execute('UPDATE bot_state SET value=? WHERE key=?', (past, 'pet_stroke:1'))
    await db.execute('UPDATE pets SET last_tick_at=? WHERE user_id=1', (past,))
    assert (await db.get_pet(1))['mood'] == 61
    assert content(await nora_game_api.stroke_companion(request(db, 1)))['ok']
    assert (await db.get_pet(1))['mood'] == 100
    await db.execute('UPDATE bot_state SET value=? WHERE key=?', (past, 'pet_stroke:1'))
    assert not (await db.stroke_pet(1))[0]
    assert await db.get_bot_state('pet_stroke:1') == past
    await db.execute('UPDATE pets SET expedition_until=? WHERE user_id=1',
                     ((datetime.now(UTC) + timedelta(hours=1)).isoformat(),))
    assert not (await db.stroke_pet(1))[0]


def test_mood_changes_odds_but_never_guarantees_success(monkeypatch):
    monkeypatch.setattr(expedition.secrets, 'randbelow', lambda _: 50)
    assert expedition.roll_expedition_loot(0).amount == 0
    assert expedition.roll_expedition_loot(100).amount > 0
    monkeypatch.setattr(expedition.secrets, 'randbelow', lambda n: n - 1)
    assert expedition.roll_expedition_loot(100).amount == 0
    monkeypatch.setattr(expedition.secrets, 'randbelow', lambda _: 0)
    assert expedition.roll_expedition_loot(100).amount == 1


@pytest.mark.asyncio
async def test_mood_changes_guard_chance(tmp_path, monkeypatch):
    db = Database(tmp_path / 'guard.db')
    await db.initialize()
    await db.ensure_user(1)
    await db.add_cookies(1, 10, 'test')
    await db.purchase_pet(1, 'cat', 'Кот', 1)
    monkeypatch.setattr('community_bot.helpers.secrets.randbelow', lambda _: 20)
    await db.execute('UPDATE pets SET mood=0 WHERE user_id=1')
    assert (await pet_guard_reputation(db, 1, -1))[0] == -1
    await db.execute('UPDATE pets SET mood=100 WHERE user_id=1')
    assert (await pet_guard_reputation(db, 1, -1))[0] == 0


@pytest.mark.asyncio
async def test_parallel_strokes_and_expedition_time(tmp_path):
    db = Database(tmp_path / 'race.db')
    await db.initialize()
    await db.ensure_user(1)
    await db.add_cookies(1, 10, 'test')
    await db.purchase_pet(1, 'cat', 'Кот', 1)
    await db.execute('UPDATE pets SET mood=0 WHERE user_id=1')
    responses = await asyncio.gather(db.stroke_pet(1), db.stroke_pet(1))
    assert sum(ok for ok, _ in responses) == 1
    assert (await db.get_pet(1))['mood'] == 50
    assert (await db.start_expedition(1))[0]
    await db.execute('UPDATE pets SET last_tick_at=?, expedition_until=? WHERE user_id=1', (
        (datetime.now(UTC) - timedelta(hours=25)).isoformat(),
        (datetime.now(UTC) - timedelta(minutes=30)).isoformat(),
    ))
    pet = await db.settle_pet(1)
    assert (pet['hunger'], pet['thirst'], pet['mood']) == (80, 80, 50)
