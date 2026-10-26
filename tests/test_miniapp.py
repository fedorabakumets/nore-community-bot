import hashlib
import hmac
import json
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from community_bot.database import Database
from community_bot.miniapp import confirm, overview, prepare, validate_init_data


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


async def test_overview_exposes_only_allowlisted_own_fields(db):
    response = await overview(Request(db))
    data = json.loads(response.body)
    assert data['user']['user_id'] == 7
    assert 'moderator_note' not in data['user']
    assert 'bot_token' not in response.text
    assert 'telegraph_token' not in response.text


async def test_role_gate_rejects_signed_member_and_moderator_and_revoked_admin(db):
    import time
    from unittest.mock import AsyncMock

    from aiohttp import web

    from community_bot.miniapp import protection

    req = Request(db)
    req.path = '/api/shop/confirm'
    req.headers = {'Authorization': 'tma '+signed(date=int(time.time()))}
    handler = AsyncMock(return_value=web.json_response({'ok': True}))
    for role in ('member', 'moderator'):
        await db.set_role(7, role)
        assert (await protection(req, handler)).status == 403
        handler.assert_not_awaited()
    await db.set_role(7, 'admin')
    assert (await protection(req, handler)).status == 200
    handler.reset_mock()
    await db.set_role(7, 'member')
    assert (await protection(req, handler)).status == 403
    handler.assert_not_awaited()
    req.headers = {}
    assert (await protection(req, handler)).status == 401
    assert (await db.get_user(7))['cookies'] == 100


async def test_profile_save_is_atomic_validated_and_protects_bot_edits(db):
    from community_bot.miniapp import save_profile
    from community_bot.profile_fields import profile_revision

    revision = profile_revision(await db.get_user(7))
    fields = {'profile_name': 'Мария', 'age': 25, 'hobbies': 'Музыка', 'profile_bio': 'Петербург'}
    response = await save_profile(Request(db, body={'fields': fields, 'revision': revision}))
    assert response.status == 200
    user = await db.get_user(7)
    assert all(user[k] == v for k, v in fields.items())
    assert user['bio_auto_warn'] == 2
    assert not user['warnings']
    assert (await db.get_user(8))['age'] is None
    current = profile_revision(user)
    await db.update_profile(7, 'profile_name', 'Изменено в боте')
    assert (await save_profile(Request(db, body={'fields': fields, 'revision': current}))).status == 409
    assert (await db.get_user(7))['profile_name'] == 'Изменено в боте'
    assert (await save_profile(Request(db, body={'fields': fields, 'revision': revision}))).status == 409
    for wrong in [{'age': 13}, {'age': True}, {'profile_bio': 'x'*281}, {'cookies': 10000},
                  {'reputation': 100}, {'user_id': 8}, {'role': 'owner'}, {'profile_private': 1},
                  {'profile_name': 'Хак', 'age': 121}, {'hobbies': ' '}]:
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
    with pytest.raises(ValueError):
        await upload_avatar(req)
    bot.send_photo.assert_not_awaited()

    async def download(file_id, destination):
        assert file_id == 'telegram-avatar-file-id'
        destination.write(raw.getvalue())
    bot.download = download
    result = await avatar(req)
    assert result.status == 200
    assert result.content_type == 'image/jpeg'
    assert Image.open(BytesIO(result.body)).size == (800, 600)


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
