"""Private registration for the standalone NORA game."""
import json
import math
import re
import sqlite3
import time

from aiohttp import web

from community_bot.database import utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS nora_game_players (
    telegram_id INTEGER PRIMARY KEY,
    nickname TEXT NOT NULL COLLATE NOCASE UNIQUE,
    CHECK(length(nickname) BETWEEN 3 AND 16 AND nickname NOT GLOB '*[^A-Za-z]*')
);
CREATE TABLE IF NOT EXISTS nora_game_outfits (
    telegram_id INTEGER PRIMARY KEY REFERENCES nora_game_players(telegram_id),
    shirt TEXT NOT NULL CHECK(shirt IN ('white', 'gray', 'burgundy')),
    pants TEXT NOT NULL CHECK(pants IN ('blue_slim', 'gray_slim', 'burgundy_wide')),
    shoes TEXT NOT NULL CHECK(shoes IN ('white_stripes', 'black_stripes', 'red_air'))
);
"""

APPEARANCE_CHOICES = {
    'gender': {'male', 'female'},
    'hairstyle': {'crop', 'bob', 'ponytail'},
    'hair_color': {'black', 'chestnut', 'brown', 'blonde', 'ginger', 'ash', 'rose', 'blue'},
    'eye_color': {'brown', 'hazel', 'green', 'blue', 'gray', 'violet'},
}
APPEARANCE_DEFAULTS = {
    'gender': 'male', 'hairstyle': 'crop', 'hair_color': 'black', 'eye_color': 'brown',
}


async def _appearance(db, telegram_id):
    row = await (await db.execute(
        'SELECT value FROM bot_state WHERE key = ?', (f'nora_game_appearance:{telegram_id}',),
    )).fetchone()
    try:
        saved = json.loads(row['value']) if row else {}
    except (ValueError, TypeError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    return {
        key: saved[key] if isinstance(saved.get(key), str) and saved[key] in allowed
        else APPEARANCE_DEFAULTS[key]
        for key, allowed in APPEARANCE_CHOICES.items()
    }


WING_IDS = frozenset({'raven', 'flame', 'frost'})
WING_PRICE = 50


async def _wings(db, telegram_id):
    row = await (await db.execute(
        'SELECT value FROM bot_state WHERE key = ?', (f'nora_game_wings:{telegram_id}',),
    )).fetchone()
    if row:
        return json.loads(row['value'])
    return {'owned': [], 'equipped': None}


async def _player_profile(database, telegram_id, *, private=False):
    async with database.connect() as db:
        row = await (await db.execute(
            'SELECT p.nickname, o.shirt, o.pants, o.shoes FROM nora_game_players AS p '
            'LEFT JOIN nora_game_outfits AS o USING (telegram_id) WHERE p.telegram_id = ?',
            (telegram_id,),
        )).fetchone()
        outfit = None
        if row and row['shirt'] is not None:
            outfit = {key: row[key] for key in ('shirt', 'pants', 'shoes')}
            outfit.update(await _appearance(db, telegram_id))
        wings = await _wings(db, telegram_id) if private and row else None
        if outfit and wings and wings['equipped']:
            outfit['wings'] = wings['equipped']
    profile = {'nickname': row['nickname'] if row else None, 'outfit': outfit}
    if wings and wings['owned']:
        profile['wings'] = wings
    return profile


async def status(request):
    return web.json_response(await _player_profile(request.app['db'], request['actor']['id'], private=True))


async def companion(request):
    """Owner-only view of the existing pet, including settled expedition state."""
    from community_bot.cabinet_api import pet_data

    return web.json_response({'pet': await pet_data(request.app['db'], {'user_id': request['actor']['id']})})


async def register(request):
    body = await request.json()
    nickname = body.get('nickname') if isinstance(body, dict) else None
    if not isinstance(nickname, str) or not re.fullmatch(r'[A-Za-z]{3,16}', nickname):
        raise ValueError('Никнейм: от 3 до 16 латинских букв без пробелов')
    async with request.app['db'].connect() as db:
        await db.execute('BEGIN IMMEDIATE')
        row = await (await db.execute(
            'SELECT nickname FROM nora_game_players WHERE telegram_id = ?',
            (request['actor']['id'],),
        )).fetchone()
        if row:
            return web.json_response({'nickname': row['nickname']})
        try:
            await db.execute('INSERT INTO nora_game_players (telegram_id, nickname) VALUES (?, ?)',
                             (request['actor']['id'], nickname))
            await db.commit()
        except sqlite3.IntegrityError:
            return web.json_response({'error': 'Этот никнейм уже занят'}, status=409)
    return web.json_response({'nickname': nickname})


async def save_outfit(request):
    body = await request.json()
    choices = {
        'shirt': {'white', 'gray', 'burgundy'},
        'pants': {'blue_slim', 'gray_slim', 'burgundy_wide'},
        'shoes': {'white_stripes', 'black_stripes', 'red_air'},
    }
    if not isinstance(body, dict) or any(
        not isinstance(body.get(key), str) or body[key] not in allowed
        for key, allowed in choices.items()
    ):
        raise ValueError('Выбери одежду из доступных вариантов')
    if any(key in body and (not isinstance(body[key], str) or body[key] not in allowed)
           for key, allowed in APPEARANCE_CHOICES.items()):
        raise ValueError('Выбери внешность из доступных вариантов')
    async with request.app['db'].connect() as db:
        await db.execute('BEGIN IMMEDIATE')
        row = await (await db.execute(
            'SELECT 1 FROM nora_game_players WHERE telegram_id = ?', (request['actor']['id'],),
        )).fetchone()
        if not row:
            raise ValueError('Сначала зарегистрируй игровой ник')
        appearance = await _appearance(db, request['actor']['id'])
        appearance.update({key: body[key] for key in APPEARANCE_CHOICES if key in body})
        await db.execute(
            'INSERT INTO nora_game_outfits (telegram_id, shirt, pants, shoes) VALUES (?, ?, ?, ?) '
            'ON CONFLICT(telegram_id) DO UPDATE SET shirt=excluded.shirt, '
            'pants=excluded.pants, shoes=excluded.shoes',
            (request['actor']['id'], body['shirt'], body['pants'], body['shoes']),
        )
        await db.execute(
            'INSERT INTO bot_state(key, value) VALUES (?, ?) '
            'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            (f"nora_game_appearance:{request['actor']['id']}", json.dumps(appearance)),
        )
        await db.commit()
    return web.json_response({'outfit': {**{key: body[key] for key in choices}, **appearance}})


async def change_wings(request):
    body = await request.json()
    if not isinstance(body, dict):
        raise ValueError('Выбери крылья')
    action, item = body.get('action'), body.get('item')
    if action not in ('buy', 'equip') or (
        not (action == 'equip' and 'item' in body and item is None)
        and (not isinstance(item, str) or item not in WING_IDS)
    ):
        raise ValueError('Выбери крылья')

    user_id = request['actor']['id']
    async with request.app['db'].connect() as db:
        await db.execute('BEGIN IMMEDIATE')
        player = await (await db.execute(
            'SELECT 1 FROM nora_game_players WHERE telegram_id = ?', (user_id,),
        )).fetchone()
        if not player:
            raise ValueError('Сначала зарегистрируй игровой ник')
        wings = await _wings(db, user_id)
        if action == 'buy':
            if item in wings['owned']:
                return web.json_response(wings)
            now = utcnow()
            debit = await db.execute(
                'UPDATE users SET cookies = cookies - ?, updated_at = ? WHERE user_id = ? AND cookies >= ?',
                (WING_PRICE, now, user_id, WING_PRICE),
            )
            if debit.rowcount != 1:
                return web.json_response({'error': 'Недостаточно печенек.'}, status=409)
            await db.execute(
                'INSERT INTO transactions(user_id, amount, kind, details, created_at) VALUES (?, ?, ?, ?, ?)',
                (user_id, -WING_PRICE, 'shop', f'nora_wings_{item}', now),
            )
            wings['owned'].append(item)
        else:
            if item is not None and item not in wings['owned']:
                raise ValueError('Сначала купи эти крылья')
            wings['equipped'] = item

        await db.execute(
            'INSERT INTO bot_state(key, value) VALUES (?, ?) '
            'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            (f'nora_game_wings:{user_id}', json.dumps(wings)),
        )
        await db.commit()
    return web.json_response(wings)


# Lobby presence expires automatically when a client closes or loses its connection.
LOBBY_TTL = 8
LOBBY_BOUNDS = {'x': (-16.35, 16.35), 'z': (-11.35, 11.35), 'heading': (-math.pi, math.pi)}
# Ground offset plus the ordinary apex and, with wings, the 6.8-speed second launch.
LOBBY_HEIGHT = .8
LOBBY_WING_HEIGHT = 2.56


async def lobby(request):
    body = await request.json()
    if not isinstance(body, dict):
        raise ValueError('Проверь данные игрока')
    session = body.get('session')
    if not isinstance(session, str) or not re.fullmatch(r'[a-f0-9-]{36}', session):
        raise ValueError('Проверь данные сессии')
    presence = request.app['nora_lobby']
    user_id = request['actor']['id']
    now = time.monotonic()
    for key, (seen, _, _) in tuple(presence.items()):
        if now - seen >= LOBBY_TTL:
            del presence[key]
    current = presence.get(user_id)
    if body.get('leave') is True:
        if current and current[1] == session:
            del presence[user_id]
        return web.json_response({'players': []})
    pose = {}
    for key, (minimum, maximum) in LOBBY_BOUNDS.items():
        value = body.get(key)
        if type(value) not in (int, float) or not minimum <= value <= maximum:
            raise ValueError('Проверь координаты игрока')
        pose[key] = value

    if current and current[1] == session:
        profile = current[2]
    else:
        profile = await _player_profile(request.app['db'], user_id)
        if not profile['nickname'] or not profile['outfit']:
            raise ValueError('Сначала создай персонажа')
    # Only the persisted equipment can authorize the higher replicated jump.
    async with request.app['db'].connect() as db:
        equipped = (await _wings(db, user_id))['equipped']
    height = body.get('y')
    maximum = LOBBY_WING_HEIGHT if equipped else LOBBY_HEIGHT
    if type(height) not in (int, float) or not 0 <= height <= maximum:
        raise ValueError('Проверь высоту прыжка')
    pose['y'] = height
    outfit = dict(profile['outfit'])
    if equipped:
        outfit['wings'] = equipped
    else:
        outfit.pop('wings', None)
    profile = {'nickname': profile['nickname'], 'outfit': outfit}
    presence[user_id] = (time.monotonic(), session, {**profile, **pose})
    others = [player for key, (_, _, player) in presence.items() if key != user_id]
    others.sort(key=lambda player: (player['x'] - pose['x']) ** 2 + (player['z'] - pose['z']) ** 2)
    return web.json_response({'players': others[:20]})
