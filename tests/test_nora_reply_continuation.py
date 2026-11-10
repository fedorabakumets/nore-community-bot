from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update, User
from test_nora_commands_release import message
from test_studio_rsvp import TelegramSession

from community_bot import openrouter_chat
from community_bot.command_registry import restore_defaults
from community_bot.config import load_settings
from community_bot.database import Database
from community_bot.routers import group as group_module
from community_bot.routers import nora as nora_module


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("BOT_TOKEN", "123456:test")
    monkeypatch.setenv("OWNER_ID", "1")
    monkeypatch.setenv("MODERATOR_IDS", "2")
    monkeypatch.setenv("COMMUNITY_CHAT_ID", "-100123")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    return load_settings()


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "reply-continuation.db")
    await database.initialize()
    return database


@pytest.fixture
def clock(monkeypatch):
    current = SimpleNamespace(now=1_800_000_000)
    monkeypatch.setattr(
        openrouter_chat,
        "time",
        SimpleNamespace(time=lambda: current.now, monotonic=lambda: current.now),
    )
    return current


def bot_message(text, message_id, chat_id=-100123):
    return Message(
        message_id=message_id,
        date=1725000000,
        chat=Chat(id=chat_id, type="private" if chat_id > 0 else "supergroup"),
        from_user=User(id=123456, is_bot=True, first_name="Нора"),
        text=text,
    )


def fake_http(monkeypatch, *, payload=None):
    session_factory = MagicMock()
    session = session_factory.return_value.__aenter__.return_value
    session.post = MagicMock()
    response = session.post.return_value.__aenter__.return_value
    response.status = 200
    response.headers = {}
    response.json = AsyncMock(return_value=payload)
    monkeypatch.setattr(openrouter_chat.aiohttp, "ClientSession", session_factory)
    return session_factory, session.post


def test_history_keeps_last_ten_messages(db, settings):
    chat = openrouter_chat.OpenRouterChat(db, settings)
    conversation_id = chat.remember_dialogue(
        chat_id=-100123, user_id=1, prompt="первый", answer="ответ 1", message_id=101,
    )
    assert conversation_id
    for index in range(2, 8):
        returned = chat.remember_dialogue(
            chat_id=-100123,
            user_id=1,
            prompt=f"вопрос {index}",
            answer=f"ответ {index}",
            message_id=100 + index,
            conversation_id=conversation_id,
        )
        assert returned == conversation_id
    event = message("а дальше?", uid=1, reply_to_message=bot_message("ответ 7", 107))
    found = chat.continuation_for(event)
    assert found is not None
    prompt, history, returned_id = found
    assert prompt == "а дальше?"
    assert returned_id == conversation_id
    assert len(history) == 10
    assert history[0] == {"role": "user", "content": "вопрос 3"}
    assert history[-1] == {"role": "assistant", "content": "ответ 7"}
    assert all(item["content"] != "первый" for item in history)


def test_history_is_isolated_by_user_and_chat(db, settings):
    chat = openrouter_chat.OpenRouterChat(db, settings)
    chat.remember_dialogue(
        chat_id=-100123, user_id=1, prompt="секрет владельца", answer="ответ", message_id=101,
    )
    other_user = message("продолжи", uid=2, reply_to_message=bot_message("ответ", 101))
    assert chat.continuation_for(other_user) is None
    other_chat = message(
        "продолжи", uid=1, chat_id=1, reply_to_message=bot_message("ответ", 101, chat_id=1),
    )
    assert chat.continuation_for(other_chat) is None
    same_user = message("продолжи", uid=1, reply_to_message=bot_message("ответ", 101))
    assert chat.continuation_for(same_user) is not None


def test_history_expires_after_one_hour(db, settings, clock):
    chat = openrouter_chat.OpenRouterChat(db, settings)
    chat.remember_dialogue(
        chat_id=-100123, user_id=1, prompt="привет", answer="ответ", message_id=101,
    )
    clock.now += 60 * 60
    event = message("продолжи", uid=1, reply_to_message=bot_message("ответ", 101))
    assert chat.continuation_for(event) is not None
    clock.now += 1
    assert chat.continuation_for(event) is None


def test_continuation_rejects_other_messages_and_commands(db, settings):
    chat = openrouter_chat.OpenRouterChat(db, settings)
    chat.remember_dialogue(
        chat_id=-100123, user_id=1, prompt="привет", answer="ответ", message_id=101,
    )
    assert chat.continuation_for(message("продолжи", uid=1)) is None
    assert chat.continuation_for(
        message("продолжи", uid=1, reply_to_message=message("чужие слова", uid=8)),
    ) is None
    assert chat.continuation_for(
        message("продолжи", uid=1, reply_to_message=bot_message("служебное", 999)),
    ) is None
    for text in ("/profile", "профиль", "Нора, профиль", "+реп", "перевести 5"):
        event = message(text, uid=1, reply_to_message=bot_message("ответ", 101))
        assert chat.continuation_for(event) is None
    assert chat.remember_dialogue(
        chat_id=-100123,
        user_id=1,
        prompt="неудача",
        answer=openrouter_chat._UNAVAILABLE,
        message_id=102,
    ) is None


async def test_answer_with_history_sends_history_and_keeps_limits(db, settings, monkeypatch):
    _, post = fake_http(
        monkeypatch, payload={"choices": [{"message": {"content": "Продолжаю."}}]},
    )
    chat = openrouter_chat.OpenRouterChat(db, settings)
    history = [
        {"role": "user", "content": "первый вопрос"},
        {"role": "assistant", "content": "первый ответ"},
    ]
    assert await chat.answer_with_history(history, "а дальше?", 1) == "Продолжаю."
    payload = post.call_args.kwargs["json"]
    assert payload["model"] == "openrouter/free"
    assert payload["messages"] == [
        {"role": "system", "content": openrouter_chat._PERSONA},
        {"role": "user", "content": "первый вопрос"},
        {"role": "assistant", "content": "первый ответ"},
        {"role": "user", "content": "а дальше?"},
    ]


async def test_reply_continues_dialogue_through_isolated_dispatcher(db, settings, clock, monkeypatch):
    restore_defaults()
    for uid in (1, 2, 7, 8):
        await db.ensure_user(uid, telegram_name=f"Участник {uid}")
    await db.execute("UPDATE users SET reputation = 80 WHERE user_id IN (1, 8)")
    session = TelegramSession()
    bot = Bot(settings.bot_token, session=session)
    monkeypatch.setattr(bot, "get_chat_member", AsyncMock(return_value=SimpleNamespace(status="member")))
    monkeypatch.setattr("community_bot.access.sync_menu", AsyncMock())
    monkeypatch.setattr("community_bot.routers.private.flow_reply_keyboard", lambda: None)
    dispatcher = Dispatcher()
    for source in (nora_module.router, group_module.router, nora_module.assistant_router):
        isolated = Router()
        isolated.message.handlers.extend(source.message.handlers)
        dispatcher.include_router(isolated)
    chat = openrouter_chat.OpenRouterChat(db, settings)
    monkeypatch.setattr(chat, "_request", AsyncMock(return_value="Привет, помню первый вопрос."))
    history_calls: list[tuple[list[dict[str, str]], str]] = []

    async def fake_history(history, prompt):
        history_calls.append((list(history), prompt))
        return "Продолжаю: помню контекст."

    monkeypatch.setattr(chat, "_request_history", fake_history)
    dispatcher["openrouter_chat"] = chat

    async def dispatch(text, *, uid=1, chat_id=-100123, **extra):
        event = message(text, uid=uid, chat_id=chat_id, **extra).model_copy(
            update={"message_id": len(session.calls) + 51},
        )
        session.calls.clear()
        await dispatcher.feed_update(bot, Update(update_id=event.message_id, message=event), db=db, settings=settings)
        return event

    def replies():
        return [call for call in session.calls if isinstance(call, SendMessage)]

    try:
        event = await dispatch("Нора, как настроение?", uid=1)
        assert replies() and replies()[0].text == "Привет, помню первый вопрос."
        ai_message_id = session.message_id
        assert replies()[0].reply_parameters.message_id == event.message_id
        clock.now += 6
        event = await dispatch(
            "а что дальше?", uid=1, reply_to_message=bot_message("Привет, помню первый вопрос.", ai_message_id),
        )
        assert len(history_calls) == 1
        assert history_calls[0] == (
            [
                {"role": "user", "content": "как настроение?"},
                {"role": "assistant", "content": "Привет, помню первый вопрос."},
            ],
            "а что дальше?",
        )
        assert replies() and replies()[0].text == "Продолжаю: помню контекст."
        assert replies()[0].reply_parameters.message_id == event.message_id
        continued_id = session.message_id
        clock.now += 6
        await dispatch(
            "а мне?", uid=7, reply_to_message=bot_message("Продолжаю: помню контекст.", continued_id),
        )
        assert len(history_calls) == 1
        assert not replies()
        clock.now += 6
        await dispatch(
            "продолжи", uid=1, reply_to_message=bot_message("Служебное сообщение", 999),
        )
        assert len(history_calls) == 1
        assert not replies()
        clock.now += 6
        await dispatch(
            "+реп", uid=1, reply_to_message=bot_message("Продолжаю: помню контекст.", continued_id),
        )
        assert len(history_calls) == 1
        assert replies() and "Репутация ботов" in replies()[0].text
    finally:
        restore_defaults()
        await dispatcher.storage.close()
        await bot.session.close()
