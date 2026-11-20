import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.methods import EditMessageText, SendMessage, SendRichMessage
from aiogram.types import (
    CallbackQuery,
    MessageEntity,
    MessageReactionUpdated,
    ReactionTypeCustomEmoji,
    ReactionTypeEmoji,
    RichMessage,
    Update,
    User,
)
from test_nora_commands_release import message
from test_studio_rsvp import TelegramSession

from community_bot import social_likes
from community_bot.command_registry import apply_rows, get_command, restore_defaults
from community_bot.config import load_settings
from community_bot.database import Database
from community_bot.ephemeral import GroupHousekeepingMiddleware
from community_bot.reaction_authors import ReactionAuthors
from community_bot.routers import group, life, member_stats, nora


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("BOT_TOKEN", "123456:test")
    monkeypatch.setenv("OWNER_ID", "1")
    monkeypatch.setenv("COMMUNITY_CHAT_ID", "-100123")
    monkeypatch.setenv("RESTRICTED_REPUTATION_THRESHOLD", "0")
    settings = load_settings()
    db = Database(tmp_path / "members.db")
    await db.initialize()
    await db.ensure_user(8, "alice", "Анна <тест>")
    await db.ensure_user(9, "boris", "Борис")
    restore_defaults()
    dispatcher = Dispatcher()
    reaction_authors = ReactionAuthors()
    dispatcher["reaction_authors"] = reaction_authors
    dispatcher.message.outer_middleware(reaction_authors)
    dispatcher.message.outer_middleware(GroupHousekeepingMiddleware())
    for source in (nora.router, life.router, member_stats.router, group.router, nora.assistant_router):
        router = Router()
        router.message.handlers.extend(source.message.handlers)
        router.callback_query.handlers.extend(source.callback_query.handlers)
        router.message_reaction.handlers.extend(source.message_reaction.handlers)
        dispatcher.include_router(router)
    session = TelegramSession()
    bot = Bot(settings.bot_token, session=session)
    monkeypatch.setattr(bot, "get_chat_member", AsyncMock(return_value=SimpleNamespace(status="member")))
    calls = 0

    async def dispatch(text, **kwargs):
        nonlocal calls
        calls += 1
        session.calls.clear()
        if isinstance(text, CallbackQuery):
            update = Update(update_id=calls, callback_query=text)
        elif isinstance(text, MessageReactionUpdated):
            update = Update(update_id=calls, message_reaction=text)
        else:
            event = message(text, **kwargs).model_copy(update={"message_id": calls + 1000, "date": datetime.now(UTC)})
            update = Update(update_id=calls, message=event)
        await dispatcher.feed_update(bot, update, db=db, settings=settings)
        return session.calls.copy()

    yield db, dispatch, session
    await dispatcher.storage.close()
    await bot.session.close()


async def test_mentions_keep_recipient_and_permissions(env, monkeypatch):
    db, dispatch, _ = env
    prepare = AsyncMock()
    monkeypatch.setattr(group, "_prepare_transfer", prepare)
    reply = message("Сообщение Бориса", uid=9)
    for command in ("Нора перевести @ALICE 100", "Нора перевести 100 @alice"):
        await dispatch(command, reply_to_message=reply)
        assert prepare.await_args.args[-2]["user_id"] == 8
        assert prepare.await_args.args[-1] == 100
    prepare.reset_mock()
    await dispatch("Нора перевести @unknown 100", reply_to_message=reply)
    prepare.assert_not_awaited()
    await dispatch("Нора перевести 100", reply_to_message=reply)
    assert prepare.await_args.args[-2]["user_id"] == 9

    selected = "😀 Анна"
    prefix = "Нора варн "
    entity = MessageEntity(type="text_mention", offset=len(prefix), length=len(selected.encode("utf-16-le")) // 2,
                           user=User(id=8, first_name="Анна <тест>", is_bot=False, username="alice"))
    warnings_before = (await db.get_user(8))["warnings"]
    await dispatch(prefix + selected + " спам в @канале", uid=7, entities=[entity])
    assert (await db.get_user(8))["warnings"] == warnings_before
    await dispatch(prefix + selected + " спам в @канале", uid=1, entities=[entity], reply_to_message=reply)
    assert (await db.get_user(8))["warnings"] == warnings_before + 1
    action = await db.fetchone(
        "SELECT target, reason, details FROM admin_audit_log WHERE action = 'warn' AND actor_id=1"
    )
    assert action["target"] == "8"
    assert action["reason"] == "спам в @канале"
    assert "|src:" not in action["details"]

    await db.execute("UPDATE users SET reputation = 80 WHERE user_id IN (7, 8)")
    await dispatch("не согласен @alice")
    assert (await db.get_user(8))["reputation"] == 75
    await dispatch("Нора репорт @alice спам", reply_to_message=reply)
    report = (await db.list_pending_reports())[0]
    assert (report["target_id"], report["message_id"], report["reason"]) == (8, 0, "спам")


async def test_chat_rankings_and_stats_use_main_chat_history(env, monkeypatch):
    db, dispatch, session = env
    today = datetime(2026, 11, 18, 12, tzinfo=ZoneInfo("Europe/Moscow"))
    monkeypatch.setattr(member_stats, "datetime", SimpleNamespace(now=lambda tz: today))
    await db.add_cookies(8, 800, "test", "")
    await db.add_cookies(9, 2_000, "test", "")
    await db.execute("UPDATE users SET profile_private = 1 WHERE user_id = 9")
    await db.ensure_user(10, "scores_bot", "Бот")
    await db.add_cookies(10, 9_000, "test", "")
    await db.execute(
        "INSERT INTO daily_scores VALUES "
        "(8,'2026-11-18',-100123,12),(8,'2026-11-17',-100123,3),(8,'2026-11-01',-100123,20),"
        "(8,'2026-10-31',-100123,60),(8,'2026-11-18',-200,999),(8,'2026-11-19',-100123,888),"
        "(9,'2026-11-18',-100123,20),(10,'2026-11-18',-100123,300)",
    )
    for uid in (8, 9, 10):
        await db.execute(
            "INSERT INTO user_activity(user_id, chat_id, message_count, last_message_at) VALUES (?, ?, ?, ?)",
            (uid, -100123, 1, today.isoformat()),
        )
    ok, _ = await db.purchase_pet(8, "cat", "Тест <кот>", 1)
    assert ok
    await db.execute("UPDATE pet_development SET level=2, stage=5 WHERE user_id=8")

    for suffix, label, value in (("", "сегодня", "12"), (" неделя", "неделю", "15"), (" месяц", "месяц", "35")):
        calls = await dispatch("Нора топ" + suffix)
        board = next(call.rich_message for call in calls if isinstance(call, SendRichMessage))
        assert label in board.blocks[0].text.text
        table = board.blocks[1].cells
        assert [cell.text for cell in table[0]] == ["№", "Участник", "Сообщения"]
        assert [row[1].text for row in table[1:3]] == (
            ["Анна <тест>", "Борис"] if suffix == " месяц" else ["Борис", "Анна <тест>"]
        )
        assert all(row[1].text != "Бот" for row in table)
        assert next(row[2].text for row in table if row[1].text == "Анна <тест>") == value
    await social_likes.give(db, 10, 8)
    await db.set_bot_state(f"{social_likes.COUNT_PREFIX}9", "100")
    sent = message(None, uid=123456).model_copy(update={
        "rich_message": RichMessage.model_validate(board.model_dump(exclude_none=True)),
    })
    for metric, header, rank in (("likes", "Лайки", "1"), ("cookies", "Печеньки", "799")):
        button = next(b for b in board.blocks[-1].buttons if b.callback_data == f"nora_top:{metric}:month")
        calls = await dispatch(CallbackQuery(id=metric, chat_instance="test", data=button.callback_data,
                                             from_user=User(id=7, first_name="Тест", is_bot=False), message=sent))
        edited = next(call for call in calls if isinstance(call, EditMessageText))
        assert edited.message_id == sent.message_id
        table = edited.rich_message.blocks[1].cells
        assert [[cell.text for cell in row] for row in table] == [
            ["№", "Участник", header], ["1", "Анна <тест>", rank],
        ]
        assert all(not isinstance(call, SendRichMessage) for call in calls)
    apply_rows([{"slug": "millionaires", "aliases_json": '["миллионеры"]'}])
    assert get_command("millionaires") is None
    assert not any(isinstance(call, SendRichMessage) for call in await dispatch("Нора миллионеры"))
    calls = await dispatch("Нора стата @alice")
    stats = next(call.text for call in calls if isinstance(call, SendMessage))
    assert "Сообщений в чате · <b>1" in stats
    assert "18 дн. с первого учтённого сообщения" in stats
    assert "Тест &lt;кот&gt; · уровень 2" in stats
    await db.remember_community_join(-100123, 8, "2026-10-01")
    await db.remember_community_join(-100123, 8, "2026-11-02")
    reply = message("Привет", uid=8).model_copy(update={
        "from_user": User(id=8, first_name="Анна <тест>", is_bot=False, username="alice"),
    })
    calls = await dispatch("Нора стата", reply_to_message=reply)
    assert any("48 дн.</b>" in call.text for call in calls if isinstance(call, SendMessage))
    calls = await dispatch("Нора стата @boris")
    assert any("Статистика скрыта" in call.text for call in calls if isinstance(call, SendMessage))
    await db.execute("UPDATE users SET profile_private = 0 WHERE user_id = 9")
    calls = await dispatch("Нора стата @boris")
    assert any("Питомец · <b>нет</b>" in call.text for call in calls if isinstance(call, SendMessage))

    chart = AsyncMock(return_value="Музыка")
    monkeypatch.setattr("community_bot.nora.music_chart", chart)
    await dispatch("Нора топ чартов")
    chart.assert_awaited_once()
    session.fail = lambda method: isinstance(method, SendRichMessage)
    calls = await dispatch("Нора топ")
    assert any("Анна &lt;тест&gt;" in call.text for call in calls if isinstance(call, SendMessage))


async def test_likes_share_daily_quota_and_purchase_restores_it(env, monkeypatch):
    db, dispatch, _ = env
    await db.ensure_user(7, username="test_user", telegram_name="Участник")
    await db.add_cookies(7, 50, "test", "")
    await db.execute("UPDATE users SET reputation=80 WHERE user_id=7")
    day = datetime.now(ZoneInfo("Europe/Moscow")).date()
    await db.set_bot_state(f"{social_likes.DAY_PREFIX}7", day.isoformat())
    calls = await dispatch("Поцеловать поцеловать @alice")
    post = next(call.text for call in calls if isinstance(call, SendMessage))
    assert post == '❤️ <a href="tg://user?id=7">@Участник 7</a> лайкнул <a href="tg://user?id=8">@alice</a>'
    assert await social_likes.count(db, 8) == 1

    sent = message(None, uid=123456)
    button = CallbackQuery(id="like", chat_instance="test", data="gprofile:like:9", message=sent,
                           from_user=User(id=7, first_name="Участник", is_bot=False))
    assert any(isinstance(call, SendMessage) for call in await dispatch(button))
    assert not any(isinstance(call, SendMessage) for call in await dispatch(button))
    assert await social_likes.count(db, 9) == 1

    await db.apply_reputation(7, 8, 0, day)
    await db.execute("UPDATE shop_items SET title=? WHERE sku='reset_limits'", ("Сброс лимитов репутации",))
    assert (await db.get_shop_item("reset_limits"))["title"] == "Сброс всех лимитов"
    ok, _ = await db.buy_item(7, "reset_limits", 15)
    assert ok and await db.reputation_actions_today(7, day) == 0
    assert any(isinstance(call, SendMessage) for call in await dispatch(button))
    assert await social_likes.count(db, 9) == 2 and await social_likes.count(db, 8) == 1

    next_day = datetime(day.year, day.month, day.day, tzinfo=ZoneInfo("Europe/Moscow"))
    monkeypatch.setattr(social_likes, "datetime", SimpleNamespace(now=lambda tz: next_day + timedelta(days=1)))
    results = await asyncio.gather(
        social_likes.give(db, 7, 8), social_likes.give(db, 7, 8), social_likes.give(db, 7, 9),
    )
    assert results.count(None) == 2
    assert await social_likes.count(db, 8) + await social_likes.count(db, 9) == 5


async def test_social_verbs_share_reputation_rules(env):
    db, dispatch, _ = env
    await db.ensure_user(7, telegram_name="Участник")
    await db.execute("UPDATE users SET reputation=CASE WHEN user_id=7 THEN 80 ELSE 60 END")
    for text, value in (("Обнять @alice", 65), ("Пнуть пнуть @alice", 60), ("Ударить", 55)):
        await dispatch(text, reply_to_message=message("Ответ", uid=8))
        assert (await db.get_user(8))["reputation"] == value
    await dispatch("Обнять @alice")
    assert (await db.get_user(8))["reputation"] == 55


@pytest.mark.parametrize("text", ["ЛАЙК лАйК", "нОРа,ЛайК", "НОРА лайк", "лайк, НОРА", "🩵💜", "😘", "😽", "👩🏿‍❤️‍💋‍👩"])
async def test_like_aliases_and_emoji_replies(env, text):
    db, dispatch, _ = env
    await dispatch(text, reply_to_message=message("Оригинал", uid=8))
    assert await social_likes.count(db, 8) == 1


async def test_native_reactions_and_textual_thumbs(env):
    db, dispatch, _ = env
    author = User(id=7, first_name="Реагирующий", is_bot=False)
    await db.ensure_user(author.id, telegram_name=author.full_name)
    await db.execute("UPDATE users SET reputation=CASE WHEN user_id=7 THEN 80 ELSE 60 END")
    await dispatch("Тема", uid=8, message_thread_id=42, is_topic_message=True)
    event = MessageReactionUpdated(chat=message(None).chat, message_id=1001, user=author,
                                   date=datetime.now(UTC), old_reaction=[], new_reaction=[])

    async def react(old, new, source=event):
        return await dispatch(source.model_copy(update={
            "old_reaction": [ReactionTypeEmoji(emoji=emoji) for emoji in old],
            "new_reaction": [ReactionTypeEmoji(emoji=emoji) for emoji in new],
        }))

    calls = await react([], ["💜", "👍"])
    posts = [call for call in calls if isinstance(call, SendMessage)]
    assert len(posts) == 2 and all(call.message_thread_id == 42 for call in posts)
    assert all(call.reply_parameters.message_id == 1001 for call in posts)
    assert await social_likes.count(db, 8) == 1 and (await db.get_user(8))["reputation"] == 65
    assert not await react(["💜", "👍"], ["💙", "👍"])
    assert not await react(["💙", "👍"], [])
    assert not await react([], ["👍"], source=event.model_copy(update={"message_id": 999}))
    await react([], ["👎"])
    assert (await db.get_user(8))["reputation"] == 60
    await dispatch("👍🏽", reply_to_message=message("Оригинал", uid=8))
    assert (await db.get_user(8))["reputation"] == 65
    await dispatch("👎", reply_to_message=message("Оригинал", uid=8))
    assert (await db.get_user(8))["reputation"] == 65


async def test_native_custom_kiss_can_use_known_author_from_archive(env, monkeypatch):
    db, dispatch, _ = env
    chat = message(None).chat
    now = datetime.now(UTC)
    await db.save_community_message(chat.id, 201, 8, "Анна", "Оригинал", now.isoformat(), 19)
    resolve = AsyncMock(return_value=[SimpleNamespace(custom_emoji_id="123", emoji="😽")])
    monkeypatch.setattr(Bot, "get_custom_emoji_stickers", resolve)
    event = MessageReactionUpdated(
        chat=chat, message_id=201, user=User(id=7, first_name="Отправитель", is_bot=False), date=now,
        old_reaction=[], new_reaction=[ReactionTypeCustomEmoji(custom_emoji_id="123")],
    )
    calls = await dispatch(event)
    assert any(call.message_thread_id == 19 for call in calls if isinstance(call, SendMessage))
    assert not await dispatch(event)
    assert await social_likes.count(db, 8) == 1
    resolve.assert_awaited_once_with(["123"])
