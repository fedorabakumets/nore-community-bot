"""Stage 9: staff chat moderation is permission bound, logged and idempotent."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramServerError
from aiogram.methods import RestrictChatMember

from community_bot.database import Database
from community_bot.staff_chat_moderation import capabilities, action, audit

GROUP = -100123456789
OP = "26b12345-aaaa-4bbb-8ccc-123456789abc"


class Request(dict):
    def __init__(self, app, uid, data=None, message_id="500"):
        super().__init__(actor={"id": uid})
        self.app = app
        self.query = {"message_id": str(message_id)}
        self.content_length = 350
        self.payload = data

    async def json(self):
        return self.payload


def payload(action_name, reason="Нарушение правил", duration="", operation_id=OP,
            message_id=500):
    return {
        "message_id": message_id, "action": action_name, "reason": reason,
        "duration": duration, "operation_id": operation_id, "confirmed": True,
    }


def parse(response):
    return json.loads(response.text)


async def environment(tmp_path):
    db = Database(tmp_path / "moderation.db")
    await db.initialize()
    for uid, role in [(8, "member"), (9, "member"), (20, "admin"),
                      (21, "moderator"), (22, "member"), (30, "admin")]:
        await db.ensure_user(uid, telegram_name=f"Тест {uid}")
        if role != "member":
            await db.set_role(uid, role)
    settings = SimpleNamespace(
        community_chat_id=GROUP,
        moderator_ids=frozenset(),
        is_owner=lambda uid: uid == 22,
    )
    bot = SimpleNamespace(
        get_chat_member=AsyncMock(return_value=SimpleNamespace(status=ChatMemberStatus.MEMBER)),
        delete_message=AsyncMock(return_value=True),
        restrict_chat_member=AsyncMock(return_value=True),
        ban_chat_member=AsyncMock(return_value=True),
        unban_chat_member=AsyncMock(return_value=True),
    )
    app = {"db": db, "settings": settings, "bot": bot}
    for mid, user_id in [(500, 8), (501, 9), (502, 20), (503, 21),
                         (504, 22), (505, 0)]:
        await db.execute(
            """INSERT INTO staff_chat_messages
               (chat_id,message_id,user_id,author_name,sent_at)
               VALUES(?,?,?,?,?)""",
            (GROUP, mid, user_id, f"Тест {user_id}", datetime.now(UTC).isoformat()),
        )
    return db, settings, bot, app


@pytest.mark.asyncio
async def test_moderator_actions_follow_actual_role_permissions_and_ranks(tmp_path):
    db, _, _, app = await environment(tmp_path)
    response = await capabilities(Request(app, 21))
    assert response.status == 200
    allowed = {item["id"] for item in parse(response)["actions"]}
    assert {"mute", "unmute", "warn", "unwarn", "kick"} <= allowed
    assert "ban" not in allowed
    assert "unban" not in allowed
    assert "delete" not in allowed
    assert parse(response)["warnings"] == (await db.get_user(8))["warnings"]

    admin = parse(await capabilities(Request(app, 20)))
    assert {"ban", "unban", "delete"} <= {item["id"] for item in admin["actions"]}
    protected = parse(await capabilities(Request(app, 21, message_id="502")))
    assert protected["actions"] == []
    self_target = parse(await capabilities(Request(app, 21, message_id="503")))
    assert self_target["actions"] == []
    missing = await capabilities(Request(app, 20, message_id="900"))
    assert missing.status == 404


@pytest.mark.asyncio
async def test_nonstaff_or_forged_actions_are_rejected(tmp_path):
    db, _, bot, app = await environment(tmp_path)
    assert (await capabilities(Request(app, 8))).status == 403
    assert (await action(Request(app, 8, payload("warn")))).status == 403
    assert (await action(Request(app, 21, payload("ban", duration="7d")))).status == 403
    assert (await action(Request(app, 21, payload("delete")))).status == 403
    assert (await action(Request(app, 20, payload("mute", duration="2y")))).status == 400
    assert (await action(Request(app, 20, payload("warn", reason="x")))).status == 400
    unconfirmed = payload("warn")
    unconfirmed["confirmed"] = False
    assert (await action(Request(app, 20, unconfirmed))).status == 400
    forged = payload("warn")
    forged["target_id"] = 9
    assert (await action(Request(app, 20, forged))).status == 400
    assert (await action(Request(app, 20, payload("warn", message_id=900)))).status == 404
    assert (await action(Request(app, 21, payload("warn", message_id=502)))).status == 403
    assert (await action(Request(app, 21, payload("warn", message_id=503)))).status == 403
    bot.restrict_chat_member.assert_not_awaited()
    assert await db.fetchone("SELECT * FROM staff_chat_dispatches") is None


@pytest.mark.asyncio
async def test_warning_updates_counter_audit_and_duplicate_is_ignored(tmp_path):
    db, _, bot, app = await environment(tmp_path)
    baseline = (await db.get_user(8))["warnings"]
    first = await action(Request(app, 21, payload("warn")))
    assert first.status == 200
    assert parse(first)["state"] == "sent"
    assert (await db.get_user(8))["warnings"] == baseline + 1
    replay = await action(Request(app, 21, payload("warn")))
    assert replay.status == 200
    assert (await db.get_user(8))["warnings"] == baseline + 1
    clash = await action(Request(app, 21, payload("warn", reason="Другая причина")))
    assert clash.status == 409
    logs = await db.fetchall("SELECT * FROM admin_audit_log WHERE action='warn' AND actor_id=21")
    assert len(logs) == 1
    assert logs[0]["actor_id"] == 21 and logs[0]["target"] == "8"
    assert logs[0]["reason"] == "Нарушение правил"
    assert "Mini App NORA" in logs[0]["details"]
    assert bot.get_chat_member.await_count >= 1
    # Unwarn is a distinct operation with a distinct ID.
    undo = await action(Request(app, 21, payload(
        "unwarn", operation_id="36b12345-aaaa-4bbb-8ccc-123456789abc",
    )))
    assert undo.status == 200
    assert (await db.get_user(8))["warnings"] == baseline


@pytest.mark.asyncio
async def test_mute_and_unmute_use_telegram_and_are_logged(tmp_path):
    db, _, bot, app = await environment(tmp_path)
    first = await action(Request(app, 21, payload("mute", duration="1h")))
    assert first.status == 200, first.text
    assert bot.restrict_chat_member.await_count == 1
    invocation = bot.restrict_chat_member.await_args
    call = invocation.kwargs
    assert invocation.args[:2] == (GROUP, 8)
    assert call["until_date"] > datetime.now(UTC)
    assert call["permissions"].can_send_messages is False
    assert (await action(Request(app, 21, payload("mute", duration="1h")))).status == 200
    assert bot.restrict_chat_member.await_count == 1
    unmute = await action(Request(app, 21, payload(
        "unmute", operation_id="36b12345-aaaa-4bbb-8ccc-123456789abc",
    )))
    assert unmute.status == 200
    assert bot.restrict_chat_member.await_count == 2
    assert "until_date" not in bot.restrict_chat_member.await_args.kwargs
    logs = await db.fetchall("SELECT action FROM admin_audit_log WHERE actor_id=21 ORDER BY id")
    assert [item["action"] for item in logs] == ["mute", "unmute"]


@pytest.mark.asyncio
async def test_delete_is_telegram_delete_not_just_hide(tmp_path):
    db, _, bot, app = await environment(tmp_path)
    assert (await action(Request(app, 20, payload("delete")))).status == 200
    bot.delete_message.assert_awaited_once_with(GROUP, 500)
    assert await db.fetchone(
        "SELECT * FROM staff_chat_messages WHERE chat_id=? AND message_id=?",
        (GROUP, 500),
    ) is None
    log = await db.fetchone("SELECT action,reason FROM admin_audit_log WHERE action='delete_message' ORDER BY id DESC LIMIT 1")
    assert log["action"] == "delete_message"
    # No repeated Telegram deletion if the source was removed.
    assert (await action(Request(app, 20, payload("delete")))).status == 404
    assert bot.delete_message.await_count == 1


@pytest.mark.asyncio
async def test_telegram_admin_is_protected_even_when_database_role_is_member(tmp_path):
    _, _, bot, app = await environment(tmp_path)
    bot.get_chat_member.return_value = SimpleNamespace(status=ChatMemberStatus.ADMINISTRATOR)
    forbidden = await action(Request(app, 20, payload("mute", duration="1h")))
    assert forbidden.status == 403
    bot.restrict_chat_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_error_is_ambiguous_and_does_not_repeat_punishment(tmp_path):
    db, _, bot, app = await environment(tmp_path)
    bot.restrict_chat_member.side_effect = TelegramServerError(
        method=RestrictChatMember(chat_id=GROUP, user_id=8,
                                  permissions={"can_send_messages": False}),
        message="Bad Gateway",
    )
    failure = await action(Request(app, 21, payload("mute", duration="1h")))
    assert failure.status == 502
    row = await db.fetchone(
        "SELECT status FROM staff_chat_dispatches WHERE user_id=? AND operation_id=?",
        (21, OP),
    )
    assert row["status"] == "uncertain"
    again = await action(Request(app, 21, payload("mute", duration="1h")))
    assert again.status == 200
    assert parse(again)["state"] == "uncertain"
    assert bot.restrict_chat_member.await_count == 1


@pytest.mark.asyncio
async def test_mod_journal_shows_only_own_events_admin_sees_all(tmp_path):
    db, _, _, app = await environment(tmp_path)
    await db.log_admin_action(21, "warn", "8", "Mini App NORA", reason="Причина модератора")
    await db.log_admin_action(20, "ban", "9", "Mini App NORA", reason="Причина администратора")
    moderator = parse(await audit(Request(app, 21)))
    assert moderator["scope"] == "own"
    assert len(moderator["items"]) == 1
    assert moderator["items"][0]["reason"] == "Причина модератора"
    administrator = parse(await audit(Request(app, 20)))
    assert administrator["scope"] == "all"
    reasons={item["reason"] for item in administrator["items"]}
    assert {"Причина модератора", "Причина администратора"} <= reasons
    assert (await audit(Request(app, 8))).status == 403


@pytest.mark.asyncio
async def test_owner_only_overrides_explicit_permissions_and_rank(tmp_path):
    _, _, bot, app = await environment(tmp_path)
    # Owner can act against a higher-ranked internal admin, but not a real
    # Telegram administrator. Test only the available capabilities here.
    owner = parse(await capabilities(Request(app, 22, message_id="502")))
    assert "ban" in {entry["id"] for entry in owner["actions"]}
    assert parse(await capabilities(Request(app, 20, message_id="504")))["actions"] == []
    bot.delete_message.assert_not_awaited()



def test_stage9_routes_are_exposed_without_adding_an_unserved_script():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "community_bot" / "miniapp.py").read_text(
        encoding="utf-8"
    )
    for route in (
        "app.router.add_get('/api/community/chat/moderation', staff_chat_moderation.capabilities)",
        "app.router.add_post('/api/community/chat/moderation', staff_chat_moderation.action)",
        "app.router.add_get('/api/community/chat/moderation/logs', staff_chat_moderation.audit)",
    ):
        assert route in source
    from community_bot.miniapp import ROOT
    assert (ROOT / "staff-chat.js").is_file()
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "/staff-chat.js?v=stage9-mod-20261122" in html
