"""Seasonal music delivery and private record collection, without schema changes."""
import json
import math
import time
from pathlib import Path

from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile
from aiohttp import web

ASSETS = Path(__file__).resolve().parent.parent / 'assets' / 'game'
RECORDS = {'standard', 'dedzytwo'}
COOLDOWN = 300
CHAT_COOLDOWN = 60


def initial_collection():
    return {'claimed': False, 'player': 'standard', 'hand': None, 'shelf': [], 'revision': 0}


async def read_collection(db, uid):
    row = await (await db.execute('SELECT value FROM bot_state WHERE key = ?',
                                 (f'nora_records:{uid}',))).fetchone()
    return json.loads(row['value']) if row else initial_collection()


async def save(db, key, value):
    await db.execute('INSERT INTO bot_state(key,value) VALUES (?,?) '
                     'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     (key, json.dumps(value)))


async def collection(request):
    async with request.app['db'].connect() as db:
        state = await read_collection(db, request['actor']['id'])
    return web.json_response(state)


async def record_action(request):
    body = await request.json()
    if not isinstance(body, dict):
        raise ValueError('Выбери действие с пластинкой')
    uid = request['actor']['id']
    action = body.get('action')
    async with request.app['db'].connect() as db:
        await db.execute('BEGIN IMMEDIATE')
        registered = await (await db.execute(
            'SELECT 1 FROM nora_game_players WHERE telegram_id = ?', (uid,),
        )).fetchone()
        if not registered:
            raise ValueError('Сначала создай персонажа Норы')
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
    return web.json_response(state)


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
    sent = []
    for recipient in (chat, uid):
        try:
            await request.app['bot'].send_audio(
                recipient, FSInputFile(ASSETS / 'dedzytwo-s1.mp3'),
                title='Музыкальная пластинка «?» (S1)', performer='dedzytwo',
                caption='Старое ≠ бесполезное\nSEASON 1 • BLOODY NORA\nhttps://t.me/thededzzyDJ',
            )
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
