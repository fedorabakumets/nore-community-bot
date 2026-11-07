"""Seasonal music delivery and private record collection, without schema changes."""
import json
import math
import time
from pathlib import Path

from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile
from aiohttp import web

from .dedzytwo_playlist import PlaylistDelivery, Track, load_tracks

ASSETS = Path(__file__).resolve().parent.parent / 'assets' / 'game'
RECORDS = {'standard', 'dedzytwo'}
COOLDOWN = 300
CHAT_COOLDOWN = 300
INVENTORY_SIZE = 8
LOBBY_DECK_KEY = 'nora_lobby_deck'
LOBBY_COOLDOWN = 90
RECORD_DURATION = {'standard': 66.743, 'dedzytwo': 60.265}


def initial_collection():
    return {'claimed': False, 'player': 'standard', 'hand': None, 'shelf': [], 'revision': 0,
            'inventory': [None] * INVENTORY_SIZE}


async def read_collection(db, uid):
    row = await (await db.execute('SELECT value FROM bot_state WHERE key = ?',
                                 (f'nora_records:{uid}',))).fetchone()
    state = json.loads(row['value']) if row else initial_collection()
    state.setdefault('inventory', [None] * INVENTORY_SIZE)
    return state


async def read_lobby_deck(db):
    row = await (await db.execute('SELECT value FROM bot_state WHERE key = ?', (LOBBY_DECK_KEY,))).fetchone()
    return json.loads(row['value']) if row else {'record': None, 'owner': None, 'playing': False, 'revision': 0}


def public_deck(deck, uid):
    return {'record': deck['record'], 'mine': deck['owner'] == uid,
            'playing': deck['playing'], 'revision': deck['revision']}


async def save(db, key, value):
    await db.execute('INSERT INTO bot_state(key,value) VALUES (?,?) '
                     'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     (key, json.dumps(value)))


async def return_lobby_record(db, deck, now, *, destination='shelf'):
    """Return the record atomically; callers hold a write transaction."""
    if not deck.get('record') or deck.get('owner') is None:
        return False
    uid = deck['owner']
    state = await read_collection(db, uid)
    if destination == 'hand' and not state['hand']:
        state['hand'] = deck['record']
    elif destination in ('hand', 'inventory') and None in state['inventory']:
        state['inventory'][state['inventory'].index(None)] = deck['record']
    elif destination == 'hand':
        raise ValueError('Освободи руку или клетку инвентаря')
    else:
        state['shelf'].append(deck['record'])
    state['revision'] += 1
    await save(db, f'nora_records:{uid}', state)
    await save(db, f'nora_lobby_cooldown:{uid}', now + LOBBY_COOLDOWN)
    deck.update(record=None, owner=None, playing=False, revision=deck['revision'] + 1)
    deck.pop('ends_at', None)
    deck.pop('remaining', None)
    deck.pop('session', None)
    await save(db, LOBBY_DECK_KEY, deck)
    return True


async def expire_lobby_deck(db, deck, now):
    if deck.get('record') and now >= deck.get('ends_at', 0):
        return await return_lobby_record(db, deck, min(now, deck.get('ends_at', now)) or now,
                                         destination='inventory')
    return False


async def settle_lobby_deck(db, deck, app):
    presence = app.get('nora_lobby')
    if deck.get('record') and presence is not None:
        owner = presence.get(deck.get('owner'))
        if (not owner or time.monotonic() - owner[0] >= 8 or
                (deck.get('session') and deck['session'] != owner[1])):
            return await return_lobby_record(db, deck, time.time())
    return await expire_lobby_deck(db, deck, time.time())


async def return_departed_record(database, uid, session):
    async with database.connect() as db:
        await db.execute('BEGIN IMMEDIATE')
        deck = await read_lobby_deck(db)
        if deck.get('owner') == uid and deck.get('session') in (None, session):
            await return_lobby_record(db, deck, time.time())
        await db.commit()


async def collection(request):
    uid = request['actor']['id']
    async with request.app['db'].connect() as db:
        await db.execute('BEGIN IMMEDIATE')
        deck = await read_lobby_deck(db)
        await settle_lobby_deck(db, deck, request.app)
        await db.commit()
        if getattr(request, 'query', {}).get('room') == 'lobby':
            return web.json_response(public_deck(deck, uid))
        state = await read_collection(db, uid)
    return web.json_response(state)


async def record_action(request):
    body = await request.json()
    if not isinstance(body, dict):
        raise ValueError('Выбери действие с пластинкой')
    uid = request['actor']['id']
    action = body.get('action')
    lobby = action in ('lobby_insert', 'lobby_eject', 'lobby_toggle')
    async with request.app['db'].connect() as db:
        await db.execute('BEGIN IMMEDIATE')
        registered = await (await db.execute(
            'SELECT 1 FROM nora_game_players WHERE telegram_id = ?', (uid,),
        )).fetchone()
        if not registered:
            raise ValueError('Сначала создай персонажа Норы')
        deck = await read_lobby_deck(db)
        if await settle_lobby_deck(db, deck, request.app):
            await db.commit()
            await db.execute('BEGIN IMMEDIATE')
            deck = await read_lobby_deck(db)
        state = await read_collection(db, uid)
        if action == 'claim' and state['claimed']:
            return web.json_response(state)
        if type(body.get('revision')) is not int or body['revision'] != state['revision']:
            return web.json_response({'error': 'Коллекция изменилась. Открой её снова'}, status=409)
        if action == 'claim':
            state['claimed'] = True
            state['shelf'].append('dedzytwo')
        elif action == 'take':
            record = body.get('record')
            if not isinstance(record, str) or record not in RECORDS or record not in state['shelf']:
                raise ValueError('Этой пластинки нет на полке')
            if state['hand']:
                raise ValueError('Сначала поставь пластинку из рук')
            state['shelf'].remove(record)
            state['hand'] = record
        elif action == 'store':
            if not state['hand']:
                raise ValueError('В руках нет пластинки')
            state['shelf'].append(state['hand'])
            state['hand'] = None
        elif action in ('pack', 'unpack'):
            slot = body.get('slot')
            inventory = state['inventory']
            if type(slot) is not int or not 0 <= slot < INVENTORY_SIZE:
                raise ValueError('Выбери клетку инвентаря')
            if action == 'pack' and state['hand'] and inventory[slot] is None:
                inventory[slot], state['hand'] = state['hand'], None
            elif action == 'unpack' and not state['hand'] and inventory[slot]:
                state['hand'], inventory[slot] = inventory[slot], None
            else:
                raise ValueError('Проверь, свободны ли руки и клетка инвентаря')
        elif lobby:
            if type(body.get('deck_revision')) is not int or body['deck_revision'] != deck['revision']:
                return web.json_response({'error': 'Проигрыватель изменился. Попробуй снова'}, status=409)
            if action == 'lobby_insert':
                presence = request.app.get('nora_lobby')
                if presence is not None and (uid not in presence or
                                             time.monotonic() - presence[uid][0] >= 8):
                    raise ValueError('Подключись к лобби, чтобы включить пластинку')
                owner_session = presence[uid][1] if presence is not None else None
                if deck['record'] or not state['hand']:
                    raise ValueError('Для установки нужна пластинка в руках и свободный проигрыватель')
                row = await (await db.execute('SELECT value FROM bot_state WHERE key = ?',
                                              (f'nora_lobby_cooldown:{uid}',))).fetchone()
                remaining = math.ceil(float(row['value']) - time.time()) if row else 0
                if remaining > 0:
                    raise ValueError(f'Проигрыватель будет доступен через {remaining} сек.')
                deck.update(record=state['hand'], owner=uid, playing=True,
                            ends_at=time.time() + RECORD_DURATION[state['hand']],
                            session=owner_session)
                state['hand'] = None
            elif deck['owner'] != uid:
                raise ValueError('Этой пластинкой управляет её владелец')
            elif action == 'lobby_eject':
                await return_lobby_record(db, deck, time.time(), destination='hand')
                state = await read_collection(db, uid)
                await db.commit()
                return web.json_response({**state, 'lobby_deck': public_deck(deck, uid)})
            else:
                deck['playing'] = not deck['playing']
            deck['revision'] += 1
            await save(db, LOBBY_DECK_KEY, deck)
        elif action == 'insert':
            if not state['hand']:
                raise ValueError('Возьми пластинку со стеллажа')
            state['player'], state['hand'] = state['hand'], state['player']
        elif action == 'eject':
            if state['hand'] or not state['player']:
                raise ValueError('Освободи руки, чтобы достать пластинку')
            state['hand'], state['player'] = state['player'], None
        else:
            raise ValueError('Неизвестное действие с пластинкой')
        state['revision'] += 1
        await save(db, f'nora_records:{uid}', state)
        await db.commit()
    return web.json_response({**state, 'lobby_deck': public_deck(deck, uid)} if lobby else state)


async def delivery_status(request):
    remaining = 0
    async with request.app['db'].connect() as db:
        for key, cooldown in ((f'nora_music_send:{request["actor"]["id"]}', COOLDOWN),
                              ('nora_music_chat', CHAT_COOLDOWN)):
            row = await (await db.execute('SELECT value FROM bot_state WHERE key = ?', (key,))).fetchone()
            if row:
                remaining = max(remaining, math.ceil(float(row['value']) + cooldown - time.time()))
    return web.json_response({'retry_after': remaining})


async def send_track(request):
    uid = request['actor']['id']
    chat = int(getattr(request.app['settings'], 'community_chat_id', 0) or 0)
    if not chat:
        raise ValueError('Чат сообщества пока не настроен')
    now = time.time()
    async with request.app['db'].connect() as db:
        await db.execute('BEGIN IMMEDIATE')
        for key, cooldown in ((f'nora_music_send:{uid}', COOLDOWN), ('nora_music_chat', CHAT_COOLDOWN)):
            row = await (await db.execute('SELECT value FROM bot_state WHERE key = ?', (key,))).fetchone()
            remaining = math.ceil(float(row['value']) + cooldown - now) if row else 0
            if remaining > 0:
                return web.json_response({'retry_after': remaining, 'message': 'Песня уже отправлена. Немного подожди'})
        await save(db, f'nora_music_send:{uid}', now)
        await save(db, 'nora_music_chat', now)
        await db.commit()
    tracks = load_tracks(
        ASSETS / 'dedzytwo-playlist.json',
        Track(FSInputFile(ASSETS / 'dedzytwo-s1.mp3'), 'Музыкальная пластинка «?» (S1)', 'dedzytwo', 66),
    )
    delivery = PlaylistDelivery(
        request.app['bot'], FSInputFile(ASSETS / 'dedzytwo-playlist.jpg'), tracks,
    )
    sent = []
    for recipient in (chat, uid):
        try:
            await delivery.send(recipient)
            sent.append(recipient)
        except TelegramAPIError:
            pass
    if len(sent) == 2:
        message = 'Отправили песню в чат и в личку 🎧'
    elif chat in sent:
        message = 'Песня уже в чате 🎧 В личку отправить не удалось — открой диалог с ботом'
    elif uid in sent:
        message = 'Песня уже в личке 🎧 В чат отправить не удалось'
    else:
        message = 'Не удалось отправить песню. Попробуй после перерыва'
    return web.json_response({'sent': len(sent) == 2, 'message': message, 'retry_after': COOLDOWN})
