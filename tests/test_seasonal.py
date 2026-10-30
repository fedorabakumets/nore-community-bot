import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from community_bot.database import Database
from community_bot.seasonal import ITEM, draw, join, manage, prepare_draw, snapshot


@pytest.fixture
async def env(tmp_path):
    db = Database(tmp_path / "season.db")
    await db.initialize()
    for uid in (7, 8, 9):
        await db.ensure_user(uid, f"user_{uid}", f"Друг {uid}")
        await db.execute(
            "UPDATE users SET age=25,profile_name=?,hobbies='Город',profile_bio='Люблю Нору',"
            "avatar_file_id='fake',cookies=100 WHERE user_id=?",
            (f"Друг {uid}", uid),
        )
    settings = SimpleNamespace(is_owner=lambda uid: uid == 7, owner_ids={7}, moderator_ids=set())
    return SimpleNamespace(db=db, settings=settings)


async def test_join_is_concurrent_once_and_does_not_charge_or_expose_roster(env):
    ledger = await env.db.fetchall("SELECT * FROM transactions ORDER BY id")
    await asyncio.gather(*[join(env.db, 8) for _ in range(12)])
    view = await snapshot(env.db, env.settings, 8)
    assert view["joined"] and view["count"] == 1 and not view["can_manage"]
    assert not (await snapshot(env.db, env.settings, 9))["joined"]
    assert (await env.db.get_user(8))["cookies"] == 100
    assert await env.db.fetchall("SELECT * FROM transactions ORDER BY id") == ledger
    assert set(view) == {
        "id",
        "title",
        "season",
        "status",
        "joined",
        "count",
        "image",
        "author",
        "author_url",
        "image_alt",
        "description",
        "links",
        "eligible",
        "can_manage",
        "winner",
        "won",
        "drawn_at",
    }
    entries = await env.db.fetchall("SELECT * FROM seasonal_entries ORDER BY user_id")
    assert entries[0]["raffle_id"] == "season1-crimson-guardian"
    await env.db.initialize()
    assert await env.db.fetchall("SELECT * FROM seasonal_entries ORDER BY user_id") == entries
    assert (await snapshot(env.db, env.settings, 8))["count"] == 1


async def test_full_profile_gate_and_foreign_admin_cannot_draw_or_read_members(env):
    await env.db.execute("UPDATE users SET hobbies='' WHERE user_id=8")
    with pytest.raises(ValueError, match="100%"):
        await join(env.db, 8)
    for fn in (prepare_draw,):
        with pytest.raises(web.HTTPForbidden):
            await fn(env.db, env.settings, 8)
    with pytest.raises(web.HTTPForbidden):
        await draw(env.db, env.settings, 8, "x" * 30)
    request = {"actor": {"id": 8, "first_name": "Друг"}}

    class Request(dict):
        pass

    r = Request(request)
    r.app = {"db": env.db, "settings": env.settings}
    with pytest.raises(web.HTTPForbidden):
        await manage(r)
    with pytest.raises(ValueError, match="нет участников"):
        await prepare_draw(env.db, env.settings, 7)


async def test_draw_freezes_winner_and_cannot_reroll_even_concurrently_or_after_restart(env):
    for uid in (8, 9):
        await join(env.db, uid)
    q1 = await prepare_draw(env.db, env.settings, 7)
    q2 = await prepare_draw(env.db, env.settings, 7)
    result = await asyncio.gather(
        draw(env.db, env.settings, 7, q1["token"]), draw(env.db, env.settings, 7, q2["token"]), return_exceptions=True
    )
    winners = [r for r in result if isinstance(r, int)]
    assert len(winners) == 1 and winners[0] in (8, 9)
    assert sum(isinstance(r, ValueError) for r in result) == 1
    row = await env.db.fetchone("SELECT * FROM seasonal_raffles WHERE id=?", (ITEM,))
    assert row["entry_count"] == 2 and len(row["entries_digest"]) == 64 and row["drawn_by"] == 7
    assert (await snapshot(env.db, env.settings, winners[0]))["won"]
    await env.db.initialize()
    with pytest.raises(ValueError, match="завершён"):
        await join(env.db, 7)
    with pytest.raises(ValueError, match="уже определён"):
        await draw(env.db, env.settings, 7, q1["token"])
    assert (await env.db.fetchone("SELECT COUNT(*) n FROM notify_inbox WHERE user_id=?", (winners[0],)))["n"] == 1
    assert "Розовый Хранитель" in json.dumps(await snapshot(env.db, env.settings, 8), ensure_ascii=False)


async def test_changed_participants_expiry_and_permissions_invalidate_confirmation(env, monkeypatch):
    await join(env.db, 8)
    q = await prepare_draw(env.db, env.settings, 7)
    await join(env.db, 9)
    with pytest.raises(ValueError, match="изменился"):
        await draw(env.db, env.settings, 7, q["token"])
    q = await prepare_draw(env.db, env.settings, 7)
    await env.db.execute("UPDATE seasonal_draw_tokens SET expires_at=0")
    with pytest.raises(ValueError, match="устарело"):
        await draw(env.db, env.settings, 7, q["token"])
    q = await prepare_draw(env.db, env.settings, 7)
    revoked = SimpleNamespace(is_owner=lambda uid: False, owner_ids=set(), moderator_ids=set())
    with pytest.raises(web.HTTPForbidden):
        await draw(env.db, revoked, 7, q["token"])
    assert (await snapshot(env.db, env.settings, 8))["status"] == "open"
