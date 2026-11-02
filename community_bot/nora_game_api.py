"""Private registration for the standalone NORA game."""
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
            outfit = dict(saved) if saved else None
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
    if not isinstance(body, dict) or any(body.get(key) not in allowed for key, allowed in choices.items()):
        raise ValueError('Выбери одежду из доступных вариантов')
    async with request.app['db'].connect() as db:
        await db.execute('BEGIN IMMEDIATE')
        row = await (await db.execute(
            'SELECT 1 FROM nora_game_players WHERE telegram_id = ?', (request['actor']['id'],),
        )).fetchone()
        if not row:
            raise ValueError('Сначала зарегистрируй игровой ник')
        await db.execute(
            'INSERT INTO nora_game_outfits (telegram_id, shirt, pants, shoes) VALUES (?, ?, ?, ?) '
            'ON CONFLICT(telegram_id) DO UPDATE SET shirt=excluded.shirt, '
            'pants=excluded.pants, shoes=excluded.shoes',
            (request['actor']['id'], body['shirt'], body['pants'], body['shoes']),
        )
        await db.commit()
    return web.json_response({'outfit': {key: body[key] for key in choices}})
