"""Same-process Mini App: Telegram-signed identity, shared economy, no browser secrets."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from community_bot.database import Database

ROOT = Path(__file__).parent / 'web'
ASSETS = Path(__file__).parent.parent / 'assets'
BUYABLE = {'rep_shield', 'immunity_24h', 'immunity_7d', 'private_profile'}


def validate_init_data(raw: str, token: str, now: float | None = None) -> dict:
    if not raw or len(raw) > 8192:
        raise ValueError('Откройте приложение из Telegram')
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    data = dict(pairs)
    if len(data) != len(pairs):
        raise ValueError('Некорректная авторизация')
    received = data.pop('hash', '')
    check = '\n'.join(f'{k}={v}' for k, v in sorted(data.items()))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, received):
        raise ValueError('Подпись Telegram не совпадает')
    age = (time.time() if now is None else now) - int(data.get('auth_date', '0'))
    if not -30 <= age <= 3600:
        raise ValueError('Вход устарел. Закройте и откройте приложение')
    user = json.loads(data['user'])
    if not isinstance(user, dict):
        raise ValueError('Некорректный пользователь')
    if type(user.get('id')) is not int or user['id'] <= 0 or user.get('is_bot'):
        raise ValueError('Некорректный пользователь')
    return user


@web.middleware
async def protection(request, handler):
    try:
        if request.path.startswith('/api/'):
            raw = request.headers.get('Authorization', '').removeprefix('tma ')
            try:
                request['actor'] = validate_init_data(raw, request.app['settings'].bot_token)
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                return web.json_response({'error': 'Откройте приложение из меню Норы в Telegram'}, status=401)
        response = await handler(request)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        response = web.json_response({'error': 'Проверьте данные запроса'}, status=400)
    response.headers['Cache-Control'] = 'no-store' if request.path.startswith('/api/') else 'no-cache'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; base-uri 'none'; "
        "frame-ancestors https://web.telegram.org https://*.telegram.org"
    )
    return response


async def actor(request):
    u = request['actor']
    return await request.app['db'].ensure_user(u['id'], u.get('username'), u.get('first_name', 'Участник'))


async def overview(request):
    from community_bot.event_access import current_event
    from community_bot.routers.group import _shop_prices

    db, settings = request.app['db'], request.app['settings']
    user = await actor(request)
    prices = await _shop_prices(db, user, settings)
    cats = await db.list_shop_categories(enabled_only=True)
    items = await db.list_shop_items(enabled_only=True)
    available = {c['slug'] for c in cats}
    products = [{'sku': i['sku'], 'title': i['title'], 'category': i['category_slug'],
                 'price': prices.get(i['sku']), 'buyable': i['sku'] in BUYABLE and i['sku'] in prices}
                for i in items if i['category_slug'] in available]
    events = []
    current = await current_event(db)
    if current:
        eid = current['event_id']
        offer = await db.get_event_offer(eid)
        events.append({'id': eid, 'title': current['title'], 'price': int(offer['price']) if offer else 0,
                       'count': await db.event_participant_count(eid),
                       'joined': await db.has_event_rsvp(eid, user['user_id']),
                       'paid': await db.has_event_payment(eid, user['user_id'])})
    history = await db.list_transactions(user['user_id'], 20)
    return web.json_response({
        'user': {k: user.get(k) for k in ('user_id', 'telegram_name', 'profile_name', 'username',
                                        'cookies', 'cookie_debt', 'reputation', 'profile_bio', 'profile_title')},
        'categories': [{'id': c['slug'], 'title': c['title']} for c in cats], 'products': products, 'events': events,
        'history': [{'amount': t['amount'], 'kind': t['kind'], 'date': t['created_at']} for t in history],
    })


async def prepare(request):
    from community_bot.routers.group import _shop_prices

    user = await actor(request)
    data = await request.json()
    if not isinstance(data, dict):
        raise ValueError("Ожидается объект")
    sku = data.get('sku')
    db = request.app['db']
    prices = await _shop_prices(db, user, request.app['settings'])
    if sku not in BUYABLE or sku not in prices:
        raise ValueError('Этот товар оформляется в боте')
    token = await db.create_wallet_intent(user['user_id'], sku, prices[sku])
    item = await db.get_shop_item(sku)
    return web.json_response({'token': token, 'price': prices[sku], 'title': item['title']})


async def confirm(request):
    user = await actor(request)
    data = await request.json()
    if not isinstance(data, dict):
        raise ValueError("Ожидается объект")
    db = request.app['db']
    intent = await db.get_wallet_intent(user['user_id'], data.get('token', ''))
    if not intent or intent['item'] not in BUYABLE:
        return web.json_response({'error': 'Подтверждение уже использовано или устарело'}, status=409)
    ok, message = await db.buy_item(user['user_id'], intent['item'], intent['price'], intent_id=data['token'])
    return web.json_response({'ok': ok, 'message': 'Покупка готова!' if ok else message}, status=200 if ok else 409)


async def join_event(request):
    from community_bot.event_access import current_event
    from community_bot.rsvp import event_lock, refresh_event_markup

    user = await actor(request)
    db, bot = request.app['db'], request.app['bot']
    data = await request.json()
    if not isinstance(data, dict):
        raise ValueError("Ожидается объект")
    event = await current_event(db)
    if not event or data.get('event_id') != event['event_id']:
        return web.json_response({'error': 'Мероприятие изменилось. Обновите экран'}, status=409)
    eid = event['event_id']
    async with event_lock(db, eid):
        offer = await db.get_event_offer(eid)
        price = int(offer['price']) if offer else 0
        if type(data.get('price')) is not int or data['price'] != price:
            return web.json_response({'error': 'Цена изменилась. Обновите экран'}, status=409)
        if price:
            ok, message, _ = await db.pay_event_offer(eid, user['user_id'], price)
        else:
            ok, message = await db.add_rsvp(eid, user['user_id'], 0, kind='rsvp')
        if ok and event['rsvp_enabled']:
            await refresh_event_markup(bot, db, eid)
    return web.json_response({'ok': ok, 'message': 'Вы в списке участников!' if ok else message},
                             status=200 if ok else 409)


async def index(request):
    return web.FileResponse(ROOT / 'index.html')


def create_app(db: Database, settings, bot):
    app = web.Application(middlewares=[protection], client_max_size=16384)
    app.update(db=db, settings=settings, bot=bot)
    app.router.add_get('/', index)
    app.router.add_get('/healthz', lambda _: web.json_response({'ok': True}))
    app.router.add_get('/api/me', overview)
    app.router.add_post('/api/shop/prepare', prepare)
    app.router.add_post('/api/shop/confirm', confirm)
    app.router.add_post('/api/events/join', join_event)
    for name in ('app.js', 'style.css'):
        app.router.add_get('/'+name, lambda r, n=name: web.FileResponse(ROOT / n))
    app.router.add_static('/art/', ASSETS / 'stickers', show_index=False)
    return app


async def start_server(db, settings, bot):
    runner = web.AppRunner(create_app(db, settings, bot), access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', '8080'))).start()
    except BaseException:
        await runner.cleanup()
        raise
    return runner
