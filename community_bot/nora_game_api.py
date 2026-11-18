"""Private registration for the standalone NORA game."""
import asyncio
import json
import logging
import math
import re
import sqlite3
import time

from aiohttp import WSMsgType, web

from community_bot import music_api, nora_burrows, nora_observatory
from community_bot.database import utcnow

logger = logging.getLogger(__name__)

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
            if wear := (await nora_burrows.inventory(db, telegram_id))['wear']:
                outfit['wear'] = wear
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


async def stroke_companion(request):
    db = request.app['db']
    if not await db.feature_enabled('tamagotchi'):
        return web.json_response({'ok': False, 'message': 'Действия питомца временно отключены.'})
    ok, message = await db.stroke_pet(request['actor']['id'])
    return web.json_response({'ok': ok, 'message': message})


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
CINEMA_ROOM = "cinema"
LOBBY_BOUNDS = {'x': (-16.35, 16.35), 'z': (-11.35, 11.35), 'heading': (-math.pi, math.pi)}
# Ground offset plus the ordinary apex and, with wings, the 6.8-speed second launch.
LOBBY_HEIGHT = .8
LOBBY_WING_HEIGHT = 2.56


async def settle_lobby_record(app):
    """Settle disconnected owners and finished records even without active clients."""
    async with app['db'].connect() as db:
        deck = await music_api.read_lobby_deck(db)
        if not deck.get('record'):
            return
        await db.execute('BEGIN IMMEDIATE')
        deck = await music_api.read_lobby_deck(db)
        await music_api.settle_lobby_deck(db, deck, app)
        await db.commit()


async def lobby_record_lifecycle(app):
    async def run():
        while True:
            try:
                await settle_lobby_record(app)
            except Exception:
                logger.exception('Lobby record settlement failed')
            await asyncio.sleep(1)

    task = asyncio.create_task(run(), name='nora-lobby-record')
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def lobby(request):
    return web.json_response(await lobby_snapshot(request.app, request['actor']['id'], await request.json()))


async def lobby_snapshot(app, user_id, body, profile=None):
    if not isinstance(body, dict):
        raise ValueError('Проверь данные игрока')
    session = body.get('session')
    if not isinstance(session, str) or not re.fullmatch(r'[a-f0-9-]{36}', session):
        raise ValueError('Проверь данные сессии')
    presence = app['nora_lobby']
    cinema = app.get('nora_cinema')
    now = time.monotonic()
    expired = [(key, sid) for key, (seen, sid, _) in presence.items() if now - seen >= LOBBY_TTL]
    for key, _ in expired:
        del presence[key]
    for key, expired_session in expired:
        await music_api.return_departed_record(app['db'], key, expired_session)
    current = presence.get(user_id)
    if body.get('leave') is True:
        if current and current[1] == session:
            del presence[user_id]
            if cinema and current[2].get('room') == CINEMA_ROOM:
                cinema.refresh(presence, now)
            await music_api.return_departed_record(app['db'], user_id, session)
        return {'players': []}
    room = body.get('room')
    in_memory = room == nora_observatory.ROOM
    in_cinema = room == CINEMA_ROOM and cinema is not None
    home = nora_burrows.ROOM.fullmatch(room) if isinstance(room, str) else None
    if room is not None and not (in_memory or in_cinema or home):
        raise ValueError('Проверь локацию игрока')
    bounds = LOBBY_BOUNDS
    if in_memory:
        limits = nora_observatory.LAYOUT['bounds']
        bounds = {**bounds, 'x': (-limits['x'], limits['x']), 'z': (-limits['z'], limits['z'])}
    if home:
        bounds = {**bounds, 'x': (-4.25, 4.25), 'z': (-4.55, 4.55)}
    if in_cinema:
        from community_bot.nora_cinema import LAYOUT, SEATS

        bounds = {**bounds, **LAYOUT['bounds']}
        requested_seat = body.get('seat')
        if requested_seat is not None and (type(requested_seat) is not int or not 0 <= requested_seat < len(SEATS)):
            raise ValueError('Проверь номер места')
    pose = {}
    for key, (minimum, maximum) in bounds.items():
        value = body.get(key)
        if type(value) not in (int, float) or not minimum <= value <= maximum:
            raise ValueError('Проверь координаты игрока')
        pose[key] = value

    supplied_profile = profile is not None
    if supplied_profile:
        equipped = profile['outfit'].get('wings') if profile['outfit'] else None
    elif current and current[1] == session:
        profile = current[2]
    else:
        profile = await _player_profile(app['db'], user_id)
        if not profile['nickname'] or not profile['outfit']:
            raise ValueError('Сначала создай персонажа')
    # Only the persisted equipment can authorize the higher replicated jump.
    if not supplied_profile:
        async with app['db'].connect() as db:
            equipped = (await _wings(db, user_id))['equipped']
            wear = (await nora_burrows.inventory(db, user_id))['wear']
            profile = {**profile, 'outfit': dict(profile['outfit'] or {})}
            if wear:
                profile['outfit']['wear'] = wear
            else:
                profile['outfit'].pop('wear', None)
    if not profile['nickname'] or not profile['outfit']:
        raise ValueError('Сначала создай персонажа')
    visits = app.get('nora_visits')
    if home and (not visits or not visits.allowed(profile['nickname'], home[1])):
        raise ValueError('Сначала получи приглашение хозяина.')
    height = body.get('y')
    maximum = LOBBY_WING_HEIGHT if equipped else LOBBY_HEIGHT
    minimum = 0
    if home:
        maximum += 3.5  # Room furniture can be stood on.
    if in_memory:
        minimum, maximum = limits['minY'], limits['maxY']
    if type(height) not in (int, float) or not minimum <= height <= maximum:
        raise ValueError('Проверь высоту прыжка')
    pose['y'] = height
    for key in ('grounded', 'sprinting', 'boosting'):
        if key in body:
            if type(body[key]) is not bool:
                raise ValueError('Проверь данные игрока')
            pose[key] = body[key]
    if pose.get('boosting') and (not equipped or in_memory or in_cinema):
        pose['boosting'] = False
    outfit = dict(profile['outfit'])
    if equipped:
        outfit['wings'] = equipped
    else:
        outfit.pop('wings', None)
    profile = {'nickname': profile['nickname'], 'outfit': outfit}
    now = time.monotonic()
    challenge = None
    if room:
        pose['room'] = room
    if in_memory:
        interaction = body.get('interaction')
        if interaction is not None and (
            not isinstance(interaction, dict)
            or not isinstance(interaction.get('id'), str)
            or interaction['id'] not in nora_observatory.LAYOUT['relics']
            or type(interaction.get('serial')) is not int
            or not 0 < interaction['serial'] <= 1_000_000
        ):
            raise ValueError('Проверь действие в воспоминании')
        challenge = await nora_observatory.progress(app, user_id, session, pose, now, interaction)
        if challenge['reset']:
            x, z = nora_observatory.SAFE[challenge['checkpoint']]
            pose.update(x=x, y=.017, z=z, grounded=True, sprinting=False)
    else:
        attempts = app.get('nora_observatory')
        if attempts and user_id in attempts and attempts[user_id].session == session:
            del attempts[user_id]
    current = presence.get(user_id)
    was_in_cinema = current and current[2].get('room') == CINEMA_ROOM
    seat = None
    if in_cinema:
        if not was_in_cinema:
            cinema.refresh(presence, now)
        seat = cinema.apply_seat(presence, user_id, current, session, pose, requested_seat, now)
    previous_room = current[2].get('room') if current else None
    if home and home[1] != profile['nickname']:
        visits.passes[profile['nickname'], home[1]] = now + 600
        if previous_room != room:
            for note in visits.inbox(profile['nickname']):
                if note['kind'] == 'allowed' and note['other'] == home[1]:
                    visits.notes.pop(note['id'], None)
    if visits and previous_room and previous_room != room and previous_room.startswith('burrow:'):
        visits.passes.pop((profile['nickname'], previous_room[7:]), None)
    presence[user_id] = (now, session, {**profile, **pose})
    if in_cinema:
        cinema_state = {
            'seat': seat, 'requestedSeat': requested_seat, 'occupied': sorted(cinema.occupied(presence, now, user_id)),
            **cinema.snapshot(presence, user_id, body.get('cinema'), now),
        }
    elif cinema and was_in_cinema:
        cinema.refresh(presence, now)
    others = [
        (seen, player) for key, (seen, _, player) in presence.items()
        if key != user_id and now - seen < LOBBY_TTL and player.get('room') == room
    ]
    others.sort(key=lambda entry: (entry[1]['x'] - pose['x']) ** 2 + (entry[1]['z'] - pose['z']) ** 2)
    return {
        'time': now * 1000,
        'players': [{**player, 'time': seen * 1000} for seen, player in others[:20]],
        **({'room': room} if room else {}),
        **({'challenge': challenge} if in_memory else {}),
        **({'cinema': cinema_state} if in_cinema else {}),
        **({'cinema': visits.sets[home[1]].snapshot(presence, user_id, body.get('cinema'), now)}
           if home and home[1] in visits.sets else {}),
        **({'burst': visits.bursts[home[1]]} if home and now-visits.bursts.get(home[1], -10) < 2 else {}),
    }


async def lobby_socket(request):
    # Browser WebSockets cannot set Authorization. Authenticate the first frame;
    # initData never appears in a URL, access log or response.
    from community_bot.access import private_allowed
    from community_bot.miniapp import validate_init_data
    from community_bot.profile_fill import profile_is_complete

    socket = web.WebSocketResponse(heartbeat=10, max_msg_size=16384, receive_timeout=10)
    await socket.prepare(request)
    session = None
    user_id = None
    try:
        credentials = await socket.receive_json(timeout=5)
        user = validate_init_data(credentials.get('auth', ''), request.app['settings'].bot_token)
        user_id = user['id']
        checked = -float('inf')
        refreshed = -float('inf')
        profile = None
        async for message in socket:
            if message.type != WSMsgType.TEXT:
                break
            now = time.monotonic()
            if now - checked >= 5:
                # Also enforce initData expiry and role revocation on open sockets.
                validate_init_data(credentials.get('auth', ''), request.app['settings'].bot_token)
                db = request.app['db']
                if not await private_allowed(db, request.app['settings'], user_id):
                    raise ValueError('Доступ к миниапке закрыт')
                if not profile_is_complete(await db.get_user(user_id) or {}):
                    raise ValueError('Заполни профиль на 100%')
                checked = now
            if now - refreshed >= 1:
                profile = await _player_profile(request.app['db'], user_id, private=True)
                refreshed = now
            body = json.loads(message.data)
            payload = await lobby_snapshot(request.app, user_id, body, profile)
            session = body['session']
            await socket.send_json(payload)
            if body.get('leave') is True:
                break
    except (ValueError, KeyError, TypeError, AttributeError, asyncio.TimeoutError):
        await socket.close(code=1008, message=b'Lobby session ended')
    finally:
        if session is not None:
            current = request.app['nora_lobby'].get(user_id)
            # A cinema visitor may continue on the HTTP fallback with the same session.
            # Explicit leave still releases immediately, and stale seats expire with presence.
            if not current or current[2].get('room') != CINEMA_ROOM:
                await lobby_snapshot(request.app, user_id, {'session': session, 'leave': True})
        await socket.close()
    return socket
