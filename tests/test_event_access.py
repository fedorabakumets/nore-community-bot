from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import User

from community_bot.database import Database
from community_bot.event_access import current_event, open_event_purchase, participants, roster
from community_bot.permissions import PERM_EVENT_PARTICIPANTS, PERMISSIONS


@pytest.fixture
async def db(tmp_path):
    db = Database(tmp_path / 'events.db')
    await db.initialize()
    await db.ensure_user(7, telegram_name='Анна')
    await db.add_cookies(7, 100, 'test')
    await db.save_studio_event('e1', -100123, 50, 'Встреча', [], 0, 1)
    return db


async def test_free_shop_registration_uses_current_event_without_spending_or_duplicates(db, monkeypatch):
    monkeypatch.setattr('community_bot.rsvp.refresh_event_markup', AsyncMock())
    callback = SimpleNamespace(from_user=User(id=7, is_bot=False, first_name='Анна'),
                               answer=AsyncMock(), message=SimpleNamespace(answer=AsyncMock()), bot=SimpleNamespace())
    await open_event_purchase(callback, db)
    await open_event_purchase(callback, db)
    assert await db.event_participant_count('e1') == 1
    assert (await db.get_user(7))['cookies'] == 100
    assert 'бесплатное' in callback.message.answer.call_args_list[0].args[0]


async def test_paid_shop_opens_actual_offer_without_charging_and_payment_appears_in_journal(db, monkeypatch):
    await db.save_event_offer('e1', -100123, 50, 'Билет', 30, 1)
    opened = AsyncMock()
    monkeypatch.setattr('community_bot.routers.life.event_pay_open', opened)
    callback = SimpleNamespace(from_user=User(id=7, is_bot=False, first_name='Анна'))
    callback.model_copy = lambda update: SimpleNamespace(**update)
    await open_event_purchase(callback, db)
    assert opened.call_args.args[0].data == 'evpay:e1'
    assert (await db.get_user(7))['cookies'] == 100
    assert (await db.pay_event_offer('e1', 7, 30))[0]
    assert not (await db.pay_event_offer('e1', 7, 30))[0]
    text, _ = await roster(db, 'e1', ledger=True)
    assert 'Анна' in text and '30' in text
    text, _ = await roster(db, 'e1')
    assert 'оплачено 30' in text


async def test_selected_event_overrides_latest_and_permission_is_separately_configurable(db):
    await db.save_studio_event('e2', -100123, 51, 'Другая встреча', [], 0, 1)
    await db.set_bot_state('current_studio_event', 'e1')
    assert (await current_event(db))['event_id'] == 'e1'
    assert PERM_EVENT_PARTICIPANTS in dict(PERMISSIONS)


async def test_unauthorized_chat_command_does_not_disclose_participants(db):
    message = SimpleNamespace(from_user=User(id=7, is_bot=False, first_name='Анна'), answer=AsyncMock())
    settings = SimpleNamespace(owner_ids=frozenset(), moderator_ids=frozenset(), is_owner=lambda _: False)
    await participants(message, db, settings)
    assert 'Недостаточно прав' in message.answer.call_args.args[0]
