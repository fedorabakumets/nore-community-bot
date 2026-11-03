import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendAudio

from community_bot import music_api, nora_game_api
from community_bot.database import Database


def request(db, uid=1, body=None, bot=None):
    class Request(dict):
        app = {'db': db, 'settings': SimpleNamespace(community_chat_id=-100),
               'bot': bot or SimpleNamespace(send_audio=AsyncMock())}
        json = AsyncMock(return_value=body)

    return Request(actor={'id': uid})


def content(response):
    return json.loads(response.text)


@pytest.mark.asyncio
async def test_collection_claim_swap_eject_store_and_reload(tmp_path):
    db = Database(tmp_path / 'records.db')
    await db.initialize()
    await nora_game_api.register(request(db, body={'nickname': 'Player'}))
    state = content(await music_api.collection(request(db)))

    async def act(action, **extra):
        nonlocal state
        state = content(await music_api.record_action(request(db, body={
            'action': action, 'revision': state['revision'], 'telegram_id': 2, **extra,
        })))
        owned = state['shelf'] + [r for r in (state['player'], state['hand']) if r]
        assert sorted(owned) == ['dedzytwo', 'standard']

    await act('claim')
    await act('claim')
    assert state['shelf'] == ['dedzytwo']
    await act('take', record='dedzytwo')
    await act('insert')
    assert state['player'] == 'dedzytwo' and state['hand'] == 'standard'
    await act('store')
    assert state['shelf'] == ['standard']
    await act('eject')
    assert state['player'] is None and state['hand'] == 'dedzytwo'
    await act('store')
    await act('take', record='standard')
    await act('insert')
    await db.initialize()
    assert content(await music_api.collection(request(db))) == state
    assert content(await music_api.collection(request(db, 2))) == music_api.initial_collection()


@pytest.mark.asyncio
async def test_collection_rejects_unregistered_invalid_and_stale_actions(tmp_path):
    db = Database(tmp_path / 'records.db')
    await db.initialize()
    with pytest.raises(ValueError):
        await music_api.record_action(request(db, body={'action': 'claim', 'revision': 0}))
    await nora_game_api.register(request(db, body={'nickname': 'Player'}))
    for body in ([], {'action': 'take', 'record': 'dedzytwo', 'revision': 0},
                 {'action': 'insert', 'revision': 0}, {'action': 'bad', 'revision': 0}):
        with pytest.raises(ValueError):
            await music_api.record_action(request(db, body=body))
    await music_api.record_action(request(db, body={'action': 'claim', 'revision': 0}))
    for revision in (0, True, '1', None):
        response = await music_api.record_action(request(db, body={
            'action': 'take', 'record': 'dedzytwo', 'revision': revision,
        }))
        assert response.status == 409
    responses = await asyncio.gather(*(music_api.record_action(request(db, body={
        'action': 'take', 'record': 'dedzytwo', 'revision': 1,
    })) for _ in range(2)))
    assert sorted(r.status for r in responses) == [200, 409]


@pytest.mark.asyncio
async def test_lobby_record_transfer_is_persistent_and_owner_only(tmp_path):
    db = Database(tmp_path / 'lobby-records.db')
    await db.initialize()
    for uid, nickname in ((1, 'Player'), (2, 'Other')):
        await nora_game_api.register(request(db, uid, {'nickname': nickname}))
    async with db.connect() as conn:
        legacy = music_api.initial_collection()
        del legacy['inventory']
        await music_api.save(conn, 'nora_records:1', legacy)
        await conn.commit()

    async def act(uid, action, **extra):
        state = content(await music_api.collection(request(db, uid)))
        return await music_api.record_action(request(db, uid, {
            'action': action, 'revision': state['revision'], **extra,
        }))

    async def lobby_deck(uid):
        req = request(db, uid)
        req.query = {'room': 'lobby'}
        return content(await music_api.collection(req))

    assert content(await music_api.collection(request(db)))['inventory'] == [None] * 8
    await act(1, 'eject')
    for invalid in (-1, 8, True):
        with pytest.raises(ValueError, match='клетку'):
            await act(1, 'pack', slot=invalid)
    assert content(await act(1, 'pack', slot=7))['inventory'][7] == 'standard'
    await db.initialize()
    assert content(await act(1, 'unpack', slot=7))['hand'] == 'standard'
    await act(2, 'eject')
    results = await asyncio.gather(*(act(uid, 'lobby_insert', deck_revision=0) for uid in (1, 2)))
    assert sorted(response.status for response in results) == [200, 409]
    owner = 1 if results[0].status == 200 else 2
    visitor = 3 - owner
    assert await lobby_deck(visitor) == {'record': 'standard', 'mine': False, 'playing': True, 'revision': 1}
    assert content(await music_api.collection(request(db, visitor)))['hand'] == 'standard'
    with pytest.raises(ValueError, match='владелец'):
        await act(visitor, 'lobby_eject', deck_revision=1)
    assert not content(await act(owner, 'lobby_toggle', deck_revision=1))['lobby_deck']['playing']
    await db.initialize()
    result = content(await act(owner, 'lobby_eject', deck_revision=2))
    assert result['hand'] == 'standard' and result['lobby_deck']['record'] is None


@pytest.mark.asyncio
async def test_delivery_cooldown_is_atomic_persistent_and_limits_shared_chat(tmp_path, monkeypatch):
    db = Database(tmp_path / 'delivery.db')
    await db.initialize()
    bot = SimpleNamespace(send_audio=AsyncMock())
    now = [10000]
    monkeypatch.setattr(music_api.time, 'time', lambda: now[0])
    results = await asyncio.gather(*(music_api.send_track(request(db, bot=bot)) for _ in range(2)))
    assert sum(content(r).get('sent', False) for r in results) == 1
    assert bot.send_audio.await_count == 2
    assert [call.args[0] for call in bot.send_audio.await_args_list] == [-100, 1]
    assert all(call.args[1].path == music_api.ASSETS / 'dedzytwo-s1.mp3'
               for call in bot.send_audio.await_args_list)
    assert content(await music_api.send_track(request(db, 2, bot=bot)))['retry_after'] == 60
    assert content(await music_api.delivery_status(request(db, 2)))['retry_after'] == 60
    assert bot.send_audio.await_count == 2
    await db.initialize()
    assert content(await music_api.delivery_status(request(db)))['retry_after'] == 300
    now[0] += 301
    assert content(await music_api.send_track(request(db, bot=bot)))['sent']
    assert bot.send_audio.await_count == 4


@pytest.mark.asyncio
@pytest.mark.parametrize('failed', [{-100}, {1}, {-100, 1}])
async def test_delivery_does_not_report_full_success_on_partial_failure(tmp_path, failed):
    db = Database(tmp_path / 'delivery.db')
    await db.initialize()

    async def send(uid, audio, **kwargs):
        if uid in failed:
            raise TelegramForbiddenError(method=SendAudio(chat_id=uid, audio='test'), message='Forbidden')

    result = content(await music_api.send_track(request(db, bot=SimpleNamespace(send_audio=send))))
    assert not result['sent']
    assert result['message'] != 'Отправили песню в чат и в личку 🎧'
    assert result['retry_after'] == 300


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/api/community/music', '/api/nora-game/records'])
async def test_music_and_records_require_signed_staff_identity(tmp_path, path):
    from aiohttp import web

    from community_bot import access, miniapp

    db = Database(tmp_path / 'auth.db')
    await db.initialize()
    req = request(db)
    req.path = path
    req.headers = {}
    req.app['settings'].bot_token = 'test-only'
    handler = AsyncMock(return_value=web.json_response({'ok': True}))
    assert (await miniapp.protection(req, handler)).status == 401
    handler.assert_not_awaited()
    # A valid signature does not bypass the existing Mini App role gate.
    from unittest.mock import patch

    with patch.object(miniapp, 'validate_init_data', return_value={'id': 1}), \
         patch.object(access, 'miniapp_allowed', AsyncMock(return_value=False)):
        assert (await miniapp.protection(req, handler)).status == 403
        handler.assert_not_awaited()
