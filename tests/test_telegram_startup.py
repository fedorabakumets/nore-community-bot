"""Transient Telegram 502 responses must not break the Mini App startup path."""
import asyncio

import pytest
from aiogram.exceptions import TelegramServerError
from aiogram.methods import SetMyCommands

from community_bot.main import retry_transient_telegram_setup


async def test_telegram_setup_retries_server_failure_without_terminating(monkeypatch):
    calls = []
    waits = []

    async def operation():
        calls.append(len(calls) + 1)
        if len(calls) <= 2:
            raise TelegramServerError(method=SetMyCommands(commands=[]), message="Bad Gateway")
        return "configured"

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    assert await retry_transient_telegram_setup("commands", operation) == "configured"
    assert calls == [1, 2, 3]
    assert waits == [3, 6]


async def test_telegram_setup_does_not_hide_programming_errors():
    async def operation():
        raise ValueError("invalid local state")

    with pytest.raises(ValueError, match="invalid local state"):
        await retry_transient_telegram_setup("commands", operation)
