"""Contest links and confirmed unique memberships remain one source of truth."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from community_bot.database import Database
from community_bot import referral_campaign as campaign


@pytest.fixture
async def setup(tmp_path):
    db = Database(tmp_path / "referrals.sqlite")
    await db.initialize()
    for uid in (101, 102, 201, 202, 203, 204):
        await db.ensure_user(uid, telegram_name=f"User {uid}")
    return db


def event(uid: int, url: str | None = None, *, when=None):
    return SimpleNamespace(
        chat=SimpleNamespace(id=-100777),
        date=when or datetime(2026, 11, 25, 15, 0, tzinfo=UTC),
        new_chat_member=SimpleNamespace(
            user=SimpleNamespace(id=uid, is_bot=False)
        ),
        invite_link=SimpleNamespace(invite_link=url) if url else None,
    )


def request(uid: int, url: str, *, when=None):
    return SimpleNamespace(
        date=when or datetime(2026, 11, 25, 14, 0, tzinfo=UTC),
        from_user=SimpleNamespace(id=uid, is_bot=False),
        invite_link=SimpleNamespace(invite_link=url),
    )


@pytest.mark.asyncio
async def test_one_link_forever_and_repeated_dm_clicks(setup):
    bot = SimpleNamespace(
        create_chat_invite_link=AsyncMock(
            return_value=SimpleNamespace(invite_link="https://t.me/+NoraA")
        ),
    )
    settings = SimpleNamespace(community_chat_id=-100777)
    # Seed via a preexisting persistent link to make this time-independent.
    await setup.execute(
        "INSERT INTO referral_campaign_links "
        "(campaign,user_id,invite_link,invite_name,created_at) VALUES(?,?,?,?,?)",
        (campaign.CAMPAIGN, 101, "https://t.me/+NoraA", "NORA26-101", "2026-11-22"),
    )
    assert await campaign.get_or_create_link(bot, setup, settings, 101) == "https://t.me/+NoraA"
    assert await campaign.get_or_create_link(bot, setup, settings, 101) == "https://t.me/+NoraA"
    bot.create_chat_invite_link.assert_not_awaited()


@pytest.mark.asyncio
async def test_verified_join_counts_only_once(setup):
    await setup.execute(
        "INSERT INTO referral_campaign_links VALUES(?,?,?,?,?)",
        (campaign.CAMPAIGN, 101, "https://t.me/+NoraA", "NORA26-101", "2026-11-22"),
    )
    first = event(201, "https://t.me/+NoraA")
    assert await campaign.record_join(setup, first)
    assert not await campaign.record_join(setup, first)
    assert not await campaign.record_join(setup, event(101, "https://t.me/+NoraA"))
    assert not await campaign.record_join(setup, event(202, "https://t.me/+Foreign"))
    assert (await campaign.leaderboard(setup))[0]["invites"] == 1


@pytest.mark.asyncio
async def test_request_fallback_is_only_used_if_event_has_no_other_link(setup):
    await setup.execute(
        "INSERT INTO referral_campaign_links VALUES(?,?,?,?,?)",
        (campaign.CAMPAIGN, 101, "https://t.me/+NoraA", "NORA26-101", "2026-11-22"),
    )
    await campaign.remember_request(setup, request(201, "https://t.me/+NoraA"))
    assert not await campaign.record_join(setup, event(201, "https://t.me/+Other"))
    assert await campaign.record_join(setup, event(201))
    assert (await campaign.leaderboard(setup))[0]["invites"] == 1


@pytest.mark.asyncio
async def test_old_member_and_duplicate_cross_referrer_are_rejected(setup):
    await setup.execute(
        "INSERT INTO referral_campaign_links VALUES(?,?,?,?,?)",
        (campaign.CAMPAIGN, 101, "https://t.me/+NoraA", "NORA26-101", "2026-11-22"),
    )
    await setup.execute(
        "INSERT INTO referral_campaign_links VALUES(?,?,?,?,?)",
        (campaign.CAMPAIGN, 102, "https://t.me/+NoraB", "NORA26-102", "2026-11-22"),
    )
    await setup.set_bot_state("community_join:-100777:202", "2026-10-01")
    assert not await campaign.record_join(setup, event(202, "https://t.me/+NoraA"))
    await setup.execute(
        "INSERT INTO daily_scores(user_id,day,chat_id,messages) VALUES(?,?,?,?)",
        (203, "2026-11-01", -100777, 10),
    )
    assert not await campaign.record_join(setup, event(203, "https://t.me/+NoraA"))
    assert await campaign.record_join(setup, event(204, "https://t.me/+NoraA"))
    assert not await campaign.record_join(setup, event(204, "https://t.me/+NoraB"))
    assert (await campaign.leaderboard(setup))[0]["invites"] == 1


@pytest.mark.asyncio
async def test_expired_join_and_empty_board(setup):
    await setup.execute(
        "INSERT INTO referral_campaign_links VALUES(?,?,?,?,?)",
        (campaign.CAMPAIGN, 101, "https://t.me/+NoraA", "NORA26-101", "2026-11-22"),
    )
    assert await campaign.leaderboard(setup) == []
    assert not await campaign.record_join(
        setup, event(201, "https://t.me/+NoraA", when=campaign.END + timedelta(seconds=1)),
    )
