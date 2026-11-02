import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from community_bot import cabinet_api, nora_game_api
from community_bot.database import Database


def request(db, uid, body=None):
    class Request(dict):
        app = {'db': db}
        json = AsyncMock(return_value=body)

    return Request(actor={'id': uid})


def content(response):
    return json.loads(response.text)


@pytest.mark.asyncio
async def test_companion_uses_own_existing_pet_and_expedition(tmp_path):
    db = Database(tmp_path / 'companion.db')
    await db.initialize()
    for uid in (1, 2):
        await db.ensure_user(uid)
        await db.add_cookies(uid, 10, 'test')
    assert content(await nora_game_api.companion(request(db, 1))) == {'pet': None}
    assert (await db.purchase_pet(1, 'fox', 'Рыжик', 1))[0]
    assert (await db.purchase_pet(2, 'cat', 'Чужой', 1))[0]
    await db.execute('UPDATE pets SET hunger = 72 WHERE user_id = 1')
    pet = content(await nora_game_api.companion(request(db, 1)))['pet']
    assert (pet['name'], pet['species'], pet['hunger']) == ('Рыжик', 'fox', 72)
    assert not {'user_id', 'telegram_id', 'username'} & pet.keys()
    assert content(await nora_game_api.companion(request(db, 2)))['pet']['name'] == 'Чужой'
    prepared = content(await cabinet_api.pet_prepare(request(db, 1, {'action': 'expedition'})))
    send = request(db, 1, {'token': prepared['token']})
    send.app['settings'] = SimpleNamespace(timezone='Europe/Moscow')
    assert content(await cabinet_api.pet_action(send))['ok']
    assert content(await nora_game_api.companion(request(db, 1)))['pet']['expedition_until']
    assert content(await nora_game_api.companion(request(db, 2)))['pet']['expedition_until'] is None
    assert not content(await cabinet_api.pet_action(send))['ok']
    before = (await db.get_user(1))['cookies']
    await db.execute('UPDATE pets SET expedition_until = ? WHERE user_id = 1',
                     ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),))
    returned = content(await nora_game_api.companion(request(db, 1)))['pet']
    assert returned['expedition_until'] is None
    after = (await db.get_user(1))['cookies']
    assert 1 <= after - before <= 10
    await nora_game_api.companion(request(db, 1))
    assert (await db.get_user(1))['cookies'] == after


@pytest.mark.asyncio
async def test_registration_is_private_persistent_and_case_insensitive(tmp_path):
    db = Database(tmp_path / 'game.db')
    await db.initialize()
    assert content(await nora_game_api.status(request(db, 1))) == {'nickname': None, 'outfit': None}
    first = await nora_game_api.register(request(db, 1, {'nickname': 'Alice'}))
    assert content(first) == {'nickname': 'Alice'}
    duplicate = await nora_game_api.register(request(db, 2, {'nickname': 'aLiCe'}))
    assert duplicate.status == 409
    assert content(await nora_game_api.status(request(db, 2))) == {'nickname': None, 'outfit': None}
    assert content(await nora_game_api.register(request(db, 1, {'nickname': 'Other'}))) == {'nickname': 'Alice'}
    await db.initialize()
    assert content(await nora_game_api.status(request(db, 1))) == {'nickname': 'Alice', 'outfit': None}


@pytest.mark.asyncio
@pytest.mark.parametrize('nickname', ['ab', 'a' * 17, 'Alice1', ' Alice', 'Аlice', '', None])
async def test_invalid_nicknames_are_rejected(tmp_path, nickname):
    db = Database(tmp_path / 'game.db')
    await db.initialize()
    with pytest.raises(ValueError):
        await nora_game_api.register(request(db, 1, {'nickname': nickname}))


@pytest.mark.asyncio
async def test_concurrent_registration_only_one_wins(tmp_path):
    db = Database(tmp_path / 'game.db')
    await db.initialize()
    responses = await asyncio.gather(
        nora_game_api.register(request(db, 1, {'nickname': 'Player'})),
        nora_game_api.register(request(db, 2, {'nickname': 'player'})),
    )
    assert sorted(response.status for response in responses) == [200, 409]


@pytest.mark.asyncio
async def test_outfit_requires_registration_and_is_private_and_persistent(tmp_path):
    db = Database(tmp_path / 'game.db')
    await db.initialize()
    clothes = {'shirt': 'gray', 'pants': 'burgundy_wide', 'shoes': 'red_air'}
    with pytest.raises(ValueError):
        await nora_game_api.save_outfit(request(db, 1, clothes))
    await nora_game_api.register(request(db, 1, {'nickname': 'Alice'}))
    expected = {**clothes, **nora_game_api.APPEARANCE_DEFAULTS}
    assert content(await nora_game_api.save_outfit(request(db, 1, clothes))) == {'outfit': expected}
    assert content(await nora_game_api.status(request(db, 1))) == {'nickname': 'Alice', 'outfit': expected}
    assert content(await nora_game_api.status(request(db, 2))) == {'nickname': None, 'outfit': None}
    await db.initialize()
    assert content(await nora_game_api.status(request(db, 1)))['outfit'] == expected
    with pytest.raises(ValueError):
        await nora_game_api.save_outfit(request(db, 1, {**clothes, 'shoes': 'invalid'}))


@pytest.mark.asyncio
async def test_appearance_survives_reload_and_legacy_clothing_updates(tmp_path):
    db = Database(tmp_path / 'game.db')
    await db.initialize()
    clothes = {'shirt': 'white', 'pants': 'blue_slim', 'shoes': 'white_stripes'}
    for uid, name in ((1, 'Alice'), (2, 'Other')):
        await nora_game_api.register(request(db, uid, {'nickname': name}))
    # A saved outfit from before the editor update must still open normally.
    await db.execute('INSERT INTO nora_game_outfits VALUES (?, ?, ?, ?)', (1, *clothes.values()))
    assert content(await nora_game_api.status(request(db, 1)))['outfit'] == {
        **clothes, **nora_game_api.APPEARANCE_DEFAULTS,
    }
    appearance = {'gender': 'female', 'hairstyle': 'ponytail', 'hair_color': 'rose', 'eye_color': 'green'}
    await nora_game_api.save_outfit(request(db, 1, {**clothes, **appearance, 'telegram_id': 2}))
    await nora_game_api.save_outfit(request(db, 2, clothes))
    await db.initialize()
    assert content(await nora_game_api.status(request(db, 1)))['outfit'] == {**clothes, **appearance}
    assert content(await nora_game_api.status(request(db, 2)))['outfit'] == {
        **clothes, **nora_game_api.APPEARANCE_DEFAULTS,
    }
    updated = {**clothes, 'shirt': 'gray'}
    assert content(await nora_game_api.save_outfit(request(db, 1, updated)))['outfit'] == {
        **updated, **appearance,
    }


@pytest.mark.asyncio
async def test_all_appearance_options_can_be_saved(tmp_path):
    db = Database(tmp_path / 'game.db')
    await db.initialize()
    await nora_game_api.register(request(db, 1, {'nickname': 'Alice'}))
    outfit = {'shirt': 'gray', 'pants': 'gray_slim', 'shoes': 'black_stripes',
              **nora_game_api.APPEARANCE_DEFAULTS}
    for key, allowed in nora_game_api.APPEARANCE_CHOICES.items():
        for value in sorted(allowed):
            outfit[key] = value
            assert content(await nora_game_api.save_outfit(request(db, 1, outfit)))['outfit'] == outfit
            assert content(await nora_game_api.status(request(db, 1)))['outfit'] == outfit


@pytest.mark.asyncio
@pytest.mark.parametrize('field', [*nora_game_api.APPEARANCE_CHOICES, 'shirt', 'pants', 'shoes'])
@pytest.mark.parametrize('value', ['invalid', None, [], {}, 42])
async def test_invalid_appearance_does_not_change_saved_outfit(tmp_path, field, value):
    db = Database(tmp_path / 'game.db')
    await db.initialize()
    await nora_game_api.register(request(db, 1, {'nickname': 'Alice'}))
    clothes = {'shirt': 'white', 'pants': 'blue_slim', 'shoes': 'white_stripes'}
    before = content(await nora_game_api.save_outfit(request(db, 1, clothes)))['outfit']
    with pytest.raises(ValueError):
        await nora_game_api.save_outfit(request(db, 1, {**before, 'shirt': 'gray', field: value}))
    assert content(await nora_game_api.status(request(db, 1)))['outfit'] == before


@pytest.mark.asyncio
@pytest.mark.parametrize('saved', ['broken json', '[]', '{"gender": [], "hair_color": "invalid"}'])
async def test_invalid_stored_appearance_falls_back_to_defaults(tmp_path, saved):
    db = Database(tmp_path / 'game.db')
    await db.initialize()
    await nora_game_api.register(request(db, 1, {'nickname': 'Alice'}))
    clothes = {'shirt': 'white', 'pants': 'blue_slim', 'shoes': 'white_stripes'}
    await nora_game_api.save_outfit(request(db, 1, clothes))
    await db.set_bot_state('nora_game_appearance:1', saved)
    assert content(await nora_game_api.status(request(db, 1)))['outfit'] == {
        **clothes, **nora_game_api.APPEARANCE_DEFAULTS,
    }
