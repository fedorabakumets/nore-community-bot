import asyncio
import json
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from community_bot import nora_burrows as homes
from community_bot import nora_game_api as game
from community_bot import nora_game_chat as chat
from community_bot.database import Database
from community_bot.nora_cinema import Cinema, cinema_api
from community_bot.social_likes import COUNT_PREFIX


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
    app = dict(db=db, nora_visits=visits, nora_lobby={}, nora_cinema=Cinema(None),
               nora_game_chat=chat.GameChat(None, 0))
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

    async def move(uid, dest, x=0, z=0):
        return await game.lobby_snapshot(app, uid, dict(session=sessions[uid], x=x, z=z, y=.017, heading=0, room=dest))

    with pytest.raises(ValueError):
        await move(bob, room)
    with pytest.raises(ValueError, match='двери'):
        await act(bob, 'knock', target='Alice')
    await move(bob, None, homes.TRAIL['first'], homes.TRAIL['doorZ'] + 1)
    await act(bob, 'knock', target='Alice')
    note, = visits.inbox('Alice')
    assert visits.inbox('Evelyn') == []
    assert json.loads((await chat.feed(Request(app, alice))).text)['visits'] == [note]
    assert json.loads((await chat.feed(Request(app, eve))).text)['visits'] == []
    with pytest.raises(ValueError):
        await act(eve, 'accept', id=note['id'])
    await act(alice, 'decline', id=note['id'])
    assert visits.inbox('Bobby')[0]['kind'] == 'declined'
    await act(bob, 'knock', target='Alice')
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


@pytest.mark.asyncio
async def test_trail_activity_ranking_and_private_statistics(tmp_path, monkeypatch):
    now = 1_800_000_000
    monkeypatch.setattr(homes, 'time', SimpleNamespace(time=lambda: now, monotonic=monotonic))
    db = Database(tmp_path / 'trail.db')
    await db.initialize()
    settings = SimpleNamespace(community_chat_id=-101)
    app = dict(db=db, settings=settings, nora_visits=homes.Visits(), nora_lobby={})
    for uid in range(1, 6):
        await db.ensure_user(uid)
    for uid, name in [(1, 'Alice'), (2, 'Bobby'), (3, 'Cathy')]:
        await game.register(Request(app, uid, {'nickname': name}))
    await db.execute("INSERT INTO nora_game_players VALUES (4, 'Legacy')")
    await db.execute("UPDATE users SET profile_private=1 WHERE user_id=3")
    await db.set_bot_state(f'{COUNT_PREFIX}1', '6')
    await db.set_bot_state(f'{COUNT_PREFIX}2', '12')
    await db.set_bot_state(f'{COUNT_PREFIX}3', '99')
    await db.add_cookies(2, 24, 'test')
    await db.record_activity(2, settings.community_chat_id)
    await db.record_activity(2, -999)
    await db.set_bot_state('burrow:2', json.dumps(
        {'owned': ['lamp'], 'wear': None, 'layout': {'0': 'lamp'}, 'record': None, 'lamp': False},
    ))

    async def houses_list():
        return json.loads((await homes.api(Request(app, 1, trail='1'))).text)['houses']

    assert await houses_list() == [
        {'name': 'Bobby', 'likes': 12, 'cookies': 24, 'messages': 1},
        {'name': 'Alice', 'likes': 6, 'cookies': 0, 'messages': 0},
        {'name': 'Legacy', 'likes': 0, 'cookies': 0, 'messages': 0},
        {'name': 'Cathy', 'likes': None, 'cookies': None, 'messages': None},
    ]
    with pytest.raises(ValueError, match='персонажа'):
        await homes.api(Request(app, 5, trail='1'))
    await db.set_bot_state(f'{COUNT_PREFIX}1', '13')
    assert [h['name'] for h in await houses_list()][:2] == ['Alice', 'Bobby']
    now += homes.HOUSE_TTL
    assert len(await houses_list()) == 4
    now += 1
    assert await houses_list() == []
    await game.status(Request(app, 2))  # Reopening the game is activity even before walking.
    db = app['db'] = Database(db.path)
    assert [h['name'] for h in await houses_list()] == ['Bobby']
    assert json.loads((await homes.api(Request(app, 2))).text)['home']['layout'] == {'0': 'lamp'}

    await game.save_outfit(Request(app, 2, {'shirt': 'white', 'pants': 'blue_slim', 'shoes': 'red_air'}))
    pose = dict(session=str(uuid4()), x=homes.TRAIL['first'], z=0, y=.017, heading=0)
    now += 120
    with pytest.raises(ValueError, match='координаты'):
        await game.lobby_snapshot(app, 2, dict(pose, z=8))
    await game.lobby_snapshot(app, 2, pose)
    now += homes.HOUSE_TTL - 1
    assert [h['name'] for h in await houses_list()] == ['Bobby']
    now += 2
    assert await houses_list() == []


def test_burrow_records_match_bundled_audio():
    media = Path(__file__).resolve().parents[1] / 'assets' / 'game'
    vinyl = [item for item in homes.ITEMS if item['group'] == 'record']
    assert len(vinyl) == len({item['name'] for item in vinyl}) == 5
    assert {item['author'] for item in vinyl} == {'dedzytwo'}
    assert {Path(item['media']).name for item in vinyl} == {p.name for p in media.glob('dedzytwo-*.mp3')}
    assert all(50 <= item['price'] <= 500 for item in homes.ITEMS)
