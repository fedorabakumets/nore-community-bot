import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from community_bot.access import miniapp_allowed
from community_bot.cabinet_api import (
    notices,
    notices_update,
    pet_action,
    pet_prepare,
    wallet_confirm,
    wallet_history,
    wallet_prepare,
)
from community_bot.database import Database
from community_bot.event_access import current_event
from community_bot.event_manager import cancel_event, update_metadata
from community_bot.miniapp import overview


class Request(dict):
    def __init__(self, env, body=None, uid=7):
        super().__init__(actor={"id": uid, "first_name": f"Имя {uid}"})
        self.app = {"db": env.db, "settings": env.settings, "bot": None}
        self.body, self.query = body or {}, {}

    async def json(self):
        return self.body


@pytest.fixture
async def env(tmp_path):
    db = Database(tmp_path / "cabinet.sqlite3")
    await db.initialize()
    for uid in (7, 8):
        await db.ensure_user(uid, username=f"user_{uid}", telegram_name=f"Имя {uid}")
        for key, value in {
            "profile_name": f"Имя {uid}",
            "age": 25,
            "hobbies": "Питер",
            "profile_bio": "Люблю Петербург и прогулки",
            "avatar_file_id": "photo",
        }.items():
            await db.update_profile(uid, key, value)
        await db.set_cookies(uid, 500, 7)
    settings = SimpleNamespace(
        is_owner=lambda uid: uid == 7,
        owner_ids={7},
        moderator_ids=set(),
        restricted_reputation_threshold=0,
        timezone="Europe/Moscow",
        community_chat_id=-100123,
    )
    return SimpleNamespace(db=db, settings=settings)


async def wallet_quote(env, action, **extra):
    return json.loads((await wallet_prepare(Request(env, {"action": action, **extra}))).body)


async def pay(env, token, uid=7, **extra):
    return await wallet_confirm(Request(env, {"token": token, **extra}, uid))


async def pet_quote(env, action, **extra):
    return json.loads((await pet_prepare(Request(env, {"action": action, **extra}))).body)


async def do_pet(env, token, uid=7, **extra):
    return await pet_action(Request(env, {"token": token, **extra}, uid))


async def test_staff_access_includes_moderator_and_custom_rank_without_granting_panel_permissions(env):
    assert await miniapp_allowed(env.db, env.settings, 7)
    for role, expected in [("member", False), ("moderator", True), ("admin", True)]:
        await env.db.set_role(8, role)
        assert await miniapp_allowed(env.db, env.settings, 8) is expected
    await env.db.create_staff_role("event_helper", "Ивент", 45, [])
    await env.db.set_role(8, "event_helper")
    assert await miniapp_allowed(env.db, env.settings, 8)
    from community_bot.helpers import has_permission

    assert not await has_permission(env.db, env.settings, 8, "admin.panel")
    await env.db.set_role(8, "member")
    assert not await miniapp_allowed(env.db, env.settings, 8)


async def test_starter_pack_shares_loan_rules_and_is_actor_bound_once_and_repayable_early(env):
    q = await wallet_quote(env, "starter_pack")
    assert q["amount"] == 100 and q["due_amount"] == 130 and q["days"] == 7
    assert (await env.db.get_user(7))["cookies"] == 500
    assert (await pay(env, q["token"], uid=8)).status == 409
    paid = await asyncio.gather(pay(env, q["token"]), pay(env, q["token"]))
    assert sorted(r.status for r in paid) == [200, 409]
    assert (await env.db.get_user(7))["cookies"] == 600
    with pytest.raises(ValueError):
        await wallet_quote(env, "starter_pack")
    q = await wallet_quote(env, "repay")
    assert q["amount"] == 130
    assert (await pay(env, q["token"])).status == 200
    assert (await pay(env, q["token"])).status == 409
    assert (await env.db.get_user(7))["cookies"] == 470
    await env.db.execute("UPDATE cookie_loans SET due_at='2000-01-01T00:00:00+00:00'")
    assert await env.db.collect_due_loans() == []
    assert (await env.db.get_user(7))["cookies"] == 470
    assert await env.db.get_active_loan(7) is None


async def test_native_existing_loan_is_visible_and_cannot_be_duplicated_in_miniapp(env):
    token = await env.db.create_wallet_intent(7, "loan", 100, payload={"interest_percent": 30})
    assert (await env.db.take_cookie_loan(7, intent_id=token))[0]
    payload = json.loads((await overview(Request(env))).body)
    assert payload["wallet"]["active"]["due_amount"] == 130
    assert not payload["wallet"]["available"]
    with pytest.raises(ValueError):
        await wallet_quote(env, "starter_pack")


async def test_transfer_quote_discloses_fee_is_actor_bound_and_uses_shared_ledger_once(env):
    q = await wallet_quote(env, "transfer", recipient="@user_8", amount=100)
    assert q["received"] == 70 and q["percent"] == 30
    assert (await pay(env, q["token"], uid=8)).status == 409
    paid = await asyncio.gather(pay(env, q["token"], amount=1, recipient="@user_7"), pay(env, q["token"]))
    assert sorted(r.status for r in paid) == [200, 409]
    assert (await env.db.get_user(7))["cookies"] == 400
    assert (await env.db.get_user(8))["cookies"] == 570
    rows = await env.db.fetchall("SELECT * FROM transactions WHERE kind='transfer'")
    assert sorted(row["amount"] for row in rows) == [-100, 70]


async def test_transfer_rejects_changed_commission_and_bad_recipients_without_debit(env):
    q = await wallet_quote(env, "transfer", recipient="@user_8", amount=100)
    await env.db.execute("UPDATE users SET reputation=90 WHERE user_id=7")
    assert (await pay(env, q["token"])).status == 409
    assert (await env.db.get_user(7))["cookies"] == 500
    for body in [
        {"recipient": "@user_7", "amount": 10},
        {"recipient": "@missing_user", "amount": 10},
        {"recipient": "@user_8", "amount": True},
        {"recipient": "@user_8", "amount": 0},
    ]:
        with pytest.raises(ValueError):
            await wallet_quote(env, "transfer", **body)


async def test_pet_actions_do_not_spend_cookies_and_same_confirmation_does_not_consume_twice(env):
    assert (await env.db.purchase_pet(7, "fox", "Лиска", 50))[0]
    await env.db.execute("UPDATE pets SET hunger=10,thirst=50,food_units=2,water_units=2 WHERE user_id=7")
    q = await pet_quote(env, "food")
    assert (await do_pet(env, q["token"], uid=8)).status == 409
    results = await asyncio.gather(do_pet(env, q["token"]), do_pet(env, q["token"]))
    assert sorted(r.status for r in results) == [200, 409]
    pet = await env.db.get_pet(7, settle=False)
    assert pet["hunger"] == 30 and pet["food_units"] == 1
    assert (await env.db.get_user(7))["cookies"] == 450
    q = await pet_quote(env, "rename", name="Рыжик")
    assert (await do_pet(env, q["token"], name="Подмена")).status == 200
    assert (await env.db.get_pet(7, settle=False))["name"] == "Рыжик"


async def test_pet_expedition_and_return_reward_are_once_and_overview_balance_is_fresh(env):
    await env.db.purchase_pet(7, "cat", "Кот", 50)
    q = await pet_quote(env, "expedition")
    assert (await do_pet(env, q["token"])).status == 200
    assert (await do_pet(env, q["token"])).status == 409
    next_q = await pet_quote(env, "expedition")
    assert (await do_pet(env, next_q["token"])).status == 409
    await env.db.execute(
        "UPDATE pets SET expedition_until=?,expedition_loot=? WHERE user_id=7",
        ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(), json.dumps({"kind": "cookies", "amount": 4})),
    )
    first = json.loads((await overview(Request(env))).body)
    second = json.loads((await overview(Request(env))).body)
    assert first["user"]["cookies"] == second["user"]["cookies"] == 454
    assert first["pet"]["expedition_until"] is None
    assert "4" in first["pet"]["last_find"]
    assert (await env.db.get_user(8))["cookies"] == 500


async def test_disabled_pet_feature_blocks_pending_actions_and_full_stat_does_not_waste_supplies(env):
    await env.db.purchase_pet(7, "cat", "Кот", 50)
    await env.db.execute("UPDATE pets SET hunger=100,food_units=2 WHERE user_id=7")
    q = await pet_quote(env, "food")
    assert (await do_pet(env, q["token"])).status == 409
    assert (await env.db.get_pet(7, settle=False))["food_units"] == 2
    await env.db.execute("UPDATE feature_flags SET enabled=0 WHERE key='tamagotchi'")
    assert (await do_pet(env, q["token"])).status == 409
    with pytest.raises(ValueError):
        await pet_quote(env, "expedition")


async def test_notices_are_own_and_read_snapshot_does_not_swallow_new_notifications(env):
    old = await env.db.notify_inbox_add(7, "pet", "<b>Находка</b>")
    other = await env.db.notify_inbox_add(8, "pet", "Чужое сообщение")
    payload = json.loads((await notices(Request(env))).body)
    assert len(payload["items"]) == 1 and payload["items"][0]["text"] == "Находка"
    newer = await env.db.notify_inbox_add(7, "pet", "Новое")
    assert (await notices_update(Request(env, {"action": "read", "through_id": old}))).status == 200
    assert await env.db.notify_unread_count(7) == 1
    assert (await env.db.fetchone("SELECT read FROM notify_inbox WHERE id=?", (other,)))["read"] == 0
    assert (await env.db.fetchone("SELECT read FROM notify_inbox WHERE id=?", (newer,)))["read"] == 0
    for _ in range(2):
        assert (await notices_update(Request(env, {"channel": "pet", "enabled": True, "digest": True}))).status == 200
    assert (await env.db.notify_prefs_map(7))["pet"] == {"enabled": 1, "digest": 1}
    assert not await env.db.notify_channel_on(8, "pet")


async def test_wallet_history_paginates_own_ledger(env):
    for i in range(45):
        await env.db.add_cookies(7, 1, "test", str(i))
        await env.db.add_cookies(8, 99, "test", "ЧУЖОЕ")
    first = json.loads((await wallet_history(Request(env))).body)
    request = Request(env)
    request.query = {"offset": "20"}
    second = json.loads((await wallet_history(request)).body)
    assert len(first["items"]) == len(second["items"]) == 20
    assert first["has_more"] and second["has_more"]
    assert {i["id"] for i in first["items"]}.isdisjoint(i["id"] for i in second["items"])
    assert all(i["amount"] == 1 for i in first["items"] + second["items"])


async def test_event_cancellation_is_atomic_preserves_history_and_blocks_stale_buttons(env):
    await env.db.save_studio_event("e1", -100123, 55, "Встреча", [], 10, 7)
    await env.db.set_bot_state("current_studio_event", "e1")
    await env.db.save_event_offer("e1", -100123, 55, "Оплатить", 30, 7)
    assert (await env.db.add_rsvp("e1", 7, 10, kind="rsvp"))[0]
    assert (await env.db.pay_event_offer("e1", 8, 30))[0]
    results = await asyncio.gather(cancel_event(env.db, "e1", 0), cancel_event(env.db, "e1", 0))
    assert sorted(results) == [(False, 0), (True, 40)]
    assert (await env.db.get_user(7))["cookies"] == (await env.db.get_user(8))["cookies"] == 500
    assert await current_event(env.db) is None
    assert (await env.db.get_studio_event("e1"))["status"] == "cancelled"
    assert await env.db.get_event_offer("e1")
    assert len(await env.db.list_rsvps("e1")) == 2
    assert not (await env.db.pay_event_offer("e1", 7, 30))[0]
    assert not (await env.db.add_rsvp("e1", 7, 10, kind="rsvp"))[0]
    assert not (await env.db.cancel_event_rsvp("e1", 7))[0]
    assert (await env.db.get_user(7))["cookies"] == 500


async def test_event_metadata_updates_are_versioned_and_legacy_funds_are_not_guessed(env):
    await env.db.save_studio_event("e1", -100123, 55, "Встреча", [], 0, 7)
    assert await update_metadata(env.db, "e1", "title", "Новое название", 0)
    assert not await update_metadata(env.db, "e1", "description", "Старый экран", 0)
    assert await update_metadata(env.db, "e1", "description", "Новое описание", 1)
    assert await update_metadata(env.db, "e1", "starts_at", "2026-10-27T17:00:00+00:00", 2)
    assert (await env.db.get_studio_event("e1"))["revision"] == 3
    await env.db.add_rsvp("e1", 8, 10, kind="legacy")
    assert await cancel_event(env.db, "e1", 3) == (True, 0)
    assert (await env.db.get_user(8))["cookies"] == 490
    assert await env.db.get_event_rsvp("e1", 8)


async def test_event_schema_migration_preserves_old_rows_and_never_reactivates_cancelled_events(tmp_path):
    db = Database(tmp_path / "old.sqlite3")
    async with db.connect() as connection:
        await connection.execute(
            "CREATE TABLE studio_events(event_id TEXT PRIMARY KEY,chat_id INTEGER NOT NULL,"
            'message_id INTEGER NOT NULL,title TEXT NOT NULL,buttons_json TEXT NOT NULL DEFAULT "[]",'
            "rsvp_enabled INTEGER NOT NULL DEFAULT 1,stake INTEGER NOT NULL DEFAULT 0,"
            "created_by INTEGER NOT NULL,created_at TEXT NOT NULL,markup_dirty INTEGER DEFAULT 0,"
            "UNIQUE(chat_id,message_id))"
        )
        await connection.execute(
            "INSERT INTO studio_events(event_id,chat_id,message_id,title,created_by,created_at) "
            'VALUES("old",-100123,10,"Старая встреча",7,"2026-01-01")'
        )
        await connection.commit()
    await db.initialize()
    row = await db.get_studio_event("old")
    assert row["title"] == "Старая встреча" and row["status"] == "active" and row["revision"] == 0
    assert await cancel_event(db, "old", 0) == (True, 0)
    await db.initialize()
    assert (await db.get_studio_event("old"))["status"] == "cancelled"


async def test_event_ledger_reader_cannot_edit_or_cancel_without_post_permission(env):
    from unittest.mock import AsyncMock

    from aiogram.types import User

    from community_bot.event_manager import handle
    from community_bot.permissions import PERM_ADMIN_PANEL, PERM_EVENT_PARTICIPANTS

    await env.db.create_staff_role("event_reader", "Просмотр событий", 45, [PERM_ADMIN_PANEL, PERM_EVENT_PARTICIPANTS])
    await env.db.set_role(8, "event_reader")
    await env.db.save_studio_event("e1", -100123, 55, "Встреча", [], 0, 7)
    callback = SimpleNamespace(
        from_user=User(id=8, is_bot=False, first_name="Читатель"),
        message=SimpleNamespace(answer=AsyncMock()),
        answer=AsyncMock(),
        data="admin:event:cancel:e1:0",
    )
    await handle(callback, SimpleNamespace(), env.db, env.settings, None)
    assert "право" in callback.answer.call_args.args[0]
    assert (await env.db.get_studio_event("e1"))["status"] == "active"
