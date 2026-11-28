"""Production regression: no replay mutes, stable polling and resilient transfer cards."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramServerError
from aiogram.methods import DeleteMessage, GetUpdates, SendMessage
from aiogram.types import Chat, Message, Update, User

from community_bot.community_scope import FreshMessageMiddleware
from community_bot.ephemeral import GroupHousekeepingMiddleware
from community_bot.message_widgets import SendWidget, WidgetSession, try_send


def msg(text="Нора перевести 100", *, age=0, mid=25):
    return Message(
        message_id=mid, date=datetime.now(UTC)-timedelta(seconds=age),
        chat=Chat(id=-100123, type="supergroup"),
        from_user=User(id=17, is_bot=False, first_name="Участник"),
        text=text,
    )


@pytest.mark.asyncio
async def test_old_group_commands_are_dropped_before_any_handlers():
    middleware = FreshMessageMiddleware()
    observed = []

    async def handler(event, _data):
        observed.append((event.message or event.edited_message).message_id)
        return "processed"

    old = Update(update_id=1, message=msg(age=3600, mid=17))
    assert await middleware(handler, old, {}) is None
    assert observed == []
    recent = Update(update_id=2, message=msg(age=4, mid=18))
    assert await middleware(handler, recent, {}) == "processed"
    assert observed == [18]

    # An edit to a historical message can still be a current update.
    edited = msg(age=86400, mid=19).model_copy(
        update={"edit_date": datetime.now(UTC)}
    )
    assert await middleware(handler, Update(update_id=3, edited_message=edited), {}) == "processed"


@pytest.mark.asyncio
async def test_beta_widgets_never_take_over_get_updates(monkeypatch):
    from aiogram.client.session.aiohttp import AiohttpSession

    stable, beta = [], []

    async def stable_request(self, bot, method, timeout=None):
        stable.append(method.__api_method__)
        return []

    async def beta_request(bot, method, timeout=None):
        beta.append(method.__api_method__)
        return None

    monkeypatch.setattr(AiohttpSession, "make_request", stable_request)
    session = WidgetSession()
    monkeypatch.setattr(session.widget_api, "make_request", beta_request)
    bot = SimpleNamespace()
    await session.make_request(bot, GetUpdates())
    await session.make_request(bot, SendWidget(chat_id=42, html="x", caption="x"))
    assert stable == ["getUpdates"]
    assert beta == ["sendWidget"]
    await session.close()


@pytest.mark.asyncio
async def test_cleanup_502_does_not_swallow_transfer_handler():
    bot = SimpleNamespace(delete_message=AsyncMock(
        side_effect=TelegramServerError(
            method=DeleteMessage(chat_id=-100123, message_id=25),
            message="Bad Gateway",
        )
    ))
    reached = []

    async def handler(message, _data):
        reached.append(message.text)

    await GroupHousekeepingMiddleware()(
        handler, msg(), {"bot": bot}
    )
    assert reached == ["Нора перевести 100"]
    assert bot.delete_message.await_count >= 1


@pytest.mark.asyncio
async def test_widget_502_falls_back_to_normal_transfer_buttons():
    bot = SimpleNamespace()

    async def beta_fail(_bot, request):
        raise TelegramServerError(method=request, message="Bad Gateway")

    request = SendWidget(chat_id=-100123, html="<b>Перевод</b>", caption="Перевод")
    assert await try_send(beta_fail, bot, request) is None
    assert getattr(bot, "_nora_widgets_retry_at", 0) > 0
    assert await try_send(beta_fail, bot, request) is None


@pytest.mark.asyncio
async def test_moderation_uses_sent_time_not_replay_arrival(monkeypatch, tmp_path):
    from community_bot import routers
    from community_bot.routers import group
    from community_bot.database import Database

    db = Database(tmp_path / "anti-flood.db")
    await db.initialize()
    await db.ensure_user(17, telegram_name="Участник")
    monkeypatch.setattr(group, "Settings", SimpleNamespace)
    monkeypatch.setattr(group, "Bot", SimpleNamespace)
    monkeypatch.setattr(group, "register_telegram_user", AsyncMock(return_value={"user_id": 17, "reputation": 69}))
    monkeypatch.setattr(Message, "delete", AsyncMock(return_value=True))
    monkeypatch.setattr(group, "needs_reapplication", AsyncMock(return_value=False))
    monkeypatch.setattr(group, "rank_of_user", AsyncMock(return_value=0))
    monkeypatch.setattr(db, "list_feature_flags", AsyncMock(return_value=[
        {"key": "anti_flood", "enabled": 1}
    ]))
    monkeypatch.setattr(db, "record_activity", AsyncMock(return_value=(1, False)))

    bot = SimpleNamespace(
        get_chat_member=AsyncMock(return_value=SimpleNamespace(status=ChatMemberStatus.MEMBER)),
        restrict_chat_member=AsyncMock(),
        send_message=AsyncMock(),
    )
    settings = SimpleNamespace(community_chat_id=-100123, restricted_reputation_threshold=0)
    middleware = group.CommunityModerationMiddleware()
    forward = AsyncMock()

    # Seven old messages processed simultaneously must NOT trigger a mute.
    for i in range(7):
        await middleware(forward, msg("обычный текст", age=75-i, mid=100+i),
                         {"db": db, "settings": settings, "bot": bot})
    bot.restrict_chat_member.assert_not_awaited()
    assert forward.await_count == 7

    # Seven *real*, closely spaced new messages still trigger ordinary anti-flood.
    for i in range(7):
        await middleware(forward, msg("обычный текст", age=1, mid=200+i),
                         {"db": db, "settings": settings, "bot": bot})
    bot.restrict_chat_member.assert_awaited_once()


@pytest.mark.asyncio
async def test_transient_admin_lookup_failure_does_not_assume_member(tmp_path):
    from community_bot.routers.group import CommunityModerationMiddleware
    middleware = CommunityModerationMiddleware()
    bot = SimpleNamespace(get_chat_member=AsyncMock(
        side_effect=TelegramServerError(
            method=SendMessage(chat_id=-100123, text="x"),
            message="Bad Gateway",
        )
    ))
    assert await middleware._is_telegram_admin(bot, -100123, 17) is True
