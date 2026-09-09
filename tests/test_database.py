from datetime import UTC, datetime, timedelta
from pathlib import Path

from community_bot.database import Database


async def test_transfer_is_atomic_and_charges_commission(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await db.ensure_user(1, "one", "One")
    await db.ensure_user(2, "two", "Two")
    await db.execute("UPDATE users SET reputation = 80 WHERE user_id = 1")
    await db.add_cookies(1, 100, "test")
    transfer_id = await db.create_transfer(1, 2, 100)

    ok, _, received = await db.complete_transfer(transfer_id, 1)

    assert ok is True
    assert received == 80
    assert (await db.get_user(1))["cookies"] == 0  # type: ignore[index]
    assert (await db.get_user(2))["cookies"] == 80  # type: ignore[index]


async def test_transfer_commission_follows_reputation(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await db.ensure_user(1, "one", "One")
    await db.ensure_user(2, "two", "Two")
    await db.add_cookies(1, 300, "test")
    await db.execute("UPDATE users SET reputation = 100 WHERE user_id = 1")
    gold_id = await db.create_transfer(1, 2, 100)
    ok, _, gold_received = await db.complete_transfer(gold_id, 1)
    assert ok is True
    assert gold_received == 90

    await db.execute("UPDATE users SET reputation = 50 WHERE user_id = 1")
    bronze_id = await db.create_transfer(1, 2, 100)
    ok, _, bronze_received = await db.complete_transfer(bronze_id, 1)
    assert ok is True
    assert bronze_received == 70


async def test_transfer_cannot_be_replayed(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="One")
    await db.ensure_user(2, telegram_name="Two")
    await db.add_cookies(1, 100, "test")
    transfer_id = await db.create_transfer(1, 2, 50)

    assert (await db.complete_transfer(transfer_id, 1))[0] is True
    assert (await db.complete_transfer(transfer_id, 1))[0] is False


async def test_shop_purchase_requires_balance(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="One")

    ok, message = await db.buy_item(1, "restore_rep", 5)

    assert ok is False
    assert "Недостаточно" in message


async def test_list_users_prioritizes_roles(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Member")
    await db.ensure_user(2, telegram_name="Admin")
    await db.set_role(2, "admin")

    users = await db.list_users()

    assert [user["user_id"] for user in users] == [2, 1]


async def test_cookie_order_can_only_be_approved_once(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Buyer")
    order_id = await db.create_cookie_order(1, 50, 500, "photo", "receipt-file")

    first = await db.review_cookie_order(order_id, reviewer_id=99, approved=True)
    second = await db.review_cookie_order(order_id, reviewer_id=99, approved=True)

    assert first is not None
    assert second is None
    assert (await db.get_user(1))["cookies"] == 50  # type: ignore[index]


async def test_set_cookies_records_exact_balance(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="User")
    await db.add_cookies(1, 10, "test")

    ok, difference = await db.set_cookies(1, 100, actor_id=9)

    assert ok is True
    assert difference == 90
    assert (await db.get_user(1))["cookies"] == 100  # type: ignore[index]


async def test_roulette_is_atomic_and_applies_non_gold_commission(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="One")
    await db.ensure_user(2, telegram_name="Two")
    await db.add_cookies(1, 20, "test")
    await db.add_cookies(2, 20, "test")
    await db.execute("UPDATE users SET reputation = 80 WHERE user_id = 1")
    game_id = await db.create_roulette(-100, 1, 2)

    ok, _, result = await db.settle_roulette(game_id, opponent_id=2, winner_id=1)
    replay = await db.settle_roulette(game_id, opponent_id=2, winner_id=1)

    assert ok is True
    assert result and result["payout"] == 8
    assert replay[0] is False
    assert (await db.get_user(1))["cookies"] == 28  # type: ignore[index]
    assert (await db.get_user(2))["cookies"] == 10  # type: ignore[index]


async def test_freebie_can_only_be_claimed_once(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="User")

    assert await db.claim_freebie(1, 10) is True
    assert await db.claim_freebie(1, 10) is False
    assert (await db.get_user(1))["cookies"] == 10  # type: ignore[index]


async def test_scheduled_message_becomes_due_and_can_be_toggled(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    schedule_id = await db.create_scheduled_message("community", "Hello", None, None, 5, created_by=1)

    future = datetime.now(UTC) + timedelta(minutes=6)
    due = await db.due_scheduled_messages(future)

    assert [row["id"] for row in due] == [schedule_id]
    assert await db.toggle_scheduled_message(schedule_id) is True
    assert await db.due_scheduled_messages(future) == []


async def test_pet_purchase_activity_rewards_and_fractional_farm(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Owner")
    await db.add_cookies(1, 100, "test")

    assert await db.purchase_pet(1, "dragon", "Искра", 50) == (True, "ok")
    assert (await db.purchase_pet(1, "cat", "Дубль", 50))[0] is False
    assert (await db.get_user(1))["cookies"] == 50  # type: ignore[index]

    for _ in range(49):
        _, rewarded = await db.record_activity(1, -100)
        assert rewarded is False
    count, rewarded = await db.record_activity(1, -100)
    assert count == 50
    assert rewarded is True
    pet = await db.get_pet(1, settle=False)
    assert pet and pet["food_units"] == 1 and pet["water_units"] == 1

    yesterday = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    await db.execute(
        "UPDATE pets SET hunger = 100, thirst = 100, last_tick_at = ?, farm_milli = 0 WHERE user_id = 1",
        (yesterday,),
    )
    settled = await db.settle_pet(1)
    assert settled and settled["payout"] == 1
    assert settled["farm_milli"] == 200
    assert (await db.get_user(1))["cookies"] == 51  # type: ignore[index]


async def test_feature_toggle_is_persistent_and_audited(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()

    assert await db.feature_enabled("games") is True
    assert await db.feature_enabled("sticker_filter") is False
    assert await db.toggle_feature("games", actor_id=7) is False
    assert await db.feature_enabled("games") is False
    await db.reset_feature_flags(actor_id=7)
    assert await db.feature_enabled("games") is True
    assert await db.feature_enabled("sticker_filter") is False
    actions = await db.recent_admin_actions()
    kinds = {row["action"] for row in actions}
    assert "feature_toggle" in kinds
    assert "feature_reset" in kinds


async def test_party_game_survives_db_state_and_resolves_once(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    for user_id in (1, 2, 3):
        await db.ensure_user(user_id, telegram_name=f"User {user_id}")

    game_id, created = await db.create_party_game(-100, "smuggle", 1)
    assert created is True
    assert (await db.join_party_game(game_id, 2))[0] is True
    assert (await db.join_party_game(game_id, 3))[0] is True
    secrets_by_user = {
        1: {"role": "traveler"},
        2: {"role": "smuggler"},
        3: {"role": "traveler"},
    }
    assert await db.start_party_game(game_id, 1, {"special_id": 2}, secrets_by_user) is True
    for voter_id in (1, 2, 3):
        assert (await db.cast_party_vote(game_id, voter_id, 2))[0] is True

    result = await db.resolve_party_game(game_id)
    assert result and result["outcome"]["selected_id"] == 2
    assert await db.resolve_party_game(game_id) is None


async def test_cookie_loan_and_collection(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Borrower")
    await db.execute("UPDATE users SET reputation = 100 WHERE user_id = 1")

    ok, _, loan = await db.take_cookie_loan(1)
    assert ok is True
    assert loan and loan["due_amount"] == 110
    assert (await db.get_user(1))["cookies"] == 100  # type: ignore[index]
    assert (await db.take_cookie_loan(1))[0] is False

    past = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    await db.execute("UPDATE cookie_loans SET due_at = ? WHERE user_id = 1", (past,))
    collected = await db.collect_due_loans()
    assert len(collected) == 1
    user = await db.get_user(1)
    assert user is not None
    assert user["cookies"] == 0
    assert user["cookie_debt"] == 10
    history = await db.list_transactions(1)
    assert any(row["kind"] == "loan_repay" for row in history)


async def test_staked_game_can_change_stake(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="A")
    await db.ensure_user(2, telegram_name="B")
    await db.add_cookies(1, 200, "test")
    await db.add_cookies(2, 200, "test")
    game_id, status = await db.create_staked_game(-100, "dice", 1, 10)
    assert status == "ok" and game_id
    assert (await db.join_staked_game(game_id, 2))[0] is True
    ok, text = await db.update_staked_game_stake(game_id, 1, 25)
    assert ok is True, text
    game = await db.get_party_game(game_id)
    assert game and game["state"]["stake"] == 25
    assert (await db.get_user(1))["cookies"] == 175  # type: ignore[index]
    assert (await db.get_user(2))["cookies"] == 175  # type: ignore[index]
    assert (await db.update_staked_game_stake(game_id, 2, 50))[0] is False
