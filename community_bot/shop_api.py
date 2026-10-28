"""Mini App shop: live catalogue and the same transactional deliveries as Telegram."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from io import BytesIO
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile
from aiohttp import web

from community_bot.domain import discounted_price, reputation_tier
from community_bot.pets_talk import SPECIES
from community_bot.rsvp import event_lock
from community_bot.shop_catalog import GIFTABLE_ITEMS, ITEM_LABELS, PET_SUPPLIES, item_discount
from community_bot.shop_text import plain_shop_text

logger = logging.getLogger(__name__)
BUYABLE = frozenset(ITEM_LABELS) | {'support'}
DESCRIPTIONS = {
    'restore_rep': '+10 к репутации в пределах доступного максимума.',
    'reset_limits': 'Обновить дневной лимит действий с репутацией.',
    'forgive': 'Очистить предупреждения и снять мут в чате.',
    'rep_shield': 'Один щит поглощает одно понижение репутации.',
    'immunity_24h': 'Защита от отрицательных оценок на 24 часа. Повторная покупка продлевает срок.',
    'private_profile': 'Скрыть профиль от других участников. Открыть его снова можно в боте.',
    'ornate_profile': 'Включить особое оформление карточки профиля в боте.',
    'video_avatar': 'Установить видео вместо фотографии в карточке профиля. Файл до 20 МБ.',
    'tamagotchi': 'Выбрать питомца и придумать ему имя. Один питомец на человека.',
    'pet_meal': '+40 сытости питомцу, максимум 100.',
    'pet_drink': '+50 жаждоутоления питомцу, максимум 100.',
    'season_pack': 'Щит от −реп и +40 сытости питомцу.',
    'support': 'Выбери сумму поддержки проекта в печеньках.',
}


async def shop_data(db, user, settings):
    from community_bot.routers.group import _shop_prices

    prices = await _shop_prices(db, user, settings)
    categories = await db.list_shop_categories(enabled_only=True)
    available = {c['slug'] for c in categories}
    pet = await db.get_pet(user['user_id'], settle=False)
    flags = {k: await db.feature_enabled(k) for k in ('tamagotchi', 'profile_video')}
    products = []
    for item in await db.list_shop_items(enabled_only=True):
        if item['category_slug'] not in available:
            continue
        sku = item['sku']
        reason = ''
        if sku not in BUYABLE and sku != 'event_pass':
            reason = 'Выдача этого товара ещё не настроена'
        elif sku != 'event_pass' and sku != 'support' and sku not in prices:
            reason = 'Цена пока не задана'
        elif sku == 'tamagotchi' and pet:
            reason = 'У тебя уже есть питомец'
        elif sku in {'tamagotchi', 'pet_meal', 'pet_drink', 'season_pack'} and not flags['tamagotchi']:
            reason = 'Тамагочи временно выключены'
        elif sku in {'pet_meal', 'pet_drink', 'season_pack'} and not pet:
            reason = 'Сначала заведи питомца'
        elif sku == 'video_avatar' and not flags['profile_video']:
            reason = 'Видео-профили временно выключены'
        elif sku == 'private_profile' and user['profile_private']:
            reason = 'Профиль уже скрыт'
        elif sku == 'ornate_profile' and user['profile_ornate']:
            reason = 'Оформление уже куплено'
        products.append({
            'sku': sku, 'title': plain_shop_text(item['title']), 'category': item['category_slug'],
            'description': plain_shop_text(item['description']) or DESCRIPTIONS.get(sku, ''),
            'price': prices.get(sku), 'base_price': item['price'], 'buyable': not reason,
            'reason': reason, 'giftable': sku in GIFTABLE_ITEMS,
            'mode': 'pet' if sku == 'tamagotchi' else 'video' if sku == 'video_avatar' else (
                'amount' if sku == 'support' else 'event' if sku == 'event_pass' else 'instant'),
            'image': bool(item['image'] and not urlparse(str(item['image'])).scheme),
        })
    from community_bot.life import vitrine_active

    featured = None
    key = await db.get_bot_state('shop_featured')
    stock = await db.get_bot_state('shop_featured_stock')
    until = await db.get_bot_state('shop_featured_until')
    if key and any(p['sku'] == key for p in products) and vitrine_active(stock, until):
        featured = {'sku': key, 'title': plain_shop_text(await db.get_bot_state('shop_featured_label')),
                    'stock': stock if stock and stock != '0' else None, 'until': until}
    from community_bot.seasonal import snapshot

    return {
        'seasonal': await snapshot(db, settings, user['user_id']),
        'featured': featured,
        'categories': [{'id': c['slug'], 'title': plain_shop_text(c['title']),
                        'description': plain_shop_text(c['description'])} for c in categories],
        'products': products,
        'pet': {k: pet[k] for k in ('species', 'name', 'hunger', 'thirst')} if pet else None,
        'species': [{'id': k, 'emoji': v[0], 'title': v[1]} for k, v in SPECIES.items()],
        'header': {k: plain_shop_text(v) if k in {'title', 'text'} else v
                   for k, v in (await db.shop_header()).items()},
        'cookie_shop': {k: plain_shop_text(v) if k in {'title', 'intro', 'button'} else v
                        for k, v in (await db.cookie_shop()).items()},
    }


async def recipient(db, uid, value):
    if not value:
        return uid, ''
    token = str(value).strip().lstrip('@')
    if token.isdigit() and len(token) <= 16:
        user = await db.get_user(int(token))
    elif re.fullmatch(r'[A-Za-z0-9_]{5,32}', token):
        user = await db.fetchone('SELECT * FROM users WHERE lower(username) = lower(?)', (token,))
    else:
        user = None
    if not user:
        raise ValueError('Получатель не найден. Укажи точный @username или Telegram ID участника Норы')
    label = user['profile_name'] or user['telegram_name'] or user['username'] or user['user_id']
    return int(user['user_id']), str(label)


async def quote(db, settings, user, data):
    from community_bot.routers.group import _shop_prices

    sku = data.get('sku')
    if not isinstance(sku, str) or sku not in BUYABLE:
        raise ValueError('Этот товар сейчас недоступен')
    item = await db.get_shop_item(sku)
    category = await db.get_shop_category(item['category_slug']) if item else None
    if not item or not item['enabled'] or not category or not category['enabled']:
        raise ValueError('Товар или категория выключены')
    target, label = await recipient(db, user['user_id'], data.get('recipient'))
    if target != user['user_id'] and sku not in GIFTABLE_ITEMS:
        raise ValueError('Этот товар нельзя подарить')
    prices = await _shop_prices(db, user, settings)
    payload = {'shop_quote': True, 'restricted_threshold': settings.restricted_reputation_threshold}
    if sku == 'support':
        amount = data.get('amount')
        if type(amount) is not int or not 1 <= amount <= 1_000_000:
            raise ValueError('Выбери целую сумму от 1 до 1 000 000 печенек')
        discount = reputation_tier(user['reputation'], settings.restricted_reputation_threshold).discount
        price = discounted_price(amount, item_discount(sku, discount))
        payload['base_amount'] = amount
    elif sku in prices:
        price = prices[sku]
    else:
        raise ValueError('Цена этого товара ещё не задана')
    feature = 'tamagotchi' if sku in {'tamagotchi', 'pet_meal', 'pet_drink', 'season_pack'} else (
        'profile_video' if sku == 'video_avatar' else None
    )
    if feature and not await db.feature_enabled(feature):
        raise ValueError('Эта функция временно выключена')
    payload['feature'] = feature
    if sku == 'tamagotchi':
        name, species = data.get('name'), data.get('species')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 24 or species not in SPECIES:
            raise ValueError('Выбери питомца и имя от 1 до 24 символов')
        if await db.get_pet(target, settle=False):
            raise ValueError('У тебя уже есть питомец')
        payload.update(name=name.strip(), species=species)
    if sku in {'pet_meal', 'pet_drink', 'season_pack'} and not await db.get_pet(target, settle=False):
        raise ValueError('У получателя пока нет питомца')
    token = await db.create_wallet_intent(user['user_id'], sku, price, target_id=target, payload=payload)
    return {'token': token, 'price': price, 'title': plain_shop_text(item['title']), 'recipient': label,
            'description': plain_shop_text(item['description']) or DESCRIPTIONS.get(sku, ''),
            'needs_video': sku == 'video_avatar'}


async def purchase(db, settings, bot, user, token):
    intent = await db.get_wallet_intent(user['user_id'], token)
    if not intent or intent['item'] not in BUYABLE:
        return False, 'Подтверждение уже использовано или устарело'
    sku, price, target, payload = intent['item'], intent['price'], intent['target_id'], intent['payload']
    if payload.get('shop_quote') and payload.get('restricted_threshold') != settings.restricted_reputation_threshold:
        return False, 'Правила скидок изменились. Открой товар заново'
    if sku == 'tamagotchi':
        ok, message = await db.purchase_pet(
            user['user_id'], payload['species'], payload['name'], price, intent_id=token,
        )
    elif sku in PET_SUPPLIES:
        kind, gain, _ = PET_SUPPLIES[sku]
        ok, message, _ = await db.purchase_pet_supply(target, kind, gain, price, sku,
                                                     payer_id=user['user_id'], intent_id=token)
    else:
        ok, message = await db.buy_item(user['user_id'], sku, price, target_id=target,
                                       intent_id=token, profile_value=payload.get('video_file_id'))
    if not ok:
        return False, message
    from community_bot.life import unlock

    try:
        await unlock(db, user['user_id'], 'shop_first')
        if sku == 'tamagotchi':
            await unlock(db, user['user_id'], 'first_pet')
        if target != user['user_id']:
            await unlock(db, user['user_id'], 'gift_first')
    except Exception as error:
        logger.warning('Shop achievement deferred: %s', type(error).__name__)
    result = 'Подарок доставлен!' if target != user['user_id'] else 'Покупка готова — изменения уже видны в боте!'
    if bot:
        if sku == 'support':
            from community_bot.helpers import safe_send, user_link

            for owner_id in settings.owner_ids:
                await safe_send(bot, owner_id, f"🍪 {user_link(user['user_id'], user['telegram_name'])} "
                                f"поддержал Нору на {price} печенек.", parse_mode='HTML')
        try:
            from community_bot.notify import vitrine_consumed

            await vitrine_consumed(bot, db, sku)
        except Exception as error:
            logger.warning('Shop notice deferred: %s', type(error).__name__)
        if sku == 'forgive' and getattr(settings, 'community_chat_id', 0):
            from community_bot.routers.life import _full_chat_permissions

            try:
                await bot.restrict_chat_member(settings.community_chat_id, target, permissions=_full_chat_permissions())
            except TelegramAPIError:
                result = 'Предупреждения очищены. Снять мут автоматически не удалось — обратись к администратору.'
    return True, result


async def upload_video(request):
    from community_bot.miniapp import actor

    user, db = await actor(request), request.app['db']
    token = request.headers.get('X-Shop-Token', '')
    async with event_lock(db, 'shop:'+token):
        intent = await db.get_wallet_intent(user['user_id'], token)
        if not intent or intent['item'] != 'video_avatar' or not intent['payload'].get('shop_quote'):
            return web.json_response({'error': 'Открой покупку видео заново'}, status=409)
        if not await db.feature_enabled('profile_video'):
            return web.json_response({'error': 'Видео-профили временно выключены'}, status=409)
        if request.content_type != 'video/mp4':
            raise ValueError('Нужно видео MP4 до 20 МБ')
        raw = await request.read()
        if len(raw) > 20 * 1024 * 1024 or len(raw) < 12 or raw[4:8] != b'ftyp':
            raise ValueError('Нужно корректное видео MP4 до 20 МБ')
        try:
            sent = await request.app['bot'].send_video(
                user['user_id'], BufferedInputFile(raw, filename='nora-profile.mp4'),
                                                       caption='Видео для профиля. Покупка ещё не подтверждена.',
                                                       disable_notification=True)
        except TelegramAPIError:
            return web.json_response({'error': 'Telegram не принял видео. Открой диалог с ботом и повтори'}, status=502)
        payload = dict(intent['payload'], video_file_id=sent.video.file_id)
        await db.execute("UPDATE wallet_intents SET payload_json=? WHERE token=? AND user_id=? AND status='pending'",
                         (json.dumps(payload, ensure_ascii=False), token, user['user_id']))
    return web.json_response({'ok': True})


async def product_image(request):
    from community_bot.miniapp import ASSETS, normalized_photo

    db, sku = request.app['db'], request.match_info['sku']
    item = await db.get_shop_item(sku)
    category = await db.get_shop_category(item['category_slug']) if item else None
    if not item or not item['enabled'] or not category or not category['enabled']:
        raise web.HTTPNotFound()
    image = str(item['image'] or '')
    if not image or urlparse(image).scheme:
        raise web.HTTPNotFound()
    try:
        path = (ASSETS.parent / image).resolve()
        if path.is_relative_to(ASSETS.resolve()) and await asyncio.to_thread(path.is_file):
            raw = await asyncio.to_thread(path.read_bytes)
        else:
            metadata = await request.app['bot'].get_file(image)
            if (metadata.file_size or 0) > 5 * 1024 * 1024:
                raise web.HTTPNotFound()
            out = BytesIO()
            await request.app['bot'].download(metadata, destination=out)
            raw = out.getvalue()
        photo = await asyncio.to_thread(normalized_photo, raw)
    except (TelegramAPIError, ValueError, OSError):
        raise web.HTTPNotFound() from None
    return web.Response(body=photo, content_type='image/jpeg')


async def topup_prepare(request):
    from community_bot.miniapp import actor

    user, db = await actor(request), request.app['db']
    data = await request.json()
    amount = data.get('amount') if isinstance(data, dict) else None
    config = await db.cookie_shop()
    if not config['enabled'] or type(amount) is not int or amount not in config['packs']:
        raise ValueError('Этот пакет сейчас недоступен')
    payment_url = getattr(request.app['settings'], 'sbp_payment_url', '')
    if urlparse(payment_url).scheme != 'https':
        raise ValueError('Ссылка на оплату пока не настроена')
    rubles = amount * config['rate_rub']
    token = await db.create_wallet_intent(user['user_id'], 'cookie_topup', rubles,
                                         payload={'amount': amount, 'rate': config['rate_rub']})
    return web.json_response({'token': token, 'amount': amount, 'rubles': rubles, 'payment_url': payment_url})


async def topup_receipt(request):
    from community_bot.miniapp import actor, normalized_photo

    user, db = await actor(request), request.app['db']
    token = request.headers.get('X-Shop-Token', '')
    async with event_lock(db, 'shop:'+token):
        intent = await db.get_wallet_intent(user['user_id'], token)
        config = await db.cookie_shop()
        if not intent or intent['item'] != 'cookie_topup' or not config['enabled'] or (
            intent['payload'].get('rate') != config['rate_rub']
            or intent['payload'].get('amount') not in config['packs']
        ):
            return web.json_response({'error': 'Условия пакета изменились. Открой оплату заново'}, status=409)
        raw = await request.read()
        if not raw or len(raw) > 5 * 1024 * 1024:
            raise ValueError('Скриншот или PDF должны быть не больше 5 МБ')
        kind = 'document' if request.content_type == 'application/pdf' and raw.startswith(b'%PDF-') else 'photo'
        if kind == 'photo':
            raw = await asyncio.to_thread(normalized_photo, raw)
        try:
            send = request.app['bot'].send_document if kind == 'document' else request.app['bot'].send_photo
            sent = await send(user['user_id'], BufferedInputFile(raw, filename='receipt.pdf' if kind == 'document'
                                                               else 'receipt.jpg'),
                              caption='Квитанция для проверки оплаты печенек.', disable_notification=True)
        except TelegramAPIError:
            return web.json_response({'error': 'Не удалось загрузить квитанцию в Telegram'}, status=502)
        file_id = sent.document.file_id if kind == 'document' else sent.photo[-1].file_id
        async with db.connect() as connection:
            await connection.execute('BEGIN IMMEDIATE')
            error = await db._consume_wallet_intent(connection, token, user['user_id'], 'cookie_topup',
                                                    intent['price'], user['user_id'])
            if error:
                await connection.rollback()
                return web.json_response({'error': error}, status=409)
            cursor = await connection.execute(
                'INSERT INTO cookie_orders(user_id,amount,rubles,receipt_media_type,receipt_file_id,created_at) '
                'VALUES(?,?,?,?,?,?)', (user['user_id'], intent['payload']['amount'], intent['price'], kind,
                                      file_id, datetime.now(ZoneInfo('UTC')).isoformat()),
            )
            order_id = cursor.lastrowid
            await connection.commit()
    try:
        await notify_cookie_order(request.app['bot'], db, request.app['settings'], order_id)
    except Exception as error:
        logger.warning('Payment notice deferred: %s', type(error).__name__)
    return web.json_response({'ok': True, 'message': f'Квитанция по заказу №{order_id} сохранена. '
                               'После проверки администратором печеньки появятся на общем балансе.',
                              'order_id': order_id})


async def notify_cookie_order(bot, db, settings, order_id):
    """Use the existing payment review queue and permission checks for both clients."""
    from community_bot.helpers import has_permission, user_link
    from community_bot.keyboards import cookie_order_review_keyboard
    from community_bot.permissions import PERM_PAYMENTS

    order = await db.get_cookie_order(order_id)
    if not order:
        return
    candidates = set(settings.reviewers)
    for user in await db.list_all_users():
        if user['role'] in {'owner', 'admin'}:
            candidates.add(int(user['user_id']))
    caption = (f"💳 <b>Заказ печенек №{order_id}</b>\n"
               f"Пользователь: {user_link(order['user_id'], order['telegram_name'] or str(order['user_id']))}\n"
               f"Пакет: <b>{order['amount']} 🍪</b> · сумма <b>{order['rubles']} ₽</b>")
    for uid in candidates:
        if not await has_permission(db, settings, uid, PERM_PAYMENTS):
            continue
        try:
            send = bot.send_photo if order['receipt_media_type'] == 'photo' else bot.send_document
            await send(uid, order['receipt_file_id'], caption=caption, parse_mode='HTML',
                       reply_markup=cookie_order_review_keyboard(order_id))
        except TelegramAPIError:
            continue
