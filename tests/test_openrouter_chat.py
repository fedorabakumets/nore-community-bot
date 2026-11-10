import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot
from aiogram.methods import DeleteMessage, SendMessage, SendPhoto
from aiogram.types import MessageOriginHiddenUser, Update
from test_nora_commands_release import message
from test_studio_rsvp import TelegramSession

from community_bot import openrouter_chat
from community_bot.command_registry import apply_rows, restore_defaults
from community_bot.config import load_settings
from community_bot.database import Database
from community_bot.main import create_dispatcher
from community_bot.states import ApplicationForm


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("BOT_TOKEN", "123456:test")
    monkeypatch.setenv("OWNER_ID", "1")
    monkeypatch.setenv("COMMUNITY_CHAT_ID", "-100123")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    return load_settings()


@pytest.fixture
async def db(tmp_path):
    db = Database(tmp_path / "openrouter.db")
    await db.initialize()
    return db


@pytest.fixture
def clock(monkeypatch):
    clock = SimpleNamespace(now=1_800_000_000)
    monkeypatch.setattr(
        openrouter_chat, "time", SimpleNamespace(time=lambda: clock.now, monotonic=lambda: clock.now),
    )
    return clock


def fake_http(monkeypatch, *, status=200, headers=None, payload=None, error=None):
    session_factory = MagicMock()
    session = session_factory.return_value.__aenter__.return_value
    session.post = MagicMock()
    response = session.post.return_value.__aenter__.return_value
    response.status = status
    response.headers = headers or {}
    response.json = AsyncMock(return_value=payload, side_effect=error)
    monkeypatch.setattr(openrouter_chat.aiohttp, "ClientSession", session_factory)
    return session_factory, session.post


async def test_request_is_free_and_contains_only_the_current_prompt(db, settings, monkeypatch):
    factory, post = fake_http(
        monkeypatch, payload={"choices": [{"message": {"content": " Привет, питерские. "}}]},
    )
    chat = openrouter_chat.OpenRouterChat(db, settings)
    assert await chat.answer("Как настроение?", 7) == "Привет, питерские."
    assert "test-key" not in repr(settings)
    assert factory.call_args.kwargs["timeout"].total == 12
    assert factory.call_args.kwargs["timeout"].connect == 3
    assert post.call_args.args == ("https://openrouter.ai/api/v1/chat/completions",)
    request = post.call_args.kwargs
    assert request["headers"] == {"Authorization": "Bearer test-key"}
    assert request["allow_redirects"] is False
    payload = request["json"]
    assert payload["model"] == "openrouter/free"
    assert "models" not in payload
    assert payload["provider"]["max_price"] == {"prompt": 0, "completion": 0, "request": 0}
    system, user = payload["messages"]
    assert system["role"] == "system" and "Петербурга" in system["content"]
    assert user == {"role": "user", "content": "Как настроение?"}


@pytest.mark.parametrize("model", ["openrouter/auto", "vendor/model", "vendor/model:free"])
async def test_model_env_allows_only_free_models(db, settings, monkeypatch, model):
    monkeypatch.setenv("OPENROUTER_MODEL", model)
    _, post = fake_http(monkeypatch, payload={"choices": [{"message": {"content": "Привет"}}]})
    answer = await openrouter_chat.OpenRouterChat(db, load_settings()).answer("Привет", 7)
    if model.endswith(":free"):
        assert answer == "Привет"
        assert post.call_args.kwargs["json"]["model"] == model
    else:
        assert answer is None
        post.assert_not_called()


async def test_parallel_calls_and_cooldowns(db, settings, clock, monkeypatch):
    chat = openrouter_chat.OpenRouterChat(db, settings)
    started, finish = asyncio.Event(), asyncio.Event()

    async def request(prompt):
        started.set()
        await finish.wait()
        return prompt

    monkeypatch.setattr(chat, "_request", request)
    pending = asyncio.create_task(chat.answer("привет", 7))
    await started.wait()
    clock.now += 6
    assert await chat.answer("параллельно", 8) is None
    finish.set()
    assert await pending == "привет"
    assert await chat.answer("тот же автор", 7) is None
    assert await chat.answer("другой автор", 8) == "другой автор"
    assert await chat.answer("слишком быстро", 9) is None
    clock.now += 30
    assert await chat.answer("снова", 7) == "снова"


async def test_daily_quota_survives_restart_and_counts_failures(db, settings, clock, monkeypatch):
    monkeypatch.setattr(openrouter_chat, "_DAILY_LIMIT", 2)
    _, post = fake_http(monkeypatch, error=TimeoutError("sensitive provider details"))
    for _ in range(2):
        chat = openrouter_chat.OpenRouterChat(db, settings)
        assert await chat.answer("обращение", 7) == openrouter_chat._UNAVAILABLE
    restarted = openrouter_chat.OpenRouterChat(db, settings)
    assert await restarted.answer("бюджет исчерпан", 8) is None
    assert post.call_count == 2
    clock.now += 24 * 60 * 60
    assert await restarted.answer("следующие сутки", 8) == openrouter_chat._UNAVAILABLE
    assert post.call_count == 3


@pytest.mark.parametrize("status, embedded, headers, seconds", [
    (401, False, {}, 900),
    (402, False, {}, 3600),
    (429, False, {"Retry-After": "120"}, 120),
    (429, True, {"X-RateLimit-Reset": str((1_800_000_000 + 180) * 1000)}, 180),
    (503, False, {"Retry-After": "120"}, 120),
])
async def test_provider_errors_back_off_without_logging_payload(
    db, settings, clock, monkeypatch, caplog, status, embedded, headers, seconds,
):
    _, post = fake_http(
        monkeypatch, status=200 if embedded else status, headers=headers,
        payload={"error": {"code": status, "message": "test-key secret prompt"}},
    )
    chat = openrouter_chat.OpenRouterChat(db, settings)
    assert await chat.answer("secret prompt", 7) in {openrouter_chat._UNAVAILABLE, openrouter_chat._LIMIT_REACHED}
    clock.now += seconds - 1
    assert await chat.answer("слишком рано", 8) is None
    assert post.call_count == 1
    clock.now += 1
    assert await chat.answer("новая попытка", 8)
    assert post.call_count == 2
    assert "test-key" not in caplog.text and "secret prompt" not in caplog.text


async def test_existing_commands_and_fsm_win_in_the_production_dispatcher(db, settings, clock, monkeypatch):
    restore_defaults()
    apply_rows([
        {"slug": "fact", "kind": "custom", "aliases_json": '["любимый факт"]', "reply_text": "Штатная команда"},
        {"slug": "disabledfact", "kind": "custom", "aliases_json": '["секретный факт"]', "enabled": 0},
    ])
    for uid in (7, 8, 9):
        await db.ensure_user(uid, telegram_name=f"Участник {uid}")
    await db.execute("UPDATE users SET reputation = 80 WHERE user_id IN (7, 9)")
    await db.execute("UPDATE users SET reputation = 60 WHERE user_id = 8")
    session = TelegramSession()
    bot = Bot(settings.bot_token, session=session)
    monkeypatch.setattr(bot, "get_chat_member", AsyncMock(return_value=SimpleNamespace(status="member")))
    monkeypatch.setattr("community_bot.access.sync_menu", AsyncMock())
    monkeypatch.setattr("community_bot.routers.private.flow_reply_keyboard", lambda: None)
    weather = AsyncMock(return_value="В Петербурге дождь.")
    monkeypatch.setattr("community_bot.morning.weather_reply", weather)
    transfer = AsyncMock()
    monkeypatch.setattr("community_bot.routers.group._prepare_transfer", transfer)
    dispatcher = create_dispatcher()
    chat = openrouter_chat.OpenRouterChat(db, settings)
    answer = AsyncMock(return_value="Нормально, <живём>.")
    monkeypatch.setattr(chat, "_request", answer)
    dispatcher["openrouter_chat"] = chat

    async def dispatch(text, *, uid=7, chat_id=-100123, **extra):
        event = message(text, uid=uid, chat_id=chat_id, **extra).model_copy(
            update={"message_id": len(session.calls) + 51},
        )
        session.calls.clear()
        await dispatcher.feed_update(bot, Update(update_id=event.message_id, message=event), db=db, settings=settings)
        return event

    def replies():
        return [call for call in session.calls if isinstance(call, SendMessage)]

    try:
        await dispatch("Нора, профиль")
        cards = [call for call in session.calls if isinstance(call, (SendMessage, SendPhoto))]
        assert cards and "Участник 7" in (getattr(cards[0], "caption", None) or cards[0].text)
        await dispatch("Нора, любимый факт")
        assert replies()[0].text == "Штатная команда"
        await dispatch("Нора, какая погода?")
        assert replies()[0].text == "В Петербурге дождь."
        weather.assert_awaited_once()
        await dispatch("Нора, перевести 5", reply_to_message=message("сообщение", uid=8))
        assert transfer.await_args.args[-1] == 5
        for uid, text, expected in [(7, "+реп", 65), (9, "-реп", 60)]:
            await dispatch(text, uid=uid, reply_to_message=message("сообщение", uid=8))
            assert (await db.get_user(8))["reputation"] == expected
            assert replies() and not any(isinstance(call, DeleteMessage) for call in session.calls)

        state = dispatcher.fsm.get_context(bot=bot, chat_id=7, user_id=7)
        await state.set_state(ApplicationForm.name)
        await dispatch("Нора, как настроение?", chat_id=7)
        assert await state.get_state() == ApplicationForm.age.state
        assert (await state.get_data())["name"] == "Нора, как настроение?"

        for text in [
            "Привет, Нора!", "Нормальный разговор", "Норабот, привет", "Нора, секретный факт", "Нора /unknown",
        ]:
            await dispatch(text)
        await dispatch("Нора, привет", chat_id=-100999)
        await dispatch("Нора, привет", forward_origin=MessageOriginHiddenUser(date=1, sender_user_name="Автор"))
        answer.assert_not_awaited()

        event = await dispatch(
            "нОРа, как настроение?",
            reply_to_message=message("чужая цитата", uid=8),
            is_topic_message=True,
            message_thread_id=12,
        )
        answer.assert_awaited_once_with("как настроение?")
        assert len(replies()) == 1
        reply = replies()[0]
        assert reply.text == "Нормально, <живём>." and reply.parse_mode is None
        assert reply.chat_id == settings.community_chat_id and reply.message_thread_id == 12
        assert reply.reply_parameters.message_id == event.message_id
        assert not any(isinstance(call, DeleteMessage) for call in session.calls)

        clock.now += 30
        event = await dispatch("Нора, расскажи шутку", uid=settings.owner_id, chat_id=settings.owner_id)
        assert answer.await_args.args == ("расскажи шутку",)
        assert replies()[0].chat_id == settings.owner_id
        assert replies()[0].reply_parameters.message_id == event.message_id
    finally:
        restore_defaults()
        await dispatcher.storage.close()
        await bot.session.close()
