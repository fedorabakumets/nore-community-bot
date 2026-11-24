from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import User

from community_bot.routers import group


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(group, "_like_limit_notices", {})
    monkeypatch.setattr(group.time, "monotonic", lambda: now[0])
    return now


def test_notice_cooldown_is_per_ordered_pair(clock):
    assert group._claim_like_limit_notice(1, 2) == 1000
    assert group._claim_like_limit_notice(1, 2) is None
    assert group._claim_like_limit_notice(1, 3) == 1000
    assert group._claim_like_limit_notice(2, 1) == 1000
    clock[0] += 299
    assert group._claim_like_limit_notice(1, 2) is None
    clock[0] += 1
    assert group._claim_like_limit_notice(1, 2) == 1300
    assert len(group._like_limit_notices) == 1


async def test_notice_contains_direct_game_links_and_is_throttled(clock):
    bot = SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(username="nora_test_bot")))
    actor = User(id=1, is_bot=False, first_name="Test", username="testuser")
    send = AsyncMock()
    await group._send_like_limit_notice(bot, actor, {"user_id": 2}, send)
    await group._send_like_limit_notice(bot, actor, {"user_id": 2}, send)
    send.assert_awaited_once()
    text = send.call_args.args[0]
    assert "лайк этому человеку уже поставлен" in text
    assert 'https://t.me/nora_test_bot?startapp=nora_to_durak">Дурака</a>' in text
    assert 'https://t.me/nora_test_bot?startapp=nora_to_barricade">Баррикаду</a>' in text
    assert send.call_args.kwargs["link_preview_options"].is_disabled
    clock[0] += 300
    await group._send_like_limit_notice(bot, actor, {"user_id": 2}, send)
    assert send.await_count == 2


async def test_failed_notice_can_retry(clock):
    bot = SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(username="nora_test_bot")))
    actor = User(id=1, is_bot=False, first_name="Test")
    send = AsyncMock(side_effect=RuntimeError("offline"))
    with pytest.raises(RuntimeError):
        await group._send_like_limit_notice(bot, actor, {"user_id": 2}, send)
    send.side_effect = None
    await group._send_like_limit_notice(bot, actor, {"user_id": 2}, send)
    assert send.await_count == 2
