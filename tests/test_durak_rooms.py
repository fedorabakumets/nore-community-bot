"""Escrow, invitation, persistence and HTTP identity regressions on disposable SQLite."""
import asyncio
import json
import random
import secrets
import time
from types import SimpleNamespace

import pytest

from community_bot import community_api, mafia_api, sea_api
from community_bot import durak_api as api
from community_bot import durak_items as items
from community_bot import durak_rooms as rooms
from community_bot import durak_rules as rules
from community_bot.database import Database
from community_bot.game_exit import exit_game, leave
from community_bot.miniapp import protection
from community_bot.release_backup import verify_durak_backup
from tests.test_miniapp import signed


@pytest.fixture
async def db(tmp_path):
    db = Database(tmp_path / "durak.sqlite3")
    await db.initialize()
    for uid in range(1, 9):
        await db.ensure_user(uid, telegram_name=f"Игрок {uid}")
        await db.execute("UPDATE users SET profile_name=?,birth_date='2000-01-01',hobbies='Карты',"
                         "profile_bio='Играю',avatar_file_id='test-avatar',role='moderator' WHERE user_id=?",
                         (f"Игрок {uid}", uid))
        await db.add_cookies(uid, 1000, "fixture")
    return db


def command(action, **fields):
    return {"action": action, "nonce": secrets.token_hex(12), **fields}


async def run(db, uid, action, **fields):
    return (await rooms.command(db, uid, command(action, **fields)))[0]


async def balance(db, uid):
    return (await db.get_user(uid))["cookies"]


async def amounts(db, rid):
    return await db.fetchall("SELECT user_id,amount,kind FROM transactions WHERE details=? ORDER BY id", ("room:"+rid,))


async def friends(db, a, b):
    await db.execute("INSERT INTO mini_friendships VALUES(?,?,?,'accepted','test','now','now',0,0)",
                     (min(a, b), max(a, b), a))


async def test_night_pack_gift_and_duplicate_charge(db):
    await friends(db, 1, 2)
    with pytest.raises(ValueError, match="друга"):
        await items.change(db, 1, {"action": "buy", "recipient": 3, "price": 149})
    gift = {"action": "buy", "recipient": 2, "price": 149}
    with pytest.raises(ValueError, match="Цена комплекта изменилась"):
        await items.change(db, 1, {**gift, "price": 90})
    assert await balance(db, 1) == 1000
    attempts = await asyncio.gather(items.change(db, 1, gift), items.change(db, 1, gift),
                                    return_exceptions=True)
    assert sum(isinstance(result, ValueError) for result in attempts) == 1
    assert await balance(db, 1) == 851 and await balance(db, 2) == 1000
    assert len(await db.fetchall("SELECT id FROM notify_inbox WHERE user_id=2")) == 1
    state = (await api.menu(db, 2))["items"]
    assert state["owned"] and not any(state["equipped"].values())
    await items.change(db, 2, {"action": "equip", "part": "back", "enabled": True})
    assert (await api.menu(db, 2))["items"]["equipped"] == {"back": True, "felt": False, "witch": False}


async def test_host_table_cosmetics_shared_and_fixed_at_deal(db):
    await items.change(db, 1, {"action": "buy", "price": 149})
    await items.change(db, 1, {"action": "equip", "part": "felt", "enabled": False})
    rid = await run(db, 1, "create", config={})
    await run(db, 2, "join", room=rid)
    await items.change(db, 1, {"action": "equip", "part": "back", "enabled": False})
    host = await api.snapshot(db, rid, 1)
    guest = await api.snapshot(db, rid, 2)
    assert host["cosmetics"] == {"back": True, "felt": False, "witch": True}
    assert guest["cosmetics"] == {"back": True, "felt": False, "witch": False}


async def test_public_private_discovery_invite_and_link(db):
    rid = await run(db, 1, "create", config={"private": True, "players": 3})
    second = await run(db, 5, "create", config={})
    listing = await api.menu(db, 2)
    assert [r["id"] for r in listing["open"]] == [second] and rid not in json.dumps(listing)
    assert (await api.menu(db, 1))["active"] == rid
    with pytest.raises(ValueError):
        await run(db, 2, "join", room=rid)
    with pytest.raises(ValueError):
        await api.snapshot(db, rid, 2)
    with pytest.raises(ValueError):
        await run(db, 1, "invite", room=rid, friend=2)
    await friends(db, 1, 2)
    invite = command("invite", room=rid, friend=2)
    assert (await rooms.command(db, 1, invite))[1]
    assert (await rooms.command(db, 1, invite))[1] is None
    assert len(await db.fetchall("SELECT id FROM notify_inbox WHERE user_id=2")) == 1
    assert (await api.menu(db, 2))["invites"][0]["id"] == rid
    await run(db, 2, "join", room=rid)
    lobby = await api.snapshot(db, rid, 1)
    assert lobby["status"] == "waiting" and len(lobby["members"]) == 2 and await balance(db, 2) == 900
    with pytest.raises(ValueError):
        await run(db, 2, "create", config={})
    await run(db, 3, "join", room=rid, code=lobby["code"])
    views = [await api.snapshot(db, rid, uid) for uid in (1, 2, 3)]
    assert all(v["status"] == "playing" and v["code"] is None for v in views)
    assert len({c for v in views for c in v["game"]["hand"]}) == 18
    assert [m["reserved"] for m in views[0]["members"]] == [100, 100, 100]
    assert not (await api.menu(db, 2))["invites"]


async def test_community_lobbies_combine_games_and_respect_room_access(db):
    settings = SimpleNamespace(is_owner=lambda uid: uid == 1, owner_ids={1}, moderator_ids=set())

    class Request(dict):
        app = {"db": db, "settings": settings}

    async def listing(uid):
        response = await community_api.lobbies(Request(actor={"id": uid}))
        return {r["id"]: r for r in json.loads(response.body)["rooms"]}

    async def mafia(uid, action, **fields):
        result = await mafia_api.apply_action(
            db, settings, uid, {"action": action, "request_id": secrets.token_hex(16), **fields}
        )
        return result[0]

    cards = await run(db, 1, "create", config={"private": True, "players": 3})
    await friends(db, 1, 2)
    await run(db, 1, "invite", room=cards, friend=2)
    sea, _, _ = await sea_api.apply_action(
        db, settings, 3, {"action": "create", "vs_bot": False, "password": "test", "request_id": secrets.token_hex(16)}
    )
    public = await mafia(4, "create", public=True)
    private = await mafia(5, "create")

    rooms = await listing(2)
    assert {(r["game"], r["locked"]) for r in rooms.values()} == {
        ("durak", True), ("sea", True), ("mafia", False),
    }
    assert rooms[cards]["action"] == "preview" and rooms[cards]["capacity"] == 3
    assert rooms[sea]["action"] == "join" and rooms[sea]["players"] == 1
    assert rooms[public]["action"] == "join" and rooms[public]["capacity"] == 12
    assert private not in rooms and cards not in await listing(6)
    assert (await listing(5))[private]["action"] == "resume"
    with pytest.raises(mafia_api.Conflict):
        await mafia(2, "join", room_id=private)

    await mafia(2, "join", room_id=public)
    assert (await listing(2))[public]["action"] == "resume"
    assert (await listing(6))[public]["players"] == 2
    await db.execute("INSERT INTO mini_friend_blocks VALUES(?,?,?,?)", (2, 6, "test", "now"))
    assert public not in await listing(6)
    with pytest.raises(mafia_api.Conflict):
        await mafia(6, "join", room_id=public)


async def test_last_seat_race_reserve_refund_leave_rejoin_and_replay(db):
    create = command("create", config={"players": 3, "stake": 300})
    created = await asyncio.gather(*(rooms.command(db, 1, create) for _ in range(4)))
    rid = created[0][0]
    assert all(x[0] == rid for x in created) and await balance(db, 1) == 700
    await run(db, 2, "join", room=rid)
    v = await api.snapshot(db, rid, 2)
    leave = command("leave", room=rid, rev=v["rev"])
    await asyncio.gather(rooms.command(db, 2, leave), rooms.command(db, 2, leave))
    assert await balance(db, 2) == 1000
    await run(db, 2, "join", room=rid)
    joined = await asyncio.gather(run(db, 3, "join", room=rid), run(db, 4, "join", room=rid), return_exceptions=True)
    assert sum(isinstance(r, str) for r in joined) == 1
    assert sum(await amounts_as_list(db, rid)) == -900
    assert sorted([await balance(db, 3), await balance(db, 4)]) == [700, 1000]
    with pytest.raises(rooms.Conflict):
        await rooms.command(db, 1, create | {"config": {"stake": 400}})


async def amounts_as_list(db, rid):
    return [r["amount"] for r in await amounts(db, rid)]


async def test_minimum_stake_reserve_refund_and_win(db):
    waiting = await run(db, 1, "create", config={"players": 3, "stake": 5})
    await run(db, 2, "join", room=waiting)
    assert await balance(db, 1) == await balance(db, 2) == 995
    v = await api.snapshot(db, waiting, 1)
    await run(db, 1, "cancel", room=waiting, rev=v["rev"])
    assert await amounts_as_list(db, waiting) == [-5, -5, 5, 5]
    assert await balance(db, 1) == await balance(db, 2) == 1000

    playing = await run(db, 1, "create", config={"stake": 5})
    await run(db, 2, "join", room=playing)
    v = await api.snapshot(db, playing, 2)
    await run(db, 2, "leave", room=playing, rev=v["rev"])
    final = await api.snapshot(db, playing, 1)
    assert final["status"] == "finished"
    assert await amounts_as_list(db, playing) == [-5, -5, 10]
    assert await balance(db, 1) == 1005
    assert await balance(db, 2) == 995


async def test_poor_player_disabled_games_and_cancel_before_start(db):
    await db.execute("UPDATE users SET cookies=99 WHERE user_id=3")
    with pytest.raises(ValueError, match="Для ставки"):
        await run(db, 3, "create", config={})
    rid = await run(db, 1, "create", config={"players": 3})
    with pytest.raises(ValueError, match="Для ставки"):
        await run(db, 3, "join", room=rid)
    await db.execute("UPDATE feature_flags SET enabled=0 WHERE key='games'")
    with pytest.raises(ValueError, match="выключены"):
        await run(db, 2, "join", room=rid)
    await db.execute("UPDATE feature_flags SET enabled=1 WHERE key='games'")
    await run(db, 2, "join", room=rid)
    v = await api.snapshot(db, rid, 1)
    with pytest.raises(ValueError):
        await run(db, 2, "cancel", room=rid, rev=v["rev"])
    cancel = command("cancel", room=rid, rev=v["rev"])
    await asyncio.gather(*[rooms.command(db, 1, cancel) for _ in range(3)])
    assert await amounts_as_list(db, rid) == [-100, -100, 100, 100]
    assert (await api.snapshot(db, rid, 1))["result"]["reason"] == "cancelled"
    assert await balance(db, 1) == await balance(db, 2) == 1000


async def test_simultaneous_moves_restart_hidden_information_and_forfeit(db, monkeypatch):
    # Both racing attacks can be defended, so restart won't collect a forced take.
    deal = rules.deal
    monkeypatch.setattr(rules, "deal", lambda config: deal(config, rng=random.Random(2)))
    rid = await run(db, 1, "create", config={"deck": 24, "speed": "fast", "stake": 125})
    await run(db, 2, "join", room=rid)
    initial = await api.snapshot(db, rid, 1)
    uid = initial["game"]["turn"] + 1
    other = 3 - uid
    view = await api.snapshot(db, rid, uid)
    moves = view["game"]["moves"]
    assert view["deadline"] - view["now"] == pytest.approx(20, abs=2)
    with pytest.raises(ValueError):
        await run(db, other, "move", room=rid, rev=view["rev"], move=moves[0])
    with pytest.raises(ValueError):
        await run(db, other, "move", room=rid, rev=view["rev"], move=moves[0], winner=other)
    req = [command("move", room=rid, rev=view["rev"], move=m) for m in moves[:2]]
    result = await asyncio.gather(*(rooms.command(db, uid, r) for r in req), return_exceptions=True)
    assert sum(isinstance(x, rooms.Conflict) for x in result) == 1
    accepted = req[next(i for i, x in enumerate(result) if not isinstance(x, Exception))]
    persisted = Database(db.path)
    await api.Updates().restore(persisted, time.time())
    await rooms.command(persisted, uid, accepted)
    fresh = await api.snapshot(persisted, rid, other, after=view["rev"])
    public = fresh["game"]
    assert len(public["table"]) == 1 and public["stock"] == 12
    assert public["hand"] == (await api.snapshot(db, rid, other))["game"]["hand"]
    assert all("hands" not in str(f) and "deck" not in str(f) for f in fresh["frames"])
    await run(persisted, other, "leave", room=rid, rev=fresh["rev"])
    assert await amounts_as_list(db, rid) == [-125, -125, 250]
    assert await balance(db, uid) == 1125 and await balance(db, other) == 875
    assert (await api.snapshot(db, rid, other))["game"] is None


@pytest.mark.parametrize("ending,stake,n,expected", [
    ("draw", 101, 2, [101, 101]), ("classic", 101, 2, [202, 0]), ("classic", 101, 3, [151, 0, 152]),
])
async def test_atomic_natural_end_draw_and_whole_cookie_split(db, ending, stake, n, expected):
    rid = await run(db, 1, "create", config={"players": n, "stake": stake, "ending": ending})
    for uid in range(2, n + 1):
        await run(db, uid, "join", room=rid)
    raw = await db.fetchone("SELECT game FROM durak_rooms WHERE id=?", (rid,))
    g = json.loads(raw["game"])
    g.update(deck=[], hands=[[16], [20]]+([[]] if n == 3 else []), trump=3, out=[2] if n == 3 else [])
    rules._open_round(g, 0)
    await db.execute("UPDATE durak_rooms SET game=? WHERE id=?", (rooms.dump(g), rid))
    first = await api.snapshot(db, rid, 1)
    attack = command("move", room=rid, rev=first["rev"], move={"kind": "attack", "card": 16})
    await rooms.command(db, 1, attack)
    if ending == "draw":
        v = await api.snapshot(db, rid, 2)
        defend = command("move", room=rid, rev=v["rev"], move={"kind": "defend", "card": 20, "slot": 0})
        await asyncio.gather(rooms.command(db, 2, defend), rooms.command(db, 2, defend))
    await rooms.command(db, 1, attack)
    final = await api.snapshot(db, rid, 1)
    assert [m["payout"] for m in final["members"]] == expected
    ledger = await amounts(db, rid)
    assert sum(r["amount"] for r in ledger) == 0 and final["status"] == "finished"
    assert all(r["kind"] == "durak_refund" for r in ledger if ending == "draw" and r["amount"] > 0)


async def test_deadlines_recovery_technical_refund_and_retention(db):
    now = time.time()
    waiting = await run(db, 1, "create", config={"players": 4})
    active = await run(db, 2, "create", config={"speed": "normal"})
    await run(db, 3, "join", room=active)
    runtime = api.Updates()
    await runtime.restore(db, now + 100)
    v = await api.snapshot(db, active, 2)
    assert v["deadline"] >= now + 160
    await runtime.tick(db, v["deadline"] + 1)
    assert (await api.snapshot(db, active, 2))["result"]["reason"] == "timeout"
    await runtime.tick(db, now + rooms.LOBBY_TTL + 5)
    assert (await api.snapshot(db, waiting, 1))["result"]["reason"] == "expired"
    another = await run(db, 4, "create", config={})
    await run(db, 5, "join", room=another)
    await asyncio.gather(rooms.expire(db, another, now+rooms.GAME_TTL+5),
                         rooms.expire(db, another, now+rooms.GAME_TTL+5))
    assert (await api.snapshot(db, another, 4))["result"]["reason"] == "technical"
    assert await balance(db, 4) == await balance(db, 5) == 1000
    before = await amounts(db, another)
    await runtime.tick(db, now + rooms.HISTORY_TTL + rooms.GAME_TTL + 100)
    assert not await db.fetchone("SELECT 1 FROM durak_rooms WHERE id=?", (another,))
    assert await amounts(db, another) == before


async def test_transaction_failure_rolls_back_room_and_escrow(db):
    await db.execute("""CREATE TRIGGER test_ledger_error BEFORE INSERT ON transactions
                      WHEN NEW.kind='durak_bet' BEGIN SELECT RAISE(ABORT,'test failure'); END""")
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        await run(db, 1, "create", config={})
    assert await balance(db, 1) == 1000
    assert not await db.fetchone("SELECT 1 FROM durak_rooms") and not await db.fetchone("SELECT 1 FROM durak_commands")


async def test_signed_http_uses_only_actor_and_rejects_unsigned(db):
    # Call the same aiohttp authentication middleware and handlers as production, without outbound sockets.
    class Request(dict):
        path = "/api/durak/action"
        content_length = None
        app = {"db": db, "bot": None, "durak_updates": api.Updates(),
               "settings": SimpleNamespace(bot_token="test-only", is_owner=lambda uid: True, moderator_ids=frozenset())}

        def __init__(self, signature, payload):
            self.headers = {"Authorization": "tma " + signature}
            self.payload = payload

        async def json(self):
            return self.payload

    payload = command("create", config={})
    assert (await protection(Request("", payload), api.action)).status == 401
    assert (await protection(Request(signed(1, int(time.time())), payload | {"uid": 2}), api.action)).status == 400
    assert (await protection(Request(signed(1, int(time.time())), payload), api.action)).status == 200
    assert await balance(db, 1) == 900 and await balance(db, 2) == 1000

    class ExitRequest(Request):
        path = "/api/games/exit/durak"
        match_info = {"game": "durak"}

    assert (await protection(ExitRequest("", {}), leave)).status == 401
    assert (await protection(ExitRequest(signed(2, int(time.time())), {"uid": 1}), leave)).status == 200
    assert await balance(db, 1) == 900
    assert (await protection(ExitRequest(signed(1, int(time.time())), {}), leave)).status == 200
    assert await balance(db, 1) == 1000


@pytest.mark.parametrize("game", ["durak", "barricade"])
async def test_confirmed_exit_resolves_waiting_or_matched_quick_game(db, game):
    async def queue(uid):
        rid, _ = await rooms.command(db, uid, command("quick", config={"stake": 5}), game=game)
        return rid

    waiting = await queue(1)
    assert await exit_game(db, 1, game) == waiting
    assert await exit_game(db, 1, game) is None
    assert await amounts_as_list(db, waiting) == ([] if game == "barricade" else [-5, 5])

    playing = await queue(1)
    assert await queue(2) == playing
    assert await exit_game(db, 1, game) == playing
    assert (await db.fetchone("SELECT status FROM durak_rooms WHERE id=?", (playing,)))["status"] == "finished"
    assert await balance(db, 1) == 995
    assert await balance(db, 2) == 1005


@pytest.mark.parametrize("n", [2, 3, 6])
async def test_reactions_wake_members_without_revising_the_room(db, n, monkeypatch):
    rid = await run(db, 1, "create", config={"players": n, "deck": 52})
    for uid in range(2, n + 1):
        await run(db, uid, "join", room=rid)
    before = await api.snapshot(db, rid, 1)
    ledger = await amounts(db, rid)
    now = [time.time()]
    monkeypatch.setattr(api, "time", SimpleNamespace(time=lambda: now[0]))
    app = {"db": db, "durak_updates": api.Updates()}
    updates = app["durak_updates"]
    body = command("reaction", room=rid, emoji_id=9)
    subscribed = asyncio.Event()
    expected_watchers = n

    class TrackingEvent(asyncio.Event):
        async def wait(self):
            if len(updates.watchers) == expected_watchers:
                subscribed.set()
            return await super().wait()

    event = updates.events[rid] = TrackingEvent()

    class Request(dict):
        content_length = None
        match_info = {"rid": rid}

        def __init__(self, uid, payload=body, **query):
            super().__init__(actor={"id": uid})
            self.app, self.payload, self.query = app, payload, query

        async def json(self):
            return self.payload

    watchers = [asyncio.create_task(api.table(Request(uid, after=str(before["rev"]), reactions="")))
                for uid in range(1, n + 1)]
    try:
        await asyncio.wait_for(subscribed.wait(), timeout=4)
        assert (await api.action(Request(8))).status == 403
        with pytest.raises(ValueError):
            await api.action(Request(1, body | {"sender_id": 8}))
        with pytest.raises(ValueError):
            await api.action(Request(1, body | {"emoji_id": True}))
        with pytest.raises(ValueError):
            await api.action(Request(1, body | {"emoji_id": 26}))
        first = json.loads((await api.action(Request(1))).body)["reactions"][0]
        assert event.is_set()
        views = await asyncio.wait_for(asyncio.gather(*watchers), timeout=4)
        assert all(json.loads(r.body)["reactions"] == [first] for r in views)
    finally:
        for task in watchers:
            task.cancel()
        await asyncio.gather(*watchers, return_exceptions=True)
    assert first["sender_id"] == 1
    # An open pre-release Mini App has no reaction cursor. It must still long-poll.
    subscribed.clear()
    expected_watchers = 1
    legacy_event = updates.events[rid] = TrackingEvent()
    legacy = asyncio.create_task(api.table(Request(1, after=str(before["rev"]))))
    try:
        await asyncio.wait_for(subscribed.wait(), timeout=4)
        assert not legacy.done()
        legacy_event.set()
        await asyncio.wait_for(legacy, timeout=4)
    finally:
        legacy.cancel()
        await asyncio.gather(legacy, return_exceptions=True)
    assert json.loads((await api.action(Request(1))).body)["reactions"] == [first]
    assert (await api.action(Request(1, body | {"emoji_id": 1}))).status == 409
    distinct = command("reaction", room=rid, emoji_id=2)
    assert (await api.action(Request(1, distinct))).status == 429
    await api.action(Request(2, distinct))
    reconnect = json.loads((await api.table(Request(n))).body)
    assert [e["sender_id"] for e in reconnect["reactions"]] == [1, 2]
    now[0] += 3
    assert not json.loads((await api.table(Request(n))).body)["reactions"]
    assert json.loads((await api.action(Request(1))).body)["reactions"] == [first]
    assert (await api.action(Request(1, distinct))).status == 200
    after = await api.snapshot(db, rid, 1)
    assert (after["deadline"], after["rev"], after["game"]) == (before["deadline"], before["rev"], before["game"])
    assert await amounts(db, rid) == ledger


async def test_undo_uses_latest_revision_and_original_clock(db, monkeypatch):
    from random import Random

    deal = rules.deal
    monkeypatch.setattr(rules, "deal", lambda config: deal(config, rng=Random(0)))
    rid = await run(db, 1, "create", config={"players": 3, "variant": "transfer"})
    for uid in (2, 3):
        await run(db, uid, "join", room=rid)
    before = await api.snapshot(db, rid, 1)
    attack, transfer, undo = {"kind": "attack", "card": 16}, {"kind": "transfer", "card": 17}, {"kind": "undo"}
    await run(db, 1, "move", room=rid, rev=before["rev"], move=attack)
    first = await api.snapshot(db, rid, 1)
    assert undo in first["game"]["moves"]
    assert undo not in (await api.snapshot(db, rid, 2))["game"]["moves"]
    with pytest.raises(rooms.Conflict):
        await run(db, 2, "move", room=rid, rev=first["rev"], move=undo)
    await run(db, 2, "move", room=rid, rev=first["rev"], move=transfer)
    second = await api.snapshot(db, rid, 2)
    assert second["game"]["defender"] == 2
    race = command("move", room=rid, rev=first["rev"], move=undo)
    with pytest.raises(rooms.Conflict):
        await rooms.command(db, 1, race)
    rollback = command("move", room=rid, rev=second["rev"], move=undo)
    await rooms.command(db, 2, rollback)
    await rooms.command(db, 2, rollback)
    restored = await api.snapshot(db, rid, 2)
    assert restored["rev"] == second["rev"] + 1
    assert restored["game"]["table"] == [[16, None]]
    assert restored["game"]["defender"] == 1 and 17 in restored["game"]["hand"]
    assert restored["deadline"] == first["deadline"]
    assert undo not in restored["game"]["moves"]
    assert await amounts_as_list(db, rid) == [-100, -100, -100]


async def test_backup_before_additive_schema_and_restore(db):
    async with db.connect() as conn:
        for name in ("durak_commands", "durak_invites", "durak_members", "durak_rooms"):
            await conn.execute(f"DROP TABLE {name}")
        await conn.commit()
    assert await verify_durak_backup(db)
    await db.initialize()
    assert not await verify_durak_backup(db)
    assert await balance(db, 1) == 1000
    assert (db.path.parent / ".nora-backups/before-durak-v1.verified.json").is_file()


async def test_damaged_game_refunds_only_its_members_and_next_table_continues(db):
    rid = await run(db, 1, "create", config={})
    good = await run(db, 3, "create", config={})
    await run(db, 2, "join", room=rid)
    await run(db, 4, "join", room=good)
    await db.execute("UPDATE durak_rooms SET game='{}',deadline=0 WHERE id=?", (rid,))
    await api.Updates().tick(db)
    assert await amounts_as_list(db, rid) == [-100, -100, 100, 100]
    assert (await api.snapshot(db, rid, 1))["result"]["reason"] == "technical"
    assert (await api.snapshot(db, good, 3))["status"] == "playing"
    with pytest.raises(ValueError):
        await api.snapshot(db, good, 1)


async def test_payout_failure_is_retriable_without_partial_credits(db):
    import sqlite3

    rid = await run(db, 1, "create", config={"players": 3})
    await run(db, 2, "join", room=rid)
    v = await api.snapshot(db, rid, 1)
    cancel = command("cancel", room=rid, rev=v["rev"])
    await db.execute("""CREATE TRIGGER stop_second_refund BEFORE INSERT ON transactions
                      WHEN NEW.kind='durak_refund' AND NEW.user_id=2
                      BEGIN SELECT RAISE(ABORT,'interrupted settlement'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        await rooms.command(db, 1, cancel)
    assert await amounts_as_list(db, rid) == [-100, -100]
    assert (await api.snapshot(db, rid, 1))["rev"] == v["rev"]
    await db.execute("DROP TRIGGER stop_second_refund")
    await asyncio.gather(rooms.command(db, 1, cancel), rooms.command(db, 1, cancel))
    assert await amounts_as_list(db, rid) == [-100, -100, 100, 100]


@pytest.mark.parametrize("n,deck", [(2, 24), (3, 36), (4, 24), (5, 36), (6, 52)])
async def test_real_room_to_natural_result_with_independent_clients(db, monkeypatch, n, deck):
    import random

    rng = random.Random(n * deck)
    deal = rules.deal
    monkeypatch.setattr(rules, "deal", lambda cfg: deal(cfg, rng=rng))
    settings = dict(players=n, deck=deck, variant="transfer", scope="all", stake=123, ending="draw")
    rid = await run(db, 1, "create", config=settings)
    for uid in range(2, n + 1):
        assert (await api.snapshot(db, rid, 1))["status"] == "waiting"
        await run(db, uid, "join", room=rid)
    view = await api.snapshot(db, rid, 1)
    for _ in range(1500):
        if view["status"] == "finished":
            break
        actor = view["members"][view["game"]["turn"]]["id"]
        own = await api.snapshot(db, rid, actor)
        moves = own["game"]["moves"]
        defend = [m for m in moves if m["kind"] == "defend"]
        transfer = [m for m in moves if m["kind"] == "transfer"]
        attack = [m for m in moves if m["kind"] == "attack"]
        choices = defend or transfer or attack or moves
        await run(db, actor, "move", room=rid, rev=view["rev"], move=rng.choice(choices))
        view = await api.snapshot(db, rid, actor)
    assert view["status"] == "finished"
    assert sum(m["payout"] for m in view["members"]) == n * 123
    assert sum(await amounts_as_list(db, rid)) == 0



async def test_rollback_drains_waiting_and_playing_tables_and_is_idempotent(db):
    waiting = await run(db, 1, "create", config={"players": 3})
    playing = await run(db, 2, "create", config={"stake": 300})
    await run(db, 3, "join", room=playing)
    assert await rooms.pause_and_refund(db) == 2
    assert await rooms.pause_and_refund(db) == 0
    assert (await api.snapshot(db, waiting, 1))["result"]["reason"] == "maintenance"
    assert await amounts_as_list(db, playing) == [-300, -300, 300, 300]
    with pytest.raises(ValueError, match="обслуживание"):
        await run(db, 4, "create", config={})
    assert (await api.menu(db, 1))["restriction"]
    from community_bot.durak_rollback import run as rollback

    await rollback(db.path, "resume")
    assert await run(db, 4, "create", config={})



async def test_ban_reset_closes_even_previously_forfeited_reserve(db):
    rid = await run(db, 1, "create", config={"players": 3})
    await run(db, 2, "join", room=rid)
    await run(db, 3, "join", room=rid)
    v = await api.snapshot(db, rid, 3)
    await run(db, 3, "leave", room=rid, rev=v["rev"])
    await db.reset_banned_user(3, None)
    final = await api.snapshot(db, rid, 1)
    assert final["result"]["reason"] == "account_reset"
    assert await balance(db, 3) == 0 and await balance(db, 1) == await balance(db, 2) == 1000
    assert sum(await amounts_as_list(db, rid)) == 0

