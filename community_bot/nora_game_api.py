"""Private registration for the standalone NORA game."""
import json
import re
import sqlite3

from aiohttp import web

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


async def status(request):
    async with request.app['db'].connect() as db:
        row = await (await db.execute(
            'SELECT nickname FROM nora_game_players WHERE telegram_id = ?',
            (request['actor']['id'],),
        )).fetchone()
    outfit = None
    if row:
        async with request.app['db'].connect() as db:
            saved = await (await db.execute(
                'SELECT shirt, pants, shoes FROM nora_game_outfits WHERE telegram_id = ?',
                (request['actor']['id'],),
            )).fetchone()
            outfit = {**dict(saved), **await _appearance(db, request['actor']['id'])} if saved else None
    return web.json_response({'nickname': row['nickname'] if row else None, 'outfit': outfit})


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
