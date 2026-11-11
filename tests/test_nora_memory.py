from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update, User
from test_nora_commands_release import message
from test_studio_rsvp import TelegramSession

from community_bot import chat_memory, openrouter_chat
from community_bot.command_registry import restore_defaults
from community_bot.config import load_settings
from community_bot.database import Database
from community_bot.memory_capture import CommunityMemoryMiddleware
from community_bot.routers import group as group_module
from community_bot.routers import nora as nora_module


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv('PYTHON_DOTENV_DISABLED', '1')
    monkeypatch.setenv('BOT_TOKEN', '123456:test')
    monkeypatch.setenv('OWNER_ID', '1')
    monkeypatch.setenv('MODERATOR_IDS', '2')
    monkeypatch.setenv('COMMUNITY_CHAT_ID', '-100123')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    monkeypatch.delenv('OPENROUTER_MODEL', raising=False)
    return load_settings()


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / 'nora-memory.db')
    await database.initialize()
    return database


@pytest.fixture
def clock(monkeypatch):
    current = SimpleNamespace(now=1800000000)
    fake_time = SimpleNamespace(time=lambda: current.now, monotonic=lambda: current.now)
    monkeypatch.setattr(openrouter_chat, 'time', fake_time)
    return current


def bot_message(text, message_id, chat_id=-100123):
    chat_type = 'private' if chat_id > 0 else 'supergroup'
    return Message(
        message_id=message_id,
        date=1725000000,
        chat=Chat(id=chat_id, type=chat_type),
        from_user=User(id=123456, is_bot=True, first_name='Нора'),
        text=text,
    )


def yesterday_noon_utc():
    local_now = datetime.now(ZoneInfo('Europe/Moscow'))
    start = (local_now - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    return start.astimezone(UTC)


async def seed_yesterday(db):
    sent = yesterday_noon_utc().isoformat()
    await db.save_community_message(
        -100123, 201, 7, 'Анна', 'Вчера обсуждали кино про Петербург и выбрали комедию', sent, thread_id=12,
    )
    await db.save_community_message(
        -100123, 202, 8, 'Коля', 'Погода в Петербурге сегодня дождливая', sent, thread_id=12,
    )
    await db.save_community_message(
        -100999, 203, 7, 'Анна', 'Вчера обсуждали кино в другом чате', sent, thread_id=12,
    )
    await db.save_community_message(
        -100123, 204, 8, 'Коля', 'Вчера обсуждали кино в другой теме', sent, thread_id=99,
    )
    return sent


async def test_save_and_search_fts_and_thread(db):
    base = yesterday_noon_utc()
    t1 = base.isoformat()
    t2 = (base + timedelta(minutes=1)).isoformat()
    t3 = (base + timedelta(minutes=2)).isoformat()
    assert await db.save_community_message(-100123, 301, 7, 'Анна', 'Обсуждали кино про Петербург', t1, thread_id=12)
    assert await db.save_community_message(-100123, 302, 8, 'Коля', 'Погода и прогулка', t2, thread_id=12)
    assert await db.save_community_message(-100123, 303, 8, 'Коля', 'Кино в другой теме', t3, thread_id=99)
    rows = await db.search_community_messages(-100123, 'кино*')
    assert [row['message_id'] for row in rows] == [301, 303]
    rows = await db.search_community_messages(-100123, 'кино*', thread_id=12)
    assert [row['message_id'] for row in rows] == [301]
    rows = await db.search_community_messages(-100123, 'кино*', thread_id=99)
    assert [row['message_id'] for row in rows] == [303]
    await db.update_community_message(-100123, 301, 'Теперь обсуждали театр')
    rows = await db.search_community_messages(-100123, 'кино*')
    assert [row['message_id'] for row in rows] == [303]
    rows = await db.search_community_messages(-100123, 'театр*')
    assert [row['message_id'] for row in rows] == [301]
    await db.delete_community_message(-100123, 303)
    rows = await db.search_community_messages(-100123, 'кино*')
    assert rows == []
    long_text = 'x' * 1500
    assert await db.save_community_message(-100123, 304, 7, 'Анна', long_text, t3)
    rows = await db.recent_community_messages(-100123, since=(base - timedelta(hours=1)).isoformat(), limit=10)
    saved = [row for row in rows if row['message_id'] == 304][0]
    assert len(saved['text']) == 1000
    assert not await db.save_community_message(-100123, 305, 7, 'Анна', 'api_key: secret123456789', t3)
    rows = await db.recent_community_messages(-100123, since=(base - timedelta(hours=1)).isoformat(), limit=10)
    assert all(row['message_id'] != 305 for row in rows)


async def test_cleanup_expires_after_48_hours_and_fts(db):
    now = datetime.now(UTC)
    old = (now - timedelta(hours=49)).isoformat()
    await db.save_community_message(-100123, 401, 7, 'Анна', 'Свежее кино', (now - timedelta(hours=2)).isoformat())
    await db.execute(
        'INSERT INTO community_messages(chat_id, message_id, user_id, author_name, text, sent_at) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (-100123, 402, 7, 'Анна', 'Очень старое кино', old),
    )
    rows = await db.search_community_messages(-100123, 'кино*')
    assert {row['message_id'] for row in rows} == {401, 402}
    deleted = await db.cleanup_community_messages(now=now)
    assert deleted >= 1
    rows = await db.search_community_messages(-100123, 'кино*')
    assert [row['message_id'] for row in rows] == [401]
    assert not await db.save_community_message(-100123, 403, 7, 'Анна', 'Слишком старое', old)


async def test_cleanup_caps_archive(db, monkeypatch):
    monkeypatch.setattr(chat_memory, 'MAX_ARCHIVE_ROWS', 2)
    now = datetime.now(UTC)
    for mid, minutes in [(501, 3), (502, 2), (503, 1), (504, 0)]:
        sent = (now - timedelta(minutes=minutes)).isoformat()
        await db.save_community_message(-100123, mid, 7, 'Анна', 'Сообщение про кино', sent)
    deleted = await db.cleanup_community_messages(now=now)
    assert deleted == 2
    rows = await db.recent_community_messages(-100123, since=(now - timedelta(days=1)).isoformat())
    assert [row['message_id'] for row in rows] == [503, 504]


def test_context_is_limited_to_2000_chars():
    rows = [{'author_name': 'Анна', 'text': 'слово ' * 100, 'sent_at': '2026-11-09T12:00:00+00:00'} for _ in range(10)]
    context = chat_memory.format_context(rows)
    assert context
    assert len(context) <= 2000
    prompt = chat_memory.build_memory_prompt('что вчера обсуждали?', context)
    assert len(prompt) <= 2000


def test_memory_question_detection_and_windows():
    assert chat_memory.is_memory_question('что вчера обсуждали?')
    assert chat_memory.is_memory_question('Нора, что позавчера обсуждали?')
    assert not chat_memory.is_memory_question('как настроение?')
    assert not chat_memory.is_memory_question('расскажи шутку')
    now = datetime(2026, 11, 10, 12, 0, tzinfo=ZoneInfo('Europe/Moscow'))
    start, end = chat_memory.parse_time_window('что вчера обсуждали?', now)
    assert start == datetime(2026, 11, 9, 0, 0, tzinfo=ZoneInfo('Europe/Moscow'))
    assert end == datetime(2026, 11, 10, 0, 0, tzinfo=ZoneInfo('Europe/Moscow'))
    start2, end2 = chat_memory.parse_time_window('что позавчера обсуждали?', now)
    assert start2.day == 8
    assert end2.day == 9
    assert chat_memory.parse_time_window('как дела?', now) is None


async def test_memory_prompt_uses_only_community_thread(db, settings):
    await seed_yesterday(db)
    chat = openrouter_chat.OpenRouterChat(db, settings)
    event = message('Нора, что вчера обсуждали про кино?', uid=1, is_topic_message=True, message_thread_id=12)
    prompt = await chat.memory_prompt('что вчера обсуждали про кино?', event)
    assert prompt is not None
    assert len(prompt) <= 2000
    assert 'кино про Петербург' in prompt
    assert 'другом чате' not in prompt
    assert 'другой теме' not in prompt
    private = message('Нора, что вчера обсуждали про кино?', uid=1, chat_id=1)
    assert await chat.memory_prompt('что вчера обсуждали про кино?', private) is None


async def test_memory_prompt_returns_none_without_data(db, settings):
    chat = openrouter_chat.OpenRouterChat(db, settings)
    event = message('Нора, что позавчера обсуждали?', uid=1)
    assert await chat.memory_prompt('что позавчера обсуждали?', event) is None


async def test_today_recap_uses_chat_messages_instead_of_matching_itself(db, settings):
    now = datetime.now(UTC).replace(microsecond=0)
    body = 'че сегодня интересного в чате было?'
    event = message(f'Нора, {body}', uid=1, is_topic_message=True, message_thread_id=12)
    event = event.model_copy(update={'date': now})
    chat = openrouter_chat.OpenRouterChat(db, settings)
    await db.set_bot_state('nora_memory_notice_v1', '1')

    async def handler(message, data):
        return await chat.memory_prompt(body, message)

    data = {'db': db, 'settings': settings}
    middleware = CommunityMemoryMiddleware()
    await db.save_community_message(event.chat.id, 9, 1, 'Роман', event.text, now.isoformat(), thread_id=12)
    assert await middleware(handler, event, data) is None
    await db.save_community_message(
        event.chat.id, 10, 7, 'Анна', 'Договорились встретиться у Финляндского вокзала', now.isoformat(), thread_id=12,
    )
    await db.save_community_message(
        event.chat.id, 11, 8, 'Иван', 'В другой теме обсуждали выставку', now.isoformat(), thread_id=99,
    )
    prompt = await middleware(handler, event, data)
    assert prompt is not None
    context, question = prompt.split('\n\nВопрос: ', 1)
    assert 'Финляндского вокзала' in context
    assert 'выставку' not in context
    assert 'интересного' not in context
    assert question.startswith(body)


async def test_middleware_saves_only_community_text(db, settings):
    middleware = CommunityMemoryMiddleware()
    async def handler(event, data):
        return 'handled'
    recent = datetime.now(UTC)
    next_id = [601]
    async def feed(text, uid=7, chat_id=-100123, **extra):
        mid = next_id[0]
        next_id[0] += 1
        event = message(text, uid=uid, chat_id=chat_id, **extra)
        event = event.model_copy(update={'date': recent, 'message_id': mid})
        result = await middleware(handler, event, {'db': db, 'settings': settings, 'bot': None})
        assert result == 'handled'
        return mid
    await feed('Сообщение до публикации уведомления')
    since = (recent - timedelta(hours=1)).isoformat()
    rows = await db.recent_community_messages(-100123, since=since)
    assert rows == []
    await db.set_bot_state('nora_memory_notice_v1', '1')
    await feed('Привет, обсуждаем кино')
    since = (recent - timedelta(hours=1)).isoformat()
    rows = await db.recent_community_messages(-100123, since=since)
    assert len(rows) == 1
    assert rows[0]['text'] == 'Привет, обсуждаем кино'
    assert rows[0]['author_name'] == 'Участник 7'
    await feed('Приватный текст', chat_id=7)
    await feed('Другой чат', chat_id=-100999)
    await feed('api_key: secret123456789')
    rows = await db.recent_community_messages(-100123, since=since)
    assert len(rows) == 1
    bot_event = Message(
        message_id=650,
        date=recent,
        chat=Chat(id=-100123, type='supergroup'),
        from_user=User(id=999, is_bot=True, first_name='Бот'),
        text='Сообщение бота',
    )
    await middleware(handler, bot_event, {'db': db, 'settings': settings, 'bot': None})
    rows = await db.recent_community_messages(-100123, since=since)
    assert len(rows) == 1


async def test_middleware_updates_edited_message(db, settings):
    await db.set_bot_state('nora_memory_notice_v1', '1')
    middleware = CommunityMemoryMiddleware()
    async def handler(event, data):
        return 'handled'
    recent = datetime.now(UTC)
    event = message('Первая версия', uid=7)
    event = event.model_copy(update={'date': recent, 'message_id': 701})
    await middleware(handler, event, {'db': db, 'settings': settings, 'bot': None})
    edited = message('Исправленная версия', uid=7, edit_date=int(recent.timestamp()))
    edited = edited.model_copy(update={'date': recent, 'message_id': 701})
    await middleware(handler, edited, {'db': db, 'settings': settings, 'bot': None})
    rows = await db.recent_community_messages(-100123, since=(recent - timedelta(hours=1)).isoformat())
    assert [row['text'] for row in rows if row['message_id'] == 701] == ['Исправленная версия']
    await db.delete_community_message(-100123, 701)
    rows = await db.search_community_messages(-100123, 'Исправленная*')
    assert rows == []


def test_retention_notice_marks_periods_beyond_48_hours():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime(2026, 11, 13, 12, 0, tzinfo=ZoneInfo('Europe/Moscow'))
    assert chat_memory.retention_notice('что вчера обсуждали?', now) is None
    assert chat_memory.retention_notice('что сегодня обсуждали?', now) is None
    assert chat_memory.retention_notice('что позавчера обсуждали?', now)
    assert chat_memory.retention_notice('что на этой неделе обсуждали?', now)
    assert chat_memory.retention_notice('что на прошлой неделе обсуждали?', now)
    window = chat_memory.parse_time_window('что на прошлой неделе обсуждали?', now)
    assert window is not None
    assert window[0] < window[1] <= now


async def test_release_snapshot_contains_no_memory_text(db, tmp_path):
    from community_bot.release_backup import _snapshot

    marker = 'УникальныйМаркерБэкапа123'
    sent = datetime.now(UTC).isoformat()
    assert await db.save_community_message(-100123, 801, 7, 'Анна', f'Обсуждали {marker} подробно', sent)
    backup = tmp_path / 'backup.sqlite3'
    _snapshot(db.path, backup)
    assert marker.encode('utf-8') not in backup.read_bytes()
    restored = Database(backup)
    since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert await restored.recent_community_messages(-100123, since=since) == []
    assert await restored.search_community_messages(-100123, 'УникальныйМаркерБэкапа123*') == []


async def test_memory_question_in_dispatcher(db, settings, clock, monkeypatch):
    restore_defaults()
    for uid in (1, 2, 7, 8):
        await db.ensure_user(uid, telegram_name=f'Участник {uid}')
    await db.execute('UPDATE users SET reputation = 80 WHERE user_id IN (1, 8)')
    await seed_yesterday(db)
    session = TelegramSession()
    bot = Bot(settings.bot_token, session=session)
    monkeypatch.setattr(bot, 'get_chat_member', AsyncMock(return_value=SimpleNamespace(status='member')))
    monkeypatch.setattr('community_bot.access.sync_menu', AsyncMock())
    monkeypatch.setattr('community_bot.routers.private.flow_reply_keyboard', lambda: None)
    dispatcher = Dispatcher()
    for source in (nora_module.router, group_module.router, nora_module.assistant_router):
        isolated = Router()
        isolated.message.handlers.extend(source.message.handlers)
        dispatcher.include_router(isolated)
    chat = openrouter_chat.OpenRouterChat(db, settings)
    request = AsyncMock(return_value='Вчера обсуждали кино, выбрали комедию.')
    monkeypatch.setattr(chat, '_request', request)
    history_calls = []
    async def fake_history(history, prompt):
        history_calls.append((list(history), prompt))
        return 'Продолжаю: вчера кино.'
    monkeypatch.setattr(chat, '_request_history', fake_history)
    dispatcher['openrouter_chat'] = chat
    async def dispatch(text, uid=1, chat_id=-100123, **extra):
        event = message(text, uid=uid, chat_id=chat_id, **extra)
        event = event.model_copy(update={'message_id': len(session.calls) + 51})
        session.calls.clear()
        await dispatcher.feed_update(bot, Update(update_id=event.message_id, message=event), db=db, settings=settings)
        return event
    def replies():
        return [call for call in session.calls if isinstance(call, SendMessage)]
    try:
        await dispatch('Нора, что вчера обсуждали про кино?', uid=1)
        assert replies()
        assert replies()[0].text == 'Вчера обсуждали кино, выбрали комедию.'
        ai_id = session.message_id
        assert request.await_count == 1
        sent_prompt = request.await_args.args[0]
        assert len(sent_prompt) <= 2000
        assert 'кино про Петербург' in sent_prompt
        assert 'другом чате' not in sent_prompt
        clock.now += 6
        await dispatch('Нора, что вчера обсуждали про кино?', uid=7)
        assert not replies()
        assert request.await_count == 1
        clock.now += 6
        reply_msg = bot_message('Вчера обсуждали кино, выбрали комедию.', ai_id)
        await dispatch('а что вчера обсуждали про кино?', uid=1, reply_to_message=reply_msg)
        assert len(history_calls) == 1
        assert 'кино про Петербург' in history_calls[0][1]
        assert replies()
        assert replies()[0].text == 'Продолжаю: вчера кино.'
        clock.now += 6
        await dispatch('Нора, что позавчера обсуждали?', uid=1)
        assert replies()
        assert 'ничего не нашла' in replies()[0].text
        assert request.await_count == 1
        assert len(history_calls) == 1
    finally:
        restore_defaults()
        await dispatcher.storage.close()
        await bot.session.close()
