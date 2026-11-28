"""Closed game access checks without real bot or wallet writes."""
from unittest.mock import AsyncMock

import pytest

from community_bot import beta_games, poker_api


@pytest.mark.parametrize("role,expected", [("owner", True), ("admin", True), ("moderator", False), ("user", False)])
async def test_beta_role(monkeypatch, role, expected):
    monkeypatch.setattr(beta_games, "effective_role", AsyncMock(return_value=role))
    assert await beta_games.allowed(None, None, 1) is expected
    req = {"actor": {"id": 1}}
    class Request(dict):
        app = {"db": None, "settings": None}
    response = await beta_games.dice_access(Request(req))
    assert response.status == (200 if expected else 403)


@pytest.mark.parametrize("kind", ["create", "state", "join", "command", "link"])
async def test_poker_denies_before_wallet(monkeypatch, kind):
    monkeypatch.setattr(beta_games, "allowed", AsyncMock(return_value=False))
    class Request(dict):
        app = {"db": None, "settings": None}
        match_info = {"kind": kind}
        path = "/api/poker/rooms"
        method = "POST"
    response = await poker_api.action(Request(actor={"id": 1}))
    assert response.status == 403
