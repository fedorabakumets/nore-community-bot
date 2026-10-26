"""Web presentation of the existing admin handlers, with isolated drafts and one-use controls.

No second Telegram poller: a separate in-process dispatcher routes only admin handlers.
A context-local request middleware captures private UI output; actual publications,
moderation and notifications still use the real Bot and existing domain operations.
"""
from __future__ import annotations

import asyncio
import html
import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from aiogram import Dispatcher, Router
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Chat,
    FSInputFile,
    InlineKeyboardMarkup,
    Message,
    MessageId,
    PhotoSize,
    Update,
    User,
)
from aiohttp import web

from community_bot.access import miniapp_allowed
from community_bot.helpers import has_permission, user_permissions
from community_bot.permissions import PERM_ADMIN_PANEL

ASSETS = Path(__file__).resolve().parent.parent / 'assets'
ACTIVE: ContextVar[Any] = ContextVar('nora_admin_web_request', default=None)
MAX_UPLOAD = 20 * 1024 * 1024


class SafeHTML(HTMLParser):
    """Render Telegram formatting without permitting arbitrary browser HTML."""
    tags = {'b', 'strong', 'i', 'em', 'u', 's', 'del', 'code', 'pre', 'blockquote'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.tags:
            self.parts.append(f'<{tag}>')
        elif tag == 'a':
            url = dict(attrs).get('href') or ''
            if urlparse(url).scheme in {'http', 'https', 'tg'}:
                self.parts.append(
                    f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
                )
        elif tag == 'br':
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in self.tags | {'a'}:
            self.parts.append(f'</{tag}>')

    def handle_data(self, data):
        self.parts.append(html.escape(data))


def safe_html(text, parse_mode):
    if str(parse_mode).casefold() != 'html':
        return html.escape(str(text or ''))
    parser = SafeHTML()
    parser.feed(str(text or ''))
    return ''.join(parser.parts)


def build_dispatcher():
    from community_bot import event_access
    from community_bot.routers import command_admin, contest, group, private, shop_admin

    dispatcher = Dispatcher(storage=MemoryStorage())
    extras = {'approve_application', 'reject_application', 'rejection_reason', 'begin_ticket_reply',
              'send_ticket_reply', 'moderator_close_ticket', 'review_cookie_order', 'participant_page'}
    for source in (command_admin.router, shop_admin.router, contest.router, private.router,
                   group.router, event_access.router):
        clone = Router(name='web_'+source.name)
        for kind in ('message', 'callback_query'):
            original, observer = source.observers[kind], clone.observers[kind]
            if original._handler.filters:
                observer.filter(*(f.magic if f.magic is not None else f.callback for f in original._handler.filters))
            for handler in original.handlers:
                name = handler.callback.__name__
                if source in (private.router, group.router, event_access.router):
                    if not name.startswith('admin_') and name not in extras:
                        continue
                elif name == 'contest_join':
                    continue
                observer.register(handler.callback,
                                  *(f.magic if f.magic is not None else f.callback for f in handler.filters or []),
                                  flags=dict(handler.flags or {}))
        dispatcher.include_router(clone)
    return dispatcher


@dataclass
class Session:
    uid: int
    permissions: tuple[str, ...]
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    touched: float = field(default_factory=time.monotonic)
    cards: dict[int, dict] = field(default_factory=dict)
    visible: list[int] = field(default_factory=list)
    changed: list[int] = field(default_factory=list)
    actions: dict[str, tuple[int, str]] = field(default_factory=dict)
    media: dict[str, tuple[str, Any]] = field(default_factory=dict)
    notices: list[str] = field(default_factory=list)
    form: str = ''
    version: str = ''
    counter: int = 0
    input_message: Message | None = None

    def next_id(self):
        self.counter -= 1
        return self.counter

    def message(self, mid, bot_id):
        card = self.cards.get(mid, {})
        return Message(message_id=mid, date=datetime.now(UTC), chat=Chat(id=self.uid, type='private'),
                       from_user=User(id=bot_id, is_bot=True, first_name='Нора'),
                       text=card.get('text') or 'Админ-панель',
                       reply_markup=card.get('markup'))

    def changed_card(self, mid):
        if mid not in self.changed:
            self.changed.append(mid)

    def capture(self, method, bot_id):
        name = method.__api_method__
        if name == 'answerCallbackQuery':
            if method.text:
                self.notices.append(method.text)
            return True
        if name == 'deleteMessage':
            mid = method.message_id
            self.cards.pop(mid, None)
            self.visible = [i for i in self.visible if i != mid]
            return True
        mid = getattr(method, 'message_id', None) or self.next_id()
        old = self.cards.get(mid, {})
        text = getattr(method, 'text', None)
        caption = getattr(method, 'caption', None)
        media = getattr(method, 'media', None)
        if media is not None and not isinstance(media, list):
            caption = getattr(media, 'caption', caption)
        if text is None and caption is None:
            text = old.get('text', '')
        parse_mode = getattr(method, 'parse_mode', None)
        if media is not None and not isinstance(media, list):
            parse_mode = getattr(media, 'parse_mode', parse_mode)
        markup = getattr(method, 'reply_markup', None)
        card = {'text': text if text is not None else caption,
                'html': safe_html(text if text is not None else caption, parse_mode),
                'markup': markup if isinstance(markup, InlineKeyboardMarkup) else None,
                'media': old.get('media')}
        if name == 'editMessageReplyMarkup':
            card = dict(old) | {'markup': markup}
        for kind in ('photo', 'video', 'animation', 'document', 'audio', 'voice', 'sticker'):
            payload = getattr(method, kind, None)
            if payload is not None:
                card['media'] = (kind, payload)
                break
        if media is not None and not isinstance(media, list):
            card['media'] = (str(media.type), media.media)
        self.cards[mid] = card
        self.changed_card(mid)
        result = self.message(mid, bot_id)
        if card.get('media'):
            result = result.model_copy(update={'photo': [PhotoSize(file_id='web-preview', file_unique_id='web-preview',
                                                                  width=512, height=512)]})
        return result


class CaptureAdminUI(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        session = ACTIVE.get()
        if session is None:
            return await make_request(bot, method)
        name = method.__api_method__
        # A synthetic text input does not exist in Telegram. Recreate it for recipients.
        if name == 'copyMessage' and method.from_chat_id == session.uid:
            incoming = session.input_message
            if incoming and method.message_id == incoming.message_id and incoming.message_id < 0:
                sent = await make_request(bot, SendMessage(
                    chat_id=method.chat_id, text=incoming.text or incoming.caption or ' ', entities=incoming.entities,
                ))
                return MessageId(message_id=sent.message_id)
        if name == 'answerCallbackQuery' or getattr(method, 'chat_id', None) == session.uid and name in {
            'sendMessage', 'sendPhoto', 'sendVideo', 'sendAnimation', 'sendDocument', 'sendAudio', 'sendVoice',
            'sendSticker', 'editMessageText', 'editMessageCaption', 'editMessageMedia', 'editMessageReplyMarkup',
            'deleteMessage',
        }:
            result = session.capture(method, bot.id)
            return result.as_(bot) if isinstance(result, Message) else result
        return await make_request(bot, method)


class AdminBridge:
    def __init__(self, db, settings, bot, runtime=None):
        self.db, self.settings, self.bot = db, settings, bot
        self.dispatcher = build_dispatcher()
        self.runtime = runtime or {}
        self.sessions: dict[int, Session] = {}
        if not getattr(bot, '_nora_admin_capture', False):
            bot.session.middleware.register(CaptureAdminUI())
            bot._nora_admin_capture = True

    async def allowed(self, uid):
        return await miniapp_allowed(self.db, self.settings, uid) and await has_permission(
            self.db, self.settings, uid, PERM_ADMIN_PANEL,
        )

    async def context(self, uid):
        return self.dispatcher.fsm.get_context(bot=self.bot, chat_id=uid, user_id=uid)

    async def session(self, uid):
        if not await self.allowed(uid):
            raise web.HTTPForbidden(text='Админ-панель недоступна')
        now = time.monotonic()
        for key, previous in list(self.sessions.items()):
            if now - previous.touched > 3600 and not previous.lock.locked():
                del self.sessions[key]
                await (await self.context(key)).clear()
        permissions = tuple(sorted(await user_permissions(self.db, self.settings, uid)))
        current = self.sessions.get(uid)
        if current and current.permissions != permissions:
            # Invalidate form capabilities when granular permissions change mid-draft.
            async with current.lock:
                await (await self.context(uid)).clear()
                self.sessions.pop(uid, None)
            raise web.HTTPConflict(text='Права изменились. Открой админ-панель заново')
        if uid not in self.sessions:
            if len(self.sessions) >= 100:
                raise web.HTTPServiceUnavailable(text='Панель занята. Повтори чуть позже')
            self.sessions[uid] = Session(uid, permissions)
        self.sessions[uid].touched = now
        return self.sessions[uid]

    async def check_permissions(self, session):
        permissions = tuple(sorted(await user_permissions(self.db, self.settings, session.uid)))
        if not await self.allowed(session.uid) or permissions != session.permissions:
            session.actions.clear()
            session.form = ''
            await (await self.context(session.uid)).clear()
            raise web.HTTPForbidden(text='Права изменились. Открой панель заново')

    async def feed(self, session, actor, *, callback=None, mid=None, message=None):
        await self.check_permissions(session)
        session.changed.clear()
        session.notices.clear()
        user = User(id=actor['id'], is_bot=False, first_name=actor.get('first_name') or 'Администратор',
                    last_name=actor.get('last_name'), username=actor.get('username'))
        if message is not None:
            incoming = message.model_copy(update={'from_user': user})
            session.input_message = incoming
            update = Update(update_id=secrets.randbelow(2**30), message=incoming)
        else:
            update = Update(update_id=secrets.randbelow(2**30), callback_query=CallbackQuery(
                id='web-'+secrets.token_urlsafe(12), from_user=user, chat_instance='miniapp-admin', data=callback,
                message=session.message(mid if mid is not None else session.next_id(), self.bot.id),
            ))
        token = ACTIVE.set(session)
        try:
            result = await self.dispatcher.feed_update(
                self.bot, update, db=self.db, settings=self.settings, **self.runtime,
            )
            if result is UNHANDLED:
                session.notices.append('Действие больше недоступно. Вернись в начало панели.')
        finally:
            ACTIVE.reset(token)
            session.input_message = None
        if session.changed:
            session.visible = [i for i in session.changed if i in session.cards]
        # Bound memory to the active view; stale controls cannot refer to old screens.
        session.cards = {i: session.cards[i] for i in session.visible if i in session.cards}

    async def snapshot(self, session):
        session.actions.clear()
        session.media.clear()
        session.form = ''
        session.version = secrets.token_urlsafe(16)
        cards = []
        for mid in session.visible:
            card = session.cards.get(mid)
            if card is None:
                continue
            rows = []
            if isinstance(card.get('markup'), InlineKeyboardMarkup):
                for row in card['markup'].inline_keyboard:
                    buttons = []
                    for button in row:
                        item = {'text': button.text, 'style': button.style or ''}
                        if button.callback_data and button.callback_data.startswith('shop:'):
                            item['tab'] = 'shop'
                        elif button.callback_data:
                            # Only server-issued controls can reach callbacks. No raw callback API exists.
                            action = secrets.token_urlsafe(18)
                            session.actions[action] = (mid, button.callback_data)
                            item['action'] = action
                        elif button.url and urlparse(button.url).scheme in {'https', 'http', 'tg'}:
                            item['url'] = button.url
                        else:
                            continue
                        buttons.append(item)
                    if buttons:
                        rows.append(buttons)
            output = {'html': card.get('html', ''), 'buttons': rows}
            if card.get('media'):
                media_id = secrets.token_urlsafe(18)
                session.media[media_id] = card['media']
                payload = card['media'][1]
                if isinstance(payload, str) and urlparse(payload).scheme in {'https', 'http'}:
                    output['media'] = {'url': payload, 'kind': card['media'][0]}
                else:
                    output['media'] = {'id': media_id, 'kind': card['media'][0]}
            cards.append(output)
        state = await (await self.context(session.uid)).get_state()
        if state:
            session.form = secrets.token_urlsafe(18)
        return {'cards': cards, 'notices': session.notices, 'form': session.form, 'state': state,
                'version': session.version, 'draft': bool(state)}

    async def open(self, actor, reset=False):
        session = await self.session(actor['id'])
        async with session.lock:
            await self.check_permissions(session)
            if reset or not session.visible:
                await (await self.context(session.uid)).clear()
                session.cards.clear()
                session.visible.clear()
                await self.feed(session, actor, callback='admin:panel')
            return await self.snapshot(session)

    async def action(self, actor, data):
        session = await self.session(actor['id'])
        async with session.lock:
            await self.check_permissions(session)
            if not isinstance(data, dict) or set(data) != {'action', 'version'} or data['version'] != session.version:
                raise web.HTTPConflict(text='Экран устарел. Обнови панель')
            control = session.actions.pop(data['action'], None)
            if not control:
                raise web.HTTPConflict(text='Кнопка уже использована или устарела')
            # Invalidate all controls before any operation; network retries cannot publish twice.
            session.actions.clear()
            session.form = ''
            mid, callback = control
            if callback in {'ui:close', 'flow:cancel', 'flow:restart'}:
                await (await self.context(session.uid)).clear()
                await self.feed(session, actor, callback='admin:panel')
            else:
                await self.feed(session, actor, callback=callback, mid=mid)
            return await self.snapshot(session)

    async def input(self, actor, data, upload=None):
        session = await self.session(actor['id'])
        async with session.lock:
            await self.check_permissions(session)
            if (not isinstance(data, dict) or set(data) - {'form', 'version', 'text', 'kind', 'format'}
                    or not session.form or data.get('form') != session.form or data.get('version') != session.version):
                raise web.HTTPConflict(text='Форма уже отправлена или устарела. Обнови панель')
            text = data.get('text') or ''
            if not isinstance(text, str) or len(text) > 4096 or not text.strip() and upload is None:
                raise ValueError('Нужен текст до 4096 символов или файл')
            if not await (await self.context(session.uid)).get_state():
                raise web.HTTPConflict(text='Нет открытой формы')
            from community_bot.admin_text import compose

            text, entities = compose(text, data.get('format', 'plain'))
            session.form = ''
            session.actions.clear()
            if upload is not None:
                kind, raw = upload
                if not raw or len(raw) > MAX_UPLOAD:
                    raise ValueError('Файл должен быть не больше 20 МБ')
                methods = {'photo': self.bot.send_photo, 'video': self.bot.send_video,
                           'animation': self.bot.send_animation, 'document': self.bot.send_document,
                           'audio': self.bot.send_audio, 'voice': self.bot.send_voice}
                if kind not in methods:
                    raise ValueError('Неподдерживаемый тип вложения')
                if kind == 'photo':
                    from community_bot.miniapp import normalized_photo

                    raw = await asyncio.to_thread(normalized_photo, raw)
                # Store the uploaded source in Telegram to get a genuine file_id for publication/copy.
                incoming = await methods[kind](session.uid, BufferedInputFile(raw, filename={
                    'photo': 'nora-upload.jpg', 'video': 'nora-upload.mp4', 'animation': 'nora-upload.gif',
                    'audio': 'nora-upload.mp3', 'voice': 'nora-upload.ogg', 'document': 'nora-upload.bin',
                }[kind]), caption=text or 'Вложение из админ-панели Норы.',
                    caption_entities=entities or None, disable_notification=True)
                if not text:
                    incoming = incoming.model_copy(update={'caption': None, 'caption_entities': None})
            else:
                incoming = Message(message_id=session.next_id(), date=datetime.now(UTC),
                                   chat=Chat(id=session.uid, type='private'), text=text, entities=entities)
            await self.feed(session, actor, message=incoming)
            return await self.snapshot(session)

    async def get_media(self, actor, media_id):
        session = await self.session(actor['id'])
        async with session.lock:
            await self.check_permissions(session)
            value = session.media.get(media_id)
            if not value:
                raise web.HTTPNotFound()
            kind, payload = value
            if isinstance(payload, FSInputFile):
                path = await asyncio.to_thread(Path(payload.path).resolve)
                if not path.is_relative_to(ASSETS) or not await asyncio.to_thread(path.is_file):
                    raise web.HTTPNotFound()
                raw = await asyncio.to_thread(path.read_bytes)
            elif isinstance(payload, BufferedInputFile):
                raw = payload.data
            elif isinstance(payload, str) and not urlparse(payload).scheme:
                metadata = await self.bot.get_file(payload)
                if (metadata.file_size or 0) > MAX_UPLOAD:
                    raise web.HTTPRequestEntityTooLarge(max_size=MAX_UPLOAD, actual_size=metadata.file_size)
                output = BytesIO()
                await self.bot.download(metadata, destination=output)
                raw = output.getvalue()
            else:
                raise web.HTTPNotFound()
            if len(raw) > MAX_UPLOAD:
                raise web.HTTPRequestEntityTooLarge(max_size=MAX_UPLOAD, actual_size=len(raw))
            if kind in {'photo', 'sticker'}:
                from community_bot.miniapp import normalized_photo

                raw = await asyncio.to_thread(normalized_photo, raw)
                mime = 'image/jpeg'
            else:
                mime = {'video': 'video/mp4', 'animation': 'video/mp4', 'audio': 'audio/mpeg',
                        'voice': 'audio/ogg'}.get(kind, 'application/octet-stream')
            return web.Response(body=raw, content_type=mime, headers={'Cache-Control': 'no-store'})


async def handle(request, operation):
    bridge = request.app.get('admin_bridge')
    if bridge is None:
        return web.json_response({'error': 'Админ-панель ещё запускается'}, status=503)
    try:
        return web.json_response(await operation(bridge))
    except web.HTTPException as error:
        return web.json_response({'error': error.text}, status=error.status)
    except ValueError:
        return web.json_response(
            {'error': 'Проверь введённое значение, размер файла и форматирование текста'}, status=400,
        )
    except TelegramAPIError:
        return web.json_response({'error': 'Telegram не принял действие. Обнови панель перед повтором'}, status=502)


async def panel(request):
    return await handle(request, lambda bridge: bridge.open(request['actor']))


async def reset(request):
    return await handle(request, lambda bridge: bridge.open(request['actor'], reset=True))


async def action(request):
    data = await request.json()
    return await handle(request, lambda bridge: bridge.action(request['actor'], data))


async def input_text(request):
    data = await request.json()
    return await handle(request, lambda bridge: bridge.input(request['actor'], data))


async def upload(request):
    # Authorization is checked before parsing files; every upload also consumes a form capability.
    bridge = request.app.get('admin_bridge')
    if bridge is None:
        return web.json_response({'error': 'Админ-панель ещё запускается'}, status=503)
    if not await bridge.allowed(request['actor']['id']):
        return web.json_response({'error': 'Недостаточно прав'}, status=403)
    data = {'form': request.headers.get('X-Admin-Form', ''), 'version': request.headers.get('X-Admin-Version', ''),
            'text': request.headers.get('X-Admin-Caption', ''),
            'format': request.headers.get('X-Admin-Format', 'plain')}
    from urllib.parse import unquote

    data['text'] = unquote(data['text'])
    raw = await request.read()
    kind = request.headers.get('X-Admin-Media', 'document')
    return await handle(request, lambda current: current.input(request['actor'], data, upload=(kind, raw)))


async def media(request):
    bridge = request.app.get('admin_bridge')
    if bridge is None:
        raise web.HTTPNotFound()
    return await bridge.get_media(request['actor'], request.match_info['media_id'])
