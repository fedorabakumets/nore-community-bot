import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from community_bot import nora_burrows as homes
from community_bot import nora_game_api as game
from community_bot import nora_game_chat as chat
from community_bot.database import Database
from community_bot.nora_cinema import Cinema, cinema_api


class Request(dict):
    def __init__(self, app, uid, body=None, **query):
        super().__init__(actor={'id': uid})
        self.app = app
        self.query = query
        self.content_length = 0
        self.method = 'GET' if body is None else 'POST'
        self.json = AsyncMock(return_value=body)


@pytest.mark.asyncio
async def test_burrow_shop_visits_chat_and_private_screen(tmp_path):
    db = Database(tmp_path / 'world.db')
    await db.initialize()
    visits = homes.Visits()
    app = dict(db=db, nora_visits=visits, nora_lobby={}, nora_cinema=Cinema(None))
    alice, bob, eve = 101, 102, 103
    for uid, name in [(alice, 'Alice'), (bob, 'Bobby'), (eve, 'Evelyn')]:
        await db.ensure_user(uid)
        await db.add_cookies(uid, 550, 'test')
        await game.register(Request(app, uid, {'nickname': name}))
        await game.save_outfit(Request(app, uid, {'shirt': 'white', 'pants': 'blue_slim', 'shoes': 'red_air'}))

    async def call(uid, body=None, **query):
        return json.loads((await homes.api(Request(app, uid, body, **query))).text)

    async def act(uid, action, **fields):
        return await call(uid, dict(action=action, **fields))

    assert [r['name'] for r in (await call(alice, directory='1'))['players']] == ['Bobby', 'Evelyn']
    await asyncio.gather(act(alice, 'buy', item='tv'), act(alice, 'buy', item='tv'))
    assert (await call(alice))['balance'] == 50
    with pytest.raises(ValueError, match='печенек'):
        await act(alice, 'buy', item='hifi')
    await act(alice, 'buy', item='beret')
    await act(alice, 'wear', item='beret')
    assert (await game._player_profile(db, alice))['outfit']['wear'] == 'beret'
    await act(alice, 'place', item='tv', slot=4)
    db2 = Database(db.path)
    async with db2.connect() as conn:
        assert (await homes.inventory(conn, alice))['layout'] == {'4': 'tv'}
        assert (await (await conn.execute("SELECT count(*) FROM transactions WHERE details='nora_burrow_tv'"))
                .fetchone())[0] == 1
    with pytest.raises(ValueError):
        await call(bob, host='Alice')
    room = 'burrow:Alice'
    sessions = {uid: str(uuid4()) for uid in [alice, bob, eve]}

    async def move(uid, dest):
        return await game.lobby_snapshot(app, uid, dict(session=sessions[uid], x=0, z=0, y=.017, heading=0, room=dest))

    with pytest.raises(ValueError):
        await move(bob, room)
    await act(bob, 'request', target='Alice')
    note, = visits.inbox('Alice')
    assert visits.inbox('Evelyn') == []
    with pytest.raises(ValueError):
        await act(eve, 'accept', id=note['id'])
    await act(alice, 'decline', id=note['id'])
    assert visits.inbox('Bobby')[0]['kind'] == 'declined'
    await act(bob, 'request', target='Alice')
    await act(alice, 'accept', id=visits.inbox('Alice')[0]['id'])
    assert (await call(bob, host='Alice')) == {'home': {'layout': {'4': 'tv'}, 'lamp': True, 'record': None},
                                               'host': 'Alice'}
    with pytest.raises(ValueError):
        await act(bob, 'place', target='Alice', item='tv', slot=None)
    await move(alice, room)
    seen = await move(bob, room)
    assert [p['nickname'] for p in seen['players']] == ['Alice']
    assert (await move(eve, 'burrow:Evelyn'))['players'] == []
    assert chat._room(app['nora_lobby'], bob, room)[0] == room
    with pytest.raises(ValueError):
        chat._room(app['nora_lobby'], eve, room)
    command = dict(room=room, action='start', url='https://example.com/test.mp4', revision='')
    await cinema_api(Request(app, alice, dict(command, session=sessions[alice])))
    show = (await move(bob, room))['cinema']['show']
    assert show['source'] == command['url'] and not show['host']
    with pytest.raises(ValueError):
        await cinema_api(Request(app, bob, dict(command, session=sessions[bob])))
    assert 'cinema' not in await move(eve, 'burrow:Evelyn')
    await move(bob, None)
    with pytest.raises(ValueError):
        await move(bob, room)
    await act(alice, 'invite', target='Evelyn')
    invitation, = visits.inbox('Evelyn')
    assert (await act(eve, 'accept', id=invitation['id']))['enter'] == 'Alice'
    await move(eve, room)
    await act(alice, 'place', item='tv', slot=None)
    assert 'cinema' not in await move(eve, room)
    await db.add_cookies(alice, 1000, 'test')
    for item in ('hifi', 'lamp', 'confetti', 'vinyl_s1'):
        await act(alice, 'buy', item=item)
    for slot, item in enumerate(('hifi', 'lamp', 'confetti')):
        await act(alice, 'place', item=item, slot=slot)
    await act(alice, 'light', item='lamp', lit=False)
    await act(alice, 'play', item='vinyl_s1')
    shared = (await call(eve, host='Alice'))['home']
    assert shared['record'] == 'vinyl_s1' and not shared['lamp']
    await act(eve, 'burst', target='Alice')
    assert 'burst' in await move(alice, room)
    with pytest.raises(ValueError):
        await act(eve, 'burst', target='Alice')
    await act(alice, 'place', item='lamp', slot=0)
    assert (await call(eve, host='Alice'))['home']['record'] is None
    assert (await call(alice))['inventory']['layout'] == {'0': 'lamp', '2': 'confetti'}


def test_burrow_records_match_bundled_audio():
    media = Path(__file__).resolve().parents[1] / 'assets' / 'game'
    vinyl = [item for item in homes.ITEMS if item['group'] == 'record']
    assert len(vinyl) == len({item['name'] for item in vinyl}) == 5
    assert {item['author'] for item in vinyl} == {'dedzytwo'}
    assert {Path(item['media']).name for item in vinyl} == {p.name for p in media.glob('dedzytwo-*.mp3')}
    assert all(50 <= item['price'] <= 500 for item in homes.ITEMS)
