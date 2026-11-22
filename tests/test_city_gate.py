"""Regression coverage for city selection, legacy accounts, and Rich replies."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from community_bot.application_form import validate_city
from community_bot.city_gate import CITY_PROMPT, CityGateMiddleware, city_keyboard
from community_bot.city_lookup import POPULAR, popular_cities, resolve_city_id, search_cities
from community_bot.database import Database


@pytest.fixture
async def city_setup(tmp_path):
    db = Database(tmp_path / "city.db")
    await db.initialize()
    await db.ensure_user(7, telegram_name="Участник")
    application_id = await db.create_application(7, {})
    await db.decide_application(application_id, 99, "approved", None)
    settings = SimpleNamespace(is_owner=lambda uid: uid == 99, moderator_ids=frozenset())
    return db, {"db": db, "settings": settings, "bot": SimpleNamespace(id=900)}


def member_message(text, *, group=False, reply=None):
    return Message(
        message_id=10, date=datetime.now(UTC),
        chat=Chat(id=-100123 if group else 7, type="supergroup" if group else "private"),
        from_user=User(id=7, is_bot=False, first_name="Участник"),
        text=text, reply_to_message=reply,
    )


def prompt_message(*, group=False, message_id=9, rich=False):
    message = Message(
        message_id=message_id, date=datetime.now(UTC),
        chat=Chat(id=-100123 if group else 7, type="supergroup" if group else "private"),
        from_user=User(id=900, is_bot=True, first_name="Нора"),
        text=None if rich else CITY_PROMPT,
    )
    if rich:
        message = message.model_copy(update={"rich_message": SimpleNamespace(
            model_dump=lambda **kw: {"blocks": [{"type": "paragraph", "text": CITY_PROMPT}]},
        )})
    return message


def city_callback(name, prompt, *, uid=7):
    return CallbackQuery(
        id="city-choice", chat_instance="test", data=name,
        from_user=User(id=uid, is_bot=False, first_name="Участник"),
        message=prompt,
    )


def test_city_normalization_and_rejection():
    assert validate_city("  Санкт-  Петербург  ") == "Санкт- Петербург"
    for bad in (None, "", " ", "X", 123, "А" * 101):
        with pytest.raises(ValueError):
            validate_city(bad)


async def test_popular_city_choice_and_page_keyboard(monkeypatch):
    assert len(POPULAR) > 25
    options, pages = popular_cities(1)
    assert options[0]["id"] == "p:6"
    assert pages > 1
    markup = city_keyboard(7, page=1)
    assert all(button.callback_data.startswith("city:") for row in markup.inline_keyboard for button in row)
    assert await resolve_city_id("p:1") == "Санкт-Петербург"
    with pytest.raises(ValueError):
        await resolve_city_id("p:99")
    async def offline(*_args, **_kwargs):
        raise AssertionError("Local city choice must work offline")
    monkeypatch.setattr("community_bot.city_lookup._geocoding", offline)
    assert await resolve_city_id("p:0") == "Москва"


async def test_search_city_matches_real_local_alias(monkeypatch):
    async def unavailable(*_args, **_kwargs):
        raise ValueError("offline")
    monkeypatch.setattr("community_bot.city_lookup._geocoding", unavailable)
    cities = await search_cities("Питер")
    assert cities[0]["name"] == "Санкт-Петербург"
    assert cities[0]["country"] == "Россия"


async def test_commands_remain_gated_until_city_button_is_confirmed(city_setup, monkeypatch):
    db, data = city_setup
    prompt = prompt_message()
    reply = AsyncMock(return_value=prompt)
    edit = AsyncMock()
    answer = AsyncMock()
    monkeypatch.setattr(Message, "reply", reply)
    monkeypatch.setattr(Message, "edit_text", edit)
    monkeypatch.setattr(CallbackQuery, "answer", answer)
    monkeypatch.setattr("community_bot.city_gate.search_cities", AsyncMock(return_value=[
        {"id": "p:0", "name": "Москва", "country": "Россия", "region": ""},
    ]))
    handler = AsyncMock()
    gate = CityGateMiddleware()

    await gate(handler, member_message("/profile"), data)
    handler.assert_not_awaited()
    reply.assert_awaited_once_with(CITY_PROMPT, reply_markup=ANY)
    assert await db.get_bot_state("city_prompt:7:7") == "9"

    await gate(handler, member_message("Москва", reply=prompt), data)
    assert (await db.get_user(7))["city"] is None
    assert reply.await_count == 2
    assert "Выбери найденный город" in reply.await_args.args[0]

    await gate(handler, city_callback("city:pick:7:p:0", prompt), data)
    assert (await db.get_user(7))["city"] == "Москва"
    assert await db.get_bot_state("city_prompt:7:7") == ""
    assert edit.await_args.kwargs["reply_markup"].inline_keyboard == []

    await gate(handler, member_message("/profile"), data)
    handler.assert_awaited_once()


async def test_group_conversation_does_not_trigger_repeated_prompt(city_setup, monkeypatch):
    _, data = city_setup
    reply = AsyncMock()
    monkeypatch.setattr(Message, "reply", reply)
    handler = AsyncMock()
    gate = CityGateMiddleware()

    await gate(handler, member_message("Привет", group=True), data)
    handler.assert_awaited_once()
    reply.assert_not_awaited()

    await gate(handler, member_message("/profile", group=True), data)
    reply.assert_awaited_once_with(CITY_PROMPT, reply_markup=ANY)


async def test_unrelated_callbacks_cannot_bypass_city_gate(city_setup, monkeypatch):
    _, data = city_setup
    answer = AsyncMock()
    monkeypatch.setattr(CallbackQuery, "answer", answer)
    monkeypatch.setattr(Message, "reply", AsyncMock())
    handler = AsyncMock()

    await CityGateMiddleware()(handler, city_callback("shop:pay:old-token", prompt_message()), data)
    handler.assert_not_awaited()
    assert answer.await_args.kwargs["show_alert"] is True


async def test_city_prompt_reply_with_rich_blocks_is_recognized(city_setup, monkeypatch):
    db, data = city_setup
    reply = AsyncMock()
    monkeypatch.setattr(Message, "reply", reply)
    monkeypatch.setattr("community_bot.city_gate.search_cities", AsyncMock(return_value=[
        {"id": "p:3", "name": "Екатеринбург", "country": "Россия", "region": ""},
    ]))
    handler = AsyncMock()

    await CityGateMiddleware()(handler, member_message("Екатеринбург", group=True,
                                 reply=prompt_message(group=True, rich=True)), data)
    handler.assert_not_awaited()
    assert (await db.get_user(7))["city"] is None
    assert "Выбери найденный город" in reply.await_args.args[0]


async def test_tracked_prompt_survives_empty_rich_reply_preview(city_setup, monkeypatch):
    db, data = city_setup
    prompt = prompt_message(group=True, message_id=22)
    reply = AsyncMock(return_value=prompt)
    monkeypatch.setattr(Message, "reply", reply)
    monkeypatch.setattr("community_bot.city_gate.search_cities", AsyncMock(return_value=[
        {"id": "p:3", "name": "Екатеринбург", "country": "Россия", "region": ""},
    ]))
    handler = AsyncMock()
    gate = CityGateMiddleware()
    await gate(handler, member_message("/profile", group=True), data)
    assert await db.get_bot_state("city_prompt:-100123:7") == "22"
    blank_preview = prompt.model_copy(update={"text": None})
    await gate(handler, member_message("Екатеринбург", group=True, reply=blank_preview), data)
    assert (await db.get_user(7))["city"] is None
    assert reply.await_count == 2


async def test_unrelated_bot_reply_is_not_accepted_as_city(city_setup, monkeypatch):
    db, data = city_setup
    reply = AsyncMock()
    monkeypatch.setattr(Message, "reply", reply)
    handler = AsyncMock()
    unrelated = prompt_message(group=True, message_id=91).model_copy(update={"text": "Баланс печенек"})

    await CityGateMiddleware()(handler, member_message("Краснодар", group=True, reply=unrelated), data)
    assert (await db.get_user(7))["city"] is None
    handler.assert_awaited_once()
    reply.assert_not_awaited()


async def test_city_backfilled_from_approved_legacy_application(tmp_path):
    db = Database(tmp_path / "legacy.db")
    await db.initialize()
    await db.ensure_user(12, telegram_name="Старый")
    app = await db.create_application(12, {"name": "Старый", "age": 20, "city": "Казань"})
    await db.decide_application(app, 99, "approved", None)
    await db.execute("ALTER TABLE users DROP COLUMN city")
    await db.initialize()
    assert (await db.get_user(12))["city"] == "Казань"


async def test_city_typo_suggests_verified_popular_match(monkeypatch):
    async def unavailable(*_args, **_kwargs):
        raise ValueError("offline")

    monkeypatch.setattr("community_bot.city_lookup._geocoding", unavailable)
    candidates = await search_cities("Масква")
    assert candidates
    assert candidates[0]["name"] == "Москва"
    assert candidates[0]["id"].startswith("p:")

