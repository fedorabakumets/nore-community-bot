"""Private, text-only matchmaking for the Mini App. No Telegram chat mirroring."""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from contextlib import suppress
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from aiohttp import web

SCHEMA = """
CREATE TABLE IF NOT EXISTS incognito_queue (
    user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    expires_at REAL NOT NULL,
    avoid_user_id INTEGER
);
CREATE TABLE IF NOT EXISTS incognito_sessions (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    touched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS incognito_members (
    user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES incognito_sessions(id) ON DELETE CASCADE,
    typing_until REAL NOT NULL DEFAULT 0,
    seen_at REAL NOT NULL DEFAULT 0
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
CREATE TABLE IF NOT EXISTS incognito_blocks (
    user_id INTEGER NOT NULL,
    other_id INTEGER NOT NULL,
    PRIMARY KEY(user_id, other_id)
);
"""

logger = logging.getLogger(__name__)

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


async def enqueue(conn, uid, now, excluded=None, allowed=None):
    if await current_session(conn, uid):
        return
    await conn.execute(
        'INSERT INTO incognito_queue(user_id, expires_at, avoid_user_id) VALUES (?, ?, ?) '
        'ON CONFLICT(user_id) DO UPDATE SET expires_at = excluded.expires_at, '
        'avoid_user_id = COALESCE(excluded.avoid_user_id, incognito_queue.avoid_user_id)',
        (uid, now + QUEUE_TTL, excluded),
    )
    own_queue = await one(conn, 'SELECT avoid_user_id FROM incognito_queue WHERE user_id = ?', (uid,))
    async with conn.execute(
        'SELECT q.user_id FROM incognito_queue q JOIN users u ON u.user_id = q.user_id '
        'WHERE q.user_id != ? AND q.user_id != ? AND q.expires_at > ? '
        'AND u.birth_date <= ? AND (q.avoid_user_id IS NULL OR q.avoid_user_id != ?) '
        'AND NOT EXISTS (SELECT 1 FROM incognito_members m WHERE m.user_id = q.user_id) '
        'AND NOT EXISTS (SELECT 1 FROM incognito_blocks b WHERE '
        '(b.user_id = ? AND b.other_id = q.user_id) OR (b.other_id = ? AND b.user_id = q.user_id)) '
        'ORDER BY RANDOM() LIMIT 20',
        (uid, own_queue['avoid_user_id'] or uid, now, adult_cutoff().isoformat(), uid, uid, uid),
    ) as cursor:
        candidates = await cursor.fetchall()
    for candidate in candidates:
        other = candidate['user_id']
        if not await eligible(conn, other) or (allowed and not await allowed(other)):
            continue
        sid = secrets.token_urlsafe(24)
        await conn.execute('INSERT INTO incognito_sessions VALUES (?, ?, ?)', (sid, now, now))
        await conn.executemany(
            'INSERT INTO incognito_members(user_id, session_id, seen_at) VALUES (?, ?, ?)',
            [(uid, sid, now), (other, sid, now)],
        )
        await conn.execute('DELETE FROM incognito_queue WHERE user_id IN (?, ?)', (uid, other))
        break


async def snapshot(conn, uid, after=0, now=0):
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
    peer = await one(conn, 'SELECT typing_until, seen_at FROM incognito_members '
                     'WHERE session_id = ? AND user_id != ?', (sid, uid))
    return {'state': 'matched', 'session': sid, 'messages': messages, 'has_more': len(rows) == 100,
            'typing': bool(peer and peer['typing_until'] > now),
            'online': bool(peer and peer['seen_at'] > now - 15)}


async def operate(db, uid, action, data=None, now=None, allowed=None):
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
        if sid:
            peer = await one(conn, 'SELECT user_id FROM incognito_members WHERE session_id = ? AND user_id != ?',
                             (sid, uid))
            if not peer or not await eligible(conn, peer['user_id']) or (allowed and not await allowed(peer['user_id'])):
                await conn.execute('DELETE FROM incognito_sessions WHERE id = ?', (sid,))
                sid = None
            else:
                await conn.execute('UPDATE incognito_members SET seen_at = ? WHERE user_id = ?', (now, uid))
        if action == 'join':
            await enqueue(conn, uid, now, allowed=allowed)
        elif action == 'status':
            if not sid:
                queued = await one(conn, 'SELECT 1 FROM incognito_queue WHERE user_id = ?', (uid,))
                if queued:
                    await enqueue(conn, uid, now, allowed=allowed)
        elif action == 'typing':
            if not sid or data.get('session') != sid:
                raise ValueError('Диалог завершён')
            await conn.execute('UPDATE incognito_members SET typing_until = ? WHERE user_id = ?', (now + 4, uid))
        elif action in {'end', 'next', 'block', 'report'}:
            # A stale tab must not end a newer conversation.
            if sid != data.get('session'):
                raise ValueError('Диалог уже изменился')
            other = None
            if sid:
                row = await one(
                    conn, 'SELECT user_id FROM incognito_members WHERE session_id = ? AND user_id != ?', (sid, uid),
                )
                other = row['user_id'] if row else None
                if other and action in {'block', 'report'}:
                    await conn.execute('INSERT OR IGNORE INTO incognito_blocks VALUES (?, ?)', (uid, other))
                if other and action == 'report':
                    async with conn.execute(
                        'SELECT body, sender_id FROM incognito_messages WHERE session_id = ? '
                        'ORDER BY id DESC LIMIT 12', (sid,),
                    ) as cursor:
                        evidence = await cursor.fetchall()
                    excerpt = '\n'.join(('Я: ' if r['sender_id'] == uid else 'Собеседник: ') + r['body']
                                        for r in reversed(evidence))[-4000:]
                    await conn.execute(
                        'INSERT INTO reports(reporter_id, target_id, chat_id, message_id, text, reason, created_at) '
                        'VALUES (?, ?, NULL, NULL, ?, ?, ?)',
                        (uid, other, excerpt, 'Инкогнито: жалоба на собеседника', datetime.now(UTC).isoformat()),
                    )
                await conn.execute('DELETE FROM incognito_sessions WHERE id = ?', (sid,))
            elif action in {'block', 'report'}:
                raise ValueError('Диалог завершён')
            await conn.execute('DELETE FROM incognito_queue WHERE user_id = ?', (uid,))
            if action == 'next':
                await enqueue(conn, uid, now, excluded=other, allowed=allowed)
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
                await conn.execute('UPDATE incognito_members SET typing_until = 0 WHERE user_id = ?', (uid,))
        else:
            raise ValueError('Неизвестное действие')
        result = await snapshot(conn, uid, after, now)
        await conn.commit()
        return result


async def endpoint(request):
    action = request.match_info['action']
    try:
        if request.content_length is None or request.content_length > 16000:
            raise ValueError('Слишком большой запрос')
        data = await request.json()
        from community_bot.access import private_allowed
        from community_bot.profile_fill import profile_is_complete

        db, settings = request.app['db'], request.app['settings']

        async def allowed(uid):
            user = await db.get_user(uid)
            return bool(user and user.get('city') and profile_is_complete(user)
                        and await private_allowed(db, settings, uid))

        result = await operate(db, request['actor']['id'], action, data, allowed=allowed)
    except PermissionError as exc:
        return web.json_response({'error': str(exc)}, status=403)
    except ValueError as exc:
        return web.json_response({'error': str(exc)}, status=400)
    return web.json_response(result)


async def cleanup_context(app):
    async def worker():
        while True:
            try:
                async with app['db'].connect() as conn:
                    await conn.execute('BEGIN IMMEDIATE')
                    await purge(conn, time.time())
                    await conn.commit()
            except Exception:
                logger.exception('Incognito cleanup failed')
            await asyncio.sleep(60)

    task = asyncio.create_task(worker())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
