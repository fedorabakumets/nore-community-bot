"""Integration checks against the real poker subprocess and a disposable wallet."""
import secrets
import time

import pytest

from community_bot import poker_api as poker
from community_bot.database import Database


@pytest.fixture
async def wallet(tmp_path, monkeypatch):
    if not poker.ENGINE.exists():
        pytest.skip("Build poker/dist before running wallet integration tests")
    db = Database(tmp_path / "poker.sqlite3")
    await db.initialize()
    async with db.connect() as conn:
        await conn.executescript(poker.SCHEMA)
        await conn.commit()
    for uid in (1, 2, 3):
        await db.ensure_user(uid, telegram_name=f"Player {uid}")
        await db.add_cookies(uid, 100, "fixture")

    async def unrestricted(*args, **kwargs):
        return ""

    monkeypatch.setattr(poker, "stake_restriction", unrestricted)
    engine = poker.PokerEngine()
    try:
        yield db, engine
    finally:
        await engine.close()


async def call(wallet, uid, kind, code=None, body=None):
    db, engine = wallet
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        result, status = await poker.wallet_action(conn, engine, uid, kind, code, body or {}, {"first_name": str(uid)})
        await conn.commit()
    return result, status


async def balance(wallet, uid):
    return (await wallet[0].get_user(uid))["cookies"]


async def command(wallet, uid, view, action):
    return await call(wallet, uid, "command", view["code"], {
        "commandId": secrets.token_hex(16), "expectedVersion": view["version"], "command": action,
    })


async def test_wallet_round_restart_and_cashout(wallet):
    created, status = await call(wallet, 1, "create", body={"buyIn": 20})
    assert status == 200
    code = created["snapshot"]["code"]
    assert await balance(wallet, 1) == 80
    assert "privateRoom" not in created
    repeated, _ = await call(wallet, 1, "create", body={"buyIn": 50})
    assert repeated["snapshot"]["code"] == code
    assert await balance(wallet, 1) == 80
    preview, _ = await call(wallet, 2, "state", code)
    assert preview == {"snapshot": None, "joinable": True, "buyIn": 20}
    joined, status = await call(wallet, 2, "join", code)
    assert status == 200
    assert await balance(wallet, 2) == 80
    await call(wallet, 2, "join", code)
    assert await balance(wallet, 2) == 80

    current, _ = await call(wallet, 1, "state", code)
    started, status = await command(wallet, 1, current["snapshot"], {"type": "start"})
    assert status == 200
    view = started["snapshot"]
    assert view["hand"]["street"] == "preflop"
    assert "deck" not in view["hand"]
    assert all(card is None for p in view["players"] if p["id"] != view["viewerId"] for card in p["hole"])
    with pytest.raises(ValueError, match="конца раздачи"):
        await call(wallet, 1, "leave", code)

    await wallet[1].close()
    restored, status = await call(wallet, 1, "state", code)
    assert status == 200 and restored["snapshot"]["hand"]["id"] == view["hand"]["id"]
    folded, status = await command(wallet, 1, restored["snapshot"], {"type": "poker", "action": {"type": "fold"}})
    assert status == 200 and folded["snapshot"]["hand"]["street"] == "complete"
    denied, status = await command(wallet, 1, folded["snapshot"], {"type": "rebuy"})
    assert status == 400
    stacks = {p["id"]: p["stack"] for p in folded["snapshot"]["players"]}
    assert sum(stacks.values()) == 40
    for uid in (1, 2):
        left, status = await call(wallet, uid, "leave", code)
        assert status == 200 and left["left"]
    assert await balance(wallet, 1) + await balance(wallet, 2) == 200
    assert (await call(wallet, 1, "leave", code))[0]["returned"] == 0
    assert await balance(wallet, 1) + await balance(wallet, 2) == 200


async def test_expiry_refunds_unfinished_round(wallet):
    created, _ = await call(wallet, 1, "create", body={"buyIn": 20})
    code = created["snapshot"]["code"]
    await call(wallet, 2, "join", code)
    current, _ = await call(wallet, 1, "state", code)
    started, status = await command(wallet, 1, current["snapshot"], {"type": "start"})
    assert status == 200 and started["snapshot"]["pot"] == 3
    db = wallet[0]
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        await conn.execute("UPDATE poker_wallet_rooms SET updated=0")
        await poker.expire_rooms(conn, time.time())
        await poker.expire_rooms(conn, time.time())
        await conn.commit()
    assert await balance(wallet, 1) == await balance(wallet, 2) == 100


async def test_unfunded_entry_and_engine_failure(wallet):
    with pytest.raises(ValueError, match="балансе"):
        await call(wallet, 1, "create", body={"buyIn": 101})
    assert await balance(wallet, 1) == 100

    class FailedEngine:
        async def request(self, payload):
            return {"status": 503, "error": "Unavailable"}

    result, status = await call((wallet[0], FailedEngine()), 1, "create", body={"buyIn": 20})
    assert status == 503
    assert await balance(wallet, 1) == 100
    assert (await call(wallet, 1, "me"))[0]["code"] is None
