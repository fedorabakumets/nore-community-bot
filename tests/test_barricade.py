import asyncio
import time
from types import SimpleNamespace

import pytest

from community_bot import barricade_api as api
from community_bot import barricade_rules as rules
from community_bot import durak_api, game_invitations
from community_bot import durak_rooms as rooms
from tests.test_durak_rooms import amounts, balance, command, friends, run
from tests.test_durak_rooms import db as room_db

db = room_db


def pawn(row, col):
    return {"kind": "pawn", "row": row, "col": col}


def wall(row, col, axis):
    return {"kind": "wall", "row": row, "col": col, "axis": axis}


async def play(db, uid, action, **fields):
    return (await rooms.command(db, uid, command(action, **fields), game="barricade"))[0]


async def create(db, uid=1):
    return await play(db, uid, "create", config={"stake": 5})


async def quick(db, uid, stake=5):
    return await play(db, uid, "quick", config={"stake": stake})


def test_jumps_around_walls_and_board_edges():
    game = rules.start()
    game["pawns"] = [[4, 4], [5, 4]]
    assert (6, 4) in rules.moves(game, 0)
    assert not {(5, 4), (5, 3), (5, 5)}.intersection(rules.moves(game, 0))
    game["walls"] = [[5, 4, "h"], [5, 4, "v"]]
    options = rules.moves(game, 0)
    assert (5, 3) in options and (5, 5) not in options and (6, 4) not in options
    game.update(pawns=[[7, 4], [8, 4]], walls=[])
    assert {(8, 3), (8, 5)}.issubset(rules.moves(game, 0))
    game.update(pawns=[[4, 4], [5, 4]], walls=[[4, 3, "h"]])
    assert all(row != 5 for row, _ in rules.moves(game, 0))


def test_wall_quota_overlaps_crossings_and_last_open_path():
    game = rules.start()
    rules.play(game, 0, wall(0, 0, "h"))
    assert game["stock"] == [9, 10] and game["turn"] == 1
    for invalid in [wall(0, 1, "h"), wall(0, 0, "v"), wall(8, 0, "h"), wall(False, 0, "h"),
                    {"kind": "wall", "row": 0, "col": 2, "axis": "v", "winner": 1}]:
        with pytest.raises(ValueError):
            rules.play(game, 1, invalid)
    assert game["walls"] == [[0, 0, "h"]] and game["stock"] == [9, 10]
    # Access to the entire top rank would be cut for the first pawn.
    game["walls"] = [[0, col, "h"] for col in (0, 2, 4, 6)]
    assert (0, 7, "v") not in rules.wall_options(game, 1)
    with pytest.raises(ValueError, match="путь"):
        rules.play(game, 1, wall(0, 7, "v"))
    game["stock"][1] = 0
    assert rules.wall_options(game, 1) == []


async def test_private_room_invite_link_decline_and_atomic_admission(db):
    rid = await create(db)
    assert await balance(db, 1) == 1000
    assert await amounts(db, rid) == []
    assert await durak_api.lobbies(db, 1) == []
    assert (await durak_api.lobbies(db, 1, game="barricade"))[0]["own"]
    assert await durak_api.lobbies(db, 2, game="barricade") == []
    with pytest.raises(ValueError, match="приглашение"):
        await play(db, 2, "join", room=rid)
    with pytest.raises(ValueError, match="друзьям"):
        await play(db, 1, "invite", room=rid, friend=2)
    await friends(db, 1, 2)
    invite = command("invite", room=rid, friend=2)
    assert (await rooms.command(db, 1, invite, game="barricade"))[1]
    assert (await rooms.command(db, 1, invite, game="barricade"))[1] is None
    assert (await api.menu(db, 2))["invites"][0]["id"] == rid
    await play(db, 2, "decline", room=rid)
    assert (await api.menu(db, 2))["invites"] == []
    with pytest.raises(ValueError, match="приглашение"):
        await play(db, 2, "join", room=rid)
    async with db.connect() as conn:
        code = (await rooms._room(conn, rid))["code"]
    await db.add_cookies(1, -998, "fixture")
    with pytest.raises(ValueError, match="ставки"):
        await play(db, 2, "join", room=rid, code=code)
    assert await balance(db, 2) == 1000 and await amounts(db, rid) == []
    assert (await api.snapshot(db, rid, 1))["status"] == "waiting"
    await db.add_cookies(1, 10, "fixture")
    attempts = await asyncio.gather(*(play(db, i, "join", room=rid, code=code) for i in (2, 3)), return_exceptions=True)
    assert attempts.count(rid) == 1
    assert len(await amounts(db, rid)) == 2


async def test_matching_exact_stake_cancel_and_no_other_game_crossover(db):
    private = await create(db, 4)
    first = await quick(db, 1, 7)
    other_stake = await quick(db, 2, 5)
    assert (await api.snapshot(db, first, 1))["status"] == "waiting"
    with pytest.raises(ValueError, match="быстрый поиск"):
        await play(db, 3, "join", room=first)
    with pytest.raises(ValueError, match="Стол недоступен"):
        await run(db, 3, "join", room=first)
    with pytest.raises(ValueError, match="Стол недоступен"):
        await durak_api.snapshot(db, first, 1)
    assert await quick(db, 3, 7) == first
    assert (await api.snapshot(db, first, 3))["board"]["pawns"] == [[0, 4], [8, 4]]
    assert await balance(db, 1) == await balance(db, 3) == 993
    assert await balance(db, 2) == 1000
    for rid, uid in [(other_stake, 2), (private, 4)]:
        rev = (await api.snapshot(db, rid, uid))["rev"]
        await play(db, uid, "cancel", room=rid, rev=rev)
        assert await balance(db, uid) == 1000
        assert await amounts(db, rid) == []


async def test_full_game_reconnect_duplicate_moves_and_single_payout(db):
    rid = await quick(db, 1)
    assert await quick(db, 2) == rid
    start = await api.snapshot(db, rid, 1)
    with pytest.raises(ValueError, match="участвуешь"):
        await api.snapshot(db, rid, 3)
    with pytest.raises(ValueError, match="ход соперника"):
        await play(db, 2, "move", room=rid, rev=start["rev"], move=pawn(7, 4))
    assert start["board"]["moves"]
    assert not (await api.snapshot(db, rid, 2))["board"]["moves"]
    n = command("move", room=rid, rev=start["rev"], move=pawn(1, 4))
    assert await asyncio.gather(*(rooms.command(db, 1, n, game="barricade") for _ in range(2))) == [(rid, None)] * 2
    with pytest.raises(rooms.Conflict, match="изменился"):
        await play(db, 1, "move", room=rid, rev=start["rev"], move=pawn(1, 4))
    feed = await api.snapshot(db, rid, 2)
    assert feed["board"]["pawns"][0] == [1, 4]
    await play(db, 2, "move", room=rid, rev=feed["rev"], move=pawn(8, 3))
    for r in range(2, 8):
        feed = await api.snapshot(db, rid, 1)
        await play(db, 1, "move", room=rid, rev=feed["rev"], move=pawn(r, 4))
        feed = await api.snapshot(db, rid, 2)
        await play(db, 2, "move", room=rid, rev=feed["rev"], move=pawn(9 - r, 3))
    feed = await api.snapshot(db, rid, 1)
    final = command("move", room=rid, rev=feed["rev"], move=pawn(8, 4))
    assert await asyncio.gather(*(rooms.command(db, 1, final, game="barricade") for _ in range(3))) == [(rid, None)] * 3
    end = await api.snapshot(db, rid, 2)
    assert end["status"] == "finished" and end["result"]["reason"] == "goal"
    assert end["members"][0]["payout"] == 10 and end["board"]["pawns"][0] == [8, 4]
    assert (await balance(db, 1), await balance(db, 2)) == (1005, 995)
    assert [row["kind"] for row in await amounts(db, rid)] == ["barricade_bet", "barricade_bet", "barricade_win"]


async def test_turn_timeout_technical_refund_and_restore(db):
    now = time.time()
    rid = await quick(db, 1)
    await quick(db, 2)
    await durak_api.Updates().restore(db, now + 60)
    state = await api.snapshot(db, rid, 1)
    assert state["deadline"] == now + 120
    assert not await rooms.expire(db, rid, now + 61)
    assert await rooms.expire(db, rid, now + 121)
    assert not await rooms.expire(db, rid, now + 122)
    assert (await api.snapshot(db, rid, 2))["result"]["loser"] == 0
    assert (await balance(db, 1), await balance(db, 2)) == (995, 1005)
    broken = await quick(db, 1)
    await quick(db, 2)
    await db.execute("UPDATE durak_rooms SET game='{}' WHERE id=?", (broken,))
    assert await rooms.expire(db, broken, now + 75)
    assert not await rooms.expire(db, broken, now + 76)
    assert (await api.snapshot(db, broken, 2))["result"]["reason"] == "technical"
    assert (await balance(db, 1), await balance(db, 2)) == (995, 1005)
    assert [row["kind"] for row in await amounts(db, broken)][2:] == ["barricade_refund"] * 2


async def test_recipient_bound_entry(db, monkeypatch):
    async def allowed(*_):
        return True

    monkeypatch.setattr(game_invitations, "miniapp_allowed", allowed)
    await friends(db, 1, 2)
    rid = await create(db)
    await play(db, 1, "invite", room=rid, friend=2)

    class Request(dict):
        app = {"db": db, "settings": SimpleNamespace()}

        async def json(self):
            return {"game": "barricade", "room_id": rid, "recipient": 2}

    assert (await game_invitations.open_invitation(Request(actor={"id": 3}))).status == 403
    assert rid in (await game_invitations.open_invitation(Request(actor={"id": 2}))).text
    assert await balance(db, 2) == 1000
