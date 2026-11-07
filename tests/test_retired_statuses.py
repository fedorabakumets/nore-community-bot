from types import SimpleNamespace

import pytest

from community_bot.database import Database
from community_bot.helpers import render_profile
from community_bot.life import unlock
from community_bot.miniapp import overview
from community_bot.shop_catalog import ITEM_LABELS, RETIRED_PROFILE_SKUS


@pytest.mark.parametrize('ornate', [0, 1])
async def test_legacy_statuses_titles_and_board_achievement_are_hidden_without_erasing_history(tmp_path, ornate):
    db = Database(tmp_path/'old.db')
    await db.initialize()
    await db.ensure_user(7, telegram_name='Анна')
    await db.execute('UPDATE users SET custom_status=?, profile_title=?, profile_ornate=? WHERE user_id=7',
                     ('Старый статус', 'На доске', ornate))
    await db.unlock_achievement(7, 'board')
    settings = SimpleNamespace(is_owner=lambda _: True, moderator_ids=frozenset(),
                               restricted_reputation_threshold=0, timezone='Europe/Moscow')
    text = await render_profile(db, settings, await db.get_user(7))
    assert 'На доске' not in text and 'Старый статус' not in text
    assert (await db.get_user(7))['custom_status'] == 'Старый статус'
    assert 'board' in await db.list_achievements(7)
    assert await unlock(db, 7, 'board') is None
    assert await unlock(db, 7, 'shop_first') == 'Покупатель'
    assert (await db.get_user(7))['profile_title'] == 'На доске'  # no new automatic title
    req = {'actor': {'id': 7, 'first_name': 'Анна'}}
    request = type('Request', (dict,), {})(req)
    request.app = {'db': db, 'settings': settings}
    data = (await overview(request)).text
    assert 'custom_status' not in data and 'profile_title' not in data


async def test_legacy_status_products_cannot_be_reactivated_or_charged(tmp_path):
    db = Database(tmp_path/'retired.db')
    await db.initialize()
    await db.ensure_user(7, telegram_name='Анна')
    await db.add_cookies(7, 100, 'test')
    for sku in RETIRED_PROFILE_SKUS:
        await db.execute('INSERT INTO shop_items(sku,category_slug,title,price,created_at,updated_at) '
                         'VALUES(?, ?, ?, 10, ?, ?)', (sku, 'profile', 'Старый товар', '2026', '2026'))
        assert sku not in ITEM_LABELS
        assert await db.get_shop_item(sku) is None
        assert await db.upsert_shop_item(sku, enabled=1) is None
        token = await db.create_wallet_intent(7, sku, 10)
        assert not (await db.buy_item(7, sku, 10, intent_id=token, profile_value='Статус'))[0]
    assert (await db.get_user(7))['cookies'] == 100
    assert not await db.list_transactions(7, 10) == []  # setup credit remains
    assert not [t for t in await db.list_transactions(7) if t['kind'] == 'shop']
    assert not set(RETIRED_PROFILE_SKUS) & {i['sku'] for i in await db.list_shop_items()}
