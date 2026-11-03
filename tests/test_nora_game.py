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


@pytest.mark.asyncio
async def test_lobby_exchanges_only_game_profiles_and_expires_presence(tmp_path, monkeypatch):
    db = Database(tmp_path / 'lobby.db')
    await db.initialize()
    now = 100
    monkeypatch.setattr(nora_game_api, 'time', SimpleNamespace(monotonic=lambda: now))
    presence = {}
    clothes = {'shirt': 'gray', 'pants': 'burgundy_wide', 'shoes': 'red_air'}
    for uid, nickname in ((1, 'Alice'), (2, 'Robin')):
        await nora_game_api.register(request(db, uid, {'nickname': nickname}))
        await nora_game_api.save_outfit(request(db, uid, clothes))

    async def exchange(uid, *, session=None, **fields):
        body = {
            'session': session or f'00000000-0000-4000-8000-{uid:012d}',
            'x': 1, 'y': .017, 'z': 2, 'heading': 0, **fields,
        }
        req = request(db, uid, body)
        req.app['nora_lobby'] = presence
        return content(await nora_game_api.lobby(req))['players']

    with pytest.raises(ValueError, match='персонажа'):
        await exchange(3)
    for bad_x in (True, float('nan'), float('inf'), 17, '1'):
        with pytest.raises(ValueError, match='координаты'):
            await exchange(1, x=bad_x)
    assert await exchange(1, nickname='Spoofed', telegram_id=2) == []
    assert await exchange(2) == [{
        'nickname': 'Alice', 'outfit': {**clothes, **nora_game_api.APPEARANCE_DEFAULTS},
        'x': 1, 'y': .017, 'z': 2, 'heading': 0,
    }]
    assert (await exchange(1))[0]['nickname'] == 'Robin'
    await exchange(2, session='00000000-0000-4000-8000-000000000099', x=5)
    await exchange(2, leave=True)
    assert (await exchange(1))[0]['x'] == 5
    await exchange(2, session='00000000-0000-4000-8000-000000000099', leave=True)
    assert await exchange(1) == []
    await exchange(2)
    now += nora_game_api.LOBBY_TTL
    assert await exchange(1) == []


@pytest.mark.asyncio
async def test_wing_purchase_and_lobby_bonus_use_persisted_equipment(tmp_path):
    db = Database(tmp_path / 'wings.db')
    await db.initialize()
    for uid, nickname in ((1, 'Alice'), (2, 'Robin')):
        await db.ensure_user(uid)
        await nora_game_api.register(request(db, uid, {'nickname': nickname}))
        await nora_game_api.save_outfit(request(db, uid, {
            'shirt': 'gray', 'pants': 'gray_slim', 'shoes': 'black_stripes',
        }))
    await db.set_cookies(1, 100, 1)
    await db.set_cookies(2, 49, 1)

    async def change(uid, action, item):
        return await nora_game_api.change_wings(request(db, uid, {
            'action': action, 'item': item, 'price': 0, 'telegram_id': 1,
        }))

    async def exchange(uid, height):
        req = request(db, uid, {
            'session': f'00000000-0000-4000-8000-{uid:012d}',
            'x': 1, 'y': height, 'z': 2, 'heading': 0, 'wings': 'flame',
        })
        req.app['nora_lobby'] = presence
        return content(await nora_game_api.lobby(req))['players']

    presence = {}
    assert (await change(2, 'buy', 'flame')).status == 409
    assert (await db.get_user(2))['cookies'] == 49
    with pytest.raises(ValueError, match='купи'):
        await change(2, 'equip', 'flame')
    responses = await asyncio.gather(change(1, 'buy', 'raven'), change(1, 'buy', 'raven'))
    assert [content(r) for r in responses] == [{'owned': ['raven'], 'equipped': None}] * 2
    assert (await db.get_user(1))['cookies'] == 50
    assert (await change(1, 'buy', 'frost')).status == 200
    assert (await db.get_user(1))['cookies'] == 0
    rows = await db.list_transactions(1)
    assert sorted((row['details'], row['amount']) for row in rows if row['kind'] == 'shop') == [
        ('nora_wings_frost', -50), ('nora_wings_raven', -50),
    ]

    await exchange(1, .017)
    with pytest.raises(ValueError, match='высоту'):
        await exchange(1, 1.02)
    await change(1, 'equip', 'raven')
    await change(1, 'equip', 'frost')
    reopened = Database(tmp_path / 'wings.db')
    profile = content(await nora_game_api.status(request(reopened, 1)))
    assert profile['wings'] == {'owned': ['raven', 'frost'], 'equipped': 'frost'}
    assert profile['outfit']['wings'] == 'frost'
    await exchange(1, 1.02)
    peer, = await exchange(2, .017)
    assert peer['outfit']['wings'] == 'frost'
    assert not {'wings', 'owned', 'telegram_id'} & peer.keys()
    await change(1, 'equip', None)
    with pytest.raises(ValueError, match='высоту'):
        await exchange(1, 1.02)
    await exchange(1, .017)
    peer, = await exchange(2, .017)
    assert 'wings' not in peer['outfit']
    assert (await db.get_user(1))['cookies'] == 0
