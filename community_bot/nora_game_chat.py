"""Short-lived chat between the NORA world and the configured Telegram group."""

import logging
import sqlite3
import time
from collections import deque
from dataclasses import dataclass
from uuid import uuid4

from aiogram import BaseMiddleware
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import ChatMemberUpdated, LinkPreviewOptions, Message
from aiohttp import web

from community_bot.aliases import is_command_message
from community_bot.chat_memory import MEMORY_NOTICE_KEY, clean_author_name, clean_stored_text
from community_bot.helpers import rank_of_user

CHAT_TTL = 30 * 60
CHAT_LENGTH = 240
BUBBLE_LIFETIME = 7
MEMBERSHIP_TTL = 30
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ChatLine:
    message_id: int
    user_id: int
    author: str
    text: str
    source: str
    at: float
    created: float


class GameChat:
    def __init__(self, bot, group_id):
        self.bot = bot
        self.group_id = group_id
        self.lines = deque(maxlen=60)
        self.revision = uuid4().hex
        self.membership = {}
        self.sent = deque()
        self.next_send = 0.0

    def _trim(self, now):
        while self.lines and now - self.lines[0].created >= CHAT_TTL:
            self.lines.popleft()
            self.revision = uuid4().hex

    def append(self, message_id, user_id, author, text, source, *, at=None):
        now = time.monotonic()
        self._trim(now)
        if any(line.message_id == message_id for line in self.lines):
            return
        self.lines.append(ChatLine(
            message_id, user_id, author, text, source, at if at is not None else time.time(), now,
        ))
        self.revision = uuid4().hex

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
            self.append(event.message_id, event.from_user.id, clean_author_name(event.from_user.full_name),
                        text, 'telegram', at=event.date.timestamp())

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

    def snapshot(self, user_id, revision, presence):
        now = time.monotonic()
        self._trim(now)
        result = {'revision': self.revision}
        if revision == self.revision:
            return result
        from community_bot.nora_game_api import LOBBY_TTL

        result['messages'] = []
        wall_time = time.time()
        for line in self.lines:
            age = max(now - line.created, wall_time - line.at)
            remaining = max(0.0, BUBBLE_LIFETIME - age)
            pose = presence.get(line.user_id)
            avatar = pose[2]['nickname'] if pose and now - pose[0] < LOBBY_TTL else None
            result['messages'].append({
                'id': line.message_id, 'source': line.source, 'author': line.author, 'text': line.text,
                'time': int(line.at * 1000), 'color': (line.user_id ^ (line.user_id >> 8)) % 10,
                'mine': line.user_id == user_id, 'avatar': avatar if remaining else None,
                'bubbleMs': int(remaining * 1000),
            })
        return result

    async def send(self, user_id, nickname, text):
        now = time.monotonic()
        while self.sent and now - self.sent[0][0] >= 60:
            self.sent.popleft()
        if now < self.next_send or len(self.sent) >= 18 or any(
            uid == user_id and now - sent_at < 4 for sent_at, uid in self.sent
        ):
            raise ValueError('Слишком часто. Подожди немного перед отправкой.')
        self.sent.append((now, user_id))
        self.next_send = now + 1.1
        try:
            sent = await self.bot.send_message(
                self.group_id, f'🎮 {nickname} · из игры Норы\n{text}', parse_mode=None,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        except TelegramRetryAfter as error:
            self.next_send = max(self.next_send, time.monotonic() + error.retry_after)
            raise ValueError('Telegram просит подождать. Попробуй позже.') from None
        except TelegramAPIError:
            raise ValueError('Telegram не подтвердил отправку сообщения.') from None
        self.append(sent.message_id, user_id, nickname, text, 'game')
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


async def feed(request):
    chat = request.app['nora_game_chat']
    user_id = request['actor']['id']
    await chat.member(user_id)
    return web.json_response(chat.snapshot(user_id, request.query.get('after'), request.app['nora_lobby']))


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
    sent = await chat.send(user_id, profile['nickname'], text)
    try:
        if await db.get_bot_state(MEMORY_NOTICE_KEY) == '1':
            await db.save_community_message(
                chat.group_id, sent.message_id, user_id, f"{profile['nickname']} (из игры)",
                text, sent.date.isoformat(),
            )
    except sqlite3.Error:
        logger.warning('Не удалось добавить сообщение из игры в память сообщества')
    return web.json_response({'ok': True})
