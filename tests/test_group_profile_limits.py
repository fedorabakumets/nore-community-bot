"""Live group profile limits and inline shop purchase flow."""
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from aiogram.types import Chat, Message, User

from community_bot.database import Database
from community_bot.profile_limits import profile_limits
from community_bot.routers import profile


@pytest.fixture
async def env(tmp_path):
    db = Database(tmp_path / "profile_limits.db")
    await db.initialize()
    await db.ensure_user(2, telegram_name="Владелец профиля")
    await db.ensure_user(3, telegram_name="Друг")
    await db.execute("UPDATE users SET reputation=95 WHERE user_id=2")
    await db.set_cookies(2, 100, 2)
    await db.upsert_shop_item("reset_limits", price=15, enabled=1)
    settings = SimpleNamespace(restricted_reputation_threshold=0, timezone="Europe/Moscow",
                               community_chat_id=-100123)
    return SimpleNamespace(db=db, settings=settings)


def _message(bot=None):
    return Message(message_id=15, date=1725000000,
                   chat=Chat(id=-100123, type="supergroup")).as_(
                       bot or SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(username="nora_bot")))
                   )


def _callback(message, data, uid=2):
    return SimpleNamespace(
        data=data, message=message,
        from_user=User(id=uid, is_bot=False, first_name="Участник"),
        answer=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_real_allowances_use_same_counters_as_commands(env):
    from community_bot.pet_progress import moscow_now

    db = env.db
    today = moscow_now().date().isoformat()
    await db.set_bot_state("nora_ai_daily:2", json.dumps({"day": today, "used": 7}))
    await db.set_bot_state(f"song:daily:2:{today}", "1")
    for idx in range(2):
        await db.execute(
            "INSERT INTO pet_video_deliveries(chat_id,message_id,user_id,day) VALUES (?,?,?,?)",
            (-100123, idx + 100, 2, today),
        )
    for idx in range(3):
        await db.execute(
            "INSERT INTO reputation_actions(actor_id,target_id,delta,action_date,created_at)"
            " VALUES (?,?,?,?,?)",
            (2, 3, 5, today, f"{today}T12:00:0{idx}+03:00"),
        )
    values = await profile_limits(db, env.settings, await db.get_user(2))
    assert values == [
        ("🐩", "93/100"),
        ("📹", "3/5"),
        ("🎧", "4/5"),
        ("⚖️", "2/5"),
    ]
    # Yesterday's AI requests do not reduce today's displayed allowance.
    await db.set_bot_state("nora_ai_daily:2", json.dumps({"day": "2020-01-01", "used": 100}))
    assert (await profile_limits(db, env.settings, await db.get_user(2)))[0] == ("🐩", "100/100")


@pytest.mark.asyncio
async def test_restore_confirmation_uses_in_place_edit_and_one_time_shop_intent(env, monkeypatch):
    bot = SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(username="nora_bot")))
    message = _message(bot)
    edit = AsyncMock()
    monkeypatch.setattr(Message, "edit_text", edit)
    restored = AsyncMock(return_value=True)
    monkeypatch.setattr(profile, "restore_group_profile_card", restored)

    from community_bot import life, notify
    monkeypatch.setattr(life, "unlock", AsyncMock())
    monkeypatch.setattr(notify, "vitrine_consumed", AsyncMock())

    uid = 2
    day = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    await env.db.set_bot_state(f"nora_ai_daily:{uid}", json.dumps({"day": day, "used": 9}))
    await env.db.set_bot_state(f"song:daily:{uid}:{day}", "5")
    await env.db.set_bot_state(f"song:last_user:{uid}", "5000")
    await env.db.set_bot_state("song:last_chat:-100123", "5000")

    ask = _callback(message, "gprofile:limits:restore:2")
    await profile.group_profile_limits(ask, env.db, env.settings)
    edit.assert_awaited_once()
    rich = edit.await_args.kwargs["rich_message"]
    pay = rich.blocks[-2].buttons[0]
    back = rich.blocks[-1].buttons[0]
    assert pay.text.startswith("Подтвердить ·")
    assert pay.callback_data.startswith("gprofile:limits:pay:2:")
    assert back.text == "←" and back.callback_data.startswith("gprofile:limits:back:2:")
    assert (await env.db.get_user(uid))["cookies"] == 100

    purchased = _callback(message, pay.callback_data)
    await profile.group_profile_limits(purchased, env.db, env.settings)
    assert await env.db.get_bot_state(f"song:daily:{uid}:{day}") is None
    assert await env.db.get_bot_state(f"nora_ai_daily:{uid}") is None
    assert await env.db.get_bot_state(f"song:last_user:{uid}") == "5000"
    assert await env.db.get_bot_state("song:last_chat:-100123") == "5000"
    assert (await env.db.get_user(uid))["cookies"] < 100
    restored.assert_awaited_once()

    balance_after = (await env.db.get_user(uid))["cookies"]
    await profile.group_profile_limits(purchased, env.db, env.settings)
    assert (await env.db.get_user(uid))["cookies"] == balance_after
    assert purchased.answer.await_args.kwargs["show_alert"] is True


@pytest.mark.asyncio
async def test_back_cancels_intent_without_charge(env, monkeypatch):
    message = _message()
    monkeypatch.setattr(Message, "edit_text", AsyncMock())
    restored = AsyncMock(return_value=True)
    monkeypatch.setattr(profile, "restore_group_profile_card", restored)
    await profile.group_profile_limits(_callback(message, "gprofile:limits:restore:2"), env.db, env.settings)
    rich = Message.edit_text.await_args.kwargs["rich_message"]
    back = rich.blocks[-1].buttons[0].callback_data
    token = back.rsplit(":", 1)[1]
    assert await env.db.get_wallet_intent(2, token)
    await profile.group_profile_limits(_callback(message, back), env.db, env.settings)
    assert await env.db.get_wallet_intent(2, token) is None
    assert (await env.db.get_user(2))["cookies"] == 100
    restored.assert_awaited_once()


@pytest.mark.asyncio
async def test_another_user_cannot_buy_from_shared_profile(env, monkeypatch):
    message = _message()
    monkeypatch.setattr(Message, "edit_text", AsyncMock())
    blocked = _callback(message, "gprofile:limits:restore:2", uid=3)
    await profile.group_profile_limits(blocked, env.db, env.settings)
    blocked.answer.assert_awaited_once()
    assert blocked.answer.await_args.kwargs["show_alert"] is True
    Message.edit_text.assert_not_awaited()
    assert (await env.db.get_user(3))["cookies"] == 0


@pytest.mark.asyncio
async def test_any_member_can_gift_reset_to_profile_owner_but_not_themselves(env, monkeypatch):
    from community_bot import life, notify
    from community_bot.pet_progress import moscow_now
    from community_bot.shop_catalog import gift_price

    message = _message()
    edit = AsyncMock()
    monkeypatch.setattr(Message, "edit_text", edit)
    restored = AsyncMock(return_value=True)
    monkeypatch.setattr(profile, "restore_group_profile_card", restored)
    monkeypatch.setattr(life, "unlock", AsyncMock())
    monkeypatch.setattr(notify, "vitrine_consumed", AsyncMock())

    day = moscow_now().date().isoformat()
    await env.db.set_cookies(3, 100, 2)
    for uid in (2, 3):
        await env.db.set_bot_state(f"song:daily:{uid}:{day}", "5")
        for idx in range(5):
            await env.db.execute(
                "INSERT INTO pet_video_deliveries(chat_id,message_id,user_id,day) VALUES (?,?,?,?)",
                (-100123, uid * 100 + idx, uid, day),
            )
    await env.db.set_bot_state("nora_ai_daily:2", json.dumps({"day": day, "used": 5}))
    await env.db.set_bot_state("song:last_user:2", "9000")

    own_gift = _callback(message, "gprofile:limits:gift:2", uid=2)
    await profile.group_profile_limits(own_gift, env.db, env.settings)
    assert "Себе подарок" in own_gift.answer.await_args.args[0]
    edit.assert_not_awaited()

    ask = _callback(message, "gprofile:limits:gift:2", uid=3)
    await profile.group_profile_limits(ask, env.db, env.settings)
    rich = edit.await_args.kwargs["rich_message"]
    assert "Подарить" in rich.blocks[0].text[0].text
    assert "Владелец профиля" in rich.blocks[1].text
    assert f"Цена: {gift_price(15)} 🍪" in rich.blocks[1].text
    pay = rich.blocks[-2].buttons[0].callback_data
    back = rich.blocks[-1].buttons[0].callback_data
    assert pay.startswith("gprofile:limits:pay:2:")
    assert back.startswith("gprofile:limits:back:2:")
    assert (await env.db.get_user(3))["cookies"] == 100

    unauthorized = _callback(message, pay, uid=2)
    await profile.group_profile_limits(unauthorized, env.db, env.settings)
    assert unauthorized.answer.await_args.kwargs["show_alert"] is True
    blocked_back = _callback(message, back, uid=2)
    await profile.group_profile_limits(blocked_back, env.db, env.settings)
    assert blocked_back.answer.await_args.kwargs["show_alert"] is True

    await profile.group_profile_limits(_callback(message, pay, uid=3), env.db, env.settings)
    assert (await env.db.get_user(3))["cookies"] == 100 - gift_price(15)
    assert (await env.db.get_user(2))["cookies"] == 100
    assert await env.db.get_bot_state("nora_ai_daily:2") is None
    assert await env.db.get_bot_state(f"song:daily:2:{day}") is None
    assert await env.db.get_bot_state("song:last_user:2") == "9000"
    assert await env.db.get_bot_state(f"song:daily:3:{day}") == "5"
    assert (await env.db.fetchone(
        "SELECT COUNT(*) AS n FROM pet_video_deliveries WHERE user_id=2 AND day=?", (day,),
    ))["n"] == 0
    assert (await env.db.fetchone(
        "SELECT COUNT(*) AS n FROM pet_video_deliveries WHERE user_id=3 AND day=?", (day,),
    ))["n"] == 5
    tx = await env.db.fetchone(
        "SELECT amount, details FROM transactions WHERE user_id=3 AND kind='shop'",
    )
    assert tx == {"amount": -gift_price(15), "details": "reset_limits->2"}
    restored.assert_awaited_once()
    await profile.group_profile_limits(_callback(message, pay, uid=3), env.db, env.settings)
    assert (await env.db.get_user(3))["cookies"] == 100 - gift_price(15)


@pytest.mark.asyncio
async def test_gift_back_is_only_for_buyer_and_cancels_without_charge(env, monkeypatch):
    message = _message()
    monkeypatch.setattr(Message, "edit_text", AsyncMock())
    monkeypatch.setattr(profile, "restore_group_profile_card", AsyncMock(return_value=True))
    await env.db.set_cookies(3, 100, 2)
    await profile.group_profile_limits(_callback(message, "gprofile:limits:gift:2", uid=3),
                                       env.db, env.settings)
    back = Message.edit_text.await_args.kwargs["rich_message"].blocks[-1].buttons[0].callback_data
    token = back.rsplit(":", 1)[1]
    assert await env.db.get_wallet_intent(3, token)
    await profile.group_profile_limits(_callback(message, back, uid=2), env.db, env.settings)
    assert await env.db.get_wallet_intent(3, token)
    await profile.group_profile_limits(_callback(message, back, uid=3), env.db, env.settings)
    assert await env.db.get_wallet_intent(3, token) is None
    assert (await env.db.get_user(3))["cookies"] == 100


@pytest.mark.asyncio
async def test_gift_price_change_rejects_stale_confirmation(env, monkeypatch):
    message = _message()
    monkeypatch.setattr(Message, "edit_text", AsyncMock())
    await env.db.set_cookies(3, 100, 2)
    await profile.group_profile_limits(_callback(message, "gprofile:limits:gift:2", uid=3),
                                       env.db, env.settings)
    pay = Message.edit_text.await_args.kwargs["rich_message"].blocks[-2].buttons[0].callback_data
    await env.db.upsert_shop_item("reset_limits", price=50, enabled=1)
    stale = _callback(message, pay, uid=3)
    await profile.group_profile_limits(stale, env.db, env.settings)
    assert stale.answer.await_args.kwargs["show_alert"] is True
    assert (await env.db.get_user(3))["cookies"] == 100


@pytest.mark.asyncio
async def test_non_owner_and_new_member_can_open_gift_from_shared_card(env, monkeypatch):
    from community_bot.ui_owner import is_owned_callback

    assert not is_owned_callback("gprofile:limits:gift:2")
    message = _message()
    edit = AsyncMock()
    monkeypatch.setattr(Message, "edit_text", edit)
    assert await env.db.get_user(4) is None
    await profile.group_profile_limits(
        _callback(message, "gprofile:limits:gift:2", uid=4), env.db, env.settings,
    )
    assert await env.db.get_user(4) is not None
    assert edit.await_count == 1
    rich = edit.await_args.kwargs["rich_message"]
    assert "Твой баланс: 0 🍪" in rich.blocks[1].text
