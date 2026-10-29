import asyncio
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from community_bot.database import Database
from community_bot.miniapp import confirm, overview, prepare
from community_bot.shop_api import product_image, topup_prepare, topup_receipt, upload_video
from community_bot.shop_catalog import SAMPLE_SHOP_PRICES
from community_bot.shop_text import clean_shop_text, plain_shop_text


class Request(dict):
    def __init__(self, env, body=None, uid=7):
        super().__init__(actor={'id': uid, 'first_name': 'Анна'})
        self.app = {'db': env.db, 'settings': env.settings, 'bot': env.bot}
        self.headers = {}
        self.content_type = 'application/json'
        self.body = body or {}

    async def json(self):
        return self.body


@pytest.fixture
async def env(tmp_path):
    db = Database(tmp_path / 'shop.sqlite3')
    await db.initialize()
    for uid in (7, 8):
        await db.ensure_user(uid, username='anna_nora' if uid == 7 else 'boris_nora', telegram_name=f'Участник {uid}')
        for key, value in {'profile_name': f'Имя {uid}', 'age': 25, 'hobbies': 'Питер',
                           'profile_bio': 'Достаточно длинное описание', 'avatar_file_id': 'test-photo'}.items():
            await db.update_profile(uid, key, value)
        await db.set_cookies(uid, 1000, 7)
    for sku, price in SAMPLE_SHOP_PRICES.items():
        await db.upsert_shop_item(sku, price=price, enabled=1)
    await db.upsert_shop_item('support', category_slug='reputation', title='Поддержка', enabled=1)
    settings = SimpleNamespace(restricted_reputation_threshold=0, timezone='Europe/Moscow',
                               is_owner=lambda uid: uid == 7, owner_ids={7}, moderator_ids=set(),
                               reviewers={7}, community_chat_id=-100123, sbp_payment_url='https://example.test/sbp')
    return SimpleNamespace(db=db, settings=settings, bot=None)


async def prepared(env, sku, **extra):
    return json.loads((await prepare(Request(env, {'sku': sku, **extra}))).body)


async def paid(env, token, uid=7, **extra):
    return await confirm(Request(env, {'token': token, **extra}, uid))


@pytest.mark.parametrize('sku,column', [('restore_rep', 'reputation'), ('rep_shield', 'hate_shields'),
                                      ('immunity_24h', 'hate_immunity_until'), ('forgive', 'warnings'),
                                      ('private_profile', 'profile_private'), ('ornate_profile', 'profile_ornate')])
async def test_shared_shop_effects_and_history_are_delivered_once(env, sku, column):
    await env.db.execute('UPDATE users SET reputation=50,warnings=3 WHERE user_id=7')
    before = await env.db.get_user(7)
    q = await prepared(env, sku)
    assert (await env.db.get_user(7))['cookies'] == before['cookies']
    results = await asyncio.gather(paid(env, q['token']), paid(env, q['token']))
    assert sorted(r.status for r in results) == [200, 409]
    after = await env.db.get_user(7)
    assert after[column] != before[column]
    assert after['cookies'] == before['cookies']-q['price']
    tx = await env.db.fetchall("SELECT * FROM transactions WHERE user_id=7 AND kind='shop' AND details=?", (sku,))
    assert len(tx) == 1 and tx[0]['amount'] == -q['price']
    assert 'shop_first' in await env.db.list_achievements(7)


async def test_gift_uses_surcharge_and_changes_only_exact_recipient(env):
    q = await prepared(env, 'rep_shield', recipient='@boris_nora', price=1, target_id=7)
    assert q['recipient'] == 'Имя 8' and q['price'] > 1
    assert (await paid(env, q['token'], uid=8)).status == 409
    assert (await paid(env, q['token'], recipient='@anna_nora')).status == 200
    assert (await env.db.get_user(8))['hate_shields'] == 1
    assert (await env.db.get_user(7))['hate_shields'] == 0
    assert (await env.db.get_user(7))['cookies'] == 1000-q['price']
    assert (await env.db.get_user(8))['cookies'] == 1000
    with pytest.raises(ValueError):
        await prepared(env, 'ornate_profile', recipient='@boris_nora')
    with pytest.raises(ValueError):
        await prepared(env, 'rep_shield', recipient='nobody_else')


@pytest.mark.parametrize('change', ['price', 'discount', 'item', 'category', 'feature'])
async def test_changed_conditions_reject_confirmation_without_debit(env, change):
    q = await prepared(env, 'video_avatar')
    # Install a server-side fixture upload so the test reaches the transactional quote validation.
    intent = await env.db.get_wallet_intent(7, q['token'])
    payload = dict(intent['payload'], video_file_id='fixture-video')
    await env.db.execute('UPDATE wallet_intents SET payload_json=? WHERE token=?', (json.dumps(payload), q['token']))
    if change == 'price':
        await env.db.upsert_shop_item('video_avatar', price=100)
    elif change == 'discount':
        await env.db.execute('UPDATE users SET reputation=90 WHERE user_id=7')
    elif change == 'item':
        await env.db.upsert_shop_item('video_avatar', enabled=0)
    elif change == 'category':
        await env.db.upsert_shop_category('profile', 'Профиль', enabled=0)
    else:
        await env.db.execute("UPDATE feature_flags SET enabled=0 WHERE key='profile_video'")
    assert (await paid(env, q['token'])).status == 409
    assert (await env.db.get_user(7))['cookies'] == 1000
    assert (await env.db.get_user(7))['avatar_file_id'] == 'test-photo'


async def test_pet_selection_name_and_supplies_use_same_pet_as_bot(env):
    with pytest.raises(ValueError):
        await prepared(env, 'pet_meal')
    q = await prepared(env, 'tamagotchi', species='fox', name='Лиска')
    assert (await paid(env, q['token'], species='dragon', name='Подмена')).status == 200
    pet = await env.db.get_pet(7, settle=False)
    assert pet['species'] == 'fox' and pet['name'] == 'Лиска'
    assert (await paid(env, q['token'])).status == 409
    await env.db.execute('UPDATE pets SET hunger=20,thirst=20 WHERE user_id=7')
    for sku in ('pet_meal', 'pet_drink', 'season_pack'):
        q = await prepared(env, sku)
        assert (await paid(env, q['token'])).status == 200
    pet = await env.db.get_pet(7, settle=False)
    assert pet['hunger'] == 100 and pet['thirst'] == 70
    assert (await env.db.get_user(7))['hate_shields'] == 1
    before = (await env.db.get_user(7))['cookies']
    q = await prepared(env, 'pet_meal')
    assert (await paid(env, q['token'])).status == 409
    assert (await env.db.get_user(7))['cookies'] == before
    with pytest.raises(ValueError):
        await prepared(env, 'tamagotchi', species='cat', name='Второй')


async def test_video_upload_is_actor_bound_and_never_debits_before_confirmation(env):
    env.bot = SimpleNamespace(send_video=AsyncMock(return_value=SimpleNamespace(
        video=SimpleNamespace(file_id='real-video'),
    )))
    q = await prepared(env, 'video_avatar')
    assert (await paid(env, q['token'], video_file_id='forged')).status == 409
    request = Request(env, uid=8)
    request.headers = {'X-Shop-Token': q['token']}
    request.content_type = 'video/mp4'
    request.read = AsyncMock(return_value=b'\x00\x00\x00\x18ftypisom0000')
    assert (await upload_video(request)).status == 409
    env.bot.send_video.assert_not_awaited()
    request['actor']['id'] = 7
    assert (await upload_video(request)).status == 200
    assert (await env.db.get_user(7))['cookies'] == 1000
    assert (await paid(env, q['token'])).status == 200
    assert (await env.db.get_user(7))['avatar_file_id'] == 'real-video'
    assert (await env.db.get_user(7))['avatar_media_type'] == 'video'
    assert (await paid(env, q['token'])).status == 409


async def test_support_requires_server_calculated_amount_and_is_once(env):
    q = await prepared(env, 'support', amount=100, price=1)
    assert q['price'] == 98
    assert (await paid(env, q['token'])).status == 200
    assert (await env.db.get_user(7))['cookies'] == 902
    for amount in (0, -1, True, 1_000_001, '100'):
        with pytest.raises(ValueError):
            await prepared(env, 'support', amount=amount)


async def test_catalogue_sync_repairs_mojibake_and_excludes_disabled_categories(env):
    corrupt = '🐾 Тамагочи'.encode().decode('cp1251')
    await env.db.upsert_shop_category('pets', corrupt, '<b>Забота</b> о питомце')
    assert (await env.db.get_shop_category('pets'))['title'] == '🐾 Тамагочи'
    data = json.loads((await overview(Request(env))).body)
    category = next(c for c in data['categories'] if c['id'] == 'pets')
    assert category['title'] == '🐾 Тамагочи' and category['description'] == 'Забота о питомце'
    assert len(data['species']) == 5
    await env.db.upsert_shop_category('pets', '🐾 Тамагочи', enabled=0)
    data = json.loads((await overview(Request(env))).body)
    assert all(p['category'] != 'pets' for p in data['products'])
    assert all(c['id'] != 'pets' for c in data['categories'])
    with pytest.raises(ValueError):
        await prepared(env, 'pet_drink')


async def test_topup_receipt_uses_existing_review_queue_and_replay_protection(env, monkeypatch):
    monkeypatch.setattr('community_bot.shop_api.notify_cookie_order', AsyncMock())
    env.bot = SimpleNamespace(send_photo=AsyncMock(return_value=SimpleNamespace(
        photo=[SimpleNamespace(file_id='receipt-photo')],
    )))
    q = json.loads((await topup_prepare(Request(env, {'amount': 50}))).body)
    assert q['rubles'] == 50
    output = BytesIO()
    Image.new('RGB', (50, 50), 'red').save(output, 'PNG')
    request = Request(env)
    request.headers = {'X-Shop-Token': q['token']}
    request.content_type = 'image/png'
    request.read = AsyncMock(return_value=output.getvalue())
    results = await asyncio.gather(topup_receipt(request), topup_receipt(request))
    assert sorted(r.status for r in results) == [200, 409]
    orders = await env.db.pending_cookie_orders()
    assert len(orders) == 1 and orders[0]['amount'] == 50
    assert (await env.db.get_user(7))['cookies'] == 1000
    assert await env.db.review_cookie_order(orders[0]['id'], 7, True)
    assert await env.db.review_cookie_order(orders[0]['id'], 7, True) is None
    assert (await env.db.get_user(7))['cookies'] == 1050


async def test_product_image_refuses_arbitrary_urls_and_hidden_items(env):
    from aiohttp import web

    await env.db.upsert_shop_item('rep_shield', image='http://169.254.169.254/private')
    request = Request(env)
    request.match_info = {'sku': 'rep_shield'}
    with pytest.raises(web.HTTPNotFound):
        await product_image(request)
    await env.db.upsert_shop_item('rep_shield', image='telegram-file', enabled=0)
    with pytest.raises(web.HTTPNotFound):
        await product_image(request)


def test_shop_text_repairs_only_encoding_and_preserves_healthy_russian_and_html():
    for text in ('🐾 Тамагочи', '🛡 Щит', '✨ Профиль', 'Санкт-Петербург', 'Имя Анна'):
        assert clean_shop_text(text) == text
        try:
            corrupt = text.encode().decode('cp1251')
        except UnicodeError:
            continue
        assert clean_shop_text(corrupt) == text
    assert plain_shop_text('<b>Питомец</b> <tg-emoji emoji-id="1">🐾</tg-emoji>') == 'Питомец 🐾'


async def test_reset_limits_uses_moscow_day_in_both_clients_after_utc_midnight_boundary(env, monkeypatch):
    from datetime import UTC, datetime

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            fixed = datetime(2026, 10, 26, 22, 30, tzinfo=UTC)
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr('community_bot.database.datetime', Clock)
    for day in ('2026-10-26', '2026-10-27'):
        await env.db.execute('INSERT INTO reputation_actions(actor_id,target_id,delta,action_date,created_at) '
                             'VALUES(7,8,5,?,?)', (day, day+'T12:00:00+00:00'))
    q = await prepared(env, 'reset_limits')
    assert (await paid(env, q['token'])).status == 200
    rows = await env.db.fetchall('SELECT action_date FROM reputation_actions WHERE actor_id=7')
    assert rows == [{'action_date': '2026-10-26'}]


async def test_changed_topup_rate_and_foreign_receipt_do_not_create_orders(env):
    q = json.loads((await topup_prepare(Request(env, {'amount': 50}))).body)
    request = Request(env, uid=8)
    request.headers = {'X-Shop-Token': q['token']}
    assert (await topup_receipt(request)).status == 409
    await env.db.set_cookie_shop(rate_rub=2)
    request['actor']['id'] = 7
    assert (await topup_receipt(request)).status == 409
    assert await env.db.pending_cookie_orders() == []
    assert (await env.db.get_user(7))['cookies'] == 1000
