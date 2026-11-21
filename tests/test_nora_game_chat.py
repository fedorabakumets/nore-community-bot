import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ChatMemberStatus
from aiogram.types import Chat, Message, User

from community_bot import nora_game_api, nora_game_chat
from community_bot.chat_memory import MEMORY_NOTICE_KEY
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
    result = chat.snapshot(42, '', presence, 'lobby', True)
    first, old = result['messages']
    assert (first['author'], first['text'], first['source'], first['avatar']) == (
        'Маша Ли', 'Всем привет!', 'telegram', 'Masha',
    )
    assert not first['mine'] and 0 < first['bubbleMs'] < first['previewMs'] <= 12_000
    assert 'user_id' not in first and 'telegram_id' not in first
    assert old['bubbleMs'] == old['previewMs'] == 0 and old['avatar'] is None
    assert chat.snapshot(42, result['revision'], presence, 'lobby', True) == {'revision': result['revision']}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('location', 'label', 'gender', 'pose'),
    [
        ('cinema', 'Кинотеатр • 🎬', 'female', {'room': 'cinema'}),
        ('lobby', 'ЛОББИ • 🌎', 'male', {}),
    ],
)
async def test_game_chat_send_uses_server_nickname_and_respects_group_restrictions(
    tmp_path, location, label, gender, pose,
):
    db = Database(tmp_path / 'chat.db')
    await db.initialize()
    await db.ensure_user(42)
    await db.update_profile(42, 'profile_name', 'Имя <Норы>')
    member = SimpleNamespace(status=ChatMemberStatus.MEMBER)
    bot = SimpleNamespace(
        get_chat_member=AsyncMock(return_value=member),
        get_chat=AsyncMock(return_value=SimpleNamespace(permissions=SimpleNamespace(can_send_messages=True))),
        me=AsyncMock(return_value=SimpleNamespace(username='test_nora')),
        send_rich_message=AsyncMock(return_value=SimpleNamespace(message_id=555, date=datetime.now(UTC))),
    )
    chat = nora_game_chat.GameChat(bot, GROUP)
    settings = SimpleNamespace(is_owner=lambda _: False, moderator_ids=frozenset(), timezone='Europe/Moscow',
                               bot_token='test-key')

    class Request(dict):
        app = {'db': db, 'settings': settings, 'nora_game_chat': chat, 'nora_lobby': {}}
        query = {'telegram': '1', 'location': location}
        content_length = 64
        json = AsyncMock()

    request = Request(actor={'id': 42, 'username': 'telegram_unused'})
    request.json.return_value = {'nickname': 'Pixel'}
    await nora_game_api.register(request)
    request.json.return_value = {
        'shirt': 'gray', 'pants': 'burgundy_wide', 'shoes': 'red_air', 'gender': gender,
    }
    await nora_game_api.save_outfit(request)

    chat.capture(telegram_message(777, 'Оригинал').model_copy(
        update={'is_topic_message': True, 'message_thread_id': 123},
    ))
    reply_id = chat.telegram[0].id
    request.app['nora_lobby'][42] = (time.monotonic(), 'session', {'nickname': 'Pixel', **pose})
    request.json.return_value = {'text': '<b>Привет</b>', 'location': location, 'telegram': True, 'replyTo': reply_id}
    member.status = ChatMemberStatus.LEFT
    with pytest.raises(ValueError, match='участникам'):
        await nora_game_chat.feed(request)
    with pytest.raises(ValueError, match='участникам'):
        await nora_game_chat.send(request)

    member.status = ChatMemberStatus.RESTRICTED
    member.is_member, member.can_send_messages = True, False
    chat.local_sent.clear()
    with pytest.raises(ValueError, match='ограничена'):
        await nora_game_chat.send(request)
    bot.send_rich_message.assert_not_called()

    member.status = ChatMemberStatus.ADMINISTRATOR
    await db.set_bot_state(MEMORY_NOTICE_KEY, '1')
    chat.local_sent.clear()
    assert json.loads((await nora_game_chat.send(request)).text) == {'ok': True}
    bot.send_rich_message.assert_awaited_once()
    assert bot.send_rich_message.call_args.args == (GROUP,)
    kwargs = bot.send_rich_message.call_args.kwargs
    html = kwargs['rich_message'].html
    assert (
        '<blockquote><b>👾<a href="https://t.me/test_nora?startapp=nora_lobby&amp;mode=fullscreen">'
        f'NORA</a> • {label}</b></blockquote>'
    ) in html
    assert any(f'<p>{emoji} Pixel (' in html for emoji in nora_game_chat.PLAYER_EMOJI[gender])
    assert '">Имя &lt;Норы&gt;</a></b>): &lt;b&gt;Привет&lt;/b&gt;</p>' in html
    assert 'telegram_unused' not in html
    assert kwargs['reply_parameters'].message_id == 777
    assert kwargs['reply_parameters'].allow_sending_without_reply is False
    assert kwargs['message_thread_id'] == 123
    result = json.loads((await nora_game_chat.feed(request)).text)
    assert result['messages'][-1]['mine']
    assert result['messages'][-1]['source'] == 'game'
    assert result['messages'][-1]['quote']['text'] == 'Оригинал'
    assert 'quote' not in chat.snapshot(42, '', {}, location, False)['messages'][0]
    rows = await db.search_community_messages(GROUP, 'Привет')
    assert [(row['author_name'], row['text']) for row in rows] == [('Pixel (из игры)', '<b>Привет</b>')]
    with pytest.raises(ValueError, match='Слишком часто'):
        await nora_game_chat.send(request)
    bot.send_rich_message.assert_awaited_once()


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
        me=AsyncMock(return_value=SimpleNamespace(username='test_nora')),
        send_rich_message=AsyncMock(side_effect=TelegramBadRequest(SendMessage(chat_id=GROUP, text='test'), 'failed')),
    )
    chat = nora_game_chat.GameChat(bot, GROUP)
    settings = SimpleNamespace(is_owner=lambda _: False, moderator_ids=frozenset(), timezone='Europe/Moscow',
                               bot_token='test-key')
    profile = {'nickname': 'Pixel', 'outfit': {'gender': 'male'}}
    monkeypatch.setattr(nora_game_api, '_player_profile', AsyncMock(return_value=profile))

    class Request(dict):
        app = {'db': db, 'settings': settings, 'nora_game_chat': chat, 'nora_lobby': {}}
        content_length = 64
        json = AsyncMock(return_value={'text': 'https://example.org', 'telegram': True})

    request = Request(actor={'id': 42})
    with pytest.raises(ValueError, match='Ссылки'):
        await nora_game_chat.send(request)
    bot.send_rich_message.assert_not_called()
    chat.local_sent.clear()
    request.json.return_value = {'text': 'Просто текст', 'telegram': True}
    with pytest.raises(ValueError, match='не подтвердил'):
        await nora_game_chat.send(request)
    assert not chat.visible('lobby', False)

@pytest.mark.asyncio
async def test_local_send_and_replies_stay_in_room_without_telegram(tmp_path, monkeypatch):
    db = Database(tmp_path / 'local.db')
    await db.initialize()
    bot = SimpleNamespace(get_chat_member=AsyncMock(), send_rich_message=AsyncMock())
    chat = nora_game_chat.GameChat(bot, GROUP)
    chat.add('home:81', 81, 'Other', 'Личный текст')
    chat.add('home:42', 42, 'Pixel', 'Начало диалога')
    chat.add('lobby', 42, 'Pixel', 'Фраза из лобби')
    chat.capture(telegram_message(222, 'Из группы'))
    profile = {'nickname': 'Pixel', 'outfit': {'gender': 'female'}}
    monkeypatch.setattr(nora_game_api, '_player_profile', AsyncMock(return_value=profile))

    class Request(dict):
        app = {'db': db, 'settings': None, 'nora_game_chat': chat, 'nora_lobby': {}}
        query = {'location': 'forest'}
        content_length = 64
        json = AsyncMock()

    request = Request(actor={'id': 42})
    result = json.loads((await nora_game_chat.feed(request)).text)
    original, = result['messages']
    assert original['text'] == 'Начало диалога'
    request.json.return_value = {'text': 'Ответ', 'location': 'forest', 'replyTo': chat.telegram[0].id}
    with pytest.raises(ValueError, match='недоступно'):
        await nora_game_chat.send(request)
    request.json.return_value['replyTo'] = original['id']
    assert json.loads((await nora_game_chat.send(request)).text) == {'ok': True}
    result = json.loads((await nora_game_chat.feed(request)).text)
    assert result['messages'][-1]['quote'] == {'author': 'Pixel', 'text': 'Начало диалога'}
    assert [line.text for line in chat.visible('lobby', False)] == ['Фраза из лобби']
    assert [line.text for line in chat.visible('home:81', False)] == ['Личный текст']
    bot.get_chat_member.assert_not_called()
    bot.send_rich_message.assert_not_called()


@pytest.mark.asyncio
async def test_signed_profile_link_posts_public_profile_in_configured_group(tmp_path):
    db = Database(tmp_path / 'profiles.db')
    await db.initialize()
    await db.ensure_user(42, 'hidden_handle', 'Имя из Telegram')
    await db.update_profile(42, 'profile_name', 'Имя Норы')
    await db.execute('INSERT INTO nora_game_players (telegram_id, nickname) VALUES (?, ?)', (42, 'Pixel'))
    bot = SimpleNamespace(
        get_chat_member=AsyncMock(return_value=SimpleNamespace(status=ChatMemberStatus.MEMBER)),
        me=AsyncMock(return_value=SimpleNamespace(username='nora_bot')),
        send_rich_message=AsyncMock(return_value=telegram_message(99, None, bot=True)),
    )
    chat = nora_game_chat.GameChat(bot, GROUP)
    settings = SimpleNamespace(bot_token='testing', restricted_reputation_threshold=15)

    class Request(dict):
        app = {'db': db, 'settings': settings, 'nora_game_chat': chat}
        json = AsyncMock()

    request = Request(actor={'id': 81})
    request.json.return_value = {'card': 'Pixel_' + '0' * 24}
    with pytest.raises(ValueError, match='недействительна'):
        await nora_game_chat.profile_card(request)

    token = nora_game_chat._profile_signature('Pixel', settings.bot_token)
    request.json.return_value = {'card': f'Pixel_{token}', 'chat_id': 42}
    await db.update_profile(42, 'profile_private', 1)
    with pytest.raises(ValueError, match='скрыт'):
        await nora_game_chat.profile_card(request)
    bot.send_rich_message.assert_not_called()

    await db.update_profile(42, 'profile_private', 0)
    result = await nora_game_chat.profile_card(request)
    assert json.loads(result.text) == {'ok': True}
    assert bot.send_rich_message.call_args.args[0] == GROUP
    card = bot.send_rich_message.call_args.kwargs['rich_message']
    assert card.blocks[1].text[0].text == 'Имя Норы'
    assert 'hidden_handle' not in card.model_dump_json()
