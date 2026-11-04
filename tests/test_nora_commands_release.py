from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Dispatcher, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.types import CallbackQuery, Chat, Message, PhotoSize, Update, User

from community_bot.aliases import CommandOrAlias, is_group_command_to_sweep, parse_trigger
from community_bot.command_registry import restore_defaults
from community_bot.database import Database
from community_bot.domain import NEGATIVE_REPUTATION_PHRASES, POSITIVE_REPUTATION_PHRASES, reputation_delta
from community_bot.ephemeral import GroupHousekeepingMiddleware, current_reply_ttl
from community_bot.routers.flows import send_update_to_dm, switch_update_page
from community_bot.routers.group import group_reply_actions
from community_bot.routers.nora import nora_address
from community_bot.updates import latest_update, update_keyboard, update_page


def message(text, uid=7, chat_id=-100123, **extra):
    return Message(
        message_id=51, date=1725000000,
        chat=Chat(id=chat_id, type='private' if chat_id > 0 else 'supergroup'),
        from_user=User(id=uid, is_bot=False, first_name=f'Участник {uid}'), text=text, **extra,
    )


@pytest.mark.parametrize('prefix', ['Нора ', 'нора ', 'Нора, ', 'нора,', 'НОРА, '])
async def test_addressed_commands_route_past_assistant(prefix):
    restore_defaults()
    event = message(prefix + 'профиль')
    assert await CommandOrAlias('profile')(event)
    assert parse_trigger(event.text) == ('profile', '')
    assert is_group_command_to_sweep(event)
    with pytest.raises(SkipHandler):
        await nora_address(event, SimpleNamespace())


@pytest.mark.parametrize('text', ['профиль', 'команды', '/profile', 'магазин', 'перевести 5'])
async def test_unaddressed_group_commands_are_ordinary_text(text):
    restore_defaults()
    event = message(text)
    assert not await CommandOrAlias('profile', 'commands', 'shop', 'transfer')(event)
    assert not is_group_command_to_sweep(event)
    assert await CommandOrAlias('profile', 'commands', 'shop', 'transfer')(message(text, chat_id=7))


@pytest.mark.parametrize('phrase', sorted(POSITIVE_REPUTATION_PHRASES | NEGATIVE_REPUTATION_PHRASES))
async def test_reputation_is_exact_and_never_swept(phrase):
    assert reputation_delta(phrase) == (5 if phrase in POSITIVE_REPUTATION_PHRASES else -5)
    for text in [phrase + ' пояснение', 'пояснение ' + phrase, 'Нора ' + phrase]:
        assert reputation_delta(text) is None
    event = message(phrase, reply_to_message=message('Оригинал', uid=8))
    bot = SimpleNamespace(delete_message=AsyncMock())

    async def handle(event, data):
        assert current_reply_ttl() is None

    await GroupHousekeepingMiddleware()(handle, event, {'bot': bot})
    bot.delete_message.assert_not_awaited()


async def test_actual_reputation_reply_survives_and_changes_sqlite(tmp_path, monkeypatch):
    db = Database(tmp_path / 'reputation.db')
    await db.initialize()
    for uid in (7, 8):
        await db.ensure_user(uid, telegram_name=f'Участник {uid}')
    await db.execute('UPDATE users SET reputation = 80 WHERE user_id IN (7, 8)')
    replies = []

    async def reply(self, text, **kwargs):
        replies.append((text, current_reply_ttl()))

    monkeypatch.setattr(Message, 'reply', reply)
    settings = SimpleNamespace(timezone='Europe/Moscow', restricted_reputation_threshold=0)
    event = message('не согласен', reply_to_message=message('Оригинал', uid=8))
    bot = SimpleNamespace(delete_message=AsyncMock())

    async def handle(event, data):
        await group_reply_actions(event, db, settings, bot)

    await GroupHousekeepingMiddleware()(handle, event, {'bot': bot})
    assert (await db.get_user(8))['reputation'] == 75
    assert len(replies) == 1 and '75' in replies[0][0] and replies[0][1] is None
    bot.delete_message.assert_not_awaited()


async def test_new_commands_reach_real_dispatcher_after_assistant(monkeypatch):
    from aiogram import Bot
    from test_studio_rsvp import TelegramSession

    from community_bot.routers import group, nora

    restore_defaults()
    dp = Dispatcher()
    for source in (nora.router, group.router):
        isolated = Router()
        isolated.message.handlers.extend(source.message.handlers)
        dp.include_router(isolated)
    prepare = AsyncMock()
    monkeypatch.setattr(group, '_prepare_transfer', prepare)
    monkeypatch.setattr(group, 'resolve_reply_target', AsyncMock(return_value={'user_id': 8}))
    bot = Bot('123456:test', session=TelegramSession())
    await dp.feed_update(bot, Update(update_id=1, message=message('Нора, перевести 5')),
                         db=SimpleNamespace(), settings=SimpleNamespace())
    assert prepare.await_args.args[-1] == 5
    await dp.storage.close()
    await bot.session.close()


def callback(data, uid=7, chat_id=7, **extra):
    return CallbackQuery(id='test', chat_instance='test', data=data,
                         from_user=User(id=uid, is_bot=False, first_name='Участник'),
                         message=message(None, chat_id=chat_id, **extra))


async def test_rich_post_has_personal_pages_and_one_photo(monkeypatch):
    item = latest_update()
    assert all(len(update_page(item, page)) <= 1024 for page in range(len(item.sections) + 1))
    assert len(update_keyboard(item, 0).inline_keyboard) == len(item.sections) + 1
    bot = SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock())
    monkeypatch.setattr(CallbackQuery, 'answer', AsyncMock())
    edit = AsyncMock()
    monkeypatch.setattr(Message, 'edit_caption', edit)
    for uid in (7, 8):
        await send_update_to_dm(callback('updates:dm', uid=uid, chat_id=-100123), bot)
    assert [call.args[0] for call in bot.send_photo.await_args_list] == [7, 8]
    bot.send_message.assert_not_awaited()
    photo = PhotoSize(file_id='photo', file_unique_id='photo', width=1280, height=720)
    await switch_update_page(callback(f'updates:page:{item.number}:2', photo=[photo]))
    assert 'Все команды репутации' in edit.await_args.kwargs['caption']
    edit.reset_mock()
    await switch_update_page(callback(f'updates:page:{item.number}:2', chat_id=-100123))
    await switch_update_page(callback(f'updates:page:{item.number}:99'))
    edit.assert_not_awaited()
