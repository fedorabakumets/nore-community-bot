from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.methods import SendMessage
from aiogram.types import CallbackQuery, Chat, Message, User

from community_bot.access import (
    OnboardingKeyboardMiddleware,
    PrivateAccessMiddleware,
    configure_private_menus,
    guest_keyboard,
    private_keyboard,
    sync_menu,
)
from community_bot.database import Database
from community_bot.keyboards import main_private_keyboard


@pytest.fixture
async def setup(tmp_path):
    db = Database(tmp_path / 'access.db')
    await db.initialize()
    await db.ensure_user(7, telegram_name='Новый')
    settings = SimpleNamespace(is_owner=lambda uid: uid == 99, moderator_ids=frozenset())
    bot = SimpleNamespace(set_chat_menu_button=AsyncMock(), community_db=db, community_settings=settings)
    return db, settings, bot


def message(text='/shop', uid=7):
    return Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=uid, type='private'),
                   from_user=User(id=uid, is_bot=False, first_name='Имя'), text=text)


async def test_guest_keyboard_and_outgoing_flow_keyboard_cannot_expose_shop(setup):
    db, settings, bot = setup
    keyboard = await private_keyboard(db, settings, 7)
    assert len(keyboard.keyboard) == len(keyboard.keyboard[0]) == 1
    assert keyboard.keyboard[0][0].text == 'Помощь'
    assert keyboard.keyboard[0][0].style == 'danger'
    send = AsyncMock()
    await OnboardingKeyboardMiddleware()(send, bot, SendMessage(chat_id=7, text='Анкета',
                                                               reply_markup=main_private_keyboard()))
    assert send.call_args.args[1].reply_markup == guest_keyboard()
    app = await db.create_application(7, {'name': 'Имя'})
    assert (await private_keyboard(db, settings, 7)) == guest_keyboard()
    await db.decide_application(app, 99, 'approved', None)
    assert (await private_keyboard(db, settings, 7)) == main_private_keyboard()


async def test_guest_cannot_bypass_gate_with_commands_and_old_inline_buttons(setup, monkeypatch):
    db, settings, bot = setup
    answers = AsyncMock()
    monkeypatch.setattr(Message, 'answer', answers)
    monkeypatch.setattr(CallbackQuery, 'answer', AsyncMock())
    state = SimpleNamespace(get_state=AsyncMock(return_value=None))
    data = {'db': db, 'settings': settings, 'bot': bot, 'state': state}
    handler = AsyncMock()
    gate = PrivateAccessMiddleware()
    for text in ('/shop', '/balance', '/profile', '📋 Меню', '🛒 Магазин'):
        await gate(handler, message(text), data)
        handler.assert_not_awaited()
    for action in ('menu:wallet', 'shop:pay:old-token', 'profile:age:7', 'admin:panel'):
        callback = CallbackQuery(id='test', from_user=message().from_user, chat_instance='test',
                                 message=message(), data=action)
        await gate(handler, callback, data)
        handler.assert_not_awaited()
    for text in ('/start', '/apply'):
        await gate(handler, message(text), data)
    assert handler.await_count == 2
    handler.reset_mock()
    state.get_state.return_value = 'ApplicationForm:name'
    await gate(handler, message('Мария'), data)
    handler.assert_awaited_once()
    handler.reset_mock()
    await gate(handler, message('/shop'), data)
    handler.assert_not_awaited()
    state.get_state.return_value = None
    await gate(handler, message('Помощь'), data)
    handler.assert_not_awaited()
    assert any('поддержке' in str(call) for call in answers.call_args_list)
    app = await db.create_application(7, {})
    await db.decide_application(app, 99, 'approved', None)
    await gate(handler, message('/shop'), data)
    handler.assert_awaited_once()


async def test_moderator_and_above_receive_miniapp_menu_and_revocation_clears_it(setup, monkeypatch):
    db, settings, bot = setup
    monkeypatch.setenv('MINIAPP_URL', 'https://example.test')
    await db.ensure_user(99, telegram_name='Owner')
    await configure_private_menus(bot, db, settings)
    calls = bot.set_chat_menu_button.call_args_list
    assert calls[0].kwargs['menu_button'].type == 'commands'
    assert next(c.kwargs['menu_button'] for c in calls if c.kwargs.get('chat_id') == 7).type == 'commands'
    assert next(c.kwargs['menu_button'] for c in calls if c.kwargs.get('chat_id') == 99).type == 'web_app'
    await db.set_role(7, 'moderator')
    await sync_menu(bot, db, settings, 7)
    assert bot._nora_menu_access[7][0] is True
    await db.set_role(7, 'admin')
    await sync_menu(bot, db, settings, 7)
    assert bot.set_chat_menu_button.call_args.kwargs['menu_button'].type == 'web_app'
    await db.set_role(7, 'member')
    await sync_menu(bot, db, settings, 7)
    assert bot.set_chat_menu_button.call_args.kwargs['menu_button'].type == 'commands'
