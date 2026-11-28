"""Regression: shop recovery must also lift legacy reputation mutes in Telegram."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ChatMemberStatus

from community_bot.database import Database
from community_bot.reputation_chat_access import sync_reputation_chat_access
from community_bot.shop_api import purchase


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    db = Database(tmp_path / "rep-recovery.db")
    await db.initialize()
    await db.ensure_user(7, telegram_name="User")
    await db.execute("UPDATE users SET reputation=45, cookies=100 WHERE user_id=7")
    settings = SimpleNamespace(community_chat_id=-100700, restricted_reputation_threshold=50)
    bot = SimpleNamespace(
        get_chat_member=AsyncMock(return_value=SimpleNamespace(
            status=ChatMemberStatus.RESTRICTED,
            is_member=True, can_send_messages=False, until_date=None,
        )),
        restrict_chat_member=AsyncMock(),
    )
    monkeypatch.setattr("community_bot.notify.vitrine_consumed", AsyncMock())
    monkeypatch.setattr("community_bot.life.unlock", AsyncMock())
    return db, settings, bot


async def buy_reputation(db, settings, bot):
    token = await db.create_wallet_intent(7, "restore_rep", 10)
    return await purchase(db, settings, bot, await db.get_user(7), token)


@pytest.mark.asyncio
async def test_miniapp_rep_purchase_reopens_legacy_untagged_mute(setup):
    db, settings, bot = setup
    assert await db.get_bot_state("reputation_chat_mute:-100700:7") is None
    ok, message = await buy_reputation(db, settings, bot)
    assert ok and "Доступ к чату" in message
    assert (await db.get_user(7))["reputation"] == 55
    bot.restrict_chat_member.assert_awaited_once()
    args = bot.restrict_chat_member.await_args
    assert args.args == (-100700, 7)
    assert args.kwargs["permissions"].can_send_messages is True
    assert args.kwargs["use_independent_chat_permissions"] is True
    assert await db.get_bot_state("reputation_chat_mute:-100700:7") == "0"


@pytest.mark.asyncio
async def test_miniapp_rep_purchase_at_40_does_not_unmute(setup):
    db, settings, bot = setup
    await db.execute("UPDATE users SET reputation=30 WHERE user_id=7")
    ok, message = await buy_reputation(db, settings, bot)
    assert ok and "минимум 50" in message
    assert (await db.get_user(7))["reputation"] == 40
    bot.restrict_chat_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_miniapp_recovery_can_release_prior_stuck_mute(setup):
    db, settings, bot = setup
    await db.execute("UPDATE users SET reputation=55 WHERE user_id=7")
    ok, message = await buy_reputation(db, settings, bot)
    assert ok and "Доступ к чату" in message
    bot.restrict_chat_member.assert_awaited_once()


@pytest.mark.asyncio
async def test_moderator_timed_mute_is_not_lifted(setup):
    db, settings, bot = setup
    bot.get_chat_member.return_value.until_date = datetime.now(UTC) + timedelta(hours=2)
    ok, message = await buy_reputation(db, settings, bot)
    assert ok and "модератором" in message
    bot.restrict_chat_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_moderator_permanent_mute_is_not_lifted(setup):
    db, settings, bot = setup
    await db.log_admin_action(
        1, "mute", "7", "навсегда", actor_name="Модератор", target_name="User",
    )
    ok, message = await buy_reputation(db, settings, bot)
    assert ok and "модератором" in message
    bot.restrict_chat_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_captcha_mute_is_not_lifted_on_recovery(setup):
    db, settings, bot = setup
    await db.add_captcha(7, settings.community_chat_id)
    ok, _message = await buy_reputation(db, settings, bot)
    assert ok
    bot.restrict_chat_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_mute_requires_explicit_recovery_event(setup):
    db, settings, bot = setup
    assert await sync_reputation_chat_access(
        db, settings, bot, settings.community_chat_id, 7, 50,
    ) is None
    bot.restrict_chat_member.assert_not_awaited()
    assert await sync_reputation_chat_access(
        db, settings, bot, settings.community_chat_id, 7, 50,
        allow_legacy_recovery=True,
    ) == "restored"
    bot.restrict_chat_member.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_membership_no_unmute(setup):
    db, settings, bot = setup
    bot.get_chat_member.return_value.is_member = False
    assert await sync_reputation_chat_access(
        db, settings, bot, settings.community_chat_id, 7, 55,
        allow_legacy_recovery=True,
    ) is None
    bot.restrict_chat_member.assert_not_awaited()
