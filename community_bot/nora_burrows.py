"""Furniture, paid accessories and private invitations in the NORA world."""
import json
import re
import time
from pathlib import Path
from uuid import uuid4

from aiohttp import web

from community_bot.database import utcnow

ITEMS = json.loads((Path(__file__).with_name('web') / 'nora-burrow-items.json').read_text(encoding='utf-8'))
CATALOG = {item['id']: item for item in ITEMS}
ROOM = re.compile(r'burrow:([A-Za-z]{3,16})\Z')
SLOTS = 8


async def inventory(db, uid):
    row = await (await db.execute('SELECT value FROM bot_state WHERE key=?', (f'burrow:{uid}',))).fetchone()
    return json.loads(row['value']) if row else {
        'owned': [], 'wear': None, 'layout': {}, 'record': None, 'lamp': True,
    }


class Visits:
    def __init__(self):
        self.notes = {}
        self.passes = {}
        self.sets = {}
        self.bursts = {}

    def prune(self):
        now = time.monotonic()
        for key in [key for key, note in self.notes.items() if note['until'] <= now]:
            del self.notes[key]
        for key in [key for key, until in self.passes.items() if until <= now]:
            del self.passes[key]

    def inbox(self, nickname):
        self.prune()
        return [{key: note[key] for key in ('id', 'kind', 'other')} for note in self.notes.values()
                if note['to'] == nickname]

    def note(self, kind, recipient, other):
        self.prune()
        for note in self.notes.values():
            if (note['kind'], note['to'], note['other']) == (kind, recipient, other):
                return
        if kind in ('request', 'invite') and sum(n['other'] == other for n in self.notes.values()) >= 30:
            raise ValueError('Дождись ответа на предыдущие приглашения.')
        token = uuid4().hex
        self.notes[token] = dict(id=token, kind=kind, to=recipient, other=other, until=time.monotonic()+600)

    def answer(self, nickname, token, accept):
        self.prune()
        note = self.notes.get(token)
        if not note or note['to'] != nickname or note['kind'] not in ('request', 'invite'):
            raise ValueError('Приглашение уже закрыто.')
        other = note['other']
        if accept:
            guest, host = (other, nickname) if note['kind'] == 'request' else (nickname, other)
            self.note('allowed', guest, host)
            self.passes[guest, host] = time.monotonic() + 600
        else:
            self.note('declined', other, nickname)
        del self.notes[token]
        return other if accept and note['kind'] == 'invite' else None

    def allowed(self, nickname, host):
        return nickname == host or self.passes.get((nickname, host), 0) > time.monotonic()

    def tv(self, app, host, active):
        from community_bot.nora_cinema import Cinema
        presence = app['nora_lobby']
        now = time.monotonic()
        for name in list(self.sets):
            if name != host and not self.sets[name].occupants(presence, now):
                del self.sets[name]
        if active and host not in self.sets:
            self.sets[host] = Cinema(app['nora_cinema'].storage, room=f'burrow:{host}')
        if active:
            self.sets[host].clips = app['nora_cinema'].clips
        if not active:
            self.sets.pop(host, None)


def public(state):
    return {key: state[key] for key in ('layout', 'lamp', 'record')}


async def api(request):
    uid = request['actor']['id']
    visits = request.app['nora_visits']
    presence = request.app['nora_lobby']
    body = await request.json() if request.method == 'POST' else {}
    if not isinstance(body, dict):
        raise ValueError('Проверь действие.')
    action = body.get('action')
    async with request.app['db'].connect() as db:
        if request.method == 'POST':
            await db.execute('BEGIN IMMEDIATE')
        row = await (await db.execute('SELECT nickname FROM nora_game_players WHERE telegram_id=?', (uid,))).fetchone()
        if not row:
            raise ValueError('Сначала создай персонажа.')
        me = row['nickname']
        if request.query.get('directory') == '1':
            query = request.query.get('q', '')[:16]
            offset = min(1000000, max(0, int(request.query.get('offset', 0))))
            rows = await (await db.execute(
                'SELECT nickname FROM nora_game_players WHERE nickname != ? AND instr(lower(nickname),lower(?))>0 '
                'ORDER BY nickname LIMIT 41 OFFSET ?', (me, query, offset))).fetchall()
            online = {p['nickname'] for seen, _, p in presence.values() if time.monotonic()-seen < 8}
            return web.json_response({'players': [{'name': r[0], 'online': r[0] in online} for r in rows[:40]],
                                      'more': len(rows) > 40})
        target = body.get('target') or request.query.get('host') or me
        if not isinstance(target, str) or not ROOM.fullmatch(f'burrow:{target}'):
            raise ValueError('Проверь игровой ник.')
        if action in ('invite', 'request'):
            found = await (await db.execute('SELECT nickname FROM nora_game_players WHERE nickname=?',
                                            (target,))).fetchone()
            if not found or found[0] == me:
                raise ValueError('Выбери другого игрока.')
            visits.note(action, found[0], me)
            return web.json_response({'ok': True})
        if action in ('accept', 'decline', 'dismiss'):
            token = body.get('id')
            if not isinstance(token, str):
                raise ValueError('Проверь приглашение.')
            if action == 'dismiss':
                note = visits.notes.get(token)
                if note and note['to'] == me:
                    del visits.notes[token]
                return web.json_response({'ok': True})
            return web.json_response({'enter': visits.answer(me, token, action == 'accept')})
        if not visits.allowed(me, target):
            raise ValueError('Сначала получи приглашение хозяина.')
        host = await (await db.execute('SELECT telegram_id FROM nora_game_players WHERE nickname=?',
                                       (target,))).fetchone()
        state = await inventory(db, host[0])
        if action == 'burst':
            pose = presence.get(uid)
            if (not pose or time.monotonic()-pose[0] >= 8 or pose[2].get('room') != f'burrow:{target}'
                    or 'confetti' not in state['layout'].values()):
                raise ValueError('Сначала подойди к шкатулке в норе.')
            now = time.monotonic()
            if now - visits.bursts.get(target, -10) < 3:
                raise ValueError('Шкатулка снова заводится.')
            visits.bursts = {k: v for k, v in visits.bursts.items() if now-v < 4}
            visits.bursts[target] = now
            return web.json_response({'ok': True})
        if action:
            if target != me:
                raise ValueError('Обустраивать нору может хозяин.')
            await change(db, uid, state, action, body)
            await db.execute('INSERT INTO bot_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE '
                             'SET value=excluded.value', (f'burrow:{uid}', json.dumps(state)))
            await db.commit()
        visits.tv(request.app, target, 'tv' in state['layout'].values())
        if target != me:
            return web.json_response({'home': public(state), 'host': target})
        balance = await (await db.execute('SELECT cookies FROM users WHERE user_id=?', (uid,))).fetchone()
        return web.json_response({'home': public(state), 'host': me, 'inventory': state, 'balance': balance[0]})


async def change(db, uid, state, action, body):
    item = body.get('item')
    if not isinstance(item, str) or item not in CATALOG:
        raise ValueError('Выбери предмет из каталога.')
    info = CATALOG[item]
    owned = state['owned']
    if action == 'buy':
        if item in owned:
            return
        price, now = info['price'], utcnow()
        debit = await db.execute('UPDATE users SET cookies=cookies-?,updated_at=? WHERE user_id=? AND cookies>=?',
                                 (price, now, uid, price))
        if debit.rowcount != 1:
            raise ValueError('Недостаточно печенек.')
        await db.execute('INSERT INTO transactions(user_id,amount,kind,details,created_at) VALUES(?,?,?,?,?)',
                         (uid, -price, 'shop', f'nora_burrow_{item}', now))
        owned.append(item)
    elif item not in owned:
        raise ValueError('Сначала купи этот предмет.')
    elif action in ('wear', 'remove') and info['group'] == 'wear':
        state['wear'] = item if action == 'wear' else None
    elif action == 'place' and info['group'] == 'decor':
        slot = body.get('slot')
        if slot is not None and (type(slot) is not int or not 0 <= slot < SLOTS):
            raise ValueError('Выбери место в комнате.')
        layout = {k: v for k, v in state['layout'].items() if v != item}
        if slot is not None:
            layout[str(slot)] = item
        state['layout'] = layout
        if 'hifi' not in layout.values():
            state['record'] = None
    elif action in ('play', 'stop') and info['group'] == 'record' and 'hifi' in state['layout'].values():
        state['record'] = item if action == 'play' else None
    elif action == 'light' and item == 'lamp' and item in state['layout'].values():
        state['lamp'] = body.get('lit') is True
    else:
        raise ValueError('Это действие недоступно.')
