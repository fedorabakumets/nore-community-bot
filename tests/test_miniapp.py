import asyncio
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import pytest
from aiohttp import web

from community_bot.database import Database
from community_bot.miniapp import confirm, overview, prepare, protection, submit_application, validate_init_data


def signed(uid=7, date=1000, token='test-only'):
    data = {'auth_date': str(date), 'user': json.dumps({'id': uid, 'first_name': 'Анна'})}
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    data['hash'] = hmac.new(secret, '\n'.join(f'{k}={v}' for k, v in sorted(data.items())).encode(),
                            hashlib.sha256).hexdigest()
    return urlencode(data)


def test_telegram_signature_and_ttl():
    assert validate_init_data(signed(), 'test-only', now=1001)['id'] == 7
    for raw, token, now in [(signed(), 'wrong', 1001), (signed(), 'test-only', 5000),
                            (signed(date=1200), 'test-only', 1000), (signed()+'&user=forged', 'test-only', 1001),
                            ('user=forged', 'test-only', 1000)]:
        with pytest.raises((ValueError, KeyError)):
            validate_init_data(raw, token, now=now)


class Request(dict):
    def __init__(self, db, uid=7, body=None):
        super().__init__(actor={'id': uid, 'first_name': 'Анна'})
        self.app = {'db': db, 'settings': SimpleNamespace(restricted_reputation_threshold=0, timezone='Europe/Moscow',
                                                     is_owner=lambda uid: uid == 99, moderator_ids=frozenset(),
                                                     bot_token='test-only'), 'bot': None}
        self.body = body or {}

    async def json(self):
        return self.body


@pytest.fixture
async def db(tmp_path):
    db = Database(tmp_path / 'mini.db')
    await db.initialize()
    await db.upsert_shop_item('rep_shield', price=12, enabled=1)
    for uid in (7, 8):
        await db.ensure_user(uid, telegram_name='Тест')
        await db.add_cookies(uid, 100, 'test')
    return db


async def test_shop_prepare_never_debits_and_confirmation_is_actor_bound_and_once(db):
    response = await prepare(Request(db, body={'sku': 'rep_shield', 'price': 1, 'user_id': 8}))
    intent = json.loads(response.body)
    assert intent['price'] > 1
    assert (await db.get_user(7))['cookies'] == 100
    assert (await confirm(Request(db, uid=8, body={'token': intent['token']}))).status == 409
    assert (await confirm(Request(db, body={'token': intent['token']}))).status == 200
    assert (await confirm(Request(db, body={'token': intent['token']}))).status == 409
    assert (await db.get_user(7))['cookies'] == 100-intent['price']
    assert (await db.get_user(8))['cookies'] == 100


async def test_overview_exposes_only_allowlisted_own_fields(db, monkeypatch):
    from community_bot import updates

    monkeypatch.setattr(updates, 'UPDATES', (updates.BotUpdate(
        number=900, slug='public-test', title='Статья участникам', summary='Публичное описание',
        details=('Возможности для участников',), staff_details=('INTERNAL_ONLY_SENTINEL',),
    ),))
    request = Request(db)
    request.app['settings'].community_invite_url = 'javascript:alert(1)'
    response = await overview(request)
    data = json.loads(response.body)
    assert data['user']['user_id'] == 7
    assert 'moderator_note' not in data['user']
    assert 'bot_token' not in response.text
    assert 'telegraph_token' not in response.text
    assert 'INTERNAL_ONLY_SENTINEL' not in response.text
    assert data['home']['community_url'] == ''
    assert data['home']['news'][0]['details'] == ['Возможности для участников']


async def test_miniapp_gate_accepts_staff_and_approved_members(db):
    req = Request(db)
    req.path = '/api/profile'
    req.headers = {'Authorization': 'tma '+signed(date=int(time.time()))}
    handler = AsyncMock(return_value=web.json_response({'ok': True}))
    await db.execute("UPDATE users SET profile_name='Анна', birth_date='2000-01-01', hobbies='Кино',"
                     "profile_bio='Описание', avatar_file_id='photo' WHERE user_id=7")
    assert (await protection(req, handler)).status == 403
    await db.set_role(7, 'admin')
    assert (await protection(req, handler)).status == 200
    await db.set_role(7, 'member')
    application_id = await db.create_application(7, {})
    await db.decide_application(application_id, 99, 'approved', None)
    assert (await protection(req, handler)).status == 200
    handler.reset_mock()
    req.headers = {'Authorization': 'tma '+signed(uid=23, date=int(time.time()))}
    assert (await protection(req, handler)).status == 403
    assert await db.get_user(23) is None
    handler.assert_not_awaited()
    req.headers = {}
    assert (await protection(req, handler)).status == 401
    assert (await db.get_user(7))['cookies'] == 100


async def test_web_application_uses_signed_identity_and_existing_review_queue(db):
    bot = SimpleNamespace(send_message=AsyncMock())
    answers = {
        'name': '  Ника ', 'birth_date': '2000-01-01', 'referral': 'Из чата', 'expectations': 'Друзей',
        'bio': 'Люблю музыку <3', 'interview': 'yes', 'user_id': 8, 'ban_version': None,
    }

    async def call(path, handler, body=None, *, signed_in=True):
        req = Request(db, uid=42, body=body)
        req.path = path
        req.headers = {'Authorization': 'tma ' + signed(uid=42, date=int(time.time()))} if signed_in else {}
        req.app.update(settings=SimpleNamespace(**vars(req.app['settings']), reviewers={99}), bot=bot)
        response = await protection(req, handler)
        return response.status, json.loads(response.body)

    assert (await call('/api/application', submit_application, answers, signed_in=False))[0] == 401
    status, home = await call('/api/me', overview)
    assert status == 200 and set(home) == {'onboarding'}
    assert home['onboarding']['status'] == 'form'
    assert await db.get_user(42) is None
    handler = AsyncMock(return_value=web.json_response({'ok': True}))
    for path in ('/api/profile', '/api/profile/avatar', '/api/notices', '/api/nora-game/lobby'):
        assert (await call(path, handler))[0] == 403
    handler.assert_not_awaited()

    for invalid in ({'name': ' '}, {'birth_date': '2025-01-01'}, {'interview': 'no'}, {'bio': 'x' * 1001}):
        assert (await call('/api/application', submit_application, answers | invalid))[0] == 400
    assert await db.get_user(42) is None
    submissions = await asyncio.gather(*[call('/api/application', submit_application, answers) for _ in range(2)])
    assert submissions == [(200, {'status': 'pending'})] * 2
    (row,) = await db.pending_applications()
    assert row['user_id'] == 42
    application = await db.get_application(row['id'])
    assert application['answers']['name'] == 'Ника'
    assert 'user_id' not in application['answers']
    assert (await db.get_user(42))['birth_date'] == '2000-01-01'
    bot.send_message.assert_awaited_once()
    assert bot.send_message.call_args.args[0] == 99
    assert '&lt;3' in bot.send_message.call_args.args[1]
    review = bot.send_message.call_args.kwargs['reply_markup']
    assert review.inline_keyboard[0][0].callback_data == f"application:approve:{row['id']}"
    assert (await call('/api/me', overview))[1] == {'onboarding': {'status': 'pending'}}
    # Approving an existing row restores the same API access as accepting a chat application.
    assert (await call('/api/profile', handler))[0] == 403
    await db.decide_application(row['id'], 99, 'approved', None)
    assert (await call('/api/profile', handler))[0] == 200

    await db.reset_banned_user(42, until=None)
    assert (await call('/api/me', overview))[1] == {'onboarding': {'status': 'blocked'}}
    assert (await call('/api/application', submit_application, answers))[1] == {'status': 'blocked'}
    await db.release_ban_reset(42)
    status, home = await call('/api/me', overview)
    assert status == 200 and home['onboarding']['status'] == 'form'
    assert home['onboarding']['ban_version']
    assert (await call('/api/application', submit_application, answers))[0] == 409


async def test_current_role_badges_enrich_game_views_without_changing_seasonal_catalog(db):
    await db.set_role(7, 'moderator')
    await db.execute("UPDATE users SET profile_name='Имя',birth_date='2000-01-01',"
                     "hobbies='Кино',profile_bio='Петербург',avatar_file_id='photo' WHERE user_id=7")
    await db.create_staff_role('styled', 'Team', 30, prefix_color='blue', prefix_emoji='⭐')
    await db.set_role(8, 'styled')
    req = Request(db)
    req.headers = {'Authorization': 'tma ' + signed(date=int(time.time()))}
    payload = {'players': [{'id': 8, 'name': 'Cached name'}]}
    for path in ('/api/sea', '/api/mafia', '/api/community', '/api/seasonal'):
        req.path = path
        result = await protection(req, AsyncMock(return_value=web.json_response(payload)))
        person = json.loads(result.body)['players'][0]
        if path == '/api/seasonal':
            assert 'prefix' not in person
        else:
            assert person['prefix'] == {'text': 'Team', 'color': 'blue', 'emoji': '⭐'}


async def test_profile_save_is_atomic_validated_and_protects_bot_edits(db):
    from community_bot.miniapp import save_profile
    from community_bot.profile_fields import profile_revision

    revision = profile_revision(await db.get_user(7))
    fields = {'profile_name': 'Мария', 'birth_date': '2000-01-01', 'hobbies': 'Музыка', 'profile_bio': 'Петербург'}
    response = await save_profile(Request(db, body={'fields': fields, 'revision': revision}))
    assert response.status == 200
    user = await db.get_user(7)
    assert all(user[k] == v for k, v in fields.items())
    assert user['bio_auto_warn'] == 2
    assert not user['warnings']
    assert (await db.get_user(8))['birth_date'] is None
    current = profile_revision(user)
    await db.update_profile(7, 'profile_name', 'Изменено в боте')
    assert (await save_profile(Request(db, body={'fields': fields, 'revision': current}))).status == 409
    assert (await db.get_user(7))['profile_name'] == 'Изменено в боте'
    assert (await save_profile(Request(db, body={'fields': fields, 'revision': revision}))).status == 409
    for wrong in [{'age': 25}, {'birth_date': True}, {'birth_date': '2000-02-31'},
                  {'profile_bio': 'x'*281}, {'cookies': 10000},
                  {'reputation': 100}, {'user_id': 8}, {'role': 'owner'}, {'profile_private': 1},
                  {'profile_name': 'Хак', 'birth_date': '2099-01-01'}, {'hobbies': ' '}]:
        with pytest.raises(ValueError):
            await save_profile(Request(db, body={'fields': wrong, 'revision': current}))
    assert (await db.get_user(7))['cookies'] == 100
    assert (await db.get_user(7))['profile_name'] == 'Изменено в боте'


async def test_avatar_upload_uses_telegram_file_id_and_is_visible_to_bot(db):
    from io import BytesIO
    from unittest.mock import AsyncMock

    from PIL import Image

    from community_bot.miniapp import avatar, upload_avatar
    from community_bot.profile_fields import profile_revision

    raw = BytesIO()
    Image.new('RGB', (800, 600), 'red').save(raw, 'PNG')
    req = Request(db)
    req.headers = {'X-Profile-Revision': profile_revision(await db.get_user(7))}
    req.content_type = 'image/png'
    req.clone = lambda **kwargs: req
    req.read = AsyncMock(return_value=raw.getvalue())
    bot = SimpleNamespace(send_photo=AsyncMock(return_value=SimpleNamespace(
        photo=[SimpleNamespace(file_id='telegram-avatar-file-id')],
    )))
    req.app['bot'] = bot
    assert (await upload_avatar(req)).status == 200
    user = await db.get_user(7)
    assert user['avatar_file_id'] == 'telegram-avatar-file-id'
    assert user['avatar_media_type'] == 'photo'
    assert bot.send_photo.call_args.args[0] == 7
    assert (await db.get_user(8))['avatar_file_id'] is None
    # A stale browser must not overwrite a photo changed in the bot.
    bot.send_photo.reset_mock()
    assert (await upload_avatar(req)).status == 409
    bot.send_photo.assert_not_awaited()
    req.headers = {'X-Profile-Revision': profile_revision(user)}
    req.read = AsyncMock(return_value=b'<svg>not a photograph</svg>')
    assert (await upload_avatar(req)).status == 400
    bot.send_photo.assert_not_awaited()

    async def download(file_id, destination):
        assert file_id == 'telegram-avatar-file-id'
        destination.write(raw.getvalue())
    bot.download = download
    result = await avatar(req)
    assert result.status == 200
    assert result.content_type == 'image/jpeg'
    assert Image.open(BytesIO(result.body)).size == (800, 600)


async def test_avatar_upload_accepts_40_mb_and_completes_profile(db):
    from io import BytesIO

    from aiohttp.test_utils import make_mocked_request
    from PIL import Image

    from community_bot.miniapp import create_app, upload_avatar
    from community_bot.profile_fields import profile_revision
    from community_bot.profile_fill import profile_fill_percent

    await db.set_role(7, 'admin')
    await db.execute("UPDATE users SET profile_name='Анна', birth_date='2000-01-01', "
                     "hobbies='Кино', profile_bio='Описание' WHERE user_id=7")
    user = await db.get_user(7)
    assert profile_fill_percent(user) == 80

    bot = SimpleNamespace(send_photo=AsyncMock(return_value=SimpleNamespace(
        photo=[SimpleNamespace(file_id='large-photo-file-id')],
    )))
    bot._nora_admin_capture = True
    app = create_app(db, Request(db).app['settings'], bot)
    png = BytesIO()
    Image.new('RGB', (3700, 3700), 'red').save(png, 'PNG', compress_level=0)
    # Pad the valid PNG to exercise the exact byte boundary.
    limit = 40 * 1024 * 1024
    raw = png.getvalue().ljust(limit, b'\0')
    assert 20 * 1024 * 1024 + 1024 < png.tell() <= len(raw) == limit
    png.close()
    headers = {
        'Authorization': 'tma ' + signed(date=int(time.time())),
        'Content-Type': 'image/png',
        'X-Profile-Revision': profile_revision(user),
    }

    def request_for(*chunks):
        payload = SimpleNamespace(readany=AsyncMock(side_effect=[*chunks, b'']),
                                  set_read_chunk_size=lambda size: None)
        return make_mocked_request('POST', '/api/profile/avatar', headers=headers, app=app,
                                   client_max_size=app._client_max_size, payload=payload)

    rejected = await protection(request_for(raw, b'!'), upload_avatar)
    assert rejected.status == 413
    assert '40 МБ' in json.loads(rejected.body)['error']
    bot.send_photo.assert_not_awaited()
    assert (await db.get_user(7))['avatar_file_id'] is None

    accepted = await protection(request_for(raw), upload_avatar)
    assert accepted.status == 200
    bot.send_photo.assert_awaited_once()
    photo = bot.send_photo.call_args.args[1].data
    assert len(photo) < 10 * 1024 * 1024
    with Image.open(BytesIO(photo)) as jpeg:
        assert jpeg.format == 'JPEG'
        assert jpeg.size == (1600, 1600)
    user = await db.get_user(7)
    assert user['avatar_file_id'] == 'large-photo-file-id'
    assert profile_fill_percent(user) == 100


async def test_profile_stats_use_the_bot_reputation_rules(db):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from community_bot.domain import reputation_tier

    req = Request(db)
    response = json.loads((await overview(req)).body)
    tier = reputation_tier(response['user']['reputation'])
    assert response['profile']['daily_actions'] == tier.daily_actions
    assert response['profile']['discount'] == tier.discount
    assert response['profile']['reputation_cap'] == 69
    today = datetime.now(ZoneInfo('Europe/Moscow')).date()
    await db.apply_reputation(7, 8, 5, today)
    response = json.loads((await overview(req)).body)
    assert response['profile']['actions_used'] == 1
    assert response['profile']['actions_left'] == 0
