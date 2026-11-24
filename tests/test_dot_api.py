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
    async def fake_replay(seed, ticks, flaps):
        return {"cookies": 4, "passed": 5, "ticks": ticks}
    monkeypatch.setattr(dot_api, "replay", fake_replay)
    ticket = await dot_api.issue(db, 101, now=100)
    payload = {"token": ticket["token"], "ticks": 120, "flaps": [0]}
    assert await dot_api.finish(db, 101, payload, now=102)
    assert await dot_api.finish(db, 101, payload, now=103)
    row = await db.fetchone("SELECT * FROM mini_dot_records WHERE user_id=101")
    assert (row["cookies"], row["passed"], row["achieved_at"]) == (4, 5, 102)
    assert (await db.get_user(101))["cookies"] == before
    with pytest.raises(ValueError):
        await dot_api.finish(db, 102, payload, now=104)
