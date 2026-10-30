"""Real SQLite Mafia lifecycle: private roles, reciprocal invites and durable clocks."""

import asyncio
import json
import secrets
from collections import Counter
from types import SimpleNamespace

import pytest

from community_bot import mafia_api as mafia
from community_bot.database import Database
from community_bot.friends_api import mutate as friend_mutate


@pytest.fixture
async def env(tmp_path):
    db = Database(tmp_path / "mafia.db")
    await db.initialize()
    for uid in range(7, 22):
        await db.ensure_user(uid, username=f"user_{uid}", telegram_name=f"Игрок {uid}")
        await db.set_role(uid, "moderator")
        await db.add_cookies(uid, 20, "fixture")
    for uid in range(8, 22):
        await db.execute(
            "INSERT INTO mini_friendships(low_id,high_id,requester_id,status,token,created_at,updated_at,expires_at) "
            "VALUES(7,?,7,'accepted',?,'fixture','fixture',9999999999)",
            (uid, secrets.token_hex(10)),
        )
    settings = SimpleNamespace(is_owner=lambda uid: uid in {7, 99}, owner_ids={7, 99}, moderator_ids=set())
    return SimpleNamespace(db=db, settings=settings, now=1000.0)


def body(action, **kwargs):
    return {"action": action, "request_id": secrets.token_hex(16), **kwargs}


async def send(env, uid, action, room=None, **kwargs):
    if room is not None:
        view = (await mafia.read_status(env.db, uid if action != "respond" else 7, now=env.now, room_id=room))["room"]
        kwargs = {"room_id": room, "phase_token": view["phase_token"], **kwargs}
    return await mafia.apply_action(env.db, env.settings, uid, body(action, **kwargs), now=env.now)


async def view(env, uid=7, room=None):
    return await mafia.read_status(env.db, uid, now=env.now, room_id=room)


async def lobby(env, count=5):
    room, _, _ = await send(env, 7, "create")
    for uid in range(8, 7 + count):
        await send(env, 7, "invite", room, user_id=uid)
        await send(env, uid, "respond", room, accept=True)
    return room


async def started(env, count=5):
    room = await lobby(env, count)
    for uid in range(7, 7 + count):
        await send(env, uid, "ready", room, ready=True)
    await send(env, 7, "start", room)
    return room


async def state(env, room):
    row = await env.db.fetchone("SELECT state_json FROM mini_mafia_rooms WHERE id=?", (room,))
    return json.loads(row["state_json"])


async def rig_roles(env, room, roles):
    value = await state(env, room)
    for uid, role in roles.items():
        value["players"][str(uid)]["role"] = role
    await env.db.execute("UPDATE mini_mafia_rooms SET state_json=? WHERE id=?", (json.dumps(value), room))


async def advance(env, seconds):
    env.now += seconds
    await mafia.tick(env.db, env.now)


async def test_lobby_requires_invite_consent_ready_and_host_start_and_no_money(env):
    ledger = await env.db.fetchall("SELECT * FROM transactions ORDER BY id")
    room = await lobby(env)
    with pytest.raises(mafia.Conflict):
        await send(env, 7, "start", room)
    for uid in range(7, 12):
        await send(env, uid, "ready", room, ready=True)
    with pytest.raises(ValueError):
        await send(env, 8, "start", room)
    await send(env, 7, "start", room)
    result = (await view(env, 7))["room"]
    assert result["phase"] == "night" and result["round"] == 1
    assert Counter(p["role"] for p in (await state(env, room))["players"].values()) == {
        "mafia": 1,
        "detective": 1,
        "civilian": 3,
    }
    assert await env.db.fetchall("SELECT * FROM transactions ORDER BY id") == ledger
    assert {row["cookies"] for row in await env.db.fetchall("SELECT cookies FROM users")} == {20}


@pytest.mark.parametrize("count,expected", [(6, 1), (8, 2), (11, 3), (12, 3)])
async def test_balanced_roles_follow_actual_player_count(env, count, expected):
    room = await started(env, count)
    roles = Counter(p["role"] for p in (await state(env, room))["players"].values())
    assert roles["mafia"] == expected and roles["detective"] == 1 and roles["doctor"] == 1
    assert sum(roles.values()) == count


async def test_host_cannot_read_other_roles_secret_chats_or_detective_results(env):
    room = await started(env, 8)
    await rig_roles(
        env,
        room,
        {
            7: "civilian",
            8: "mafia",
            9: "mafia",
            10: "detective",
            11: "doctor",
            12: "civilian",
            13: "civilian",
            14: "civilian",
        },
    )
    await send(env, 8, "chat", room, channel="mafia", text="Тайный план")
    host = (await view(env, 7))["room"]
    assert all(p["role"] is None for p in host["players"] if p["id"] != 7)
    assert not host["messages"] and host["self"]["investigations"] == []
    teammate = (await view(env, 9))["room"]
    assert {p["id"] for p in teammate["players"] if p["role"] == "mafia"} == {8, 9}
    assert teammate["messages"][0]["text"] == "Тайный план"
    with pytest.raises(ValueError):
        await view(env, 21, room)
    with pytest.raises(ValueError):
        await send(env, 7, "chat", room, channel="mafia", text="Хозяин не мафия")
    with pytest.raises(ValueError):
        await send(env, 7, "night", room, target_id=8)
    with pytest.raises(ValueError):
        await send(env, 8, "night", room, target_id=9)
    await send(env, 10, "night", room, target_id=8)
    await advance(env, 60)
    own = (await view(env, 10))["room"]["self"]["investigations"]
    assert own == [{"round": 1, "target_id": 8, "name": "Игрок 8", "mafia": True}]
    assert "investigations" not in (await view(env, 7))["room"]["players"][3]
    assert "Тайный план" not in json.dumps(await view(env, 7), ensure_ascii=False)


async def test_night_doctor_protects_only_one_target_with_repeat_and_self_heal_limits(env):
    room = await started(env, 6)
    await rig_roles(
        env, room, {7: "mafia", 8: "doctor", 9: "detective", 10: "civilian", 11: "civilian", 12: "civilian"}
    )
    await send(env, 7, "night", room, target_id=10)
    await send(env, 8, "night", room, target_id=10)
    await advance(env, 60)
    assert next(p for p in (await view(env))["room"]["players"] if p["id"] == 10)["alive"]
    await advance(env, 135)
    with pytest.raises(ValueError):
        await send(env, 8, "night", room, target_id=10)
    await send(env, 8, "night", room, target_id=8)
    await advance(env, 195)
    assert 8 not in (await view(env, 8))["room"]["available_targets"]
    await send(env, 8, "night", room, target_id=10)
    await advance(env, 195)
    assert 8 not in (await view(env, 8))["room"]["available_targets"]


async def test_tied_mafia_votes_do_not_kill_and_dead_chat_is_private(env):
    room = await started(env, 8)
    await rig_roles(
        env,
        room,
        {
            7: "mafia",
            8: "mafia",
            9: "doctor",
            10: "detective",
            11: "civilian",
            12: "civilian",
            13: "civilian",
            14: "civilian",
        },
    )
    await send(env, 7, "night", room, target_id=11)
    await send(env, 8, "night", room, target_id=12)
    await advance(env, 60)
    assert all(p["alive"] for p in (await view(env))["room"]["players"])
    await advance(env, 135)
    await send(env, 7, "night", room, target_id=11)
    await send(env, 8, "night", room, target_id=11)
    await advance(env, 60)
    await send(env, 11, "chat", room, channel="ghost", text="Секрет призрака")
    with pytest.raises(ValueError):
        await send(env, 11, "chat", room, channel="public", text="Подсказка живым")
    assert (await view(env, 11))["room"]["messages"][-1]["text"] == "Секрет призрака"
    assert "Секрет призрака" not in json.dumps(await view(env, 7), ensure_ascii=False)
    assert (await view(env, 11))["room"]["available_targets"] == []
    with pytest.raises(mafia.Conflict):
        await send(env, 11, "vote", room, target_id=7)


async def test_ballot_skip_tie_then_unique_vote_finishes_and_reveals_roles_once(env):
    room = await started(env)
    await rig_roles(env, room, {7: "mafia", 8: "detective", 9: "civilian", 10: "civilian", 11: "civilian"})
    await advance(env, 150)
    await send(env, 8, "vote", room, target_id=7)
    await send(env, 9, "vote", room, target_id=None)
    await advance(env, 45)
    assert (await view(env))["room"]["phase"] == "night"
    assert all(p["alive"] for p in (await view(env))["room"]["players"])
    await advance(env, 150)
    await send(env, 8, "vote", room, target_id=7)
    await send(env, 9, "vote", room, target_id=7)
    await advance(env, 45)
    final = (await view(env, 7, room))["room"]
    assert final["status"] == "finished" and final["winner"] == "town"
    assert all(p["role"] for p in final["players"])
    assert (await view(env))["room"] is None
    notices = await env.db.fetchall("SELECT * FROM notify_inbox WHERE text LIKE 'Мафия ·%'")
    assert len(notices) == 5
    await mafia.tick(env.db, env.now + 1000)
    assert await env.db.fetchall("SELECT * FROM notify_inbox WHERE text LIKE 'Мафия ·%'") == notices


async def test_mafia_parity_wins_after_surrender_and_lobby_host_transfers(env):
    room = await lobby(env)
    old_token = (await view(env))["room"]["phase_token"]
    await send(env, 7, "leave", room)
    current = (await view(env, 8))["room"]
    assert current["host_id"] == 8 and current["phase_token"] != old_token
    assert not any(p["ready"] for p in current["players"])
    await send(env, 8, "cancel", room)
    room = await started(env)
    await rig_roles(env, room, {7: "mafia", 8: "detective", 9: "civilian", 10: "civilian", 11: "civilian"})
    for uid in (8, 9, 10):
        await send(env, uid, "leave", room)
    assert (await view(env, 7, room))["room"]["winner"] == "mafia"


async def test_restart_uses_persisted_deadlines_and_finishes_afk_party_without_money(env):
    room = await started(env)
    env.db = Database(env.db.path)
    await env.db.initialize()
    await advance(env, 150)
    result = (await view(env))["room"]
    assert result["phase"] == "vote" and result["deadline"] == 1195_000
    await advance(env, 7200)
    result = (await view(env, 7, room))["room"]
    assert result["status"] == "finished" and result["winner"] == "draw"
    assert await env.db.fetchall("SELECT user_id FROM mini_mafia_members WHERE active=1") == []
    assert {row["cookies"] for row in await env.db.fetchall("SELECT cookies FROM users")} == {20}


async def test_stale_phase_is_rejected_and_duplicate_requests_and_races_are_safe(env):
    create = body("create")
    outcomes = await asyncio.gather(
        *(mafia.apply_action(env.db, env.settings, 7, create, now=env.now) for _ in range(5))
    )
    assert len({r[0] for r in outcomes}) == 1
    room = outcomes[0][0]
    assert len(await env.db.fetchall("SELECT * FROM mini_mafia_rooms")) == 1
    with pytest.raises(mafia.Conflict):
        await mafia.apply_action(env.db, env.settings, 7, {**create, "title": "Подмена"}, now=env.now)
    old = (await view(env))["room"]["phase_token"]
    await send(env, 7, "invite", room, user_id=8)
    accepted = body("respond", room_id=room, accept=True)
    outcomes = await asyncio.gather(
        *(mafia.apply_action(env.db, env.settings, 8, accepted, now=env.now) for _ in range(3))
    )
    assert len({r[0] for r in outcomes}) == 1
    assert len((await view(env))["room"]["players"]) == 2
    with pytest.raises(mafia.Conflict):
        await mafia.apply_action(
            env.db, env.settings, 7, body("ready", room_id=room, phase_token=old, ready=True), now=env.now
        )
    current = (await view(env))["room"]["phase_token"]
    chat = body("chat", room_id=room, phase_token=current, text="Привет!", channel="public")
    await asyncio.gather(*(mafia.apply_action(env.db, env.settings, 7, chat, now=env.now) for _ in range(3)))
    assert len((await view(env))["room"]["messages"]) == 1
    with pytest.raises(ValueError, match="пару секунд"):
        await send(env, 7, "chat", room, text="Спам", channel="public")


async def test_action_arriving_at_deadline_cannot_change_completed_night(env):
    room = await started(env)
    await rig_roles(env, room, {7: "mafia", 8: "detective", 9: "civilian", 10: "civilian", 11: "civilian"})
    old = (await view(env))["room"]["phase_token"]
    env.now += 60
    with pytest.raises(mafia.Conflict):
        await mafia.apply_action(
            env.db,
            env.settings,
            7,
            body("night", room_id=room, phase_token=old, target_id=9),
            now=env.now,
        )
    current = (await view(env))["room"]
    assert current["phase"] == "discussion" and current["deadline"] == 1150_000
    assert all(p["alive"] for p in current["players"])


async def test_invites_require_current_mutual_friendship_and_blocks_revoke_pending(env):
    room, _, _ = await send(env, 7, "create")
    with pytest.raises(ValueError):
        await send(env, 8, "respond", room, accept=True)
    await env.db.execute("UPDATE mini_friendships SET status='closed' WHERE high_id=8")
    with pytest.raises(ValueError):
        await send(env, 7, "invite", room, user_id=8)
    await send(env, 7, "invite", room, user_id=9)
    assert len((await view(env, 9))["invites"]) == 1
    await friend_mutate(env.db, env.settings, 9, {"action": "block", "target_id": 7})
    assert (await view(env, 9))["invites"] == []
    with pytest.raises(mafia.Conflict):
        await send(env, 9, "respond", room, accept=True)
    await env.db.set_role(10, "member")
    with pytest.raises(ValueError):
        await send(env, 7, "invite", room, user_id=10)
    await send(env, 7, "invite", room, user_id=11)
    await env.db.set_role(11, "member")
    with pytest.raises(ValueError):
        await send(env, 11, "respond", room, accept=True)


async def test_invitation_decline_commits_without_requiring_room_membership(env, monkeypatch):
    room, _, _ = await send(env, 7, "create")
    await send(env, 7, "invite", room, user_id=8)
    monkeypatch.setattr(mafia.time, "time", lambda: env.now)

    class Request(dict):
        app = {"db": env.db, "settings": env.settings, "bot": None}

        async def json(self):
            return body("respond", room_id=room, accept=False)

    result = await mafia.action(Request(actor={"id": 8, "first_name": "Игрок 8"}))
    response = json.loads(result.body)
    assert result.status == 200 and response["room"] is None and response["invites"] == []
    assert response["message"] == "Приглашение отклонено"


async def test_feature_switch_blocks_new_play_but_preserves_exit_and_settlement(env):
    room = await started(env)
    await env.db.execute("UPDATE feature_flags SET enabled=0 WHERE key='games'")
    with pytest.raises(ValueError, match="выключены"):
        await send(env, 21, "create")
    await send(env, 8, "leave", room)
    await advance(env, 7201)
    assert (await view(env, 7, room))["room"]["status"] == "finished"


async def test_lobby_expiry_cancels_invites_and_releases_members(env):
    room, _, _ = await send(env, 7, "create")
    await send(env, 7, "invite", room, user_id=8)
    await advance(env, 3601)
    assert (await view(env))["room"] is None
    assert (await view(env, 8))["invites"] == []
    assert (await view(env, 7, room))["room"]["status"] == "cancelled"


async def test_invitation_user_text_is_escaped_for_telegram_and_owner_is_initialized(env, monkeypatch):
    await env.db.execute("UPDATE users SET profile_name='<b>Имя</b>' WHERE user_id=7")
    room, _, _ = await send(env, 7, "create", title="<a>Комната</a>")
    _, _, notice = await send(env, 7, "invite", room, user_id=8)
    assert "&lt;b&gt;" in notice["text"] and "<b>" not in notice["text"]
    assert "&lt;a&gt;" in notice["text"] and "<a>" not in notice["text"]
    monkeypatch.setattr(mafia.time, "time", lambda: env.now)

    class Request(dict):
        app = {"db": env.db, "settings": env.settings, "bot": None}

        async def json(self):
            return body("create")

    result = await mafia.action(Request(actor={"id": 99, "first_name": "Новый владелец"}))
    assert result.status == 200
    assert (await env.db.get_user(99))["telegram_name"] == "Новый владелец"


async def test_creator_can_leave_and_delete_active_room_releasing_every_player(env):
    room = await started(env)
    with pytest.raises(ValueError, match="создатель"):
        await send(env, 8, "cancel", room)
    focus, _, _ = await send(env, 7, "cancel", room)
    assert focus is None
    assert (await env.db.get_user(7))["cookies"] == 20
    assert (await view(env, 8))["room"] is None
    assert (await env.db.fetchone("SELECT status FROM mini_mafia_rooms WHERE id=?", (room,)))["status"] == "cancelled"
    new_room, _, _ = await send(env, 7, "create")
    assert new_room != room


async def test_invite_notices_have_actor_bound_buttons_and_do_not_survive_response(env, monkeypatch):
    from unittest.mock import AsyncMock

    from community_bot.cabinet_api import notices
    from community_bot.mafia_notifications import invitation_keyboard, respond

    monkeypatch.setattr(mafia.time, "time", lambda: env.now)
    room, _, _ = await send(env, 7, "create")
    _, _, notice = await send(env, 7, "invite", room, user_id=8)
    assert notice["room_id"] == room
    keyboard = invitation_keyboard(room)
    assert [b.text for b in keyboard.inline_keyboard[0]] == ["Принять", "Отклонить"]

    class Request(dict):
        def __init__(self, uid):
            super().__init__(actor={"id": uid, "first_name": "Друг"})
            self.app = {"db": env.db, "settings": env.settings, "bot": None}

    payload = json.loads((await notices(Request(8))).body)
    assert next(n for n in payload["items"] if n["id"] == notice["id"])["mafia_invite"]["room_id"] == room
    assert not json.loads((await notices(Request(9))).body)["mafia_invites"]
    callback = SimpleNamespace(
        id="987654321123456789",
        data=f"mfin:y:{room}",
        from_user=SimpleNamespace(id=9),
        message=SimpleNamespace(chat=SimpleNamespace(type="private"), edit_reply_markup=AsyncMock()),
        answer=AsyncMock(),
    )
    await respond(callback, env.db, env.settings)
    assert (await view(env, 9))["room"] is None
    callback.from_user.id = 8
    await respond(callback, env.db, env.settings)
    assert (await view(env, 8))["room"]["id"] == room
    await respond(callback, env.db, env.settings)  # replay remains harmless
    assert (await env.db.fetchone("SELECT COUNT(*) n FROM mini_mafia_members WHERE user_id=8"))["n"] == 1
    payload = json.loads((await notices(Request(8))).body)
    assert not payload["mafia_invites"]
    assert all(not n["mafia_invite"] for n in payload["items"])


async def test_invitation_is_sent_with_direct_buttons_even_if_games_digest_is_off(env, monkeypatch):
    from unittest.mock import AsyncMock

    from community_bot.friends_api import deliver_notice
    from community_bot.mafia_notifications import invitation_keyboard, respond

    monkeypatch.setattr(mafia.time, "time", lambda: env.now)
    room, _, _ = await send(env, 7, "create")
    _, _, notice = await send(env, 7, "invite", room, user_id=8)
    bot = SimpleNamespace(send_message=AsyncMock())
    await deliver_notice(
        bot, env.db, notice["id"], 8, notice["text"], reply_markup=invitation_keyboard(room), force=True
    )
    assert bot.send_message.call_args.kwargs["reply_markup"].inline_keyboard[0][1].callback_data == f"mfin:n:{room}"
    callback = SimpleNamespace(
        id="987654321123456788",
        data=f"mfin:n:{room}",
        from_user=SimpleNamespace(id=8),
        message=SimpleNamespace(chat=SimpleNamespace(type="private"), edit_reply_markup=AsyncMock()),
        answer=AsyncMock(),
    )
    await respond(callback, env.db, env.settings)
    assert not (await view(env, 8))["invites"]
    assert (await view(env, 8))["room"] is None
