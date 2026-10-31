"""Real SQLite Sea Battle lifecycle: boards, stakes, persistence and notifications."""

import json
import secrets
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from community_bot import sea_api as sea
from community_bot.database import Database
from community_bot.friends_api import mutate as friend_mutate


def assert_no_touch(board, fleet):
    assert len(board) == sea.SIZE * sea.SIZE
    assert set(board) - {0} == set(fleet)
    cells_by_ship = {}
    for index, value in enumerate(board):
        if value:
            cells_by_ship.setdefault(value, []).append(index)
    for ship_id, size in fleet.items():
        assert len(cells_by_ship[ship_id]) == size
    ship_ids = list(fleet)
    for a in range(len(ship_ids)):
        for b in range(a + 1, len(ship_ids)):
            for i in cells_by_ship[ship_ids[a]]:
                for j in cells_by_ship[ship_ids[b]]:
                    assert max(abs(i // 10 - j // 10), abs(i % 10 - j % 10)) > 1


@pytest.fixture
async def env(tmp_path):
    db = Database(tmp_path / "sea.db")
    await db.initialize()
    for uid in range(7, 11):
        await db.ensure_user(uid, username=f"user_{uid}", telegram_name=f"Игрок {uid}")
        await db.execute(
            "UPDATE users SET profile_name=?,age=25,hobbies='Космос',profile_bio='Люблю гулять',role='moderator' "
            "WHERE user_id=?",
            (f"Игрок {uid}", uid),
        )
        await db.add_cookies(uid, 100, "fixture")
    for uid in (8, 9, 10):
        await db.execute(
            "INSERT INTO mini_friendships(low_id,high_id,requester_id,status,token,created_at,updated_at,expires_at) "
            "VALUES(7,?,7,'accepted',?,'fixture','fixture',9999999999)",
            (uid, secrets.token_hex(10)),
        )
    settings = SimpleNamespace(is_owner=lambda uid: uid in {7, 99}, owner_ids={7, 99}, moderator_ids=set())
    return SimpleNamespace(db=db, settings=settings, now=1000.0)


def body(action, **kwargs):
    return {"action": action, **kwargs}


async def send(env, uid, action, room=None, **kwargs):
    if room is not None:
        kwargs = {"room_id": room, **kwargs}
    return await sea.apply_action(env.db, env.settings, uid, body(action, **kwargs), now=env.now)


async def view(env, uid=7, room=None):
    return await sea.read_status(env.db, uid, now=env.now, room_id=room)


async def state(env, room):
    row = await env.db.fetchone("SELECT state_json FROM mini_sea_rooms WHERE id=?", (room,))
    return json.loads(row["state_json"])


async def advance(env, seconds):
    env.now += seconds
    await sea.tick(env.db, env.now)


def test_placement_never_touches_and_stuck_layout_falls_back_safely():
    for _ in range(50):
        assert_no_touch(*sea.place_board(secrets.SystemRandom()))

    class Stuck:
        def random(self):
            return 1.0

        def randrange(self, *args):
            return 0

    assert_no_touch(*sea.place_board(Stuck()))


async def test_bot_game_is_free_and_boards_are_private_until_finish(env):
    ledger = await env.db.fetchall("SELECT * FROM transactions ORDER BY id")
    room, _, _ = await send(env, 7, "create", vs_bot=True, stake=0)
    current = (await view(env))["room"]
    assert current["status"] == "lobby" and current["bot"] is True and len(current["players"]) == 2
    await send(env, 7, "start", room)
    result = (await view(env))["room"]
    assert result["status"] == "active" and result["turn"] in {7, -1}
    me = next(p for p in result["players"] if p["id"] == 7)
    foe = next(p for p in result["players"] if p["id"] == -1)
    assert set(me["board"]) and set(me["shots"]) == {False}
    assert "ships" not in foe and "board" not in foe
    assert await env.db.fetchall("SELECT * FROM transactions ORDER BY id") == ledger


async def test_bot_fires_after_player_miss_and_pass_turn(env):
    room, _, _ = await send(env, 7, "create", vs_bot=True, stake=0)
    await send(env, 7, "start", room)
    stored = await state(env, room)
    stored["turn"] = 7
    stored["players"]["bot"]["board"] = [0] * (sea.SIZE * sea.SIZE)
    await env.db.execute("UPDATE mini_sea_rooms SET state_json=? WHERE id=?", (json.dumps(stored), room))
    await send(env, 7, "shoot", room, cell=0)
    assert (await view(env))["room"]["turn"] == -1
    await advance(env, 2)
    stored = await state(env, room)
    assert any(value for value in stored["players"]["bot"]["shots"])


async def test_friend_game_charges_then_refunds_both_on_draw(env):
    room, _, _ = await send(env, 7, "create", vs_bot=False, stake=10)
    assert (await env.db.get_user(7))["cookies"] == 90
    await send(env, 7, "invite", room, user_id=8)
    await send(env, 8, "respond", room, accept=True)
    for uid in (7, 8):
        await send(env, uid, "ready", room, ready=True)
    await send(env, 7, "start", room)
    assert (await env.db.get_user(8))["cookies"] == 90
    await advance(env, 3700)
    result = (await view(env, 7, room))["room"]
    assert result["status"] == "finished" and result["winner"] is None
    assert (await env.db.get_user(7))["cookies"] == 100
    assert (await env.db.get_user(8))["cookies"] == 100
    kinds = [row["kind"] for row in await env.db.fetchall("SELECT kind FROM transactions WHERE user_id=7 ORDER BY id")]
    assert kinds == ["sea_bet", "sea_refund"]


async def test_winner_takes_double_stake_and_finish_reveals_ships(env):
    room, _, _ = await send(env, 7, "create", vs_bot=False, stake=10)
    await send(env, 7, "invite", room, user_id=8)
    await send(env, 8, "respond", room, accept=True)
    for uid in (7, 8):
        await send(env, uid, "ready", room, ready=True)
    await send(env, 7, "start", room)
    stored = await state(env, room)
    stored["players"]["8"]["board"] = [1 if i == 0 else 0 for i in range(sea.SIZE * sea.SIZE)]
    stored["players"]["8"]["fleet"] = {1: 1}
    stored["players"]["7"]["shots"] = [0] * (sea.SIZE * sea.SIZE)
    stored["turn"] = 7
    await env.db.execute("UPDATE mini_sea_rooms SET state_json=? WHERE id=?", (json.dumps(stored), room))
    message = await send(env, 7, "shoot", room, cell=0)
    assert message[1] == "Флот соперника уничтожен — победа!"
    result = (await view(env, 7, room))["room"]
    assert result["status"] == "finished" and result["winner"] == 7
    assert "ships" in next(p for p in result["players"] if p["id"] == 8)
    assert (await env.db.get_user(7))["cookies"] == 110
    assert (await env.db.get_user(8))["cookies"] == 90


async def test_bot_stake_is_charged_at_create_and_refunded_on_cancel(env):
    room, _, _ = await send(env, 7, "create", vs_bot=True, stake=25)
    assert (await env.db.get_user(7))["cookies"] == 75
    bets = await env.db.fetchall("SELECT amount,kind FROM transactions WHERE user_id=7 ORDER BY id")
    assert bets[-1]["amount"] == -25 and bets[-1]["kind"] == "sea_bet"
    await send(env, 7, "cancel", room)
    assert (await env.db.get_user(7))["cookies"] == 100
    last = await env.db.fetchone("SELECT amount,kind FROM transactions WHERE user_id=7 ORDER BY id DESC LIMIT 1")
    assert last["kind"] == "sea_refund" and last["amount"] == 25


async def test_invites_require_mutual_friendship_and_block_revokes(env):
    room, _, _ = await send(env, 7, "create", vs_bot=False, stake=0)
    await env.db.execute("UPDATE mini_friendships SET status='closed' WHERE high_id=8")
    with pytest.raises(ValueError):
        await send(env, 7, "invite", room, user_id=8)
    await send(env, 7, "invite", room, user_id=9)
    assert len((await view(env, 9))["invites"]) == 1
    await friend_mutate(env.db, env.settings, 9, {"action": "block", "target_id": 7})
    assert (await view(env, 9))["invites"] == []
    with pytest.raises(sea.Conflict):
        await send(env, 9, "respond", room, accept=True)


async def test_leaving_active_game_forfeits_to_opponent_and_releases_member(env):
    room, _, _ = await send(env, 7, "create", vs_bot=False, stake=0)
    await send(env, 7, "invite", room, user_id=8)
    await send(env, 8, "respond", room, accept=True)
    for uid in (7, 8):
        await send(env, uid, "ready", room, ready=True)
    await send(env, 7, "start", room)
    await send(env, 7, "leave", room)
    assert (await view(env, 8, room))["room"]["winner"] == 8
    assert await env.db.fetchall("SELECT user_id FROM mini_sea_members WHERE active=1") == []


async def test_lobby_leave_releases_member_for_rejoin(env):
    room, _, _ = await send(env, 7, "create", vs_bot=False, stake=0)
    await send(env, 7, "invite", room, user_id=8)
    await send(env, 8, "respond", room, accept=True)
    await send(env, 8, "leave", room)
    row = await env.db.fetchone("SELECT active FROM mini_sea_members WHERE user_id=8")
    assert row is None or row["active"] == 0
    other = await send(env, 8, "create", vs_bot=True, stake=0)
    assert other[0]


async def test_feature_switch_blocks_creation_but_preserves_exit(env):
    room, _, _ = await send(env, 7, "create", vs_bot=True, stake=0)
    await env.db.execute("UPDATE feature_flags SET enabled=0 WHERE key='games'")
    with pytest.raises(ValueError, match="выключены"):
        await send(env, 8, "create", vs_bot=True, stake=0)
    await send(env, 7, "leave", room)
    assert (await view(env, 7, room))["room"]["status"] == "cancelled"


async def test_age_and_miniapp_gate_block_stakes_and_actions(env):
    await env.db.execute("UPDATE users SET age=17 WHERE user_id=9")
    with pytest.raises(ValueError, match="18 лет"):
        await send(env, 9, "create", vs_bot=True, stake=10)
    await env.db.set_role(10, "member")
    with pytest.raises(ValueError, match="модератора"):
        await send(env, 10, "create", vs_bot=True, stake=0)


async def test_sea_invitation_buttons_accept_via_telegram(env, monkeypatch):
    from community_bot.sea_notifications import invitation_keyboard, respond

    monkeypatch.setattr(sea.time, "time", lambda: env.now)
    room, _, _ = await send(env, 7, "create", vs_bot=False, stake=10)
    _, _, notice = await send(env, 7, "invite", room, user_id=8)
    assert notice["room_id"] == room
    assert await env.db.get_bot_state(f"sea_notice:{notice['id']}") == room
    keyboard = invitation_keyboard(room)
    assert [b.text for b in keyboard.inline_keyboard[0]] == ["Принять", "Отклонить"]
    assert keyboard.inline_keyboard[0][0].callback_data == f"seafin:y:{room}"
    callback = SimpleNamespace(
        id="987654321123456789",
        data=f"seafin:y:{room}",
        from_user=SimpleNamespace(id=8),
        message=SimpleNamespace(chat=SimpleNamespace(type="private"), edit_reply_markup=AsyncMock()),
        answer=AsyncMock(),
    )
    await respond(callback, env.db, env.settings)
    assert (await view(env, 8))["room"]["id"] == room


async def test_notices_expose_sea_invite_for_inbox_acceptance(env, monkeypatch):
    from community_bot.cabinet_api import notices

    monkeypatch.setattr(sea.time, "time", lambda: env.now)
    room, _, _ = await send(env, 7, "create", vs_bot=False, stake=10)
    _, _, notice = await send(env, 7, "invite", room, user_id=8)

    class Request(dict):
        def __init__(self, uid):
            super().__init__(actor={"id": uid, "first_name": "Друг"})
            self.app = {"db": env.db, "settings": env.settings, "bot": None}

    payload = json.loads((await notices(Request(8))).body)
    linked = next(n for n in payload["items"] if n["id"] == notice["id"])
    assert linked["sea_invite"] == {
        "room_id": room,
        "title": "Морской бой",
        "stake": 10,
        "sender_name": "Игрок 7",
    }