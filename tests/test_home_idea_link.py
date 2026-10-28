from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from community_bot.routers import private


@pytest.mark.parametrize('payload,opens_ticket', [('idea', True), ('', False)])
async def test_start_idea_reuses_ticket_flow_without_changing_normal_start(monkeypatch, payload, opens_ticket):
    message = SimpleNamespace(from_user=SimpleNamespace(id=7), chat=SimpleNamespace(type='private'),
                              text='/start '+payload, bot=object())
    state, db, settings = AsyncMock(), object(), object()
    register, ticket, welcome, keyboard = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(private, 'register_telegram_user', register)
    monkeypatch.setattr(private, 'open_ticket', ticket)
    monkeypatch.setattr(private, '_send_welcome', welcome)
    monkeypatch.setattr(private, '_private_keyboard', keyboard)
    await private.start(message, state, db, settings)
    state.clear.assert_awaited_once()
    register.assert_awaited_once_with(db, message.from_user)
    if opens_ticket:
        ticket.assert_awaited_once_with(message, state, db, settings, message.bot)
        welcome.assert_not_awaited()
    else:
        ticket.assert_not_awaited()
        welcome.assert_awaited_once()
