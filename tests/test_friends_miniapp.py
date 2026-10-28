import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from community_bot.database import Database
from community_bot.friends_api import (
    SCHEMA,
    accepted,
    action,
    deliver_notice,
    mutate,
    snapshot,
    status,
)


@pytest.fixture
async def env(tmp_path):
    db = Database(tmp_path / "friends.sqlite3")
    await db.initialize()
    async with db.connect() as connection:
        await connection.executescript(SCHEMA)
    for uid in range(1, 17):
        await db.ensure_user(uid, f"person{uid}", f"Имя {uid}")
        await db.set_role(uid, "moderator")
    settings = SimpleNamespace(is_owner=lambda uid: uid == 1, moderator_ids=set())
    return SimpleNamespace(db=db, settings=settings)


async def do(env, uid, command, other=None, **kwargs):
    body = {"action": command, **kwargs}
    if command == "request":
        body["recipient"] = kwargs.get("recipient", str(other))
    else:
        body["target_id"] = other
    return await mutate(env.db, env.settings, uid, body)


async def relation(env, uid, category):
    return (await snapshot(env.db, env.settings, uid))[category][0]


async def befriend(env, a=1, b=2):
    await do(env, a, "request", b)
    token = (await relation(env, b, "incoming"))["token"]
    await do(env, b, "accept", a, token=token)
    return token


async def test_mutual_consent_owns_actions_and_private_snapshot(env):
    await env.db.update_profile(1, "profile_private", 1)
    await env.db.update_profile(1, "moderator_note", "private note must never leave database")
    await env.db.set_cookies(1, 777, 1)
    message, notices = await do(env, 1, "request", recipient="@PeRsOn2")
    assert "подтверждения" in message and len(notices) == 1
    assert not await accepted(env.db, 1, 2)
    row = await relation(env, 2, "incoming")
    assert row["id"] == 1
    assert set(row) == {"id", "name", "username", "token", "created_at", "updated_at", "available"}
    assert "private note" not in json.dumps(await snapshot(env.db, env.settings, 2))
    with pytest.raises(ValueError, match="получатель"):
        await do(env, 1, "accept", 2, token=row["token"])
    with pytest.raises(ValueError, match="Список изменился"):
        await do(env, 3, "accept", 1, token=row["token"])
    with pytest.raises(ValueError, match="только свой"):
        await do(env, 2, "cancel", 1, token=row["token"])
    await do(env, 2, "accept", 1, token=row["token"])
    assert await accepted(env.db, 1, 2) and await accepted(env.db, 2, 1)
    assert (await relation(env, 1, "friends"))["id"] == 2
    assert (await env.db.get_user(1))["cookies"] == 777


async def test_duplicate_concurrent_requests_accept_and_cross_requests_no_auto_consent(env):
    calls = await asyncio.gather(*[do(env, 1, "request", 2) for _ in range(5)])
    assert sum(len(notices) for _, notices in calls) == 1
    crossed, notices = await do(env, 2, "request", 1)
    assert "входящий" in crossed and not notices
    assert not await accepted(env.db, 1, 2)
    row = await relation(env, 2, "incoming")
    calls = await asyncio.gather(*[do(env, 2, "accept", 1, token=row["token"]) for _ in range(5)])
    assert sum(len(notices) for _, notices in calls) == 1
    assert (await env.db.fetchone("SELECT COUNT(*) AS n FROM notify_inbox"))["n"] == 2
    assert (await env.db.fetchone("SELECT COUNT(*) AS n FROM mini_friendships"))["n"] == 1


async def test_decline_cancel_cooldown_and_stale_token_do_not_reopen_relation(env, monkeypatch):
    import community_bot.friends_api as friends

    monkeypatch.setattr(friends.time, "time", lambda: 1_800_000_000)
    await do(env, 1, "request", 2)
    token = (await relation(env, 2, "incoming"))["token"]
    await do(env, 2, "decline", 1, token=token)
    with pytest.raises(ValueError, match="24 часа"):
        await do(env, 1, "request", 2)
    with pytest.raises(ValueError, match="24 часа"):
        await do(env, 2, "request", 1)
    with pytest.raises(ValueError, match="закрыт"):
        await do(env, 2, "accept", 1, token=token)
    monkeypatch.setattr(friends.time, "time", lambda: 1_800_090_000)
    await do(env, 1, "request", 2)
    with pytest.raises(ValueError, match="Список изменился"):
        await do(env, 2, "accept", 1, token=token)
    new = (await relation(env, 1, "outgoing"))["token"]
    await do(env, 1, "cancel", 2, token=new)
    assert not (await snapshot(env.db, env.settings, 2))["incoming"]


async def test_remove_block_revoke_invites_and_unblock_does_not_restore_friendship(env):
    token = await befriend(env)
    async with env.db.connect() as connection:
        exists = await (await connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mini_mafia_invites'"
        )).fetchone()
        if not exists:
            await connection.execute(
                "CREATE TABLE mini_mafia_invites(room_id TEXT,user_id INTEGER,sender_id INTEGER,status TEXT)"
            )
            await connection.execute("INSERT INTO mini_mafia_invites VALUES ('room',2,1,'pending')")
            await connection.commit()
    await do(env, 1, "block", 2)
    assert not await accepted(env.db, 1, 2)
    block = await relation(env, 1, "blocked")
    assert not (await snapshot(env.db, env.settings, 2))["blocked"]
    for a, b in [(1, 2), (2, 1)]:
        with pytest.raises(ValueError, match="недоступны"):
            await do(env, a, "request", b)
    with pytest.raises(ValueError, match="Список изменился"):
        await do(env, 1, "unblock", 2, token="invalid")
    await do(env, 1, "unblock", 2, token=block["token"])
    assert not await accepted(env.db, 1, 2)
    assert not (await snapshot(env.db, env.settings, 1))["blocked"]
    with pytest.raises(ValueError, match="закрыт"):
        await do(env, 2, "accept", 1, token=token)


async def test_remove_friend_works_from_either_side_and_cannot_remove_pending(env):
    await do(env, 1, "request", 2)
    token = (await relation(env, 2, "incoming"))["token"]
    with pytest.raises(ValueError, match="изменился"):
        await do(env, 1, "remove", 2, token=token)
    await do(env, 2, "accept", 1, token=token)
    await do(env, 2, "remove", 1, token=token)
    assert not await accepted(env.db, 1, 2)
    message, notices = await do(env, 1, "remove", 2, token=token)
    assert "уже закрыты" in message and not notices


async def test_exact_lookup_not_directory_self_unknown_invalid_and_role_gate(env):
    for value in ["", "person", "@person*", "https://t.me/person2", "2 OR 1=1", None, True]:
        with pytest.raises(ValueError):
            await do(env, 1, "request", recipient=value)
    with pytest.raises(ValueError, match="Себя"):
        await do(env, 1, "request", 1)
    with pytest.raises(ValueError, match="не найден"):
        await do(env, 1, "request", 999)
    await env.db.set_role(2, "member")
    with pytest.raises(ValueError, match="нет доступа"):
        await do(env, 1, "request", 2)
    await env.db.set_role(2, "moderator")
    await do(env, 1, "request", 2)
    token = (await relation(env, 2, "incoming"))["token"]
    await env.db.set_role(2, "member")
    with pytest.raises(ValueError, match="от роли модератора"):
        await do(env, 2, "accept", 1, token=token)
    assert not await accepted(env.db, 1, 2)


async def test_request_rate_not_reset_by_cancelling_and_expiration(env, monkeypatch):
    import community_bot.friends_api as friends

    monkeypatch.setattr(friends.time, "time", lambda: 1_800_000_000)
    for other in range(2, 12):
        await do(env, 1, "request", other)
        token = (await snapshot(env.db, env.settings, 1))["outgoing"][0]["token"]
        # Read the matching row, since requests have equal timestamps in this test.
        rows = (await snapshot(env.db, env.settings, 1))["outgoing"]
        token = next(row["token"] for row in rows if row["id"] == other)
        await do(env, 1, "cancel", other, token=token)
    with pytest.raises(ValueError, match="10 новых"):
        await do(env, 1, "request", 12)
    monkeypatch.setattr(friends.time, "time", lambda: 1_800_004_000)
    await do(env, 1, "request", 12)
    token = (await relation(env, 12, "incoming"))["token"]
    monkeypatch.setattr(friends.time, "time", lambda: 1_800_700_000)
    assert not (await snapshot(env.db, env.settings, 12))["incoming"]
    with pytest.raises(ValueError, match="истёк"):
        await do(env, 12, "accept", 1, token=token)


async def test_notice_html_escaped_dm_optin_digest_and_delivery_failure_keeps_success(env):
    await env.db.update_profile(1, "profile_name", "<b>Не разметка</b>")
    _, notices = await do(env, 1, "request", 2)
    inbox_id, uid, text = notices[0]
    assert "&lt;b&gt;" in text
    bot = SimpleNamespace(send_message=AsyncMock())
    await deliver_notice(bot, env.db, inbox_id, uid, text)
    bot.send_message.assert_not_awaited()
    await env.db.notify_toggle_enabled(2, "games")
    await env.db.notify_toggle_digest(2, "games")
    await deliver_notice(bot, env.db, inbox_id, uid, text)
    bot.send_message.assert_not_awaited()
    await env.db.notify_toggle_digest(2, "games")
    bot.send_message.side_effect = RuntimeError("test transport failure")
    await deliver_notice(bot, env.db, inbox_id, uid, text)
    assert (await env.db.fetchone("SELECT delivered FROM notify_inbox WHERE id=?", (inbox_id,)))["delivered"] == 0
    assert (await relation(env, 2, "incoming"))["id"] == 1
    bot.send_message.side_effect = None
    await deliver_notice(bot, env.db, inbox_id, uid, text)
    assert (await env.db.fetchone("SELECT delivered FROM notify_inbox WHERE id=?", (inbox_id,)))["delivered"] == 1


class Request(dict):
    def __init__(self, env, uid, body=None):
        super().__init__(actor={"id": uid, "first_name": f"Имя {uid}", "username": f"person{uid}"})
        self.app = {"db": env.db, "settings": env.settings, "bot": None}
        self.body = body

    async def json(self):
        return self.body


async def test_http_handlers_take_actor_only_and_never_client_user_id(env):
    response = await action(Request(env, 1, {"action": "request", "recipient": "2", "user_id": 3}))
    assert response.status == 200
    response = await status(Request(env, 2))
    payload = json.loads(response.body)
    assert payload["incoming"][0]["id"] == 1
    assert not (await snapshot(env.db, env.settings, 3))["outgoing"]


async def test_custom_staff_role_and_demoted_friend_availability(env):
    await env.db.create_staff_role("helper45", "Помощник", 45, [])
    await env.db.set_role(2, "helper45")
    await befriend(env)
    await env.db.set_role(2, "member")
    assert (await relation(env, 1, "friends"))["available"] is False
