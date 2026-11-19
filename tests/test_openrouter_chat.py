import asyncio
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.methods import DeleteMessage, SendMessage, SendRichMessage
from aiogram.types import ChatJoinRequest, MessageOriginHiddenUser, Update, VideoNote, Voice
from test_nora_commands_release import message
from test_studio_rsvp import TelegramSession, callback

from community_bot import nora_speech, openrouter_chat
from community_bot.command_registry import apply_rows, restore_defaults
from community_bot.config import load_settings
from community_bot.database import Database
from community_bot.ephemeral import GroupHousekeepingMiddleware, patch_bot_ephemeral
from community_bot.main import create_dispatcher
from community_bot.private_rich import PrivateRichContextMiddleware, PrivateRichMiddleware
from community_bot.reply_rich import ReplyRichMiddleware
from community_bot.routers import nora
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
    assert factory.call_args.kwargs["timeout"].total == 35
    assert factory.call_args.kwargs["timeout"].connect == 5
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


async def test_release_answer_receives_public_details_and_dates(db, settings, monkeypatch):
    _, post = fake_http(monkeypatch, payload={"choices": [{"message": {"content": "Вышел кинотеатр."}}]})
    chat = openrouter_chat.OpenRouterChat(db, settings)
    event = message("Нора, когда вышло обновление №22 и что в нём?", uid=7)
    prompt = chat.prompt_for(event)
    assert prompt is not None
    assert await chat.answer(prompt, 7, message=event) == "Вышел кинотеатр."
    system = post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "№22 · 2026-11-18 · В Норе кино" in system
    assert "Выбрать видео" in system
    assert "объекты префикса" not in system and "передаёт по каналу лобби" not in system


@pytest.mark.parametrize("private, fallback", [(False, False), (True, False), (True, True)])
async def test_speech_context_quotes_media_and_closes_even_with_a_private_panel(
    db, settings, monkeypatch, private, fallback,
):
    uid = settings.owner_id
    chat_id = uid if private else settings.community_chat_id
    await db.ensure_user(uid)
    await db.add_cookies(uid, 20, "test")
    assert (await db.purchase_pet(uid, "cat", "Кот", 10))[0]
    if private:
        await db.set_bot_state(f"private_rich_panel:{uid}", '{"message_id": 444}')
    pending = asyncio.Event()

    async def wait_for_expiry(sent, delay):
        if "уровне" not in (sent.text or ""):
            await pending.wait()

    expire = AsyncMock(side_effect=wait_for_expiry)
    monkeypatch.setattr("community_bot.ephemeral.delete_later", expire)
    answers = AsyncMock(return_value=("Встретимся в семь. <Текст записи>", "В семь."))
    dispatcher = Dispatcher()
    dispatcher.message.outer_middleware(GroupHousekeepingMiddleware())
    dispatcher.message.outer_middleware(PrivateRichContextMiddleware())
    dispatcher.callback_query.outer_middleware(PrivateRichContextMiddleware())
    isolated = Router()
    isolated.message.handlers.extend(nora.assistant_router.message.handlers)
    isolated.callback_query.handlers.extend(nora.router.callback_query.handlers)
    dispatcher.include_router(isolated)
    assistant = openrouter_chat.OpenRouterChat(db, settings)
    monkeypatch.setattr(assistant, "answer_speech", answers)
    dispatcher["openrouter_chat"] = assistant
    session = TelegramSession()
    session.fail = lambda method: fallback and isinstance(method, SendRichMessage)
    async with Bot(settings.bot_token, session=session) as bot:
        bot.community_db = db
        bot.session.middleware.register(PrivateRichMiddleware())
        patch_bot_ephemeral(bot)
        bot.session.middleware.register(ReplyRichMiddleware())
        media = (
            {"voice": Voice(file_id="v", file_unique_id="v", duration=9)}
            if private else {"video_note": VideoNote(file_id="c", file_unique_id="c", duration=9, length=240)}
        )
        source = message(None, uid=uid if private else 8, chat_id=chat_id, **media).model_copy(
            update={"message_id": 42},
        )
        topic = {} if private else {"is_topic_message": True, "message_thread_id": 12}
        event = message("Нора, во сколько встреча?", uid=uid, chat_id=chat_id, reply_to_message=source, **topic)
        await dispatcher.feed_update(bot, Update(update_id=1, message=event), db=db, settings=settings)
        answers.assert_not_awaited()
        assert any("2 уровне" in str(call) for call in session.calls)
        await db.execute("UPDATE pet_development SET stage=5, level=2 WHERE user_id=?", (uid,))
        session.calls.clear()
        await dispatcher.feed_update(bot, Update(update_id=2, message=event), db=db, settings=settings)
        answers.assert_awaited_once()
        assert answers.await_args.args[0].message_id == source.message_id
        assert answers.await_args.args[1:] == ("во сколько встреча?", uid)
        rich = next(call for call in session.calls if isinstance(call, SendRichMessage))
        assert rich.reply_parameters.message_id == source.message_id
        assert rich.message_thread_id == topic.get("message_thread_id")
        answer, details, buttons = rich.rich_message.blocks
        assert answer.text == "В семь."
        assert details.type == "details" and "<Текст записи>" in details.blocks[0].text
        assert buttons.buttons[0].text == "❌"
        action = buttons.buttons[0].callback_data
        markup = None
        if fallback:
            plain = next(call for call in session.calls if isinstance(call, SendMessage))
            assert plain.reply_parameters.message_id == source.message_id
            assert "<blockquote expandable>" in plain.text and "&lt;Текст записи&gt;" in plain.text
            markup = plain.reply_markup
        await asyncio.sleep(0)
        assert expire.await_args.args[1] == 120
        if not private:
            other = callback(action, user_id=8, chat_id=chat_id, message_id=session.message_id, markup=markup)
            await dispatcher.feed_update(bot, Update(update_id=3, callback_query=other), db=db, settings=settings)
            assert not any(isinstance(call, DeleteMessage) for call in session.calls)
        close = callback(action, user_id=uid, chat_id=chat_id, message_id=session.message_id, markup=markup)
        await dispatcher.feed_update(bot, Update(update_id=4, callback_query=close), db=db, settings=settings)
        assert any(isinstance(call, DeleteMessage) and call.message_id == close.message.message_id
                   for call in session.calls)
        pending.set()
    await dispatcher.storage.close()


async def test_speech_translation_uses_the_same_daily_limit(db, settings, clock, monkeypatch):
    chat = openrouter_chat.OpenRouterChat(db, replace(settings, groq_api_key="test"))
    recognize = AsyncMock(return_value=("Seven o’clock.", False))
    monkeypatch.setattr(openrouter_chat, "transcribe", recognize)
    answer = AsyncMock(return_value='{"translation":"В семь часов.","answer":"В семь."}')
    monkeypatch.setattr(chat, "_request_history", answer)
    source = message(None, voice=Voice(file_id="v", file_unique_id="v", duration=8))
    for _ in range(5):
        assert await chat.answer_speech(source, "Во сколько?", 7) == ("В семь часов.", "В семь.")
        clock.now += 6
    assert "лимит" in await chat.answer("А теперь шутку", 7)
    assert recognize.await_count == 5
    assert "Seven o’clock." in answer.await_args.args[1]


async def test_speech_download_is_bounded_before_contacting_provider(monkeypatch):
    download = AsyncMock()
    monkeypatch.setattr(Bot, "download", download)
    async with Bot("123456:test") as bot:
        source = message(
            None, voice=Voice(file_id="v", file_unique_id="v", duration=nora_speech.MAX_SECONDS + 1),
        ).as_(bot)
        with pytest.raises(nora_speech.SpeechError, match="до 3 минут"):
            await nora_speech.transcribe(source, groq_key="test", gemini_key="")
        download.assert_not_awaited()


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
    assert await chat.answer("тот же автор", 7) == "тот же автор"
    assert await chat.answer("слишком быстро", 9) is None
    clock.now += 5
    assert await chat.answer("другой автор", 8) == "другой автор"
    clock.now += 5
    assert await chat.answer("снова", 7) == "снова"


async def test_daily_quota_survives_restart_and_counts_failures(db, settings, clock, monkeypatch):
    clock.now = datetime(2026, 11, 18, 23, 59, 45, tzinfo=ZoneInfo(settings.timezone)).timestamp()
    _, post = fake_http(monkeypatch, error=TimeoutError("sensitive provider details"))
    for _ in range(5):
        chat = openrouter_chat.OpenRouterChat(db, settings)
        assert await chat.answer("обращение", 7) == openrouter_chat._UNAVAILABLE
    restarted = openrouter_chat.OpenRouterChat(db, settings)
    assert "5 на уровне" in await restarted.answer("лимит бронзы", 7)
    assert post.call_count == 5
    assert await restarted.answer("свой лимит", 8) == openrouter_chat._UNAVAILABLE
    clock.now += 15
    assert await restarted.answer("следующий день", 7) == openrouter_chat._UNAVAILABLE
    assert post.call_count == 7


@pytest.mark.parametrize("reputation,limit", [(69, 5), (70, 10), (90, 100)])
async def test_reputation_sets_the_personal_ai_quota(db, settings, clock, reputation, limit):
    await db.ensure_user(7)
    await db.execute("UPDATE users SET reputation = ? WHERE user_id = 7", (reputation,))
    day = datetime.fromtimestamp(clock.now, ZoneInfo(settings.timezone)).date().isoformat()
    await db.set_bot_state("nora_ai_daily:7", f'{{"day":"{day}","used":{limit - 1}}}')
    chat = openrouter_chat.OpenRouterChat(db, settings)
    concurrent = await asyncio.gather(chat._reserve_request(7), chat._reserve_request(7))
    assert concurrent.count(None) == 1
    assert f"({limit} на уровне" in next(error for error in concurrent if error)


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
    for uid in (7, 8, 9, settings.owner_id):
        await db.ensure_user(uid, telegram_name=f"Участник {uid}")
    await db.execute("UPDATE users SET reputation = 80 WHERE user_id IN (7, 9)")
    await db.execute("UPDATE users SET reputation = 60 WHERE user_id = 8")
    session = TelegramSession()
    bot = Bot(settings.bot_token, session=session)
    monkeypatch.setattr(bot, "me", AsyncMock(return_value=SimpleNamespace(username="nora_bot")))
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
    group_answer = AsyncMock(return_value="Нормально, <живём>.")
    monkeypatch.setattr(chat, "_request_history", group_answer)
    dispatcher["openrouter_chat"] = chat

    async def dispatch(text, *, uid=7, chat_id=-100123, **extra):
        event = message(text, uid=uid, chat_id=chat_id, **extra).model_copy(
            update={"message_id": len(session.calls) + 51},
        )
        session.calls.clear()
        await dispatcher.feed_update(bot, Update(update_id=event.message_id, message=event), db=db, settings=settings)
        return event

    async def feed(**event):
        await dispatcher.feed_update(bot, Update(update_id=50, **event), db=db, settings=settings)

    def replies():
        return [call for call in session.calls if isinstance(call, SendMessage)]

    try:
        foreign_chat_id = -100999
        foreign_reply = message("сообщение", uid=8, chat_id=foreign_chat_id)
        await dispatch("+реп", chat_id=foreign_chat_id, reply_to_message=foreign_reply)
        foreign_message = await dispatch("Привет", uid=77, chat_id=foreign_chat_id)
        assert await db.get_user(77) is None
        assert (await db.get_user(8))["reputation"] == 60
        foreign_join = ChatJoinRequest(
            chat=foreign_message.chat, from_user=foreign_message.from_user,
            user_chat_id=77, date=foreign_message.date,
        )
        await feed(chat_join_request=foreign_join)
        await feed(callback_query=callback("nwn:read:1", chat_id=foreign_chat_id))
        assert not session.calls
        assert await db.get_user(77) is None

        await db.add_captcha(settings.owner_id, foreign_chat_id)
        await feed(callback_query=callback(f"captcha:ok:{foreign_chat_id}"))
        assert len(session.calls) == 1 and session.calls[0].text == "Эта кнопка больше не действует."
        assert await db.pop_captcha(settings.owner_id, foreign_chat_id)

        await dispatch("Нора, профиль")
        cards = [call for call in session.calls if isinstance(call, SendRichMessage)]
        assert len(cards) == 1 and cards[0].rich_message.blocks[1].text == "Участник 7"
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
        assert await state.get_state() == ApplicationForm.birth_date.state
        assert (await state.get_data())["name"] == "Нора, как настроение?"

        for text in [
            "Привет, Нора!", "Нормальный разговор", "Норабот, привет", "Нора, секретный факт", "Нора /unknown",
        ]:
            await dispatch(text)
        await dispatch("Нора, привет", chat_id=-100999)
        await dispatch("Нора, привет", forward_origin=MessageOriginHiddenUser(date=1, sender_user_name="Автор"))
        answer.assert_not_awaited()
        group_answer.assert_not_awaited()

        await db.add_cookies(settings.owner_id, 20, "test")
        assert (await db.purchase_pet(settings.owner_id, "cat", "Кот", 10))[0]
        await db.execute("UPDATE pet_development SET stage=5,level=2 WHERE user_id=?", (settings.owner_id,))
        event = await dispatch(
            "нОРа, как настроение?",
            uid=settings.owner_id,
            reply_to_message=message("чужая цитата", uid=8),
            is_topic_message=True,
            message_thread_id=12,
        )
        assert group_answer.await_args.args == ([], "как настроение?")
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
