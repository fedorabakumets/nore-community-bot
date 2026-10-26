import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import User

from community_bot.database import Database
from community_bot.routers import flows, group, life, pets, private, wallet


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "economy.db")
    await database.initialize()
    await database.ensure_user(7, telegram_name="Анна")
    await database.add_cookies(7, 150, "test")
    return database


async def test_inline_wallet_uses_person_who_clicked_not_message_author(db, monkeypatch):
    person = User(id=7, is_bot=False, first_name="Анна")
    bot_user = User(id=900, is_bot=True, first_name="Нора")
    message = SimpleNamespace(from_user=bot_user, chat=SimpleNamespace(type="private", id=7))
    callback = SimpleNamespace(from_user=person, message=message, answer=AsyncMock())
    sent = AsyncMock()
    monkeypatch.setattr(wallet, "replace_block", sent, raising=False)
    monkeypatch.setattr(wallet, "answer_block", sent)
    settings = SimpleNamespace(restricted_reputation_threshold=0, timezone="Europe/Moscow")

    await private.menu_wallet(callback, db, settings)

    assert await db.get_user(900) is None
    assert "150" in sent.call_args.args[2]


async def test_wallet_does_not_cut_large_balances_or_use_a_wide_table(db):
    user = dict(await db.get_user(7), cookies=123456789012345678)
    settings = SimpleNamespace(restricted_reputation_threshold=0, timezone="Europe/Moscow")
    text = await wallet.wallet_text(db, settings, user)
    assert "123456789012345678" in text
    assert "<pre>" not in text


async def test_purchase_confirmation_only_charges_once_even_with_concurrent_connections(db):
    token = await db.create_wallet_intent(7, "rep_shield", 12)
    second_connection = Database(db.path)
    results = await asyncio.gather(
        db.buy_item(7, "rep_shield", 12, intent_id=token),
        second_connection.buy_item(7, "rep_shield", 12, intent_id=token),
    )
    assert sum(ok for ok, _ in results) == 1
    user = await db.get_user(7)
    assert (user["cookies"], user["hate_shields"]) == (138, 1)
    assert len([row for row in await db.list_transactions(7) if row["kind"] == "shop"]) == 1


async def test_debt_can_be_paid_explicitly_once_and_is_recorded(db):
    await db.execute("UPDATE users SET cookie_debt = 90 WHERE user_id = 7")
    token = await db.create_wallet_intent(7, "debt_repay", 90)
    assert (await db.repay_cookie_debt(7, 90, intent_id=token))[0]
    assert not (await db.repay_cookie_debt(7, 90, intent_id=token))[0]
    user = await db.get_user(7)
    assert (user["cookies"], user["cookie_debt"]) == (60, 0)
    assert (await db.list_transactions(7))[0]["kind"] == "debt_repay"


def callback_for(data, person_id=7):
    return SimpleNamespace(
        data=data,
        from_user=User(id=person_id, is_bot=False, first_name="Анна"),
        message=SimpleNamespace(
            from_user=User(id=900, is_bot=True, first_name="Нора"),
            chat=SimpleNamespace(id=person_id, type="private"),
            message_id=10,
            date=datetime.now(UTC),
            answer=AsyncMock(),
        ),
        answer=AsyncMock(),
    )


class Flow:
    def __init__(self, **data):
        self.data = data

    async def get_data(self):
        return dict(self.data)

    async def set_data(self, data):
        self.data = data

    async def set_state(self, state):
        self.state = state

    async def clear(self):
        self.data = {}


def settings():
    return SimpleNamespace(
        restricted_reputation_threshold=0, timezone="Europe/Moscow", community_chat_id=0, owner_ids=[], reviewers=[],
    )


async def test_return_to_cabinet_preserves_actor_permissions_balance_and_badge(db, monkeypatch):
    import community_bot.blocks as blocks

    check_permission = AsyncMock(return_value=True)
    monkeypatch.setattr(flows, "has_permission", check_permission)
    unread = AsyncMock(return_value=3)
    monkeypatch.setattr(db, "notify_unread_count", unread)
    edited = AsyncMock()
    monkeypatch.setattr(blocks, "replace_block", edited)
    await flows.menu_home(callback_for("menu:home"), db, settings())
    assert "150" in edited.call_args.args[2]
    assert "Анна" in edited.call_args.args[2]
    buttons = [b.callback_data for row in edited.call_args.kwargs["reply_markup"].inline_keyboard for b in row]
    assert "menu:admin" in buttons
    assert {"menu:shop", "menu:wallet", "menu:question"} <= set(buttons)
    unread.assert_awaited_once_with(7)
    assert check_permission.call_args.args[2] == 7
    assert await db.get_user(900) is None


async def test_support_button_opens_ticket_for_person_not_bot(db, monkeypatch):
    monkeypatch.setattr(private, "answer_block", AsyncMock())
    state = Flow()
    await private.menu_question(callback_for("menu:question"), state, db, settings(), SimpleNamespace())
    row = await db.fetchone("SELECT user_id FROM tickets WHERE id = ?", (state.data["ticket_id"],))
    assert row["user_id"] == 7
    assert await db.get_user(900) is None


@pytest.mark.parametrize("wrong", ["person", "item", "price", "target", "expired", "disabled", "changed"])
async def test_confirmation_rejects_changed_or_unapproved_conditions_without_spending(db, wrong):
    await db.ensure_user(8, telegram_name="Борис")
    token = await db.create_wallet_intent(7, "rep_shield", 12)
    actor, item, price, target = 7, "rep_shield", 12, 7
    if wrong == "person":
        actor = 8
    elif wrong == "item":
        item = "private_profile"
    elif wrong == "price":
        price = 13
    elif wrong == "target":
        target = 8
    elif wrong == "expired":
        await db.execute("UPDATE wallet_intents SET expires_at = '2000-01-01' WHERE token = ?", (token,))
    elif wrong == "disabled":
        await db.upsert_shop_item("rep_shield", enabled=0)
    elif wrong == "changed":
        await db.upsert_shop_item("rep_shield", price=20)
    ok, _ = await db.buy_item(actor, item, price, target_id=target, intent_id=token)
    assert not ok
    assert (await db.get_user(7))["cookies"] == 150
    assert len(await db.list_transactions(7)) == 1


async def test_failed_debit_can_be_retried_after_topup_using_same_confirmation(db):
    token = await db.create_wallet_intent(7, "rep_shield", 200)
    assert not (await db.buy_item(7, "rep_shield", 200, intent_id=token))[0]
    assert await db.get_wallet_intent(7, token)
    await db.add_cookies(7, 100, "test")
    assert (await db.buy_item(7, "rep_shield", 200, intent_id=token))[0]
    assert (await db.get_user(7))["cookies"] == 50


async def test_effect_failure_rolls_back_charge_ledger_and_confirmation(db, monkeypatch):
    token = await db.create_wallet_intent(7, "rep_shield", 12)
    apply_effect = db._apply_shop_effect

    async def fail_after_effect(*args):
        await apply_effect(*args)
        raise RuntimeError("simulated storage failure")

    monkeypatch.setattr(db, "_apply_shop_effect", fail_after_effect)
    with pytest.raises(RuntimeError, match="simulated"):
        await db.buy_item(7, "rep_shield", 12, intent_id=token)
    user = await db.get_user(7)
    assert (user["cookies"], user["hate_shields"]) == (150, 0)
    assert await db.get_wallet_intent(7, token)
    assert len(await db.list_transactions(7)) == 1


async def test_restarting_database_does_not_allow_replay(db):
    token = await db.create_wallet_intent(7, "rep_shield", 12)
    assert (await db.buy_item(7, "rep_shield", 12, intent_id=token))[0]
    restarted = Database(db.path)
    assert not (await restarted.buy_item(7, "rep_shield", 12, intent_id=token))[0]
    assert (await restarted.get_user(7))["cookies"] == 138


async def test_catalog_change_during_status_flow_is_not_charged(db):
    token = await db.create_wallet_intent(7, "custom_status", 10)
    await db.upsert_shop_item("custom_status", price=50)
    ok, _ = await db.buy_item(7, "custom_status", 10, intent_id=token, profile_value="Привет")
    assert not ok
    assert (await db.get_user(7))["cookies"] == 150
    assert not (await db.get_user(7))["custom_status"]


async def test_concurrent_status_messages_only_apply_one_paid_value(db):
    token = await db.create_wallet_intent(7, "custom_status", 10)
    values = ["Первый", "Второй"]
    results = await asyncio.gather(*(
        db.buy_item(7, "custom_status", 10, intent_id=token, profile_value=value) for value in values
    ))
    assert sum(ok for ok, _ in results) == 1
    winner = next(value for value, result in zip(values, results, strict=True) if result[0])
    user = await db.get_user(7)
    assert (user["cookies"], user["custom_status"]) == (140, winner)


async def test_gift_requires_confirmation_and_only_delivers_once(db, monkeypatch):
    await db.ensure_user(8, telegram_name="Борис")
    message = SimpleNamespace(answer=AsyncMock())
    await life._confirm_gift(message, db, 7, await db.get_user(8), "rep_shield", 12)
    assert (await db.get_user(7))["cookies"] == 150
    data = message.answer.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data
    token = data.removeprefix("shop:pay:")
    assert (await db.get_wallet_intent(7, token))["target_id"] == 8
    assert (await db.buy_item(7, "rep_shield", 12, target_id=8, intent_id=token))[0]
    assert not (await db.buy_item(7, "rep_shield", 12, target_id=8, intent_id=token))[0]
    assert (await db.get_user(8))["hate_shields"] == 1


async def test_legacy_event_amount_cannot_charge_without_published_event(db, monkeypatch):
    state = Flow(flex_item="event_pass", flex_discount=0)
    message = SimpleNamespace(from_user=User(id=7, is_bot=False, first_name="Анна"), text="30", answer=AsyncMock())
    await group.finish_flexible_purchase(message, state, db, settings(), SimpleNamespace())
    assert (await db.get_user(7))["cookies"] == 150
    data = message.answer.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data
    monkeypatch.setattr(group, "edit_block", AsyncMock())
    import community_bot.notify as notify

    monkeypatch.setattr(notify, "vitrine_consumed", AsyncMock())
    await group.buy_shop_item(callback_for(data), state, db, settings(), SimpleNamespace())
    assert (await db.get_user(7))["cookies"] == 150
    await group.buy_shop_item(callback_for(data), state, db, settings(), SimpleNamespace())
    assert (await db.get_user(7))["cookies"] == 150


async def test_actual_shop_callbacks_with_double_click_only_charge_once(db, monkeypatch):
    await db.upsert_shop_item("rep_shield", price=12)
    edited = AsyncMock()
    monkeypatch.setattr(group, "edit_block", edited)
    import community_bot.notify as notify

    monkeypatch.setattr(notify, "vitrine_consumed", AsyncMock())
    await group.buy_shop_item(callback_for("shop:rep_shield"), Flow(), db, settings(), SimpleNamespace())
    data = edited.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data
    before = await db.get_wallet_intent(7, data.removeprefix("shop:pay:"))
    assert (await db.get_user(7))["cookies"] == 150
    await asyncio.gather(*(
        group.buy_shop_item(callback_for(data), Flow(), db, settings(), SimpleNamespace()) for _ in range(2)
    ))
    user = await db.get_user(7)
    assert (user["cookies"], user["hate_shields"]) == (150 - before["price"], 1)


async def test_legacy_purchase_and_pet_buttons_cannot_charge(db):
    callback = callback_for("shop:ok:rep_shield")
    await group.buy_shop_item(callback, Flow(), db, settings(), SimpleNamespace())
    assert callback.answer.call_args.kwargs["show_alert"]
    callback = callback_for("pet:species:cat:1")
    await pets.choose_species(callback, Flow(), db, settings())
    assert callback.answer.call_args.kwargs["show_alert"]
    assert (await db.get_user(7))["cookies"] == 150
    assert await db.get_pet(7, settle=False) is None


@pytest.mark.parametrize("item", ["restore_rep", "season_pack", "not_configured"])
async def test_purchases_with_no_deliverable_effect_leave_balance_unchanged(db, item):
    token = await db.create_wallet_intent(7, item, 10)
    ok, _ = await db.buy_item(7, item, 10, intent_id=token)
    assert not ok
    assert (await db.get_user(7))["cookies"] == 150
    assert await db.get_wallet_intent(7, token)


async def test_immunity_is_delivered_atomically_and_existing_time_is_not_lost(db):
    old_until = datetime.now(UTC) + timedelta(days=2)
    await db.set_immunity(7, old_until)
    token = await db.create_wallet_intent(7, "immunity_24h", 10)
    assert (await db.buy_item(7, "immunity_24h", 10, intent_id=token))[0]
    user = await db.get_user(7)
    assert datetime.fromisoformat(user["hate_immunity_until"]) == old_until + timedelta(days=1)
    assert user["cookies"] == 140


async def test_missing_pet_supply_error_has_correct_result_shape_and_does_not_charge(db):
    token = await db.create_wallet_intent(7, "pet_meal", 10)
    ok, _, pet = await db.purchase_pet_supply(7, "food", 40, 10, "pet_meal", intent_id=token)
    assert not ok and pet is None
    assert (await db.get_user(7))["cookies"] == 150


async def test_full_pet_is_not_charged_for_food_and_purchase_can_be_retried_later(db):
    assert (await db.purchase_pet(7, "cat", "Булочка", 10))[0]
    await db.execute("UPDATE pets SET hunger = 100 WHERE user_id = 7")
    token = await db.create_wallet_intent(7, "pet_meal", 10)
    assert not (await db.purchase_pet_supply(7, "food", 40, 10, "pet_meal", intent_id=token))[0]
    assert (await db.get_user(7))["cookies"] == 140
    await db.execute("UPDATE pets SET hunger = 20 WHERE user_id = 7")
    assert (await db.purchase_pet_supply(7, "food", 40, 10, "pet_meal", intent_id=token))[0]
    assert not (await db.purchase_pet_supply(7, "food", 40, 10, "pet_meal", intent_id=token))[0]
    assert (await db.get_user(7))["cookies"] == 130


async def test_partial_debt_repayment_preserves_unpaid_remainder(db):
    await db.execute("UPDATE users SET cookie_debt = 200 WHERE user_id = 7")
    token = await db.create_wallet_intent(7, "debt_repay", 150)
    assert (await db.repay_cookie_debt(7, 150, intent_id=token))[0]
    user = await db.get_user(7)
    assert (user["cookies"], user["cookie_debt"]) == (0, 50)


async def test_loan_uses_confirmed_interest_and_cannot_be_reborrowed_with_old_button(db):
    from community_bot.economy import loan_interest_percent

    percent = loan_interest_percent(int((await db.get_user(7))["reputation"]))
    token = await db.create_wallet_intent(7, "loan", 100, payload={"interest_percent": percent})
    assert (await db.take_cookie_loan(7, intent_id=token))[0]
    await db.execute("UPDATE cookie_loans SET due_at = '2000-01-01' WHERE user_id = 7")
    await db.collect_due_loans()
    before = (await db.get_user(7))["cookies"]
    assert not (await db.take_cookie_loan(7, intent_id=token))[0]
    assert (await db.get_user(7))["cookies"] == before


async def test_unconfirmed_changed_interest_does_not_create_a_loan(db):
    token = await db.create_wallet_intent(7, "loan", 100, payload={"interest_percent": 1})
    assert not (await db.take_cookie_loan(7, intent_id=token))[0]
    assert (await db.get_user(7))["cookies"] == 150
    assert await db.get_active_loan(7) is None


async def test_loan_collection_records_actual_balance_debit_and_unpaid_debt(db):
    assert (await db.take_cookie_loan(7))[0]
    await db.set_cookies(7, 5, actor_id=99)
    await db.execute("UPDATE cookie_loans SET due_at = '2000-01-01' WHERE user_id = 7")
    collected = await db.collect_due_loans()
    row = (await db.list_transactions(7))[0]
    assert row["amount"] == -5
    assert f";debt:{collected[0]['debt_added']}" in row["details"]
    assert sum(row["amount"] for row in await db.list_transactions(7, 100)) == (await db.get_user(7))["cookies"]


async def test_concurrent_transfer_confirmation_cannot_pay_twice(db):
    await db.ensure_user(8, telegram_name="Борис")
    transfer = await db.create_transfer(7, 8, 100)
    results = await asyncio.gather(*(db.complete_transfer(transfer, 7) for _ in range(2)))
    assert sum(ok for ok, _, _ in results) == 1
    assert (await db.get_user(7))["cookies"] == 50
    assert (await db.get_user(8))["cookies"] == next(received for ok, _, received in results if ok)


async def test_concurrent_game_settlement_cannot_pay_twice(db):
    await db.ensure_user(8, telegram_name="Борис")
    await db.add_cookies(8, 150, "test")
    game_id, _ = await db.create_staked_game(-100, "dice", 7, 10)
    assert (await db.join_staked_game(game_id, 8))[0]
    await asyncio.gather(*(db.payout_staked_game(game_id, {7: 20}) for _ in range(2)))
    assert (await db.get_user(7))["cookies"] + (await db.get_user(8))["cookies"] == 300
    assert len([row for row in await db.list_transactions(7) if row["kind"] == "cookie_game_win"]) == 1


@pytest.mark.parametrize("game_type", ["bj", "dice", "crash", "trap"])
async def test_creator_cannot_cancel_started_paid_game_to_avoid_a_loss(db, game_type):
    game_id, _ = await db.create_staked_game(-100, game_type, 7, 10)
    assert await db.start_party_game(game_id, 7, {"stake": 10, "phase": "turn"}, {7: {"stake": 10}})
    assert not await db.cancel_party_game(game_id, 7)
    assert (await db.get_user(7))["cookies"] == 140
    assert (await db.get_party_game(game_id))["status"] == "active"
    assert await db.cancel_party_game(game_id, 99, is_admin=True)
    assert (await db.get_user(7))["cookies"] == 150
    assert not await db.cancel_party_game(game_id, 99, is_admin=True)


async def test_creator_can_still_cancel_paid_lobby_with_single_refund(db):
    game_id, _ = await db.create_staked_game(-100, "dice", 7, 10)
    assert await db.cancel_party_game(game_id, 7)
    assert not await db.cancel_party_game(game_id, 7)
    assert (await db.get_user(7))["cookies"] == 150


async def test_wallet_history_has_complete_pages_and_local_times(db, monkeypatch):
    from community_bot.economy import transaction_line

    row = {"kind": "shop", "amount": -12, "details": "rep_shield", "created_at": "2026-10-26T09:15:00+00:00"}
    line = transaction_line(row)
    assert "Щит" in line and "12:15" in line and "rep_shield" not in line
    for i in range(10):
        await db.add_cookies(7, i + 1, "subscription_freebie")
    edited = AsyncMock()
    monkeypatch.setattr(wallet, "edit_block", edited)
    await wallet.wallet_history(callback_for("wallet:history"), db, settings())
    text = edited.call_args.args[1]
    assert text.count("<i>") == 5
    data = [b.callback_data for r in edited.call_args.kwargs["reply_markup"].inline_keyboard for b in r]
    assert "wallet:history:5" in data
    assert len(text.encode("utf-16-le")) // 2 < 1024
    await wallet.wallet_history(callback_for("wallet:history:5"), db, settings())
    data = [b.callback_data for r in edited.call_args.kwargs["reply_markup"].inline_keyboard for b in r]
    assert "wallet:history:0" in data


async def test_existing_database_gains_confirmation_storage_without_balance_changes(tmp_path):
    import re

    from community_bot.database import SCHEMA

    old_schema = re.sub(r"CREATE TABLE IF NOT EXISTS wallet_intents \(.*?\);", "", SCHEMA, flags=re.S)
    database = Database(tmp_path / "before.db")
    async with database.connect() as connection:
        await connection.executescript(old_schema)
    await database.ensure_user(7, telegram_name="Анна")
    await database.execute("UPDATE users SET cookies = 123, cookie_debt = 17, reputation = 59 WHERE user_id = 7")
    await database.initialize()
    await database.initialize()
    user = await database.get_user(7)
    assert (user["cookies"], user["cookie_debt"], user["reputation"]) == (123, 17, 59)
    assert await database.create_wallet_intent(7, "rep_shield", 10)


async def test_long_html_is_not_sliced_when_a_card_becomes_text():
    from community_bot.blocks import edit_block

    message = SimpleNamespace(
        photo=[object()], caption="Кошелёк", edit_caption=AsyncMock(),
        edit_reply_markup=AsyncMock(), answer=AsyncMock(),
    )
    text = "<b>История</b>\n" + "<blockquote>" + "&amp;" * 240 + "</blockquote>"
    await edit_block(message, text, parse_mode="HTML")
    message.edit_caption.assert_not_called()
    message.answer.assert_awaited_once_with(text, parse_mode="HTML")


async def test_unchanged_card_does_not_spawn_duplicate_message():
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import EditMessageText

    from community_bot.blocks import edit_block

    method = EditMessageText(chat_id=7, message_id=10, text="Кошелёк")
    message = SimpleNamespace(
        photo=[], caption=None, answer=AsyncMock(),
        edit_text=AsyncMock(side_effect=TelegramBadRequest(method=method, message="message is not modified")),
    )
    await edit_block(message, "Кошелёк")
    message.answer.assert_not_called()


@pytest.mark.parametrize("action", ["menu:home", "menu:wallet", "menu:profile", "shop:home", "ui:close"])
async def test_navigation_cancels_pending_paid_flow_and_old_confirmation(db, action):
    from aiogram.types import CallbackQuery, Chat, InlineKeyboardButton, InlineKeyboardMarkup, Message

    from community_bot.navigation import CabinetNavigationMiddleware

    token = await db.create_wallet_intent(7, "custom_status", 10)
    state = Flow(purchase_intent=token, shop_price=10)
    callback = CallbackQuery(
        id="nav", chat_instance="private", from_user=User(id=7, is_bot=False, first_name="Анна"), data=action,
        message=Message(
            message_id=10, date=datetime.now(UTC), chat=Chat(id=7, type="private"),
            from_user=User(id=900, is_bot=True, first_name="Нора"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Подтвердить", callback_data=f"shop:pay:{token}")],
            ]),
        ),
    )
    handler = AsyncMock()
    await CabinetNavigationMiddleware()(handler, callback, {"db": db, "state": state})
    handler.assert_awaited_once()
    assert state.data == {}
    assert not (await db.buy_item(7, "custom_status", 10, intent_id=token, profile_value="Случайный текст"))[0]
    assert (await db.get_user(7))["cookies"] == 150
