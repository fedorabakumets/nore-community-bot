"""One admin-published live lobby widget; no automatic message publication."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
import zlib
from pathlib import Path

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from community_bot.message_widgets import EditSharedWidgetData, SendSharedWidget, SendWidget
from community_bot.nora_game_api import LOBBY_TTL

logger = logging.getLogger(__name__)
TEMPLATE = Path(__file__).with_name('widgets') / 'lobby.html'
UPDATE_INTERVAL = 10


def delivery_error(error):
    """Expose Telegram's reason, never its request URL, token or payload."""
    method = getattr(error.method, '__api_method__', '')
    stages = {'getMe': 'получение ссылки на игру', 'getChatMemberCount': 'число участников',
              'sendWidget': 'отправка виджета', 'sendSharedWidget': 'публикация общего виджета в сообщество',
              'editSharedWidgetData': 'обновление счётчика', 'pinChatMessage': 'закрепление'}
    reason = re.sub(r'\d{5,}:[A-Za-z0-9_-]+', '[скрыто]', error.message)
    reason = re.sub(r'https?://\S+', '[адрес скрыт]', reason)
    reason = ' '.join(reason.split())[:240]
    return f"Telegram: {stages.get(method, 'публикация')} — {reason}"


def document(url):
    if not re.fullmatch(r'https://t\.me/[A-Za-z0-9_]+\?startapp=nora_lobby&mode=fullscreen', url):
        raise ValueError('Не удалось создать ссылку на игру')
    result = TEMPLATE.read_text(encoding='utf-8').replace('/*URL*/""', json.dumps(url))
    raw = result.encode('utf-8')
    if len(raw) > 32768 or len(zlib.compress(raw, 9)) > 4096:
        raise ValueError('Виджет превышает лимит Telegram')
    return result


class LobbyWidget:
    def __init__(self, app):
        self.app = app
        self.bot, self.db = app['bot'], app['db']
        self.chat_id = app['settings'].community_chat_id
        self.key = f'nora_lobby_widget:{self.chat_id}'
        self.lock = asyncio.Lock()
        self.saved = None
        self.loaded = False
        self.members = None
        self.members_at = 0
        self.revision = 0

    async def load(self):
        if not self.loaded:
            raw = await self.db.get_bot_state(self.key)
            self.saved = json.loads(raw) if raw else None
            self.loaded = True

    async def snapshot(self):
        now = time.monotonic()
        if self.members is None or now - self.members_at >= 60:
            # A failed lookup does not invent a zero or publish stale membership data.
            self.members = await self.bot.get_chat_member_count(self.chat_id)
            self.members_at = time.monotonic()
        now = time.monotonic()
        online = sum(now - seen < LOBBY_TTL for seen, _, _ in self.app['nora_lobby'].values())
        stamp = int(time.time() * 1000)
        self.revision = max(stamp, self.revision + 1)
        return json.dumps({'online': online, 'members': self.members, 'updated': stamp,
                           'revision': self.revision}, separators=(',', ':'))

    async def publish(self, actor_id=None):
        """Serialized across admins; persist before pinning so pin retries reuse the message."""
        async with self.lock:
            if not self.chat_id:
                raise ValueError('Чат сообщества не настроен')
            await self.load()
            if not self.saved:
                me = await self.bot.get_me()
                url = f'https://t.me/{me.username}?startapp=nora_lobby&mode=fullscreen'
                request = SendWidget(
                    chat_id=self.chat_id, html=document(url), is_shared=True,
                    public_data=await self.snapshot(), width=320, height=320,
                    caption='NORA · Лобби. Живой счётчик доступен внутри виджета.',
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text='Войти в NORA', url=url),
                    ]]),
                )
                sent_privately = False
                try:
                    message = await self.bot(request)
                except TelegramBadRequest as error:
                    # Server rollout may still restrict direct widgets to private chats.
                    # Only retry an explicit rejection, never an ambiguous network failure.
                    if 'input_media_widget_not_allowed' not in error.message.casefold() or not actor_id:
                        raise
                    sent_privately = True
                    message = await self.bot(request.model_copy(update={'chat_id': actor_id}))
                widget = getattr(message, 'widget', None)
                widget_id = widget.get('id') if isinstance(widget, dict) else getattr(widget, 'id', None)
                self.saved = {'message_id': None if sent_privately else message.message_id,
                              'widget_id': str(widget_id) if widget_id is not None else None}
                await self.db.set_bot_state(self.key, json.dumps(self.saved))
            if not self.saved.get('widget_id'):
                return 'Telegram отправил сообщение без ID общего виджета. Живое обновление недоступно.'
            if not self.saved.get('message_id'):
                # Reuse the object even if the original private message cannot be forwarded.
                # This also resumes sources persisted by the previous delivery implementation.
                message = await self.bot(SendSharedWidget(
                    chat_id=self.chat_id, widget_id=self.saved['widget_id'],
                ))
                self.saved['message_id'] = message.message_id
                await self.db.set_bot_state(self.key, json.dumps(self.saved))
            update_error = None
            try:
                await self.update()
            except TelegramAPIError as error:
                update_error = delivery_error(error)
            try:
                await self.bot.pin_chat_message(self.chat_id, self.saved['message_id'], disable_notification=True)
            except TelegramBadRequest as error:
                if 'message to pin not found' in error.message.casefold():
                    self.saved = None
                    await self.db.set_bot_state(self.key, '')
                    return 'Сообщение удалено. Нажми «Опубликовать и закрепить» ещё раз, чтобы создать новое.'
                return f'Виджет отправлен. {delivery_error(error)}'
            except TelegramAPIError as error:
                return f'Виджет отправлен. {delivery_error(error)}'
            if update_error:
                return f'Виджет отправлен и закреплён. {update_error}. Автообновление повторится позже.'
            return 'Лобби NORA опубликовано и закреплено. Счётчик обновляется автоматически.'

    async def update(self):
        if not self.saved or not self.saved.get('widget_id'):
            return
        try:
            await self.bot(EditSharedWidgetData(widget_id=self.saved['widget_id'], public_data=await self.snapshot()))
        except TelegramBadRequest as error:
            if 'not modified' not in error.message.casefold():
                raise

    async def run(self):
        while True:
            delay = UPDATE_INTERVAL
            try:
                async with self.lock:
                    await self.load()
                    await self.update()
            except TelegramRetryAfter as error:
                delay = max(delay, error.retry_after)
            except Exception as error:
                # Never include request objects / bot token in operational logs.
                logger.warning('Lobby widget update failed (%s)', type(error).__name__)
                delay = 60
            await asyncio.sleep(delay)


async def lifecycle(app):
    bot = app['bot']
    if bot is None:
        yield
        return
    service = LobbyWidget(app)
    bot._nora_lobby_widget = service
    task = asyncio.create_task(service.run(), name='nora-lobby-widget')
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        del bot._nora_lobby_widget
