from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.methods import SendMessage, SendRichMessage
from aiogram.types import MessageEntity, Update, User
from test_nora_commands_release import message
from test_studio_rsvp import TelegramSession

from community_bot.command_registry import restore_defaults
from community_bot.config import load_settings
from community_bot.database import Database
from community_bot.ephemeral import GroupHousekeepingMiddleware
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
    dispatcher.message.outer_middleware(GroupHousekeepingMiddleware())
    for source in (nora.router, life.router, member_stats.router, group.router, nora.assistant_router):
        router = Router()
        router.message.handlers.extend(source.message.handlers)
        dispatcher.include_router(router)
    session = TelegramSession()
    bot = Bot(settings.bot_token, session=session)
    monkeypatch.setattr(bot, "get_chat_member", AsyncMock(return_value=SimpleNamespace(status="member")))
    calls = 0

    async def dispatch(text, **kwargs):
        nonlocal calls
        calls += 1
        session.calls.clear()
        event = message(text, **kwargs).model_copy(update={"message_id": calls + 1000})
        await dispatcher.feed_update(bot, Update(update_id=calls, message=event), db=db, settings=settings)
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
    calls = await dispatch("Нора миллионеры")
    table = next(call.rich_message.blocks[1].cells for call in calls if isinstance(call, SendRichMessage))
    assert [[cell.text for cell in row] for row in table] == [
        ["№", "Участник", "Печеньки"], ["1", "Анна <тест>", "799"],
    ]
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
