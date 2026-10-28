"""Same-process Mini App: Telegram-signed identity, shared economy, no browser secrets."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile
from aiohttp import web
from PIL import Image, ImageOps, UnidentifiedImageError

from community_bot.database import Database

ROOT = Path(__file__).parent / 'web'
ASSETS = Path(__file__).parent.parent / 'assets'



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
                return web.json_response(
                    {'error': 'Откройте приложение из меню Норы в Telegram'},
                    status=401, headers={'Cache-Control': 'no-store'},
                )
            from community_bot.access import miniapp_allowed

            if not await miniapp_allowed(request.app['db'], request.app['settings'], request['actor']['id']):
                return web.json_response({'error': 'Миниапка пока доступна модераторам и администраторам'},
                                         status=403, headers={'Cache-Control': 'no-store'})
            if request.path.startswith(('/api/shop/', '/api/events/')):
                from community_bot.profile_fill import profile_is_complete

                user = await request.app['db'].get_user(request['actor']['id'])
                if not user or not profile_is_complete(user):
                    return web.json_response({'error': 'Заполни профиль на 100% в ЛК, чтобы открыть магазин и события'},
                                             status=403, headers={'Cache-Control': 'no-store'})
        response = await handler(request)
    except web.HTTPRequestEntityTooLarge:
        limit = 'Файл должен быть не больше 20 МБ' if request.path.startswith('/api/admin') else (
            'Фотография должна быть не больше 5 МБ'
        )
        response = web.json_response({'error': limit}, status=413)
    except ValueError as error:
        if request.path.startswith(('/api/shop/', '/api/pet/', '/api/wallet/', '/api/notices',
                                    '/api/friends', '/api/mafia', '/api/rocket', '/api/seasonal',
                                    '/api/people', '/api/presence')):
            return web.json_response({'error': str(error) or 'Проверь данные покупки'}, status=400,
                                     headers={'Cache-Control': 'no-store'})
        response = web.json_response(
            {'error': 'Проверь поля профиля, формат и размер фотографии (до 5 МБ)'}, status=400,
        )
    except (KeyError, TypeError, json.JSONDecodeError):
        response = web.json_response({'error': 'Проверьте данные запроса'}, status=400)
    response.headers['Cache-Control'] = 'no-store' if request.path.startswith('/api/') else 'no-cache'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; font-src 'self'; base-uri 'none'; "
        "frame-ancestors https://web.telegram.org https://*.telegram.org"
    )
    return response


async def actor(request):
    u = request['actor']
    return await request.app['db'].ensure_user(u['id'], u.get('username'), u.get('first_name', 'Участник'))


async def overview(request):
    from community_bot.cabinet_api import pet_data, wallet_data
    from community_bot.event_access import current_event
    from community_bot.shop_api import shop_data
    from community_bot.shop_text import plain_shop_text

    db, settings = request.app['db'], request.app['settings']
    user = await actor(request)
    pet = await pet_data(db, user)
    user = await db.get_user(user['user_id'])
    shop = await shop_data(db, user, settings)
    events = []
    current = await current_event(db)
    if current:
        eid = current['event_id']
        offer = await db.get_event_offer(eid)
        events.append({'id': eid, 'title': current['title'], 'price': int(offer['price']) if offer else 0,
                       'count': await db.event_participant_count(eid),
                       'joined': await db.has_event_rsvp(eid, user['user_id']),
                       'description': plain_shop_text(current['description']), 'starts_at': current['starts_at'],
                       'paid': await db.has_event_payment(eid, user['user_id'])})
    for product in shop['products']:
        if product['sku'] == 'event_pass':
            product.update(price=events[0]['price'] if events else None, buyable=bool(events),
                           description=events[0]['title'] if events else 'Следи за анонсами в сообществе',
                           reason='' if events else 'Сейчас нет опубликованного мероприятия')
    from community_bot.domain import reputation_tier
    from community_bot.helpers import effective_role, has_permission, role_title
    from community_bot.profile_fields import profile_revision
    from community_bot.profile_fill import profile_block_states, profile_fill_percent, reputation_cap

    tier = reputation_tier(int(user['reputation']), settings.restricted_reputation_threshold)
    today = datetime.now(ZoneInfo(getattr(settings, 'timezone', 'Europe/Moscow'))).date()
    used = await db.reputation_actions_today(user['user_id'], today)
    role = await effective_role(db, settings, user['user_id'])
    stats = {
        'fill_percent': profile_fill_percent(user), 'reputation_cap': reputation_cap(user),
        'tier': tier.label, 'discount': tier.discount, 'daily_actions': tier.daily_actions,
        'actions_used': used, 'actions_left': max(0, tier.daily_actions - used), 'can_minus': tier.can_minus,
        'role': await role_title(db, role), 'timezone': getattr(settings, 'timezone', 'Europe/Moscow'),
        'blocks': [{'title': label, 'filled': filled} for _, label, filled in profile_block_states(user)],
    }
    from community_bot.domain import reputation_tier as tier_for

    levels = [{'label': label, 'range': span, 'discount': tier_for(value).discount,
               'daily_actions': tier_for(value).daily_actions, 'can_minus': tier_for(value).can_minus}
              for value, label, span in [(0, 'Бронза', 'до 69'), (70, 'Серебро', '70–89'), (90, 'Золото', '90–100')]]
    history = await db.list_transactions(user['user_id'], 20)
    return web.json_response({
        'user': {k: user.get(k) for k in ('user_id', 'telegram_name', 'profile_name', 'username',
                                        'cookies', 'cookie_debt', 'reputation', 'profile_bio',
                                        'age', 'hobbies', 'warnings', 'profile_private',
                                        'hate_shields', 'hate_immunity_until')},
        'admin_available': await has_permission(
            db, settings, user['user_id'], 'admin.panel',
        ),
        'levels': levels,
        'profile': stats, 'revision': profile_revision(user),
        'has_avatar': bool(user.get('avatar_file_id')), 'avatar_video': user.get('avatar_media_type') == 'video',
        **shop, 'pet': pet, 'wallet': await wallet_data(db, settings, user),
        'unread_notices': await db.notify_unread_count(user['user_id']), 'events': events,
        'history': [{'amount': t['amount'], 'kind': t['kind'], 'date': t['created_at']} for t in history],
    })


async def prepare(request):
    from community_bot.shop_api import quote

    data = await request.json()
    if not isinstance(data, dict):
        raise ValueError('Ожидается объект')
    return web.json_response(await quote(request.app['db'], request.app['settings'], await actor(request), data))


async def confirm(request):
    from community_bot.shop_api import purchase

    data = await request.json()
    if not isinstance(data, dict) or not isinstance(data.get('token'), str):
        raise ValueError('Открой подтверждение покупки заново')
    db = request.app['db']
    from community_bot.rsvp import event_lock

    async with event_lock(db, 'shop:'+data['token']):
        ok, message = await purchase(
            db, request.app['settings'], request.app['bot'], await actor(request), data['token'],
        )
    return web.json_response({'ok': ok, 'message': message}, status=200 if ok else 409)


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


def normalized_photo(raw: bytes) -> bytes:
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format not in {'JPEG', 'PNG', 'WEBP'} or image.width * image.height > 20_000_000:
                raise ValueError('Нужна фотография JPG, PNG или WebP до 20 мегапикселей')
            image.load()
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((1600, 1600))
            output = BytesIO()
            image.save(output, 'JPEG', quality=88)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError('Не удалось прочитать фотографию') from error


async def save_profile(request):
    from community_bot.profile_fields import validate_profile_fields

    user = await actor(request)
    data = await request.json()
    if not isinstance(data, dict) or set(data) != {'fields', 'revision'} or not isinstance(data['revision'], str):
        raise ValueError('Некорректный запрос профиля')
    fields = validate_profile_fields(data['fields'])
    if not await request.app['db'].save_self_profile(user['user_id'], fields, data['revision']):
        return web.json_response({'error': 'Профиль уже изменился в боте. Обнови ЛК перед сохранением'}, status=409)
    return web.json_response({'ok': True, 'message': 'Профиль сохранён — изменения уже видны в боте'})


async def upload_avatar(request):
    from community_bot.profile_fields import profile_revision

    user = await actor(request)
    # Check the version before sending media; repeat atomically before writing the file_id.
    revision = request.headers.get('X-Profile-Revision', '')
    if revision != profile_revision(user):
        return web.json_response({'error': 'Профиль изменился. Обнови ЛК и повтори загрузку'}, status=409)
    if request.content_type not in {'image/jpeg', 'image/png', 'image/webp'}:
        raise ValueError('Выбери фотографию JPG, PNG или WebP')
    raw = await request.read()
    if not raw or len(raw) > 5 * 1024 * 1024:
        raise ValueError('Фотография должна быть не больше 5 МБ')
    photo = await asyncio.to_thread(normalized_photo, raw)
    try:
        sent = await request.app['bot'].send_photo(
            user['user_id'], BufferedInputFile(photo, filename='nora-avatar.jpg'),
            caption='Фото для профиля из миниапки.', disable_notification=True,
        )
    except TelegramAPIError:
        return web.json_response({'error': 'Не удалось загрузить фото в Telegram. Открой диалог с ботом и повтори'},
                                 status=502)
    values = {'avatar_file_id': sent.photo[-1].file_id, 'avatar_media_type': 'photo'}
    if not await request.app['db'].save_self_profile(user['user_id'], values, revision, avatar=True):
        return web.json_response({'error': 'Профиль изменился во время загрузки. Обнови ЛК и повтори'}, status=409)
    return web.json_response({'ok': True, 'message': 'Фото профиля обновлено в миниапке и боте'})


async def avatar(request):
    user = await actor(request)
    file_id = user.get('avatar_file_id')
    if not file_id or user.get('avatar_media_type') == 'video':
        raise web.HTTPNotFound()
    try:
        output = BytesIO()
        await request.app['bot'].download(file_id, destination=output)
        photo = await asyncio.to_thread(normalized_photo, output.getvalue())
    except (TelegramAPIError, ValueError):
        raise web.HTTPNotFound() from None
    return web.Response(body=photo, content_type='image/jpeg')


async def index(request):
    return web.FileResponse(ROOT / 'index.html')


def create_app(db: Database, settings, bot, admin_runtime=None):
    app = web.Application(middlewares=[protection], client_max_size=20 * 1024 * 1024 + 1024)
    app.update(db=db, settings=settings, bot=bot)
    app.router.add_get('/', index)
    app.router.add_get('/healthz', lambda _: web.json_response({'ok': True}))
    from community_bot import admin_web

    if bot is not None:
        app['admin_bridge'] = admin_web.AdminBridge(db, settings, bot, admin_runtime)
        async def close_admin(_):
            await app['admin_bridge'].dispatcher.storage.close()
        app.on_cleanup.append(close_admin)
    app.router.add_get('/api/admin', admin_web.panel)
    app.router.add_post('/api/admin/reset', admin_web.reset)
    app.router.add_post('/api/admin/action', admin_web.action)
    app.router.add_post('/api/admin/input', admin_web.input_text)
    app.router.add_post('/api/admin/upload', admin_web.upload)
    app.router.add_get('/api/admin/media/{media_id}', admin_web.media)
    app.router.add_get('/api/me', overview)
    app.router.add_post('/api/profile', save_profile)
    app.router.add_post('/api/profile/avatar', upload_avatar)
    app.router.add_get('/api/profile/avatar', avatar)
    from community_bot import cabinet_api, friends_api, mafia_api, rocket_api, seasonal, shop_api

    app.router.add_get('/api/seasonal', seasonal.status)
    app.router.add_post('/api/seasonal/join', seasonal.participate)
    app.router.add_get('/api/seasonal/manage', seasonal.manage)
    app.router.add_post('/api/seasonal/draw/prepare', seasonal.draw_prepare)
    app.router.add_post('/api/seasonal/draw/confirm', seasonal.draw_confirm)
    app.router.add_get('/seasonal/guardian-season1.jpg', lambda _: web.FileResponse(
        ASSETS / 'seasonal' / 'guardian-season1.jpg'))
    from community_bot import social_profiles

    app.router.add_get('/api/presence', social_profiles.status)
    app.router.add_post('/api/presence', social_profiles.update)
    app.router.add_get('/api/people', social_profiles.profile)
    app.router.add_get('/api/people/{user_id}', social_profiles.profile)
    app.router.add_get('/api/people/{user_id}/avatar', social_profiles.avatar)
    app.router.add_get('/api/friends', friends_api.status)
    app.router.add_post('/api/friends/action', friends_api.action)
    app.router.add_get('/api/mafia', mafia_api.status)
    app.router.add_post('/api/mafia/action', mafia_api.action)
    app.router.add_get('/api/rocket', rocket_api.status)
    app.router.add_post('/api/rocket/prepare', rocket_api.prepare)
    app.router.add_post('/api/rocket/launch', rocket_api.launch)
    app.router.add_post('/api/rocket/cashout', rocket_api.cashout)

    from community_bot.interactive_runtime import lifecycle

    app.cleanup_ctx.append(lifecycle)

    app.router.add_post('/api/pet/prepare', cabinet_api.pet_prepare)
    app.router.add_post('/api/pet/action', cabinet_api.pet_action)
    app.router.add_post('/api/wallet/prepare', cabinet_api.wallet_prepare)
    app.router.add_post('/api/wallet/confirm', cabinet_api.wallet_confirm)
    app.router.add_get('/api/wallet/history', cabinet_api.wallet_history)
    app.router.add_get('/api/notices', cabinet_api.notices)
    app.router.add_post('/api/notices', cabinet_api.notices_update)

    app.router.add_post('/api/shop/video', shop_api.upload_video)
    app.router.add_get('/api/shop/media/{sku}', shop_api.product_image)
    app.router.add_post('/api/shop/topup/prepare', shop_api.topup_prepare)
    app.router.add_post('/api/shop/topup/receipt', shop_api.topup_receipt)
    app.router.add_post('/api/shop/prepare', prepare)
    app.router.add_post('/api/shop/confirm', confirm)
    app.router.add_post('/api/events/join', join_event)
    for name in ('intro.js', 'app.js', 'shop.js', 'cabinet.js', 'admin.js', 'interactive.js', 'people.js', 'style.css'):
        app.router.add_get('/'+name, lambda r, n=name: web.FileResponse(ROOT / n))
    app.router.add_get('/fonts/Monocraft.ttf', lambda _: web.FileResponse(
        ASSETS / 'fonts' / 'Monocraft.ttf', headers={'Content-Type': 'font/ttf'}))
    app.router.add_get('/fonts/Monocraft-LICENSE.txt', lambda _: web.FileResponse(
        ASSETS / 'fonts' / 'Monocraft-LICENSE.txt', headers={'Content-Type': 'text/plain; charset=utf-8'}))
    app.router.add_static('/intro/', ASSETS / 'branding', show_index=False)
    app.router.add_static('/art/', ASSETS / 'stickers', show_index=False)
    return app


async def start_server(db, settings, bot, admin_runtime=None):
    runner = web.AppRunner(create_app(db, settings, bot, admin_runtime), access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, '0.0.0.0', int(os.getenv('PORT', '8080'))).start()
    except BaseException:
        await runner.cleanup()
        raise
    return runner
