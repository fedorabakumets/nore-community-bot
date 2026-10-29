import asyncio
import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from aiohttp import web
from PIL import Image

from community_bot.cabinet_api import wallet_confirm, wallet_prepare
from community_bot.database import Database
from community_bot.friends_api import mutate, snapshot
from community_bot.social_profiles import avatar, heartbeat, presence_map, profile, update


@pytest.fixture
async def env(tmp_path):
    db = Database(tmp_path / "social.db")
    await db.initialize()
    await db.create_staff_role("helper45", "Помощник", 45, [])
    for uid in (7, 8, 9):
        await db.ensure_user(uid, f"person{uid}", f"Участник {uid}")
        await db.set_role(uid, "helper45")
        await db.execute(
            "UPDATE users SET profile_name=?,age=25,hobbies='Город',profile_bio='Био участника',"
            "avatar_file_id='avatar',cookies=100,moderator_note='secret note' WHERE user_id=?",
            (f"Участник {uid}", uid),
        )
        await db.reward_complete_profile(uid)
        await db.execute("UPDATE users SET cookies=100 WHERE user_id=?", (uid,))
    settings = SimpleNamespace(
        is_owner=lambda uid: uid == 7,
        owner_ids={7},
        moderator_ids=set(),
        restricted_reputation_threshold=0,
        timezone="Europe/Moscow",
    )
    return SimpleNamespace(db=db, settings=settings)


class Request(dict):
    def __init__(self, env, uid=8, target="9", body=None):
        super().__init__(actor={"id": uid, "first_name": f"Участник {uid}"})
        self.app = {"db": env.db, "settings": env.settings, "bot": None}
        self.match_info = {"user_id": target} if target else {}
        self.query = {}
        self.body = body

    async def json(self):
        return self.body


async def befriend(env, a=7, b=8):
    await mutate(env.db, env.settings, a, {"action": "request", "recipient": str(b)})
    token = (await snapshot(env.db, env.settings, b))["incoming"][0]["token"]
    await mutate(env.db, env.settings, b, {"action": "accept", "target_id": a, "token": token})
    return token


async def test_presence_tracks_foreground_sessions_stale_sequences_and_expiry(env):
    await heartbeat(env.db, 8, "a" * 20, 1, True, now=100)
    assert (await presence_map(env.db, [8], now=110))[8]["online"]
    await heartbeat(env.db, 8, "b" * 20, 1, True, now=101)
    await heartbeat(env.db, 8, "a" * 20, 3, False, now=115)
    await heartbeat(env.db, 8, "a" * 20, 2, True, now=120)  # reordered old active request
    assert (await presence_map(env.db, [8], now=130))[8]["online"]  # second window stays open
    await heartbeat(env.db, 8, "b" * 20, 2, False, now=140)
    assert not (await presence_map(env.db, [8], now=141))[8]["online"]
    await heartbeat(env.db, 8, "b" * 20, 3, True, now=150)
    assert not (await presence_map(env.db, [8], now=211))[8]["online"]  # missed offline falls back to TTL
    for n in range(10):
        await heartbeat(env.db, 8, str(n) * 20, 1, True, now=250 + n)
    assert (await env.db.fetchone("SELECT COUNT(*) n FROM mini_presence WHERE user_id=8"))["n"] <= 5
    with pytest.raises(ValueError):
        await heartbeat(env.db, 8, "bad", True, True)


async def test_presence_privacy_and_private_profile_hide_all_activity(env):
    await befriend(env)
    await heartbeat(env.db, 8, "a" * 20, 1, True)
    assert (await snapshot(env.db, env.settings, 7))["friends"][0]["presence"]["online"]
    await update(Request(env, body={"hidden": True}))
    p = (await snapshot(env.db, env.settings, 7))["friends"][0]["presence"]
    assert not p["visible"] and p["last_seen"] is None and not p["online"]
    await update(Request(env, body={"hidden": False}))
    await env.db.update_profile(8, "profile_private", 1)
    assert not (await presence_map(env.db, [8]))[8]["visible"]
    with pytest.raises(ValueError):
        await update(Request(env, body={"hidden": True, "user_id": 9}))


async def test_public_profile_omits_money_secrets_and_does_not_expose_nonfriend_online(env):
    await heartbeat(env.db, 9, "b" * 20, 1, True)
    result = json.loads((await profile(Request(env))).body)
    assert result["id"] == 9 and result["bio"] == "Био участника" and not result["hidden"]
    assert not result["presence"]["visible"]
    assert not {"cookies", "cookie_debt", "moderator_note", "avatar_file_id", "warnings"} & result.keys()
    assert "secret note" not in json.dumps(result)
    await befriend(env, 8, 9)
    assert json.loads((await profile(Request(env))).body)["presence"]["online"]
    lookup = Request(env, target=None)
    lookup.query = {"recipient": "@person9"}
    assert json.loads((await profile(lookup)).body)["id"] == 9


async def test_hidden_and_blocked_profiles_and_avatars_are_enforced_on_server(env):
    await befriend(env, 8, 9)
    await env.db.update_profile(9, "profile_private", 1)
    p = json.loads((await profile(Request(env))).body)
    assert p["hidden"] and set(p) == {"id", "name", "username", "friend", "hidden"}
    with pytest.raises(web.HTTPForbidden):
        await avatar(Request(env))
    # Existing see-private permission still works for the configured owner.
    assert not json.loads((await profile(Request(env, uid=7))).body)["hidden"]
    await env.db.update_profile(9, "profile_private", 0)
    await mutate(env.db, env.settings, 8, {"action": "block", "target_id": 9})
    with pytest.raises(web.HTTPNotFound):
        await profile(Request(env))
    with pytest.raises(web.HTTPNotFound):
        await profile(Request(env, uid=9, target="8"))


async def test_avatar_rechecks_privacy_after_download(env):
    raw = BytesIO()
    Image.new("RGB", (50, 50), "red").save(raw, "JPEG")

    class Bot:
        async def download(self, file_id, destination):
            destination.write(raw.getvalue())
            await env.db.update_profile(9, "profile_private", 1)

    request = Request(env)
    request.app["bot"] = Bot()
    with pytest.raises(web.HTTPForbidden):
        await avatar(request)


async def test_friend_transfer_uses_shared_quote_and_is_once(env):
    await befriend(env)
    q = json.loads(
        (await wallet_prepare(Request(env, uid=7, body={"action": "transfer", "friend_id": 8, "amount": 20}))).body
    )
    assert (await env.db.get_user(7))["cookies"] == 100
    result = await asyncio.gather(*[wallet_confirm(Request(env, uid=7, body={"token": q["token"]})) for _ in range(3)])
    assert sum(r.status == 200 for r in result) == 1
    assert (await env.db.get_user(7))["cookies"] == 80
    assert (await env.db.get_user(8))["cookies"] == 100 + q["received"]


async def test_removed_friend_cannot_be_paid_by_a_stale_friend_quote(env):
    token = await befriend(env)
    q = json.loads(
        (await wallet_prepare(Request(env, uid=7, body={"action": "transfer", "friend_id": 8, "amount": 20}))).body
    )
    await mutate(env.db, env.settings, 7, {"action": "remove", "target_id": 8, "token": token})
    result = await wallet_confirm(Request(env, uid=7, body={"token": q["token"]}))
    assert result.status == 409 and "Дружба" in json.loads(result.body)["message"]
    assert (await env.db.get_user(7))["cookies"] == 100
    assert (await env.db.get_user(8))["cookies"] == 100
    with pytest.raises(ValueError):
        await wallet_prepare(Request(env, uid=7, body={"action": "transfer", "friend_id": 8, "amount": 20}))
    with pytest.raises(ValueError):
        await wallet_prepare(Request(env, uid=7, body={"action": "transfer", "friend_id": True, "amount": 20}))


async def test_privacy_requires_purchase_and_survives_reopening(env):
    from community_bot.miniapp import profile_privacy

    denied = await profile_privacy(Request(env, body={'hidden': True}))
    assert denied.status == 403
    assert not (await env.db.get_user(8))['profile_private']
    ok, _ = await env.db.buy_item(8, 'private_profile', 10)
    assert ok
    before = (await env.db.get_user(8))['cookies']
    for hidden in (False, True, True, False):
        response = await profile_privacy(Request(env, body={'hidden': hidden}))
        assert response.status == 200
        assert bool((await env.db.get_user(8))['profile_private']) == hidden
    assert await env.db.owns_profile_privacy(8)
    ok, _ = await env.db.buy_item(8, 'private_profile', 10)
    assert not ok
    assert (await env.db.get_user(8))['cookies'] == before
    with pytest.raises(ValueError):
        await profile_privacy(Request(env, body={'hidden': 'false'}))
    with pytest.raises(ValueError):
        await profile_privacy(Request(env, body={'hidden': True, 'user_id': 9}))


async def test_privacy_gifts_and_legacy_hidden_profiles(env):
    ok, _ = await env.db.buy_item(7, 'private_profile', 10, target_id=9)
    assert ok
    await env.db.update_profile(9, 'profile_private', 0)
    assert await env.db.owns_profile_privacy(9)
    assert not await env.db.owns_profile_privacy(7)
    await env.db.update_profile(8, 'profile_private', 1)
    assert await env.db.set_profile_privacy(8, False)
    reopened = Database(env.db.path)
    assert await reopened.set_profile_privacy(8, True)
