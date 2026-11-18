"""Short-lived chat between the NORA world and the configured Telegram group."""

import hmac
import logging
import re
import sqlite3
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from random import choice
from uuid import uuid4

from aiogram import BaseMiddleware
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import Chat, ChatMemberUpdated, InputRichMessage, Message, ReplyParameters
from aiohttp import web

from community_bot.aliases import is_command_message
from community_bot.chat_memory import MEMORY_NOTICE_KEY, clean_author_name, clean_stored_text
from community_bot.helpers import rank_of_user

CHAT_TTL = 30 * 60
CHAT_LENGTH = 240
BUBBLE_LIFETIME = 7
MEMBERSHIP_TTL = 30
PLAYER_EMOJI = {
    'male': ('👱🏻‍♂️', '👨🏽‍🦲', '🧔🏼‍♂️', '🧔🏿', '👴', '👨🏾‍🦰'),
    'female': ('👩🏼', '👩🏽‍🦰', '👩🏾‍🦱', '👱🏽‍♀️', '👵🏽', '🧔🏿‍♀️'),
}
ROOM_LABELS = {'lobby': 'ЛОББИ • 🌎', 'cinema': 'Кинотеатр • 🎬', 'observatory': 'Воспоминание • ⚡'}
SOLO_LOCATIONS = {'tavern': 'Таверна • 🍺', 'forest': 'Лесная поляна • 🌲'}
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ChatLine:
    id: str
    user_id: int
    author: str
    text: str
    at: float
    created: float
    telegram_id: int | None = None
    thread_id: int | None = None
    quote: tuple[str, str, bool] | None = None


class GameChat:
    def __init__(self, bot, group_id):
        self.bot = bot
        self.group_id = group_id
        self.rooms = OrderedDict()
        self.telegram = deque(maxlen=60)
        self.membership = {}
        self.sent = deque()
        self.next_send = 0.0
        self.local_sent = OrderedDict()
        self.next_card = 0.0

    @staticmethod
    def _trim(lines, now):
        while lines and now - lines[0].created >= CHAT_TTL:
            lines.popleft()

    def add(self, room, user_id, author, text, *, telegram_id=None, thread_id=None, at=None, reply=None):
        now = time.monotonic()
        if room is None:
            lines = self.telegram
            if any(line.telegram_id == telegram_id for line in lines):
                return
        else:
            lines = self.rooms.setdefault(room, deque(maxlen=60))
            self.rooms.move_to_end(room)
            if len(self.rooms) > 256:
                self.rooms.popitem(last=False)
        self._trim(lines, now)
        quote = (reply.author, reply.text[:140], reply.telegram_id is not None) if reply else None
        lines.append(ChatLine(uuid4().hex, user_id, author, text, at if at is not None else time.time(), now,
                              telegram_id, thread_id, quote))

    def visible(self, room, telegram):
        now = time.monotonic()
        lines = self.rooms.get(room, deque())
        self._trim(lines, now)
        if not telegram:
            return list(lines)
        self._trim(self.telegram, now)
        return sorted((*lines, *self.telegram), key=lambda line: line.created)[-60:]

    def capture(self, event):
        if (
            not self.group_id or event.chat.id != self.group_id
            or event.chat.type not in {'group', 'supergroup'}
            or not event.from_user or event.from_user.is_bot or event.sender_chat
            or event.has_protected_content
            or time.time() - event.date.timestamp() >= CHAT_TTL
        ):
            return
        text = clean_stored_text(event.text or event.caption)
        if text and not text.startswith('/') and not is_command_message(text):
            if len(text) > CHAT_LENGTH:
                text = text[:CHAT_LENGTH - 1] + '…'
            self.add(None, event.from_user.id, clean_author_name(event.from_user.full_name), text,
                     telegram_id=event.message_id,
                     thread_id=event.message_thread_id if event.is_topic_message else None,
                     at=event.date.timestamp())

    async def member(self, user_id, *, fresh=False):
        if not self.group_id or self.bot is None:
            raise ValueError('Связь с группой Telegram пока недоступна.')
        now = time.monotonic()
        cached = self.membership.get(user_id)
        if cached and now < cached[0] and not fresh:
            member = cached[1]
        else:
            try:
                member = await self.bot.get_chat_member(self.group_id, user_id)
            except TelegramAPIError:
                self.membership.pop(user_id, None)
                raise ValueError('Не удалось проверить доступ к группе Telegram.') from None
            if len(self.membership) >= 512:
                self.membership = {uid: item for uid, item in self.membership.items() if item[0] > now}
                if len(self.membership) >= 512:
                    del self.membership[next(iter(self.membership))]
            self.membership[user_id] = (now + MEMBERSHIP_TTL, member)
        if member.status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED} or (
            member.status == ChatMemberStatus.RESTRICTED and not member.is_member
        ):
            raise ValueError('Общий чат доступен участникам группы Норы.')
        return member

    def snapshot(self, user_id, revision, presence, room, telegram):
        from community_bot.nora_game_api import LOBBY_TTL

        lines = self.visible(room, telegram)
        revision_now = f'{int(telegram)}-{lines[0].id}-{lines[-1].id}' if lines else f'{int(telegram)}'
        result = {'revision': revision_now}
        if revision == revision_now:
            return result
        result['messages'] = []
        now, wall_time = time.monotonic(), time.time()
        for line in lines:
            age = max(now - line.created, wall_time - line.at)
            remaining = max(0.0, BUBBLE_LIFETIME - age)
            pose = presence.get(line.user_id)
            same_room = pose and (pose[2].get('room') or 'lobby') == room
            avatar = pose[2]['nickname'] if same_room and now - pose[0] < LOBBY_TTL else None
            message = {
                'id': line.id, 'source': 'telegram' if line.telegram_id is not None else 'game',
                'author': line.author, 'text': line.text, 'time': int(line.at * 1000),
                'color': (line.user_id ^ (line.user_id >> 8)) % 10, 'mine': line.user_id == user_id,
                'avatar': avatar if remaining else None, 'bubbleMs': int(remaining * 1000),
            }
            if line.quote and (telegram or not line.quote[2]):
                message['quote'] = {'author': line.quote[0], 'text': line.quote[1]}
            result['messages'].append(message)
        return result

    def limit_local(self, user_id):
        now = time.monotonic()
        if now - self.local_sent.get(user_id, -10) < 1:
            raise ValueError('Слишком часто. Подожди немного перед отправкой.')
        self.local_sent[user_id] = now
        self.local_sent.move_to_end(user_id)
        if len(self.local_sent) > 512:
            self.local_sent.popitem(last=False)

    async def relay(self, user_id, nickname, text, *, location, gender, identity, secret, reply):
        now = time.monotonic()
        while self.sent and now - self.sent[0][0] >= 60:
            self.sent.popleft()
        if now < self.next_send or len(self.sent) >= 18 or any(
            uid == user_id and now - sent_at < 4 for sent_at, uid in self.sent
        ):
            raise ValueError('Слишком часто. Подожди немного перед отправкой.')
        self.sent.append((now, user_id))
        self.next_send = now + 1.1
        emoji = choice(PLAYER_EMOJI[gender])
        target = reply.telegram_id if reply else None
        parameters = ReplyParameters(message_id=target, allow_sending_without_reply=False) if target else None
        try:
            username = (await self.bot.me()).username
            if not username:
                raise ValueError('Ссылка на Нору пока недоступна.')
            base = f'https://t.me/{username}?startapp='
            card = f'{base}nora_card_{nickname}_{_profile_signature(nickname, secret)}'
            html = (
                f'<blockquote><b>👾<a href="{base}nora_lobby&amp;mode=fullscreen">NORA</a>'
                f' • {escape(location)}</b></blockquote>'
                f'<p>{emoji} {escape(nickname)} (<b><a href="{card}">{escape(identity)}</a></b>): {escape(text)}</p>'
            )
            sent = await self.bot.send_rich_message(
                self.group_id, rich_message=InputRichMessage(html=html, skip_entity_detection=True),
                reply_parameters=parameters,
                message_thread_id=reply.thread_id if target else None,
            )
        except TelegramRetryAfter as error:
            self.next_send = max(self.next_send, time.monotonic() + error.retry_after)
            raise ValueError('Telegram просит подождать. Попробуй позже.') from None
        except TelegramAPIError:
            raise ValueError('Telegram не подтвердил отправку сообщения.') from None
        return sent


class GameChatMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message | ChatMemberUpdated, data):
        chat = data.get('nora_game_chat')
        if chat is not None:
            if isinstance(event, Message):
                chat.capture(event)
            elif event.chat.id == chat.group_id:
                chat.membership.pop(event.new_chat_member.user.id, None)
        return await handler(event, data)


def _room(presence, user_id, location):
    from community_bot.nora_game_api import LOBBY_TTL

    if location in SOLO_LOCATIONS:
        return f'home:{user_id}', SOLO_LOCATIONS[location]
    if location not in ROOM_LABELS:
        raise ValueError('Неизвестная локация чата.')
    if location != 'lobby':
        pose = presence.get(user_id)
        if not pose or time.monotonic() - pose[0] >= LOBBY_TTL or pose[2].get('room') != location:
            raise ValueError('Подключаем чат локации. Попробуй через секунду.')
    return location, ROOM_LABELS[location]


async def feed(request):
    chat = request.app['nora_game_chat']
    user_id = request['actor']['id']
    presence = request.app['nora_lobby']
    room, _ = _room(presence, user_id, request.query.get('location', 'lobby'))
    telegram = request.query.get('telegram') == '1'
    if telegram:
        await chat.member(user_id)
    return web.json_response(chat.snapshot(user_id, request.query.get('after'), presence, room, telegram))


def _profile_signature(nickname, secret):
    return hmac.digest(secret.encode(), f'nora-chat-card:{nickname}'.encode(), 'sha256').hex()[:24]


async def profile_card(request):
    from community_bot.helpers import render_profile
    from community_bot.routers.profile import send_profile_card
    from community_bot.ui_owner import bind_ui_owner

    db, settings, chat = request.app['db'], request.app['settings'], request.app['nora_game_chat']
    actor = request['actor']['id']
    body = await request.json()
    token = body.get('card') if isinstance(body, dict) else None
    match = re.fullmatch(r'([A-Za-z]{3,16})_([a-f0-9]{24})', token) if isinstance(token, str) else None
    if not match or not hmac.compare_digest(match[2], _profile_signature(match[1], settings.bot_token)):
        raise ValueError('Ссылка на профиль недействительна.')
    await chat.member(actor, fresh=True)
    row = await db.fetchone('SELECT telegram_id FROM nora_game_players WHERE nickname = ?', (match[1],))
    user = await db.get_user(row['telegram_id']) if row else None
    if not user or user['profile_private']:
        raise ValueError('Профиль скрыт или недоступен.')
    text = await render_profile(db, settings, {**user, 'username': None}, compact=True)
    now = time.monotonic()
    if now < chat.next_card:
        raise ValueError('Подожди несколько секунд перед показом профиля.')
    chat.next_card = now + 8
    group = Chat(id=chat.group_id, type='supergroup')
    message = Message(message_id=0, date=datetime.now(UTC), chat=group).as_(chat.bot)
    try:
        sent = await send_profile_card(message, user, settings, editable=False, text=text, db=db)
    except TelegramAPIError:
        raise ValueError('Не удалось показать профиль в группе.') from None
    await bind_ui_owner(db, sent, actor, 'profile')
    return web.json_response({'ok': True})


async def send(request):
    chat = request.app['nora_game_chat']
    db, settings = request.app['db'], request.app['settings']
    user_id = request['actor']['id']
    if request.content_length is not None and request.content_length > 4096:
        raise ValueError(f'Сообщение должно содержать от 1 до {CHAT_LENGTH} символов.')
    body = await request.json()
    raw = body.get('text') if isinstance(body, dict) else None
    text = clean_stored_text(raw) if isinstance(raw, str) and len(raw) <= CHAT_LENGTH else None
    if not text:
        raise ValueError(f'Введите обычный текст от 1 до {CHAT_LENGTH} символов.')

    from community_bot.nora_game_api import _player_profile
    from community_bot.routers.group import text_moderation_reason

    profile = await _player_profile(db, user_id)
    if not profile['nickname'] or not profile['outfit']:
        raise ValueError('Сначала создай персонажа.')
    location = body.get('location', 'lobby')
    if not isinstance(location, str):
        raise ValueError('Неизвестная локация чата.')
    room, label = _room(request.app['nora_lobby'], user_id, location)
    telegram = body.get('telegram') is True
    reply = None
    if body.get('replyTo') is not None:
        reply = next((line for line in chat.visible(room, telegram) if line.id == body['replyTo']), None)
        if reply is None:
            raise ValueError('Сообщение для ответа больше недоступно.')
    chat.limit_local(user_id)
    if not telegram:
        chat.add(room, user_id, profile['nickname'], text, reply=reply)
        return web.json_response({'ok': True})

    member = await chat.member(user_id, fresh=True)
    if member.status == ChatMemberStatus.RESTRICTED and not member.can_send_messages:
        raise ValueError('Отправка сообщений ограничена в группе Telegram.')
    if member.status == ChatMemberStatus.MEMBER:
        try:
            group = await chat.bot.get_chat(chat.group_id)
        except TelegramAPIError:
            raise ValueError('Не удалось проверить права отправки в Telegram.') from None
        if group.permissions and not group.permissions.can_send_messages:
            raise ValueError('Отправка сообщений закрыта в группе Telegram.')
    if member.status not in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR} and (
        await rank_of_user(db, settings, user_id) < 40
    ):
        flags = {str(row['key']): bool(int(row['enabled'])) for row in await db.list_feature_flags()}
        activity = await db.get_activity(user_id, chat.group_id) if flags.get('raid_mode') else None
        blocked = await text_moderation_reason(
            db, settings, flags, text, (activity or {}).get('message_count', 0) + 1,
        )
        if blocked:
            raise ValueError(blocked)
    user = await db.get_user(user_id) or {}
    identity = clean_author_name(user.get('profile_name'))
    sent = await chat.relay(
        user_id, profile['nickname'], text, location=label, gender=profile['outfit'].get('gender', 'male'),
        identity=identity, secret=settings.bot_token, reply=reply,
    )
    chat.add(room, user_id, profile['nickname'], text, reply=reply)
    try:
        if await db.get_bot_state(MEMORY_NOTICE_KEY) == '1':
            await db.save_community_message(
                chat.group_id, sent.message_id, user_id, f"{profile['nickname']} (из игры)",
                text, sent.date.isoformat(),
            )
    except sqlite3.Error:
        logger.warning('Не удалось добавить сообщение из игры в память сообщества')
    return web.json_response({'ok': True})
