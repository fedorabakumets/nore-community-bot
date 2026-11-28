"""Private, text-only matchmaking for the Mini App. No Telegram chat mirroring."""
from __future__ import annotations

import re
import secrets
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

from aiohttp import web

SCHEMA = """
CREATE TABLE IF NOT EXISTS incognito_queue (
    user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS incognito_sessions (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    touched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS incognito_members (
    user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES incognito_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_incognito_members_session ON incognito_members(session_id);
CREATE TABLE IF NOT EXISTS incognito_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES incognito_sessions(id) ON DELETE CASCADE,
    sender_id INTEGER NOT NULL,
    client_id TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(session_id, sender_id, client_id)
);
CREATE INDEX IF NOT EXISTS idx_incognito_messages_session ON incognito_messages(session_id, id);
"""

QUEUE_TTL = 45
IDLE_TTL = 1800
SESSION_TTL = 86400
MAX_MESSAGES = 1000
MAX_TEXT = 2000


def adult_cutoff():
    today = datetime.now(ZoneInfo('Europe/Moscow')).date()
    try:
        return today.replace(year=today.year - 18)
    except ValueError:
        return today.replace(year=today.year - 18, day=28)


async def one(conn, sql, args=()):
    async with conn.execute(sql, args) as cursor:
        return await cursor.fetchone()


async def purge(conn, now):
    await conn.execute('DELETE FROM incognito_queue WHERE expires_at <= ?', (now,))
    await conn.execute(
        'DELETE FROM incognito_sessions WHERE touched_at <= ? OR created_at <= ? '
        'OR (SELECT COUNT(*) FROM incognito_members m WHERE m.session_id = incognito_sessions.id) != 2',
        (now - IDLE_TTL, now - SESSION_TTL),
    )


async def eligible(conn, uid):
    row = await one(conn, 'SELECT birth_date FROM users WHERE user_id = ?', (uid,))
    try:
        return bool(row and date.fromisoformat(row['birth_date']) <= adult_cutoff())
    except (ValueError, TypeError, KeyError, IndexError):
        return False


async def current_session(conn, uid):
    row = await one(conn, 'SELECT session_id FROM incognito_members WHERE user_id = ?', (uid,))
    return row['session_id'] if row else None


async def enqueue(conn, uid, now, excluded=None):
    if await current_session(conn, uid):
        return
    await conn.execute(
        'INSERT INTO incognito_queue(user_id, expires_at) VALUES (?, ?) '
        'ON CONFLICT(user_id) DO UPDATE SET expires_at = excluded.expires_at',
        (uid, now + QUEUE_TTL),
    )
    async with conn.execute(
        'SELECT q.user_id FROM incognito_queue q JOIN users u ON u.user_id = q.user_id '
        'WHERE q.user_id != ? AND q.user_id != ? AND q.expires_at > ? '
        'AND u.birth_date <= ? '
        'AND NOT EXISTS (SELECT 1 FROM incognito_members m WHERE m.user_id = q.user_id) '
        'ORDER BY RANDOM() LIMIT 20',
        (uid, excluded or uid, now, adult_cutoff().isoformat()),
    ) as cursor:
        candidates = await cursor.fetchall()
    for candidate in candidates:
        other = candidate['user_id']
        if not await eligible(conn, other):
            continue
        sid = secrets.token_urlsafe(24)
        await conn.execute('INSERT INTO incognito_sessions VALUES (?, ?, ?)', (sid, now, now))
        await conn.executemany('INSERT INTO incognito_members VALUES (?, ?)', [(uid, sid), (other, sid)])
        await conn.execute('DELETE FROM incognito_queue WHERE user_id IN (?, ?)', (uid, other))
        break


async def snapshot(conn, uid, after=0):
    sid = await current_session(conn, uid)
    if not sid:
        queued = await one(conn, 'SELECT 1 FROM incognito_queue WHERE user_id = ?', (uid,))
        return {'state': 'searching' if queued else 'idle', 'session': None, 'messages': []}
    async with conn.execute(
        'SELECT id, sender_id, body, created_at FROM incognito_messages '
        'WHERE session_id = ? AND id > ? ORDER BY id LIMIT 100',
        (sid, after),
    ) as cursor:
        rows = await cursor.fetchall()
    messages = [
        {'id': r['id'], 'mine': r['sender_id'] == uid, 'text': r['body'], 'created_at': r['created_at']}
        for r in rows
    ]
    return {'state': 'matched', 'session': sid, 'messages': messages, 'has_more': len(rows) == 100}


async def operate(db, uid, action, data=None, now=None):
    """Serialize matchmaking and membership checks in the same write transaction."""
    now = time.time() if now is None else now
    data = {} if data is None else data
    if not isinstance(data, dict):
        raise ValueError('Некорректный запрос')
    after = data.get('after', 0)
    if type(after) is not int or not 0 <= after <= 2**63 - 1:
        raise ValueError('Некорректный курсор')
    async with db.connect() as conn:
        await conn.execute('BEGIN IMMEDIATE')
        await purge(conn, now)
        sid = await current_session(conn, uid)
        if not await eligible(conn, uid):
            if sid:
                await conn.execute('DELETE FROM incognito_sessions WHERE id = ?', (sid,))
            await conn.execute('DELETE FROM incognito_queue WHERE user_id = ?', (uid,))
            await conn.commit()
            raise PermissionError('Инкогнито доступно с 18 лет')
        if action == 'join':
            await enqueue(conn, uid, now)
        elif action == 'status':
            if not sid:
                queued = await one(conn, 'SELECT 1 FROM incognito_queue WHERE user_id = ?', (uid,))
                if queued:
                    await enqueue(conn, uid, now)
        elif action in {'end', 'next'}:
            # A stale tab must not end a newer conversation.
            if sid != data.get('session'):
                raise ValueError('Диалог уже изменился')
            other = None
            if sid:
                row = await one(
                    conn, 'SELECT user_id FROM incognito_members WHERE session_id = ? AND user_id != ?', (sid, uid),
                )
                other = row['user_id'] if row else None
                await conn.execute('DELETE FROM incognito_sessions WHERE id = ?', (sid,))
            await conn.execute('DELETE FROM incognito_queue WHERE user_id = ?', (uid,))
            if action == 'next':
                await enqueue(conn, uid, now, excluded=other)
            after = 0
        elif action == 'send':
            if not sid or data.get('session') != sid:
                raise ValueError('Диалог завершён')
            body = data.get('text')
            key = data.get('client_id')
            if not isinstance(body, str) or not body.strip() or len(body) > MAX_TEXT:
                raise ValueError('Сообщение должно содержать от 1 до 2000 символов')
            if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', key):
                raise ValueError('Некорректный идентификатор сообщения')
            old = await one(
                conn, 'SELECT id FROM incognito_messages WHERE session_id = ? AND sender_id = ? AND client_id = ?',
                (sid, uid, key),
            )
            if not old:
                recent = await one(
                    conn, 'SELECT MAX(created_at) AS last FROM incognito_messages '
                    'WHERE session_id = ? AND sender_id = ?', (sid, uid),
                )
                if recent['last'] is not None and now - recent['last'] < 0.5:
                    raise ValueError('Не отправляй сообщения так быстро')
                count = await one(conn, 'SELECT COUNT(*) AS n FROM incognito_messages WHERE session_id = ?', (sid,))
                if count['n'] >= MAX_MESSAGES:
                    raise ValueError('Достигнут лимит сообщений этого диалога')
                await conn.execute(
                    'INSERT INTO incognito_messages(session_id, sender_id, client_id, body, created_at) '
                    'VALUES (?, ?, ?, ?, ?)', (sid, uid, key, body.strip(), now),
                )
                await conn.execute('UPDATE incognito_sessions SET touched_at = ? WHERE id = ?', (now, sid))
        else:
            raise ValueError('Неизвестное действие')
        result = await snapshot(conn, uid, after)
        await conn.commit()
        return result


async def endpoint(request):
    action = request.match_info['action']
    try:
        if request.content_length and request.content_length > 16000:
            raise ValueError('Слишком большой запрос')
        data = await request.json()
        result = await operate(request.app['db'], request['actor']['id'], action, data)
    except PermissionError as exc:
        return web.json_response({'error': str(exc)}, status=403)
    except ValueError as exc:
        return web.json_response({'error': str(exc)}, status=400)
    return web.json_response(result)
