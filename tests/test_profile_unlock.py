import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import CallbackQuery, User
from aiohttp import web

from community_bot.access import ProfileAccessMiddleware
from community_bot.database import Database
from community_bot.miniapp import protection
from community_bot.profile_fields import profile_revision


@pytest.fixture
async def db(tmp_path):
    db = Database(tmp_path/'unlock.db')
    await db.initialize()
    await db.ensure_user(7, telegram_name='Анна')
    return db


async def fill(db):
    for field, value in {'profile_name':'Анна','age':25,'hobbies':'Музыка','profile_bio':'Петербург',
                         'avatar_file_id':'photo'}.items():
        await db.update_profile(7, field, value)


async def test_reward_once_across_concurrent_edits_and_database_restart(db):
    await fill(db)
    assert (await db.get_user(7))['cookies'] == 10
    await db.update_profile(7, 'profile_bio', '')
    await db.update_profile(7, 'profile_bio', 'Новое описание')
    results = await asyncio.gather(*(db.reward_complete_profile(7) for _ in range(8)))
    assert not any(results)
    restarted = Database(db.path)
    await restarted.initialize()
    await restarted.ensure_user(7, telegram_name='Анна')
    assert (await restarted.get_user(7))['cookies'] == 10
    rows = await db.fetchall("SELECT * FROM transactions WHERE kind='profile_complete'")
    assert len(rows) == 1 and rows[0]['amount'] == 10


async def test_first_completion_through_atomic_miniapp_editor(db):
    await db.update_profile(7, 'avatar_file_id', 'photo')
    revision = profile_revision(await db.get_user(7))
    assert await db.save_self_profile(7, {'profile_name':'Анна','age':25,'hobbies':'Музыка',
                                        'profile_bio':'Описание'}, revision)
    assert (await db.get_user(7))['cookies'] == 10
    assert not await db.save_self_profile(7, {'age':26}, revision)
    assert (await db.get_user(7))['cookies'] == 10


async def test_existing_full_profile_rewarded_only_when_user_returns(db):
    await db.execute("UPDATE users SET profile_name='Анна', age=25, hobbies='Музыка', "
                     "profile_bio='Описание', avatar_file_id='photo' WHERE user_id=7")
    await db.initialize()
    assert (await db.get_user(7))['cookies'] == 0
    await db.ensure_user(7, telegram_name='Анна')
    await db.ensure_user(7, telegram_name='Анна')
    assert (await db.get_user(7))['cookies'] == 10


async def test_api_gate_denies_old_confirmations_until_complete(db):
    import hashlib
    import hmac
    from urllib.parse import urlencode

    payload = {'auth_date':str(int(time.time())), 'user':json.dumps({'id':7,'first_name':'Анна'})}
    secret = hmac.new(b'WebAppData', b'test-only', hashlib.sha256).digest()
    payload['hash'] = hmac.new(secret, '\n'.join(f'{k}={v}' for k,v in sorted(payload.items())).encode(),
                               hashlib.sha256).hexdigest()
    class Request(dict):
        pass
    request = Request()
    request.app = {'db':db, 'settings':SimpleNamespace(bot_token='test-only',is_owner=lambda _:True)}
    request.headers = {'Authorization':'tma '+urlencode(payload)}
    handler = AsyncMock(return_value=web.json_response({'ok':True}))
    for path in ('/api/shop/prepare','/api/shop/confirm','/api/events/join'):
        request.path = path
        assert (await protection(request,handler)).status == 403
    handler.assert_not_awaited()
    await fill(db)
    assert (await protection(request,handler)).status == 200
    await db.update_profile(7,'profile_bio','')
    assert (await protection(request,handler)).status == 403


async def test_telegram_old_shop_button_also_requires_complete_profile(db, monkeypatch):
    callback = CallbackQuery(id='test', chat_instance='test', from_user=User(id=7,is_bot=False,first_name='Анна'),
                             data='shop:pay:old-token')
    monkeypatch.setattr(CallbackQuery,'answer',AsyncMock())
    handler = AsyncMock()
    await ProfileAccessMiddleware()(handler,callback,{'db':db})
    handler.assert_not_awaited()
    await fill(db)
    await ProfileAccessMiddleware()(handler,callback,{'db':db})
    handler.assert_awaited_once()
