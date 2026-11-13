import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramForbiddenError, TelegramNotFound
from aiogram.methods import SendAudio, SendRichMessage

from community_bot import music_api, nora_game_api
from community_bot.database import Database


def delivery_bot(send_audio=None):
    return SimpleNamespace(
        me=AsyncMock(return_value=SimpleNamespace(username='nora_test_bot')),
        send_rich_message=AsyncMock(side_effect=TelegramNotFound(
            method=SendRichMessage(chat_id=1, rich_message={'blocks': []}), message='Not Found',
        )),
        send_audio=send_audio or AsyncMock(),
    )


def request(db, uid=1, body=None, bot=None):
    class Request(dict):
        app = {'db': db, 'settings': SimpleNamespace(community_chat_id=-100),
               'bot': bot or delivery_bot()}
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
    assert result['hand'] == 'standard' and result['shelf'] == []
    assert result['lobby_deck']['record'] is None


@pytest.mark.asyncio
async def test_delivery_cooldown_is_atomic_persistent_and_limits_shared_chat(tmp_path, monkeypatch):
    db = Database(tmp_path / 'delivery.db')
    await db.initialize()
    bot = delivery_bot()
    now = [10000]
    monkeypatch.setattr(music_api.time, 'time', lambda: now[0])
    results = await asyncio.gather(*(music_api.send_track(request(db, bot=bot)) for _ in range(2)))
    assert sum(content(r).get('sent', False) for r in results) == 1
    assert bot.send_audio.await_count == 2
    assert [call.args[0] for call in bot.send_audio.await_args_list] == [-100, 1]
    assert all(call.args[1].path == music_api.ASSETS / 'dedzytwo-s1.mp3'
               for call in bot.send_audio.await_args_list)
    assert content(await music_api.send_track(request(db, 2, bot=bot)))['retry_after'] == 300
    assert content(await music_api.delivery_status(request(db, 2)))['retry_after'] == 300
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

    result = content(await music_api.send_track(request(db, bot=delivery_bot(send))))
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


@pytest.mark.asyncio
async def test_delivers_native_playlist_to_both_recipients(tmp_path, monkeypatch):
    db = Database(tmp_path / 'delivery.db')
    await db.initialize()
    (tmp_path / 'extra.mp3').touch()
    monkeypatch.setattr(music_api, 'ASSETS', tmp_path)
    (tmp_path / 'dedzytwo-playlist.json').write_text(json.dumps([
        {'media': 'test-file-id', 'title': 'L.O.T.R', 'performer': 'kizaru', 'duration': 123},
        {'media': './extra.mp3', 'title': 'Holla Holla'},
    ]), encoding='utf-8')
    bot = delivery_bot()
    bot.send_rich_message.side_effect = None
    bot.send_rich_message.return_value = SimpleNamespace(rich_message=None)

    assert content(await music_api.send_track(request(db, bot=bot)))['sent']
    assert [call.args[0] for call in bot.send_rich_message.await_args_list] == [-100, 1]
    for call in bot.send_rich_message.await_args_list:
        message = call.kwargs['rich_message']
        assert [block.type for block in message.blocks] == [
            'photo', 'paragraph', 'heading', 'details', 'divider',
            'audio', 'audio', 'audio', 'divider', 'buttons',
        ]
        assert message.blocks[0].photo.media.path.name == 'dedzytwo-playlist.jpg'
        assert message.blocks[3].is_open
        track = message.blocks[6].audio
        assert (track.media, track.title, track.performer, track.duration) == (
            'test-file-id', 'L.O.T.R', 'kizaru', 123,
        )
        button = message.blocks[-1].buttons[0]
        assert button.text == 'НОРА' and button.url == 'https://t.me/nora_test_bot?startapp'
    bot.send_audio.assert_not_awaited()

    session = AiohttpSession()
    transport_bot = Bot('123456:test-token', session=session)
    files = {}
    payload = json.loads(session.prepare_value(message, bot=transport_bot, files=files))
    assert len(files) == 3
    assert payload['blocks'][0]['photo']['media'].startswith('attach://')
    assert payload['blocks'][5]['audio']['media'].startswith('attach://')
    assert payload['blocks'][6]['audio']['media'] == 'test-file-id'
    assert files[payload['blocks'][7]['audio']['media'].removeprefix('attach://')].path == tmp_path / 'extra.mp3'


@pytest.mark.asyncio
async def test_ambiguous_rich_delivery_failure_does_not_duplicate_message(tmp_path):
    from aiogram.exceptions import TelegramNetworkError

    db = Database(tmp_path / 'delivery.db')
    await db.initialize()
    bot = delivery_bot()
    bot.send_rich_message.side_effect = TelegramNetworkError(
        method=SendRichMessage(chat_id=1, rich_message={'blocks': []}), message='timeout',
    )

    assert not content(await music_api.send_track(request(db, bot=bot)))['sent']
    assert bot.send_rich_message.await_count == 2
    bot.send_audio.assert_not_awaited()


def test_bundled_playlist_has_all_five_tracks():
    from community_bot.dedzytwo_playlist import Track, load_tracks

    assets = music_api.ASSETS
    original = Track('original', 'Original')
    tracks = load_tracks(assets / 'dedzytwo-playlist.json', original)
    assert len(tracks) == 5
    assert all(track.media.path.stat().st_size > 0 for track in tracks[1:])

@pytest.mark.asyncio
async def test_lobby_finished_record_inventory_fallback_and_personal_cooldown(tmp_path, monkeypatch):
    db = Database(tmp_path / 'lobby-finish.db')
    await db.initialize()
    now = [1000.0]
    monkeypatch.setattr(music_api.time, 'time', lambda: now[0])
    for uid, name in ((1, 'Alice'), (2, 'Bob')):
        await nora_game_api.register(request(db, uid, {'nickname': name}))

    async def act(uid, action, **extra):
        state = content(await music_api.collection(request(db, uid)))
        return await music_api.record_action(request(db, uid, {
            'action': action, 'revision': state['revision'], **extra,
        }))

    await act(1, 'eject')
    await act(1, 'lobby_insert', deck_revision=0)
    now[0] += music_api.RECORD_DURATION['standard'] + 1
    state = content(await music_api.collection(request(db, 1)))
    assert state['inventory'][0] == 'standard' and not state['shelf']
    await act(1, 'unpack', slot=0)
    with pytest.raises(ValueError, match='доступен через'):
        await act(1, 'lobby_insert', deck_revision=2)
    await act(2, 'eject')
    await act(2, 'lobby_insert', deck_revision=2)
    async with db.connect() as conn:
        state = await music_api.read_collection(conn, 2)
        state['inventory'] = ['standard'] * 8
        await music_api.save(conn, 'nora_records:2', state)
        await conn.commit()
    now[0] += music_api.RECORD_DURATION['standard'] + 1
    state = content(await music_api.collection(request(db, 2)))
    assert state['shelf'] == ['standard'] and len(state['inventory']) == 8


@pytest.mark.asyncio
async def test_disconnected_owner_returns_record_to_shelf_and_manual_eject_uses_hand(tmp_path):
    db = Database(tmp_path / 'lobby-disconnect.db')
    await db.initialize()
    await nora_game_api.register(request(db, 1, {'nickname': 'Alice'}))

    async def act(action, **extra):
        state = content(await music_api.collection(request(db)))
        return content(await music_api.record_action(request(db, body={
            'action': action, 'revision': state['revision'], **extra,
        })))

    await act('eject')
    await act('lobby_insert', deck_revision=0)
    await nora_game_api.settle_lobby_record({'db': db, 'nora_lobby': {}})
    state = content(await music_api.collection(request(db)))
    assert state['shelf'] == ['standard'] and not any(state['inventory'])
    async with db.connect() as conn:
        await music_api.save(conn, 'nora_lobby_cooldown:1', 0)
        await conn.commit()
    await act('take', record='standard')
    await act('lobby_insert', deck_revision=2)
    state = await act('lobby_eject', deck_revision=3)
    assert state['hand'] == 'standard' and state['shelf'] == []
