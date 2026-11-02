import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from community_bot import nora_game_api
from community_bot.database import Database


def request(db, uid, body=None):
    class Request(dict):
        app = {'db': db}
        json = AsyncMock(return_value=body)

    return Request(actor={'id': uid})


def content(response):
    return json.loads(response.text)


@pytest.mark.asyncio
async def test_registration_is_private_persistent_and_case_insensitive(tmp_path):
    db = Database(tmp_path / 'game.db')
    await db.initialize()
    assert content(await nora_game_api.status(request(db, 1))) == {'nickname': None}
    first = await nora_game_api.register(request(db, 1, {'nickname': 'Alice'}))
    assert content(first) == {'nickname': 'Alice'}
    duplicate = await nora_game_api.register(request(db, 2, {'nickname': 'aLiCe'}))
    assert duplicate.status == 409
    assert content(await nora_game_api.status(request(db, 2))) == {'nickname': None}
    assert content(await nora_game_api.register(request(db, 1, {'nickname': 'Other'}))) == {'nickname': 'Alice'}
    await db.initialize()
    assert content(await nora_game_api.status(request(db, 1))) == {'nickname': 'Alice'}


@pytest.mark.asyncio
@pytest.mark.parametrize('nickname', ['ab', 'a' * 17, 'Alice1', ' Alice', 'Аlice', '', None])
async def test_invalid_nicknames_are_rejected(tmp_path, nickname):
    db = Database(tmp_path / 'game.db')
    await db.initialize()
    with pytest.raises(ValueError):
        await nora_game_api.register(request(db, 1, {'nickname': nickname}))


@pytest.mark.asyncio
async def test_concurrent_registration_only_one_wins(tmp_path):
    db = Database(tmp_path / 'game.db')
    await db.initialize()
    responses = await asyncio.gather(
        nora_game_api.register(request(db, 1, {'nickname': 'Player'})),
        nora_game_api.register(request(db, 2, {'nickname': 'player'})),
    )
    assert sorted(response.status for response in responses) == [200, 409]
