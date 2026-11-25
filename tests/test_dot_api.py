import shutil

import pytest

from community_bot import dot_api
from community_bot.database import Database


@pytest.mark.asyncio
async def test_dot_replay_and_invalid_end():
    if not (shutil.which("deno") or shutil.which("node")):
        pytest.skip("JavaScript runtime not installed")
    assert await dot_api.replay(42, 166, [0]) == {"cookies":0,"passed":0,"ticks":166}
    with pytest.raises(ValueError):
        await dot_api.replay(42, 1, [0])


@pytest.mark.asyncio
async def test_dot_record_is_single_use_and_does_not_touch_wallet(tmp_path, monkeypatch):
    db = Database(tmp_path / "dot.sqlite")
    await db.initialize()
    await db.ensure_user(101, "dot_test", "DOT Test")
    before = (await db.get_user(101))["cookies"]
    await db.ensure_user(102, "leader", "Leader")
    await db.execute("INSERT INTO mini_dot_records VALUES(?,?,?,?)", (102, 10, 11, 99))
    async def fake_replay(seed, ticks, flaps):
        return {"cookies": 4, "passed": 5, "ticks": ticks}
    monkeypatch.setattr(dot_api, "replay", fake_replay)
    ticket = await dot_api.issue(db, 101, now=100)
    payload = {"token": ticket["token"], "ticks": 120, "flaps": [0]}
    assert (await dot_api.finish(db, 101, payload, now=102))["new_record"]
    assert (await dot_api.finish(db, 101, payload, now=103))["reward"] == 0
    row = await db.fetchone("SELECT * FROM mini_dot_records WHERE user_id=101")
    assert (row["cookies"], row["passed"], row["achieved_at"]) == (4, 5, 102)
    assert (await db.get_user(101))["cookies"] == before
    with pytest.raises(ValueError):
        await dot_api.finish(db, 102, payload, now=104)


@pytest.mark.asyncio
async def test_dot_world_record_rewards_rolling_limit_and_preserves_existing(tmp_path, monkeypatch):
    db = Database(tmp_path / "dot.sqlite")
    await db.initialize()
    for uid in (101, 102):
        await db.ensure_user(uid, f"user{uid}", f"User {uid}")
    await db.execute("INSERT INTO mini_dot_records VALUES(?,?,?,?)", (102, 10, 12, 99))
    before = (await db.get_user(101))["cookies"]
    score = 10

    async def fake_replay(seed, ticks, flaps):
        return {"cookies": score, "passed": score + 1, "ticks": ticks}

    monkeypatch.setattr(dot_api, "replay", fake_replay)

    async def play(value, now):
        nonlocal score
        score = value
        ticket = await dot_api.issue(db, 101, now=now-2)
        payload = {"token": ticket["token"], "ticks": 120, "flaps": [0]}
        result = await dot_api.finish(db, 101, payload, now=now)
        assert await dot_api.finish(db, 101, payload, now=now+0.1) == result
        return result

    assert (await play(10, 100))["reward"] == 0
    assert (await play(11, 110))["reward"] == 11
    assert (await play(12, 120))["reward"] == 12
    capped = await play(13, 130)
    assert capped["world_record"] and capped["limit_reached"] and capped["reward"] == 0
    assert (await play(13, 140))["reward"] == 0
    assert (await play(14, 86_509))["reward"] == 0
    assert (await play(15, 86_510))["reward"] == 15
    assert (await db.get_user(101))["cookies"] == before + 38
    old = await db.fetchone("SELECT cookies,passed FROM mini_dot_records WHERE user_id=102")
    assert (old["cookies"], old["passed"]) == (10, 12)
    latest = await db.fetchone("SELECT cookies FROM mini_dot_records WHERE user_id=101")
    assert latest["cookies"] == 15
    tx = await db.fetchone("SELECT COUNT(*) n FROM transactions WHERE user_id=101 AND kind='dot_record'")
    assert tx["n"] == 3


@pytest.mark.asyncio
async def test_dot_currency_shop_is_separate_persistent_and_idempotent(tmp_path, monkeypatch):
    db = Database(tmp_path / "dot.sqlite")
    await db.initialize()
    await db.ensure_user(101, "dot_test", "DOT Test")
    await db.ensure_user(102, "leader", "Leader")
    await db.execute("INSERT INTO mini_dot_records VALUES(?,?,?,?)", (102, 9999, 9999, 99))
    before = (await db.get_user(101))["cookies"]

    async def fake_replay(seed, ticks, flaps):
        return {"cookies": 500, "passed": 501, "ticks": ticks}

    monkeypatch.setattr(dot_api, "replay", fake_replay)
    assert (await dot_api.shop(db, 101))["balance"] == 0
    for now in (100, 110):
        ticket = await dot_api.issue(db, 101, now=now-2)
        body = {"token": ticket["token"], "ticks": 120, "flaps": [0]}
        result = await dot_api.finish(db, 101, body, now=now)
        assert result["dot_earned"] == 500 and result["reward"] == 0
        assert await dot_api.finish(db, 101, body, now=now+1) == result
    assert (await dot_api.shop(db, 101))["balance"] == 1000
    with pytest.raises(ValueError):
        await dot_api.shop(db, 101, "equip", "mint")
    bought = await dot_api.shop(db, 101, "buy", "mint")
    assert bought["balance"] == 0 and bought["equipped"] == "mint"
    assert bought["owned"] == ["red", "mint"]
    assert await dot_api.shop(db, 101, "buy", "mint") == bought
    with pytest.raises(ValueError):
        await dot_api.shop(db, 101, "buy", "ice")
    assert (await dot_api.shop(db, 101, "equip", "red"))["equipped"] == "red"
    assert (await dot_api.shop(db, 101, "equip", "mint"))["equipped"] == "mint"
    assert (await dot_api.shop(db, 102))["owned"] == ["red"]
    assert (await db.get_user(101))["cookies"] == before


@pytest.mark.asyncio
async def test_owner_dot_grant_only_once(tmp_path):
    db = Database(tmp_path / "dot.sqlite")
    await db.initialize()
    for uid in (101, 102):
        await db.ensure_user(uid, f"user{uid}", f"User {uid}")
    before = (await db.get_user(101))["cookies"]
    assert not await dot_api.grant_owner_dot_cookies(db, 102, 101)
    assert await dot_api.grant_owner_dot_cookies(db, 101, 101)
    assert not await dot_api.grant_owner_dot_cookies(db, 101, 101)
    assert (await dot_api.shop(db, 101))["balance"] == 4000
    assert (await dot_api.shop(db, 102))["balance"] == 0
    assert (await db.get_user(101))["cookies"] == before
