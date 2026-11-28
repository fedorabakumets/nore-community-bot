from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import User

from community_bot.routers import group


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(group, "_like_limit_notices", {})
    monkeypatch.setattr(group, "time", SimpleNamespace(monotonic=lambda: now[0]))
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


async def test_notice_contains_colored_rich_game_buttons_and_is_throttled(clock):
    bot = SimpleNamespace(
        me=AsyncMock(return_value=SimpleNamespace(username="nora_test_bot")),
        send_rich_message=AsyncMock(),
    )
    actor = User(id=1, is_bot=False, first_name="Test", username="testuser")
    for _ in range(2):
        await group._send_like_limit_notice(bot, actor, {"user_id": 2}, -100123, 44, 7)
    bot.send_rich_message.assert_awaited_once()
    kwargs = bot.send_rich_message.call_args.kwargs
    blocks = kwargs["rich_message"].blocks
    assert len(blocks) == 2
    assert blocks[0].text.startswith("💔 Лайк этому участнику уже поставлен.")
    assert [(b.text, b.style, b.url) for b in blocks[1].buttons] == [
        ("🃏 Дурак", "primary", "https://t.me/nora_test_bot?startapp=nora_to_durak"),
        ("🪵 Баррикада", "success", "https://t.me/nora_test_bot?startapp=nora_to_barricade"),
    ]
    assert kwargs["reply_parameters"].message_id == 44
    assert kwargs["message_thread_id"] == 7
    clock[0] += 300
    await group._send_like_limit_notice(bot, actor, {"user_id": 2}, -100123, 44, 7)
    assert bot.send_rich_message.await_count == 2


async def test_failed_notice_can_retry(clock):
    bot = SimpleNamespace(
        me=AsyncMock(return_value=SimpleNamespace(username="nora_test_bot")),
        send_rich_message=AsyncMock(side_effect=RuntimeError("offline")),
    )
    actor = User(id=1, is_bot=False, first_name="Test")
    with pytest.raises(RuntimeError):
        await group._send_like_limit_notice(bot, actor, {"user_id": 2}, -100123, 44)
    bot.send_rich_message.side_effect = None
    await group._send_like_limit_notice(bot, actor, {"user_id": 2}, -100123, 44)
    assert bot.send_rich_message.await_count == 2


async def test_rich_rejection_falls_back_to_colored_buttons(clock):
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import SendMessage

    bot = SimpleNamespace(
        me=AsyncMock(return_value=SimpleNamespace(username="nora_test_bot")),
        send_rich_message=AsyncMock(side_effect=TelegramBadRequest(
            method=SendMessage(chat_id=-100123, text="test"), message="unsupported",
        )),
        send_message=AsyncMock(),
    )
    actor = User(id=1, is_bot=False, first_name="Test")
    await group._send_like_limit_notice(bot, actor, {"user_id": 2}, -100123, 44, 7)
    kwargs = bot.send_message.call_args.kwargs
    assert [b.style for b in kwargs["reply_markup"].inline_keyboard[0]] == ["primary", "success"]
    assert kwargs["reply_parameters"].message_id == 44
    assert kwargs["message_thread_id"] == 7


async def test_reaction_duplicate_replies_to_original_message(clock, monkeypatch):
    from community_bot import social_likes

    actor = User(id=1, is_bot=False, first_name="Test")
    event = SimpleNamespace(
        user=actor, chat=SimpleNamespace(id=-100123), message_id=44, new_reaction=[object()],
    )
    authors = SimpleNamespace(
        claim_update=lambda _: True,
        added=AsyncMock(return_value={"like"}),
        target=AsyncMock(return_value=({"user_id": 2}, 7)),
    )
    bot = SimpleNamespace(
        me=AsyncMock(return_value=SimpleNamespace(username="nora_test_bot")),
        send_rich_message=AsyncMock(),
    )
    monkeypatch.setattr(group, "needs_reapplication", AsyncMock(return_value=False))
    monkeypatch.setattr(group, "_give_like", AsyncMock(return_value=social_likes.ALREADY_PROFILE_LIKED))
    settings = SimpleNamespace(community_chat_id=-100123)
    await group.group_reaction(event, SimpleNamespace(update_id=1), None, settings, bot, authors)
    await group.group_reaction(event, SimpleNamespace(update_id=2), None, settings, bot, authors)
    bot.send_rich_message.assert_awaited_once()
    kwargs = bot.send_rich_message.call_args.kwargs
    assert kwargs["reply_parameters"].message_id == 44
    assert kwargs["message_thread_id"] == 7
    clock[0] += 300
    await group.group_reaction(event, SimpleNamespace(update_id=3), None, settings, bot, authors)
    assert bot.send_rich_message.await_count == 2
