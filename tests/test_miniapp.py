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
        self.app = {'db': db, 'settings': SimpleNamespace(restricted_reputation_threshold=0), 'bot': None}
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
