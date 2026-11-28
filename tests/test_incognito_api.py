import asyncio

import pytest

from community_bot.database import Database
from community_bot.incognito_api import IDLE_TTL, QUEUE_TTL, SCHEMA, operate


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / 'incognito.sqlite')
    async with database.connect() as conn:
        await conn.executescript(
            'CREATE TABLE users(user_id INTEGER PRIMARY KEY, birth_date TEXT);'
            'CREATE TABLE reports(reporter_id INTEGER, target_id INTEGER, chat_id INTEGER, '
            'message_id INTEGER, text TEXT, reason TEXT, created_at TEXT);' + SCHEMA,
        )
        await conn.executemany('INSERT INTO users VALUES (?, ?)', [
            (1, '1990-01-01'), (2, '1991-01-01'), (3, '1992-01-01'),
            (4, '1993-01-01'), (5, '2099-01-01'), (6, None),
        ])
        await conn.commit()
    return database


@pytest.mark.asyncio
async def test_pair_and_private_messages(db):
    assert (await operate(db, 1, 'join', now=100))['state'] == 'searching'
    paired = await operate(db, 2, 'join', now=101)
    sid = paired['session']
    assert sid and (await operate(db, 1, 'status', now=102))['session'] == sid
    data = {'session': sid, 'client_id': 'abcdefghijklmnop', 'text': 'hello'}
    sent = await operate(db, 1, 'send', data, now=103)
    assert sent['messages'][0]['mine'] is True
    await operate(db, 1, 'send', data, now=103.1)
    received = await operate(db, 2, 'status', now=104)
    assert len(received['messages']) == 1
    assert received['messages'][0]['mine'] is False
    assert set(received['messages'][0]) == {'id', 'mine', 'text', 'created_at'}
    assert received['messages'][0]['text'] == 'hello'
    assert (await operate(db, 3, 'status', now=105))['messages'] == []
    with pytest.raises(ValueError):
        await operate(db, 3, 'send', data, now=105)
    with pytest.raises(ValueError):
        await operate(db, 3, 'end', {'session': sid}, now=105)
    assert (await operate(db, 2, 'status', now=105))['session'] == sid


@pytest.mark.asyncio
async def test_next_excludes_previous_and_erases_history(db):
    await operate(db, 1, 'join', now=100)
    sid = (await operate(db, 2, 'join', now=101))['session']
    await operate(db, 1, 'send', {
        'session': sid, 'client_id': 'abcdefghijklmnop', 'text': 'private',
    }, now=102)
    assert (await operate(db, 1, 'next', {'session': sid}, now=103))['state'] == 'searching'
    assert (await operate(db, 2, 'status', now=104))['state'] == 'idle'
    assert (await operate(db, 2, 'join', now=105))['state'] == 'searching'
    assert (await operate(db, 1, 'status', now=106))['state'] == 'searching'
    await operate(db, 3, 'join', now=107)
    async with db.connect() as conn:
        async with conn.execute('SELECT COUNT(*) FROM incognito_messages') as cursor:
            assert (await cursor.fetchone())[0] == 0
    with pytest.raises(ValueError):
        await operate(db, 1, 'end', {'session': sid}, now=108)


@pytest.mark.asyncio
async def test_concurrent_joins_only_create_disjoint_pairs(db):
    await asyncio.gather(*(operate(db, uid, 'join', now=100) for uid in (1, 2, 3, 4)))
    states = await asyncio.gather(*(operate(db, uid, 'status', now=101) for uid in (1, 2, 3, 4)))
    sessions = [state['session'] for state in states]
    assert None not in sessions
    assert len(set(sessions)) == 2
    assert all(sessions.count(sid) == 2 for sid in sessions)


@pytest.mark.asyncio
async def test_expiration_and_age_gate(db):
    for uid in (5, 6):
        with pytest.raises(PermissionError):
            await operate(db, uid, 'join', now=100)
    await operate(db, 1, 'join', now=100)
    assert (await operate(db, 1, 'status', now=100 + QUEUE_TTL))['state'] == 'idle'
    await operate(db, 1, 'join', now=200)
    await operate(db, 2, 'join', now=201)
    assert (await operate(db, 1, 'status', now=201 + IDLE_TTL))['state'] == 'idle'


@pytest.mark.asyncio
async def test_report_after_peer_leaves_and_never_rematch(db):
    await operate(db, 1, 'join', now=100)
    sid = (await operate(db, 2, 'join', now=101))['session']
    await operate(db, 2, 'send', {
        'session': sid, 'client_id': 'abcdefghijklmnop', 'text': 'evidence',
    }, now=102)
    await operate(db, 2, 'end', {'session': sid}, now=103)
    ended = await operate(db, 1, 'status', now=104)
    assert ended['recent'] == sid and ended['messages'] == []
    with pytest.raises(ValueError):
        await operate(db, 3, 'report', {'session': sid}, now=105)
    await operate(db, 1, 'report', {'session': sid}, now=106)
    async with db.connect() as conn:
        async with conn.execute('SELECT reporter_id, target_id, text FROM reports') as cursor:
            rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]['reporter_id'] == 1 and rows[0]['target_id'] == 2
    assert 'evidence' in rows[0]['text']
    await operate(db, 1, 'join', now=107)
    assert (await operate(db, 2, 'join', now=108))['state'] == 'searching'


@pytest.mark.asyncio
async def test_typing_and_presence(db):
    await operate(db, 1, 'join', now=100)
    sid = (await operate(db, 2, 'join', now=101))['session']
    await operate(db, 1, 'typing', {'session': sid}, now=102)
    assert (await operate(db, 2, 'status', now=103))['typing']
    assert not (await operate(db, 2, 'status', now=107))['typing']
