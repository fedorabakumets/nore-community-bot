from unittest.mock import AsyncMock

import pytest
from aiogram.types import Chat, Message, MessageEntity, User

from community_bot.aliases import CommandOrAlias, message_trigger
from community_bot.database import Database
from community_bot.routers import profile


def event(text, entities=None, reply=None):
    return Message(message_id=1, date=1725000000, chat=Chat(id=-100123, type='supergroup'),
                   from_user=User(id=7, is_bot=False, first_name='Автор'), text=text,
                   entities=entities, reply_to_message=reply)


@pytest.mark.parametrize('text', ['Нора профиль @Some_User', 'Нора, профиль @Some_User'])
async def test_username_profile_command(text):
    assert (await CommandOrAlias('profile')(event(text)))['command'].args == '@Some_User'


async def test_selected_name_without_username():
    target = User(id=8, is_bot=False, first_name='😀 Анна')
    text = 'Нора профиль 😀 Анна'
    entity = MessageEntity(type='text_mention', offset=13, length=7, user=target)
    assert message_trigger(event(text, [entity])) == ('profile', '😀 Анна')
    assert await CommandOrAlias('profile')(event(text, [entity]))
    assert not await CommandOrAlias('profile')(event(text + ' привет', [entity]))


async def test_profile_mention_targets_and_privacy(tmp_path, monkeypatch):
    db = Database(tmp_path / 'test.db')
    await db.initialize()
    await db.ensure_user(8, username='Some_User', telegram_name='Анна')
    send = AsyncMock()
    view = AsyncMock(return_value=True)
    monkeypatch.setattr(profile, 'send_profile_card', send)
    monkeypatch.setattr(profile, 'can_view_profile', view)
    monkeypatch.setattr(profile, 'render_profile', AsyncMock(return_value='card'))
    await profile.show_profile(event('Нора профиль @some_user'), db, object())
    assert send.await_args.args[1]['user_id'] == 8
    target = User(id=9, is_bot=False, first_name='Анна')
    entity = MessageEntity(type='text_mention', offset=13, length=4, user=target)
    await profile.show_profile(event('Нора профиль Анна', [entity]), db, object())
    assert send.await_args.args[1]['user_id'] == 9
    assert view.await_args.args[2] == 7


async def test_unknown_username_does_not_show_own_profile(tmp_path, monkeypatch):
    db = Database(tmp_path / 'test.db')
    await db.initialize()
    answer = AsyncMock()
    send = AsyncMock()
    monkeypatch.setattr(Message, 'answer', answer)
    monkeypatch.setattr(profile, 'send_profile_card', send)
    await profile.show_profile(event('Нора профиль @unknown'), db, object())
    answer.assert_awaited_once()
    send.assert_not_awaited()
