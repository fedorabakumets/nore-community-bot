"""Staff-chat statistics controls reuse actual roles and existing NORA state."""
import json
from types import SimpleNamespace

import pytest

from community_bot.database import Database
from community_bot.staff_chat_admin import capabilities, change
from community_bot.social_likes import count


class Request(dict):
    content_length = 128

    def __init__(self, app, actor, payload=None, target_id=None):
        super().__init__(actor={"id": actor})
        self.app = app
        self.payload = payload
        self.query = {"target_id": str(target_id)} if target_id is not None else {}

    async def json(self):
        return self.payload


async def setup(tmp_path):
    db = Database(tmp_path / "staff-stats.db")
    await db.initialize()
    for uid, role in [(20, "admin"), (21, "moderator"), (22, "member"), (23, "owner")]:
        await db.ensure_user(uid, telegram_name=f"Участник {uid}")
        await db.set_role(uid, role)
    settings = SimpleNamespace(
        community_chat_id=-100123456789, moderator_ids=frozenset(),
        is_owner=lambda uid: uid == 23,
    )
    return db, {"db": db, "settings": settings}


def payload(metric, value, expected, target=22, confirmed=True):
    return {
        "target_id": target, "metric": metric, "value": value,
        "expected": expected, "confirmed": confirmed,
    }


@pytest.mark.asyncio
async def test_admin_can_edit_real_cookies_reputation_and_likes_atomically(tmp_path):
    db, app = await setup(tmp_path)
    await db.set_bot_state("likes_received:22", "8")
    response = await capabilities(Request(app, 20, target_id=22))
    body = json.loads(response.text)
    assert response.status == 200
    assert body["can_cookies"] and body["can_profile"] and body["can_likes"]
    assert body["target"]["likes"] == 8

    initial = await db.get_user(22)
    changes = [
        ("cookies", 152, int(initial["cookies"])),
        ("reputation", 87, int(initial["reputation"])),
        ("likes", 50, 8),
    ]
    for metric, value, expected in changes:
        result = await change(Request(app, 20, payload(metric, value, expected)))
        assert result.status == 200, result.text
        assert json.loads(result.text)["target"][metric] == value
    stored = await db.get_user(22)
    assert stored["cookies"] == 152
    assert stored["reputation"] == 87
    assert await count(db, 22) == 50
    history = await db.fetchall(
        "SELECT amount,kind FROM transactions WHERE user_id=?", (22,)
    )
    assert any(row["kind"] == "admin_set" and row["amount"] == 152 for row in history)
    audit = await db.fetchall(
        "SELECT action FROM admin_audit_log WHERE actor_id=? AND target=?", (20, "22")
    )
    assert {"user_cookies", "user_reputation", "user_likes"} <= {
        item["action"] for item in audit
    }


@pytest.mark.asyncio
async def test_moderator_may_open_settings_but_cannot_edit_stats(tmp_path):
    db, app = await setup(tmp_path)
    view = await capabilities(Request(app, 21))
    assert view.status == 200
    info = json.loads(view.text)
    assert info["can_open"] and not info["can_cookies"] and not info["can_profile"]
    denied = await change(Request(app, 21, payload("likes", 50, 0)))
    assert denied.status == 403
    assert await count(db, 22) == 0


@pytest.mark.asyncio
async def test_admin_cannot_edit_owner_and_stale_changes_do_not_apply(tmp_path):
    db, app = await setup(tmp_path)
    assert (await capabilities(Request(app, 20, target_id=23))).status == 403
    before = await db.get_user(22)
    old = int(before["cookies"])
    assert (await change(Request(app, 20, payload("cookies", 50, old, confirmed=False)))).status == 400
    assert (await change(Request(app, 20, payload("cookies", 50, old + 1)))).status == 409
    after = await db.get_user(22)
    assert int(after["cookies"]) == old
    assert not await db.fetchall("SELECT * FROM transactions WHERE user_id=?", (22,))
