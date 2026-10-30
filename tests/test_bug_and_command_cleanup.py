import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import Chat, Message, ReplyParameters, User

from community_bot.aliases import COMMAND_ALIASES, CommandOrAlias, is_group_command_to_sweep, parse_trigger
from community_bot.command_registry import restore_defaults
from community_bot.ephemeral import EphemeralSendMiddleware, GroupHousekeepingMiddleware, current_reply_ttl
from community_bot.routers.life import bug_message


def group_message(text, **extra):
    return Message(message_id=51, date=1_725_000_000,
                   chat=Chat(id=-100123, type='supergroup', title='Тест'),
                   from_user=User(id=7, is_bot=False, first_name='Администратор'), text=text, **extra)


@pytest.mark.parametrize('slug,alias', [(slug, alias) for slug, aliases in COMMAND_ALIASES.items()
                                      for alias in (slug, *aliases) if slug not in {'start', 'apply', 'close'}])
async def test_every_spoken_group_command_is_swept_and_replies_get_ttl(slug, alias):
    restore_defaults()
    message = group_message(alias)
    deleted = AsyncMock(return_value=True)
    assert parse_trigger(alias) == (slug, '')
    assert is_group_command_to_sweep(message)
    observed = []

    async def handle(event, data):
        observed.append(current_reply_ttl())
        assert deleted.await_count == 1

    await GroupHousekeepingMiddleware()(handle, message, {'bot': SimpleNamespace(delete_message=deleted)})
    assert observed[0] and observed[0] > 0
    assert current_reply_ttl() is None


@pytest.mark.parametrize('text', ['участники встречи пришли', 'стикеры прикольные',
                                 'Вопрос к чату: как дела?', 'Закрыть окно', 'в магазине скидки'])
def test_ordinary_sentences_are_kept(text):
    restore_defaults()
    assert not is_group_command_to_sweep(group_message(text))


async def test_recent_commands_use_shared_alias_filters():
    from community_bot.event_access import router as events
    from community_bot.routers.life import router as life

    restore_defaults()
    for router, handler_name, text in [(events, 'participants', 'Участники!'),
                                       (life, 'sticker_pack', 'Стикеры!'), (life, 'bug_message', 'Баг кнопка')]:
        handlers = [h for h in router.message.handlers if h.callback.__name__ == handler_name]
        filters = [f.callback for h in handlers for f in h.filters if isinstance(f.callback, CommandOrAlias)]
        assert len(filters) == 1
        assert await filters[0](group_message(text))


async def test_cleanup_also_wraps_profile_gate_and_reply_to_deleted_command(monkeypatch):
    from aiogram.methods import SendMessage

    from community_bot.access import ProfileAccessMiddleware

    restore_defaults()
    message = group_message('магазин')
    delete = AsyncMock(return_value=True)
    sent, scheduled = [], []
    bot = SimpleNamespace(delete_message=delete)

    async def expire(message, delay):
        scheduled.append((message.message_id, delay))

    monkeypatch.setattr('community_bot.ephemeral.delete_later', expire)

    async def request(bot, method):
        sent.append(method)
        return group_message('Сначала профиль').model_copy(update={'message_id': 90})

    async def answer(self, text, **kwargs):
        return await EphemeralSendMiddleware()(request, bot, SendMessage(chat_id=self.chat.id, text=text))

    monkeypatch.setattr(Message, 'answer', answer)
    db = SimpleNamespace(get_user=AsyncMock(return_value={'user_id': 7}))
    handle = AsyncMock()

    async def profile(event, data):
        await ProfileAccessMiddleware()(handle, event, data)
        await EphemeralSendMiddleware()(request, bot, SendMessage(
            chat_id=event.chat.id, text='Служебный ответ',
            reply_parameters=ReplyParameters(message_id=event.message_id),
        ))

    await GroupHousekeepingMiddleware()(profile, message, {'db': db, 'bot': bot})
    await asyncio.sleep(0)
    handle.assert_not_awaited()
    delete.assert_awaited_once_with(message.chat.id, message.message_id)
    assert len(scheduled) == 2 and all(ttl > 0 for _, ttl in scheduled)
    assert sent[-1].reply_parameters.allow_sending_without_reply is True


async def test_bug_permissions_reply_required_and_media_snapshot_survives_source_deletion(tmp_path):
    import json

    from community_bot.database import Database

    db = Database(tmp_path / 'bugs.sqlite3')
    await db.initialize()
    settings = SimpleNamespace(owner_ids={7}, moderator_ids=set(), is_owner=lambda uid: uid == 7)
    fake = SimpleNamespace(from_user=User(id=8, is_bot=False, first_name='Участник'), answer=AsyncMock())
    await bug_message(fake, db, settings)
    assert 'администраторам' in fake.answer.call_args.args[0]
    assert await db.list_pending_reports() == []
    fake.from_user = User(id=7, is_bot=False, first_name='Владелец')
    fake.reply_to_message = None
    await bug_message(fake, db, settings)
    assert 'Ответьте' in fake.answer.call_args.args[0]
    assert await db.list_pending_reports() == []
    source = group_message(None, caption='<broken button> ' + 'т' * 2000,
                           photo=[{'file_id': 'saved-photo', 'file_unique_id': 'one', 'width': 40, 'height': 40}])
    fake.reply_to_message, fake.chat, fake.text, fake.caption = source, source.chat, 'баг кнопка не отвечает', None
    await bug_message(fake, db, settings)
    row, = await db.list_pending_reports()
    assert row['text'] == source.caption  # Not the old 1000-character truncation.
    assert row['reason'] == 'БАГ · кнопка не отвечает'
    assert row['message_id'] == source.message_id and row['chat_id'] == source.chat.id
    assert json.loads(await db.get_bot_state(f"report_attachment:{row['id']}")) == ['photo', 'saved-photo']
    assert 'сохранён' in fake.answer.call_args.args[0]
    reopened = Database(db.path)
    assert (await reopened.list_pending_reports())[0]['text'] == source.caption


async def test_bug_on_bot_and_anonymous_messages_is_allowed(tmp_path):
    from community_bot.database import Database

    db = Database(tmp_path / 'bot-bugs.sqlite3')
    await db.initialize()
    settings = SimpleNamespace(owner_ids={7}, moderator_ids=set(), is_owner=lambda uid: uid == 7)
    for author in (User(id=123456, is_bot=True, first_name='Нора'), None):
        source = group_message('Ошибка').model_copy(update={'from_user': author})
        fake = SimpleNamespace(from_user=User(id=7, is_bot=False, first_name='Владелец'),
                               reply_to_message=source, chat=source.chat, text='баг', caption=None, answer=AsyncMock())
        await bug_message(fake, db, settings)
    assert len(await db.list_pending_reports()) == 2


@pytest.mark.parametrize('text', ['+реп', 'поддерживаю', 'ненавижу', 'перевести 5 печенек', 'передать 1 🍪'])
def test_reputation_and_transfer_words_are_commands_only_when_replying(text):
    message = group_message(text)
    assert not is_group_command_to_sweep(message)
    assert is_group_command_to_sweep(message.model_copy(update={'reply_to_message': group_message('Оригинал')}))


async def test_bot_reply_cleanup_does_not_touch_private_chat_or_published_posts(monkeypatch):
    from community_bot.ephemeral import keep_in_chat, reply_ttl

    scheduled = []

    async def expire(message, delay):
        scheduled.append((message.chat.id, delay))

    monkeypatch.setattr('community_bot.ephemeral.delete_later', expire)

    async def request(bot, method):
        return method

    group = group_message('Ответ')
    private = group.model_copy(update={'chat': Chat(id=7, type='private')})
    middleware = EphemeralSendMiddleware()
    with reply_ttl(30):
        await middleware(request, None, group)
        await middleware(request, None, private)
        with keep_in_chat():
            await middleware(request, None, group)
    await asyncio.sleep(0)
    assert scheduled == [(group.chat.id, 30)]
