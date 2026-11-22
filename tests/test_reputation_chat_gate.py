"""Regression tests: below-bronze members must not post to the community."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ChatMemberStatus
from aiogram.types import Chat, Message, User

from community_bot.database import Database
from community_bot.routers import group


def message(user_id: int = 17, chat_id: int = -100123) -> Message:
    return Message(
        message_id=42,
        date=datetime.now(UTC),
        chat=Chat(id=chat_id, type="supergroup"),
        from_user=User(id=user_id, is_bot=False, first_name="Участник"),
        text="обычное сообщение",
    )


async def setup_gate(monkeypatch, tmp_path, *, reputation: int, admin: bool = False):
    db = Database(tmp_path / "rep-gate.db")
    await db.initialize()
    await db.ensure_user(17, telegram_name="Участник")
    await db.execute("UPDATE users SET reputation=? WHERE user_id=17", (reputation,))
    monkeypatch.setattr(group, "Settings", SimpleNamespace)
    monkeypatch.setattr(group, "Bot", SimpleNamespace)
    monkeypatch.setattr(group, "needs_reapplication", AsyncMock(return_value=False))
    monkeypatch.setattr(group, "rank_of_user", AsyncMock(return_value=0))
    monkeypatch.setattr(Message, "delete", AsyncMock())
    monkeypatch.setattr(db, "list_feature_flags", AsyncMock(return_value=[]))
    activity = AsyncMock(return_value=(1, False))
    monkeypatch.setattr(db, "record_activity", activity)
    bot = SimpleNamespace(
        get_chat_member=AsyncMock(return_value=SimpleNamespace(
            status=ChatMemberStatus.ADMINISTRATOR if admin else ChatMemberStatus.MEMBER,
        )),
        restrict_chat_member=AsyncMock(),
        send_message=AsyncMock(),
    )
    settings = SimpleNamespace(community_chat_id=-100123, restricted_reputation_threshold=50)
    return db, bot, settings, activity


@pytest.mark.asyncio
async def test_below_bronze_message_is_deleted_and_member_remuted(monkeypatch, tmp_path):
    db, bot, settings, activity = await setup_gate(monkeypatch, tmp_path, reputation=49)
    middleware = group.CommunityModerationMiddleware()
    handler = AsyncMock(return_value="delivered")
    data = {"db": db, "bot": bot, "settings": settings}

    assert await middleware(handler, message(), data) is None
    assert await middleware(handler, message(), data) is None
    assert Message.delete.await_count == 2
    assert bot.restrict_chat_member.await_count == 2
    kwargs = bot.restrict_chat_member.await_args.kwargs
    assert kwargs["permissions"].can_send_messages is False
    assert bot.send_message.await_count == 1  # Do not flood private chat with notices.
    handler.assert_not_awaited()
    activity.assert_not_awaited()


@pytest.mark.asyncio
async def test_bronze_member_can_write(monkeypatch, tmp_path):
    db, bot, settings, activity = await setup_gate(monkeypatch, tmp_path, reputation=50)
    handler = AsyncMock(return_value="delivered")
    result = await group.CommunityModerationMiddleware()(
        handler, message(), {"db": db, "bot": bot, "settings": settings},
    )
    assert result == "delivered"
    handler.assert_awaited_once()
    bot.restrict_chat_member.assert_not_awaited()
    Message.delete.assert_not_awaited()
    activity.assert_awaited_once()


@pytest.mark.asyncio
async def test_other_group_is_not_reputation_gated(monkeypatch, tmp_path):
    db, bot, settings, _ = await setup_gate(monkeypatch, tmp_path, reputation=-10)
    handler = AsyncMock(return_value="delivered")
    result = await group.CommunityModerationMiddleware()(
        handler, message(chat_id=-100321), {"db": db, "bot": bot, "settings": settings},
    )
    assert result == "delivered"
    handler.assert_awaited_once()
    bot.restrict_chat_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_admin_is_not_restricted(monkeypatch, tmp_path):
    db, bot, settings, _ = await setup_gate(monkeypatch, tmp_path, reputation=-5, admin=True)
    handler = AsyncMock(return_value="delivered")
    result = await group.CommunityModerationMiddleware()(
        handler, message(), {"db": db, "bot": bot, "settings": settings},
    )
    assert result == "delivered"
    handler.assert_awaited_once()
    bot.restrict_chat_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_unmute_command_cannot_override_reputation_gate(monkeypatch):
    monkeypatch.setattr(group, "_require_perm", AsyncMock(return_value="admin"))
    monkeypatch.setattr(group, "_take_target", AsyncMock(return_value=(
        {"user_id": 27, "reputation": -1}, [],
    )))
    respond = AsyncMock()
    monkeypatch.setattr(group, "_respond", respond)
    bot = SimpleNamespace(restrict_chat_member=AsyncMock())
    settings = SimpleNamespace(restricted_reputation_threshold=50)
    await group.unmute_member(message(), SimpleNamespace(), settings, bot)
    bot.restrict_chat_member.assert_not_awaited()
    assert "ниже бронзы" in respond.await_args.args[1].lower()


@pytest.mark.asyncio
async def test_miniapp_chat_relay_cannot_bypass_reputation_gate(monkeypatch, tmp_path):
    from community_bot import staff_chat_send

    db = Database(tmp_path / "miniapp-rep-gate.db")
    await db.initialize()
    await db.ensure_user(17, telegram_name="Участник")
    await db.execute("UPDATE users SET reputation=49 WHERE user_id=17")
    monkeypatch.setattr(staff_chat_send, "staff_allowed", AsyncMock(return_value=True))
    bot = SimpleNamespace(send_message=AsyncMock())
    settings = SimpleNamespace(
        community_chat_id=-100123, restricted_reputation_threshold=50,
    )

    class Request(dict):
        app = {"db": db, "settings": settings, "bot": bot}

    credentials, denied = await staff_chat_send._member(Request(actor={"id": 17}))
    assert credentials is None
    assert denied.status == 403
    bot.send_message.assert_not_awaited()
