import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ChatMemberStatus
from aiogram.types import Chat, Message, User

from community_bot import nora_game_api, nora_game_chat
from community_bot.database import Database

GROUP = -100123


def telegram_message(message_id, text, *, user_id=23, chat_id=GROUP, date=None, bot=False, protected=False):
    return Message(
        message_id=message_id, date=date or datetime.now(UTC), text=text, has_protected_content=protected,
        from_user=User(id=user_id, is_bot=bot, first_name='Маша', last_name='Ли'),
        chat=Chat(id=chat_id, type='supergroup' if chat_id < 0 else 'private'),
    )


@pytest.mark.asyncio
async def test_chat_mirrors_only_allowed_group_text_and_keeps_private_ids_off_wire():
    chat = nora_game_chat.GameChat(None, GROUP)
    downstream = AsyncMock()
    middleware = nora_game_chat.GameChatMiddleware()
    eligible = telegram_message(1, 'Всем привет!')
    for message in (
        eligible, eligible, telegram_message(2, 'Личное', chat_id=42),
        telegram_message(3, 'Другая группа', chat_id=-100456),
        telegram_message(4, 'Текст от бота', bot=True), telegram_message(5, '/start'),
        telegram_message(6, 'Защищённое сообщение', protected=True),
        telegram_message(7, 'Реплика была минуту назад', date=datetime.now(UTC) - timedelta(minutes=1)),
    ):
        await middleware(downstream, message, {'nora_game_chat': chat})

    presence = {23: (time.monotonic(), 'session', {'nickname': 'Masha'})}
    result = chat.snapshot(42, '', presence)
    first, old = result['messages']
    assert (first['author'], first['text'], first['source'], first['avatar']) == (
        'Маша Ли', 'Всем привет!', 'telegram', 'Masha',
    )
    assert not first['mine'] and first['bubbleMs'] > 0
    assert 'user_id' not in first and 'telegram_id' not in first
    assert old['bubbleMs'] == 0 and old['avatar'] is None
    assert chat.snapshot(42, result['revision'], presence) == {'revision': result['revision']}


@pytest.mark.asyncio
async def test_game_chat_send_uses_server_nickname_and_respects_group_restrictions(tmp_path):
    db = Database(tmp_path / 'chat.db')
    await db.initialize()
    await db.ensure_user(42)
    member = SimpleNamespace(status=ChatMemberStatus.MEMBER)
    bot = SimpleNamespace(
        get_chat_member=AsyncMock(return_value=member),
        get_chat=AsyncMock(return_value=SimpleNamespace(permissions=SimpleNamespace(can_send_messages=True))),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=555)),
    )
    chat = nora_game_chat.GameChat(bot, GROUP)
    settings = SimpleNamespace(is_owner=lambda _: False, moderator_ids=frozenset(), timezone='Europe/Moscow')

    class Request(dict):
        app = {'db': db, 'settings': settings, 'nora_game_chat': chat, 'nora_lobby': {}}
        query = {}
        content_length = 64
        json = AsyncMock()

    request = Request(actor={'id': 42})
    request.json.return_value = {'nickname': 'Pixel'}
    await nora_game_api.register(request)
    request.json.return_value = {'shirt': 'gray', 'pants': 'burgundy_wide', 'shoes': 'red_air'}
    await nora_game_api.save_outfit(request)

    request.json.return_value = {'text': '<b>Привет</b>', 'author': 'быть другим', 'chat_id': 42}
    member.status = ChatMemberStatus.LEFT
    with pytest.raises(ValueError, match='участникам'):
        await nora_game_chat.feed(request)
    with pytest.raises(ValueError, match='участникам'):
        await nora_game_chat.send(request)

    member.status = ChatMemberStatus.RESTRICTED
    member.is_member, member.can_send_messages = True, False
    with pytest.raises(ValueError, match='ограничена'):
        await nora_game_chat.send(request)
    bot.send_message.assert_not_called()

    member.status = ChatMemberStatus.ADMINISTRATOR
    assert json.loads((await nora_game_chat.send(request)).text) == {'ok': True}
    bot.send_message.assert_awaited_once()
    assert bot.send_message.call_args.args == (GROUP, '🎮 Pixel · из игры Норы\n<b>Привет</b>')
    assert bot.send_message.call_args.kwargs['parse_mode'] is None
    result = json.loads((await nora_game_chat.feed(request)).text)
    assert result['messages'][0]['mine']
    assert result['messages'][0]['source'] == 'game'
    with pytest.raises(ValueError, match='Слишком часто'):
        await nora_game_chat.send(request)
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_game_chat_applies_link_filter_and_does_not_show_failed_delivery(tmp_path, monkeypatch):
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import SendMessage

    db = Database(tmp_path / 'chat.db')
    await db.initialize()
    await db.ensure_user(42)
    db.list_feature_flags = AsyncMock(return_value=[{'key': 'link_filter', 'enabled': 1}])
    bot = SimpleNamespace(
        get_chat_member=AsyncMock(return_value=SimpleNamespace(status=ChatMemberStatus.MEMBER)),
        get_chat=AsyncMock(return_value=SimpleNamespace(permissions=SimpleNamespace(can_send_messages=True))),
        send_message=AsyncMock(side_effect=TelegramBadRequest(SendMessage(chat_id=GROUP, text='test'), 'failed')),
    )
    chat = nora_game_chat.GameChat(bot, GROUP)
    settings = SimpleNamespace(is_owner=lambda _: False, moderator_ids=frozenset(), timezone='Europe/Moscow')
    monkeypatch.setattr(nora_game_api, '_player_profile', AsyncMock(return_value={'nickname': 'Pixel', 'outfit': True}))

    class Request(dict):
        app = {'db': db, 'settings': settings, 'nora_game_chat': chat}
        content_length = 64
        json = AsyncMock(return_value={'text': 'https://example.org'})

    request = Request(actor={'id': 42})
    with pytest.raises(ValueError, match='Ссылки'):
        await nora_game_chat.send(request)
    bot.send_message.assert_not_called()
    request.json.return_value = {'text': 'Просто текст'}
    with pytest.raises(ValueError, match='не подтвердил'):
        await nora_game_chat.send(request)
    assert not chat.lines
