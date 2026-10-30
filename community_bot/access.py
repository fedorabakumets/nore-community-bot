"""Private onboarding gate and staff Mini App visibility (moderator rank and above)."""
from __future__ import annotations

import os

from aiogram import BaseMiddleware
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    MenuButtonCommands,
    MenuButtonWebApp,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from community_bot.helpers import rank_of_user
from community_bot.keyboards import STYLE_CLOSE, ibtn, kbtn, main_private_keyboard


def guest_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[kbtn('Помощь', STYLE_CLOSE)]], resize_keyboard=True, is_persistent=True)


async def miniapp_allowed(db, settings, uid):
    return await rank_of_user(db, settings, uid) >= 40


async def private_allowed(db, settings, uid):
    return await db.has_approved_application(uid) or await rank_of_user(db, settings, uid) > 0


async def private_keyboard(db, settings, uid):
    return main_private_keyboard() if await private_allowed(db, settings, uid) else guest_keyboard()


async def sync_menu(bot, db, settings, uid):
    cache = getattr(bot, '_nora_menu_access', None)
    if cache is None:
        cache = {}
        bot._nora_menu_access = cache
    url = os.getenv('MINIAPP_URL', '')
    allowed = url.startswith('https://') and await miniapp_allowed(db, settings, uid)
    signature = (allowed, url)
    if cache.get(uid) == signature:
        return
    button = MenuButtonWebApp(text='Открыть Нору', web_app=WebAppInfo(url=url)) if allowed else MenuButtonCommands()
    try:
        await bot.set_chat_menu_button(chat_id=uid, menu_button=button)
        cache[uid] = signature
    except (TelegramBadRequest, TelegramForbiddenError):
        pass  # A user who has never opened the private dialog cannot receive a chat-specific menu.


async def configure_private_menus(bot, db, settings):
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    for user in await db.list_all_users():
        await sync_menu(bot, db, settings, int(user['user_id']))


class OnboardingKeyboardMiddleware(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        markup, uid = getattr(method, 'reply_markup', None), getattr(method, 'chat_id', None)
        db, settings = getattr(bot, 'community_db', None), getattr(bot, 'community_settings', None)
        if isinstance(markup, ReplyKeyboardMarkup) and isinstance(uid, int) and uid > 0 and db and settings:
            if not await private_allowed(db, settings, uid):
                method = method.model_copy(update={'reply_markup': guest_keyboard()})
        return await make_request(bot, method)


class PrivateAccessMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        message = event.message if isinstance(event, CallbackQuery) else event
        if not getattr(message, 'chat', None) or message.chat.type != 'private' or not event.from_user:
            return await handler(event, data)
        db, settings, state = data['db'], data['settings'], data.get('state')
        uid = event.from_user.id
        await sync_menu(data['bot'], db, settings, uid)
        if await private_allowed(db, settings, uid):
            return await handler(event, data)
        current = (await state.get_state() if state else '') or ''
        if isinstance(event, CallbackQuery):
            action = event.data or ''
            allowed = action in {
                'start:apply', 'menu:apply', 'menu:question', 'flow:cancel', 'flow:restart', 'ui:close',
            }
            allowed |= current == 'ApplicationForm:interview' and action.startswith('application:interview:')
            if allowed:
                return await handler(event, data)
            await event.answer('Сначала заполни анкету и дождись одобрения.', show_alert=True)
        else:
            text = (event.text or '').strip().casefold()
            command = text.split('@', 1)[0].split(' ', 1)[0]
            if text in {'помощь', 'хелп'} or command in {'/help', '/commands'}:
                await event.answer(
                    'Сначала заполни анкету. После одобрения откроются кабинет и магазин. '
                    'Если нужна помощь, напиши поддержке.',
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [ibtn('📝 Заполнить анкету', 'start:apply')],
                        [ibtn('Написать поддержке', 'menu:question', STYLE_CLOSE)],
                    ]),
                )
                await event.answer('Помощь всегда здесь.', reply_markup=guest_keyboard())
                return
            if command in {'/start', '/apply'} or text in {'старт', 'анкета', '📝 заполнить анкету'}:
                return await handler(event, data)
            blocked_nav = text in {'📋 меню', '🛒 магазин', '💼 кошелёк', '🎫 тикет', '👤 мой профиль',
                                   'магазин', 'кошелек', 'кошелёк', 'профиль', 'меню'}
            if current.startswith(('ApplicationForm:', 'TicketForm:')) and not blocked_nav:
                if not text.startswith('/') or command == '/close' and current.startswith('TicketForm:'):
                    return await handler(event, data)
        answer = message.answer if isinstance(message, Message) else (
            lambda text, **kwargs: data['bot'].send_message(uid, text, **kwargs)
        )
        pending = await db.has_pending_application(uid)
        body = 'Анкета на проверке. Решение придёт сюда.' if pending else 'Сначала заполни анкету — это вход в Нору.'
        if not pending:
            await answer(body, reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[ibtn('📝 Заполнить анкету', 'start:apply')]],
            ))
        await answer('Остальные разделы откроются после одобрения.' if not pending else body,
                             reply_markup=guest_keyboard())


class ProfileAccessMiddleware(BaseMiddleware):
    """The same profile gate for customer actions in Telegram, including old buttons."""
    async def __call__(self, handler, event, data):
        from community_bot.aliases import parse_trigger
        from community_bot.profile_fill import profile_is_complete

        if not event.from_user:
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            action = event.data or ''
            gated = action.startswith(('shop:', 'rsvp:', 'rsvpj:', 'evpay:', 'evpaygo:', 'evpayyes:'))
            gated |= action in {'menu:shop'}
            gated &= action not in {'shop:close'}
        elif isinstance(event, Message):
            parsed = parse_trigger(event.text or '')
            gated = bool(parsed and parsed[0] in {'shop', 'store', 'buycookies', 'gift'})
            gated |= event.text == '🛒 Магазин'
        else:
            gated = False
        if isinstance(event, Message) and data.get('state'):
            flow = await data['state'].get_data()
            gated |= bool(flow.get('purchase_intent'))
        if isinstance(event, CallbackQuery) and (event.data or '').startswith('rsvp:'):
            if await data['db'].has_event_rsvp(event.data.split(':', 1)[1], event.from_user.id):
                gated = False  # Existing participants must retain access to withdrawal/refund.
        if gated:
            user = await data['db'].get_user(event.from_user.id)
            if not user or not profile_is_complete(user):
                text = ('Заполни профиль на 100%: имя, возраст, увлечения, описание и фото. '
                        'Затем откроются магазин и события.')
                if isinstance(event, CallbackQuery):
                    await event.answer(text, show_alert=True)
                else:
                    await event.answer(text)
                return
        return await handler(event, data)
