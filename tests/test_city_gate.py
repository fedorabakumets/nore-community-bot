"""Regression coverage for city validation, legacy profiles and access gates."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from community_bot.application_form import validate_city
from community_bot.city_gate import CITY_PROMPT, CityGateMiddleware
from community_bot.database import Database


@pytest.fixture
async def city_setup(tmp_path):
    db = Database(tmp_path / 'city.db')
    await db.initialize()
    await db.ensure_user(7, telegram_name='Участник')
    application_id = await db.create_application(7, {})
    await db.decide_application(application_id, 99, 'approved', None)
    settings = SimpleNamespace(is_owner=lambda uid: uid == 99, moderator_ids=frozenset())
    bot = SimpleNamespace(id=900)
    return db, {'db': db, 'settings': settings, 'bot': bot}


def make_message(text, *, group=False, reply=None):
    uid = -100123 if group else 7
    return Message(
        message_id=10,
        date=datetime.now(UTC),
        chat=Chat(id=uid, type='supergroup' if group else 'private'),
        from_user=User(id=7, is_bot=False, first_name='Участник'),
        text=text,
        reply_to_message=reply,
    )


def test_city_normalization_and_rejection():
    assert validate_city('  Санкт-  Петербург  ') == 'Санкт- Петербург'
    for bad in (None, '', ' ', 'X', 123, 'А' * 101):
        with pytest.raises(ValueError):
            validate_city(bad)


async def test_telegram_commands_are_gated_until_reply(city_setup, monkeypatch):
    db, data = city_setup
    response = AsyncMock()
    monkeypatch.setattr(Message, 'reply', response)
    handler = AsyncMock()
    gate = CityGateMiddleware()

    await gate(handler, make_message('/profile'), data)
    handler.assert_not_awaited()
    assert response.await_args.args == (CITY_PROMPT,)

    prompt = Message(
        message_id=9, date=datetime.now(UTC),
        chat=Chat(id=7, type='private'),
        from_user=User(id=900, is_bot=True, first_name='Нора'),
        text=CITY_PROMPT,
    )
    await gate(handler, make_message('Москва', reply=prompt), data)
    handler.assert_not_awaited()
    assert (await db.get_user(7))['city'] == 'Москва'
    assert 'Команды Норы' in response.await_args.args[0]

    await gate(handler, make_message('/profile'), data)
    handler.assert_awaited_once()


async def test_group_chat_without_command_is_not_flooded(city_setup, monkeypatch):
    db, data = city_setup
    response = AsyncMock()
    monkeypatch.setattr(Message, 'reply', response)
    handler = AsyncMock()
    gate = CityGateMiddleware()

    await gate(handler, make_message('Привет, друзья', group=True), data)
    handler.assert_awaited_once()
    response.assert_not_awaited()
    handler.reset_mock()

    await gate(handler, make_message('/profile', group=True), data)
    handler.assert_not_awaited()
    response.assert_awaited_once_with(CITY_PROMPT)


async def test_old_inline_buttons_cannot_bypass_city(city_setup, monkeypatch):
    _, data = city_setup
    response = AsyncMock()
    monkeypatch.setattr(CallbackQuery, 'answer', response)
    monkeypatch.setattr(Message, 'answer', AsyncMock())
    monkeypatch.setattr(Message, 'reply', AsyncMock())
    handler = AsyncMock()
    event = CallbackQuery(
        id='check', chat_instance='check', from_user=make_message('/profile').from_user,
        message=make_message('/profile'), data='shop:pay:old-token',
    )
    await CityGateMiddleware()(handler, event, data)
    handler.assert_not_awaited()
    response.assert_awaited_once()
    assert response.await_args.kwargs['show_alert'] is True


async def test_city_backfilled_from_approved_legacy_application(tmp_path):
    db = Database(tmp_path / 'legacy.db')
    await db.initialize()
    await db.ensure_user(12, telegram_name='Старый')
    app = await db.create_application(12, {'name': 'Старый', 'age': 20, 'city': 'Казань'})
    await db.decide_application(app, 99, 'approved', None)
    await db.execute("ALTER TABLE users DROP COLUMN city")
    await db.initialize()
    assert (await db.get_user(12))['city'] == 'Казань'



async def test_legacy_member_without_approved_application_can_set_city_in_group(city_setup, monkeypatch):
    db, data = city_setup
    await db.execute("DELETE FROM applications WHERE user_id=7")
    sent = AsyncMock()
    monkeypatch.setattr(Message, "reply", sent)
    handler = AsyncMock()
    gate = CityGateMiddleware()

    await gate(handler, make_message("Нора профиль", group=True), data)
    handler.assert_not_awaited()
    sent.assert_awaited_once_with(CITY_PROMPT)

    prompt = Message(
        message_id=17, date=datetime.now(UTC), chat=Chat(id=-100123, type="supergroup"),
        from_user=User(id=900, is_bot=True, first_name="Нора"), text=CITY_PROMPT,
    )
    await gate(handler, make_message("Тюмень", group=True, reply=prompt), data)
    assert (await db.get_user(7))["city"] == "Тюмень"
    assert "Команды Норы" in sent.await_args.args[0]


async def test_reply_to_rich_city_prompt_is_recognized(city_setup, monkeypatch):
    db, data = city_setup
    reply = AsyncMock()
    monkeypatch.setattr(Message, "reply", reply)
    handler = AsyncMock()

    # Telegram Rich replies have rich_message blocks but no Message.text.
    prompt = Message(
        message_id=19, date=datetime.now(UTC), chat=Chat(id=-100123, type="supergroup"),
        from_user=User(id=900, is_bot=True, first_name="Нора"),
    ).model_copy(update={
        "rich_message": SimpleNamespace(
            model_dump=lambda **kwargs: {"blocks": [{"type": "paragraph", "text": CITY_PROMPT}]}
        ),
    })
    message = make_message("Казань", group=True).model_copy(update={"reply_to_message": prompt})
    await CityGateMiddleware()(handler, message, data)

    assert (await db.get_user(7))["city"] == "Казань"
    handler.assert_not_awaited()
    assert "✅ Город сохранён" in reply.await_args.args[0]


async def test_city_response_uses_tracked_prompt_when_telegram_omits_original_content(city_setup, monkeypatch):
    db, data = city_setup
    sent = Message(
        message_id=22, date=datetime.now(UTC), chat=Chat(id=-100123, type="supergroup"),
        from_user=User(id=900, is_bot=True, first_name="Нора"),
    )
    reply = AsyncMock(side_effect=[sent, None])
    monkeypatch.setattr(Message, "reply", reply)
    handler = AsyncMock()

    await CityGateMiddleware()(handler, make_message("/profile", group=True), data)
    assert await db.get_bot_state("city_prompt:-100123:7") == "22"

    response = make_message("Екатеринбург", group=True, reply=sent)
    await CityGateMiddleware()(handler, response, data)
    assert (await db.get_user(7))["city"] == "Екатеринбург"
    assert await db.get_bot_state("city_prompt:-100123:7") == ""
    handler.assert_not_awaited()


async def test_unrelated_bot_reply_is_not_accepted_as_city(city_setup, monkeypatch):
    db, data = city_setup
    reply = AsyncMock()
    monkeypatch.setattr(Message, "reply", reply)
    handler = AsyncMock()

    unrelated = Message(
        message_id=91, date=datetime.now(UTC), chat=Chat(id=-100123, type="supergroup"),
        from_user=User(id=900, is_bot=True, first_name="Нора"), text="Баланс печенек",
    )
    await CityGateMiddleware()(handler, make_message("Краснодар", group=True, reply=unrelated), data)
    assert (await db.get_user(7))["city"] is None
    handler.assert_awaited_once()
    reply.assert_not_awaited()
