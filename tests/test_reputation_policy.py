"""Bronze entry, vote weights and reputation-owned Telegram chat permissions."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ChatMemberStatus

from community_bot.database import Database
from community_bot.domain import BRONZE_REPUTATION_MIN, reputation_delta, reputation_tier
from community_bot.reputation import change_community_reputation
from community_bot.reputation_chat_access import sync_reputation_chat_access


@pytest.mark.parametrize(("points", "tier"), [
    (-20, "restricted"), (0, "restricted"), (49, "restricted"),
    (50, "bronze"), (69, "bronze"), (70, "silver"),
    (89, "silver"), (90, "gold"), (100, "gold"),
])
def test_reputation_tier_boundaries(points, tier):
    assert BRONZE_REPUTATION_MIN == 50
    assert reputation_tier(points).key == tier


@pytest.mark.parametrize("phrase", [
    "-реп", "−реп", "–реп", "не согласен", "не уважаю",
    "пнуть", "пнуть пнуть", "ударить", "ударить ударить", "ты не прав",
])
def test_every_negative_reputation_phrase_costs_ten(phrase):
    assert reputation_delta(phrase) == -10


@pytest.mark.parametrize("phrase", [
    "+реп", "+", "согласен", "уважаю", "ты прав", "обнять",
])
def test_every_positive_reputation_phrase_gives_five(phrase):
    assert reputation_delta(phrase) == 5


@pytest.mark.asyncio
async def test_reputation_vote_moves_target_through_bronze_boundary(tmp_path):
    db = Database(tmp_path / "votes.db")
    await db.initialize()
    for uid in (1, 2, 3):
        await db.ensure_user(uid, telegram_name=f"User {uid}")
    await db.execute("UPDATE users SET reputation=80 WHERE user_id=1")
    await db.execute("UPDATE users SET reputation=50 WHERE user_id=2")
    await db.execute("UPDATE users SET reputation=55 WHERE user_id=3")
    settings = SimpleNamespace(restricted_reputation_threshold=50)
    actor = await db.get_user(1)
    bronze = await db.get_user(2)
    ok, text, current, _ = await change_community_reputation(
        db, settings, actor, bronze, reputation_delta("-реп"), date.today(),
    )
    assert ok and current == 40
    assert "-10" in text
    assert reputation_tier(current).key == "restricted"

    bronze_actor = await db.get_user(3)
    low_target = await db.get_user(2)
    ok, text, current, _ = await change_community_reputation(
        db, settings, bronze_actor, low_target, reputation_delta("+реп"), date.today(),
    )
    assert ok and current == 45
    assert "+5" in text
    ok, text, current, _ = await change_community_reputation(
        db, settings, actor, low_target, reputation_delta("+реп"), date.today(),
    )
    assert ok and current == 50
    assert reputation_tier(current).key == "bronze"


@pytest.fixture
async def gate(tmp_path):
    db = Database(tmp_path / "permissions.db")
    await db.initialize()
    await db.ensure_user(7, telegram_name="Guest")
    settings = SimpleNamespace(community_chat_id=-100987, restricted_reputation_threshold=50)
    bot = SimpleNamespace(
        get_chat_member=AsyncMock(return_value=SimpleNamespace(status=ChatMemberStatus.MEMBER)),
        restrict_chat_member=AsyncMock(),
    )
    return db, settings, bot


@pytest.mark.asyncio
async def test_gate_restores_only_its_own_mute_at_50(gate):
    db, settings, bot = gate
    action = sync_reputation_chat_access
    assert await action(db, settings, bot, -100987, 7, 49) == "restricted"
    assert bot.restrict_chat_member.await_count == 1
    assert bot.restrict_chat_member.await_args.kwargs["permissions"].can_send_messages is False
    assert await db.get_bot_state("reputation_chat_mute:-100987:7") == "1"

    bot.get_chat_member.return_value = SimpleNamespace(
        status=ChatMemberStatus.RESTRICTED, is_member=True,
        can_send_messages=False, until_date=None,
    )
    assert await action(db, settings, bot, -100987, 7, 50) == "restored"
    assert bot.restrict_chat_member.await_count == 2
    assert bot.restrict_chat_member.await_args.kwargs["permissions"].can_send_messages is True
    assert await db.get_bot_state("reputation_chat_mute:-100987:7") == "0"


@pytest.mark.asyncio
async def test_manual_mute_remains_after_reputation_recovers(gate):
    db, settings, bot = gate
    bot.get_chat_member.return_value = SimpleNamespace(
        status=ChatMemberStatus.RESTRICTED, is_member=True,
        can_send_messages=False, until_date=datetime.now(UTC) + timedelta(hours=1),
    )
    # A moderator already muted this participant: reputation cannot own the mute.
    assert await sync_reputation_chat_access(db, settings, bot, -100987, 7, 49) is None
    assert await sync_reputation_chat_access(db, settings, bot, -100987, 7, 50) is None
    bot.restrict_chat_member.assert_not_awaited()
    assert await db.get_bot_state("reputation_chat_mute:-100987:7") is None


@pytest.mark.asyncio
async def test_manual_timed_mute_replaces_former_reputation_mute(gate):
    db, settings, bot = gate
    assert await sync_reputation_chat_access(db, settings, bot, -100987, 7, 49) == "restricted"
    bot.restrict_chat_member.reset_mock()
    bot.get_chat_member.return_value = SimpleNamespace(
        status=ChatMemberStatus.RESTRICTED, is_member=True,
        can_send_messages=False, until_date=datetime.now(UTC) + timedelta(days=1),
    )
    assert await sync_reputation_chat_access(db, settings, bot, -100987, 7, 50) is None
    bot.restrict_chat_member.assert_not_awaited()
    assert await db.get_bot_state("reputation_chat_mute:-100987:7") == "0"


@pytest.mark.asyncio
async def test_other_group_does_not_get_reputation_mute(gate):
    db, settings, bot = gate
    assert await sync_reputation_chat_access(db, settings, bot, -100321, 7, 49) is None
    bot.restrict_chat_member.assert_not_awaited()
