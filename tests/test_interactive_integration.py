"""Mini App boundary and startup guarantees for persistent interactive features."""
import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from test_miniapp import signed

from community_bot.database import Database
from community_bot.interactive_runtime import lifecycle, settle
from community_bot.miniapp import create_app, protection


@pytest.fixture
async def env(tmp_path):
    db = Database(tmp_path / 'interactive-integration.db')
    await db.initialize()
    await db.ensure_user(7, username='test_anna', telegram_name='Анна')
    await db.add_cookies(7, 30, 'fixture')
    settings = SimpleNamespace(bot_token='test-only', owner_ids=frozenset(),
                               is_owner=lambda uid: False, moderator_ids=frozenset(),
                               restricted_reputation_threshold=0, timezone='Europe/Moscow')
    return SimpleNamespace(db=db, settings=settings)


class Request(dict):
    def __init__(self, env, path, authorized):
        super().__init__()
        self.path = path
        self.app = {'db': env.db, 'settings': env.settings, 'bot': None}
        self.headers = {'Authorization': 'tma ' + signed(date=int(time.time()))} if authorized else {}


@pytest.mark.parametrize('path', [
    '/api/friends', '/api/friends/action', '/api/mafia', '/api/mafia/action',
    '/api/rocket', '/api/rocket/prepare', '/api/rocket/launch', '/api/rocket/cashout',
])
async def test_every_interactive_api_keeps_telegram_and_current_staff_gate(env, path):
    handler = AsyncMock(return_value=web.json_response({'ok': True}))
    assert (await protection(Request(env, path, False), handler)).status == 401
    assert (await protection(Request(env, path, True), handler)).status == 403
    handler.assert_not_awaited()
    await env.db.set_role(7, 'moderator')
    response = await protection(Request(env, path, True), handler)
    assert response.status == 200
    assert response.headers['Cache-Control'] == 'no-store'
    handler.reset_mock()
    await env.db.set_role(7, 'member')
    assert (await protection(Request(env, path, True), handler)).status == 403
    handler.assert_not_awaited()
    assert (await env.db.get_user(7))['cookies'] == 30


async def test_interactive_errors_reach_client_without_profile_error_replacement(env):
    await env.db.set_role(7, 'moderator')
    for path in ('/api/friends/action', '/api/mafia/action', '/api/rocket/launch'):
        response = await protection(Request(env, path, True), AsyncMock(side_effect=ValueError('Комната уже закрыта')))
        assert response.status == 400
        assert json.loads(response.body)['error'] == 'Комната уже закрыта'
        assert response.headers['Cache-Control'] == 'no-store'


async def test_additive_game_schema_can_initialize_twice_without_touching_existing_money(env):
    before_user = await env.db.get_user(7)
    before_ledger = await env.db.list_transactions(7)
    await env.db.initialize()
    await env.db.initialize()
    assert (await env.db.get_user(7))['cookies'] == before_user['cookies']
    assert await env.db.list_transactions(7) == before_ledger
    assert (await env.db.fetchone('PRAGMA integrity_check'))['integrity_check'] == 'ok'


async def test_games_use_aiohttp_lifecycle_and_one_failure_does_not_stop_other_settlement(env, monkeypatch):
    from community_bot import mafia_api, rocket_api

    rocket = AsyncMock(side_effect=RuntimeError('isolated fixture error'))
    mafia = AsyncMock()
    monkeypatch.setattr(rocket_api, 'tick', rocket)
    monkeypatch.setattr(mafia_api, 'tick', mafia)
    await settle(env.db)
    rocket.assert_awaited_once_with(env.db)
    mafia.assert_awaited_once_with(env.db)
    app = create_app(env.db, env.settings, None)
    assert lifecycle in app.cleanup_ctx
    paths = {resource.canonical for resource in app.router.resources()}
    assert {'/api/friends', '/api/mafia/action', '/api/rocket/cashout', '/interactive.js'} <= paths
    ctx = lifecycle(app)
    await anext(ctx)
    tasks = [task for task in asyncio.all_tasks() if task.get_name() == 'nora-interactive-deadlines']
    assert len(tasks) == 1
    await ctx.aclose()
    assert tasks[0].done()
