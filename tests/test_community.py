import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest
from aiohttp import web
from PIL import Image

from community_bot.community_api import day_window, directory, presence, status
from community_bot.database import Database
from community_bot.social_profiles import avatar, heartbeat


@pytest.fixture
async def env(tmp_path):
    db = Database(tmp_path / 'community.db')
    await db.initialize()
    await db.create_staff_role('event', 'Ивент-менеджер', 30, [])
    await db.create_staff_role('helper', 'Хелпер', 20, [])
    for uid in range(1, 65):
        await db.ensure_user(uid, f'person{uid}', f'Участник {uid}')
        await db.execute("UPDATE users SET avatar_file_id='photo',moderator_note='PRIVATE' WHERE user_id=?", (uid,))
        if uid < 64:
            await db.record_activity(uid, -100, False)
    await db.set_role(2, 'admin')
    await db.set_role(3, 'event')
    await db.set_role(4, 'helper')
    await db.update_profile(5, 'profile_name', 'Алёна Норская')
    settings = SimpleNamespace(is_owner=lambda uid: uid == 1, moderator_ids={6}, community_chat_id=-100)
    return SimpleNamespace(db=db, settings=settings)


class Request(dict):
    def __init__(self, env, uid=5, query=None, target='2'):
        super().__init__(actor={'id': uid})
        self.app = {'db': env.db, 'settings': env.settings, 'bot': None}
        self.query = query or {}
        self.match_info = {'user_id': target}


async def test_directory_unicode_pagination_known_members_and_private_fields(env):
    first = json.loads((await directory(Request(env))).body)
    assert first['total'] == 63 and len(first['items']) == 50 and first['next_offset'] == 50
    second = json.loads((await directory(Request(env, query={'offset': '50'}))).body)
    assert len(second['items']) == 13 and second['next_offset'] is None
    assert not set(p['id'] for p in first['items']) & set(p['id'] for p in second['items'])
    for q in ('АЛЕНА', 'НОРСК', '@person5'):
        found = json.loads((await directory(Request(env, query={'q': q}))).body)
        assert 5 in [p['id'] for p in found['items']]
    assert 'PRIVATE' not in json.dumps(first) and 'avatar_file_id' not in json.dumps(first)
    with pytest.raises(web.HTTPBadRequest):
        await directory(Request(env, query={'offset': '-1'}))
    assert not json.loads((await directory(Request(env, query={'q': "%'; DROP TABLE users;--"}))).body)['items']


async def test_board_today_top_five_actual_yesterday_reward_no_new_credit(env):
    today, yesterday = day_window()
    await env.db.execute('DELETE FROM daily_scores')
    for uid in range(1, 16):
        await env.db.execute('INSERT INTO daily_scores VALUES(?,?,?,?)', (uid, yesterday.isoformat(), -100, 20))
    for uid in range(16, 24):
        await env.db.execute('INSERT INTO daily_scores VALUES(?,?,?,?)', (uid, today.isoformat(), -100, 100-uid))
    await env.db.execute('INSERT INTO daily_scores VALUES(?,?,?,?)', (17, yesterday.isoformat(), -999, 999))
    await env.db.execute('INSERT INTO daily_scores VALUES(?,?,?,?)', (18, yesterday.isoformat(), -100, 0))
    initial = json.loads((await status(Request(env))).body)
    assert [p['id'] for p in initial['leaders']] == [16, 17, 18, 19, 20]
    assert initial['winner'] is None and not initial['awarded']
    # Recipient comes from ledger, even if ranking was corrected later.
    await env.db.add_cookies(3, 1, 'daily_chat', yesterday.isoformat())
    for _ in range(2):
        result = json.loads((await status(Request(env))).body)
        assert result['winner']['id'] == 3 and result['day'] == today.isoformat()
        assert result['winner_day'] == yesterday.isoformat()
    assert (await env.db.get_user(3))['cookies'] == 1
    assert [p['id'] for p in result['staff']] == [1, 2, 6, 3, 4]


async def test_blocks_privacy_presence_and_thumbnail(env):
    await env.db.execute("UPDATE users SET profile_private=1 WHERE user_id=2")
    found = json.loads((await directory(Request(env, query={'q': '@person2'}))).body)
    assert not next(p for p in found['items'] if p['id'] == 2)['has_avatar']
    await heartbeat(env.db, 3, 'a' * 20, 1, True)
    await heartbeat(env.db, 2, 'b' * 20, 1, True)
    online = json.loads((await presence(Request(env))).body)
    assert online['3']['online'] and not online['2']['online']
    await env.db.execute("INSERT INTO mini_friend_blocks VALUES(3,5,'token','now')")
    assert '3' not in json.loads((await presence(Request(env))).body)
    assert 3 not in [p['id'] for p in json.loads(
        (await directory(Request(env, query={'q': '@person3'}))).body)['items']]
    req = Request(env, query={'size': 'thumb'}, target='4')
    raw = BytesIO()
    Image.new('RGB', (500, 300), 'red').save(raw, 'JPEG')

    class Bot:
        async def download(self, file_id, destination):
            destination.write(raw.getvalue())

    req.app['bot'] = Bot()
    response = await avatar(req)
    with Image.open(BytesIO(response.body)) as photo:
        assert photo.size == (96, 58)


def test_midnight_is_moscow_not_utc():
    before, previous = day_window(datetime(2026, 10, 28, 20, 59, tzinfo=UTC))
    after, yesterday = day_window(datetime(2026, 10, 28, 21, 0, tzinfo=UTC))
    assert after == before + timedelta(days=1)
    assert yesterday == before and previous == before - timedelta(days=1)


async def test_bot_accounts_excluded_from_directory_board_and_direct_profiles(env):
    await env.db.ensure_user(20, 'WeatherBot', 'Weather')
    await env.db.ensure_user(21, None, 'Another Bot')
    await env.db.set_bot_state('telegram_is_bot:21', '1')
    found = json.loads((await directory(Request(env))).body)
    assert not {20, 21} & {p['id'] for p in found['items']}
    board = json.loads((await status(Request(env))).body)
    assert not {20, 21} & {p['id'] for p in board['leaders']}
    with pytest.raises(web.HTTPNotFound):
        await avatar(Request(env, target='21'))


async def test_bot_identity_from_telegram_and_friend_lists(env):
    from aiogram.types import User

    from community_bot.friends_api import snapshot
    from community_bot.helpers import register_telegram_user

    await register_telegram_user(env.db, User(id=22, is_bot=True, first_name='Robot'))
    await env.db.execute(
        "INSERT INTO mini_friendships VALUES(5,22,5,'accepted','token','now','now',0,9999999999)"
    )
    result = await snapshot(env.db, env.settings, 5)
    assert 22 not in [item['id'] for item in result['friends']]
    assert await env.db.get_bot_state('telegram_is_bot:22') == '1'
