from pathlib import Path

from community_bot.aliases import parse_trigger
from community_bot.domain import AUTO_REPUTATION_CAP, STARTING_REPUTATION, discounted_price, reputation_tier
from community_bot.helpers import lobby_count_ok, profile_text
from community_bot.keyboards import close_btn, pet_keyboard, public_profile_keyboard, shop_home_keyboard
from community_bot.pet_cosmetics import COSMETIC_BONUS_MILLI, COSMETIC_ORDER, pet_hourly_milli, render_pet_image
from community_bot.pets_talk import is_feminine, pet_pronouns, species_meta
from community_bot.shop_catalog import item_discount, shop_prices_for
from community_bot.social_data import deal_mafia_roles
from community_bot.ui_owner import is_owned_callback


def test_shop_trigger_is_exact_only() -> None:
    assert parse_trigger("магазин") == ("shop", "")
    assert parse_trigger("/shop") == ("shop", "")
    assert parse_trigger("Магазин где купить?") is None
    assert parse_trigger("Магазин, привет") is None
    assert parse_trigger("В магазине открыто") is None


def test_reputation_discounts_and_event_exclusion() -> None:
    assert reputation_tier(95).discount == 10
    assert reputation_tier(80).discount == 5
    assert reputation_tier(40).discount == 2
    assert discounted_price(50, 10) == 45
    assert item_discount("event_pass", 10) == 0
    assert item_discount("forgive", 10) == 10
    prices = shop_prices_for({"reputation": 95}, 0)
    assert prices["forgive"] == 45
    assert "event_pass" not in prices


def test_pet_gender_and_cosmetics_render() -> None:
    assert is_feminine("fox") is True
    assert is_feminine("cat") is False
    assert pet_pronouns("fox")["went"] == "ушла"
    assert pet_pronouns("dog")["went"] == "ушёл"
    emoji, label = species_meta("fox")
    assert "лиса" in label
    assert emoji
    path = render_pet_image("fox", ["pet_hat", "pet_glasses"])
    assert path is not None and path.is_file()
    hungry = {"hunger": 80, "thirst": 80, "sleeping": 0}
    base = pet_hourly_milli(hungry, ())
    boosted = pet_hourly_milli(hungry, list(COSMETIC_ORDER))
    assert boosted == base + sum(COSMETIC_BONUS_MILLI.values())
    sleeping = pet_hourly_milli({"hunger": 0, "thirst": 80, "sleeping": 1}, list(COSMETIC_ORDER))
    assert sleeping == 0


def test_close_and_owned_callbacks() -> None:
    assert "✖️ Закрыть" in close_btn().text
    pet_labels = [button.text for row in pet_keyboard().inline_keyboard for button in row]
    assert any("Кастомизация" in text for text in pet_labels)
    assert any("Закрыть" in text for text in pet_labels)
    public = [button.callback_data for row in public_profile_keyboard(1).inline_keyboard for button in row]
    assert "ui:close" in public
    home = [button.callback_data for row in shop_home_keyboard().inline_keyboard for button in row]
    assert "shop:cat:cosmetics" in home
    assert is_owned_callback("shop:home") is True
    assert is_owned_callback("pet:custom") is True
    assert is_owned_callback("profile:bio:1") is True
    assert is_owned_callback("profile_action:rep_up:1") is False
    assert is_owned_callback("cg:join:3") is False
    assert is_owned_callback("evpay:e1") is False
    assert is_owned_callback("sg:join:3") is False


def test_admin_can_start_short_lobby() -> None:
    assert lobby_count_ok(1, 2, 4, True) is True
    assert lobby_count_ok(1, 2, 4, False) is False
    assert lobby_count_ok(0, 2, 4, True) is False
    roles = deal_mafia_roles(1)
    assert len(roles) == 1


def test_public_profile_shows_warn_count() -> None:
    from types import SimpleNamespace

    text = profile_text(
        {
            "user_id": 9,
            "profile_name": "Нора",
            "telegram_name": "Nora",
            "username": "nora",
            "role": "member",
            "custom_status": None,
            "hobbies": "чат",
            "age": 20,
            "reputation": 69,
            "cookies": 1,
            "warnings": 3,
            "profile_bio": "есть описание",
        },
        SimpleNamespace(restricted_reputation_threshold=0),
    )
    assert "Предупреждения" in text
    assert "3" in text
    assert "вечное" not in text.casefold()


async def test_bio_auto_warn_once_and_incomplete_reset(tmp_path: Path) -> None:
    from community_bot.database import Database

    db = Database(tmp_path / "warn.db")
    await db.initialize()
    user = await db.ensure_user(5, telegram_name="Empty")
    assert int(user["warnings"]) == 1
    assert int(user["bio_auto_warn"]) == 1
    assert int(user["reputation"]) == STARTING_REPUTATION
    await db.execute("UPDATE users SET reputation = 90 WHERE user_id = 5")
    await db.reset_incomplete_reputation_to_bronze()
    fresh = await db.get_user(5)
    assert int(fresh["reputation"]) == AUTO_REPUTATION_CAP
    await db.update_profile(5, "profile_bio", "теперь есть текст")
    cleared = await db.get_user(5)
    assert int(cleared["bio_auto_warn"]) == 2
    assert int(cleared["warnings"]) == 0
    await db.update_profile(5, "profile_bio", "ещё раз")
    again = await db.get_user(5)
    assert int(again["warnings"]) == 0
    assert int(again["bio_auto_warn"]) == 2
    warns = await db.list_user_warns(5)
    assert warns
    assert warns[0]["reason"] == "Не заполнено описание профиля"


async def test_pet_cosmetic_changes_farm_and_image(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    from community_bot.database import Database

    db = Database(tmp_path / "pet.db")
    await db.initialize()
    await db.ensure_user(8, telegram_name="Owner")
    await db.add_cookies(8, 80, "test")
    assert await db.purchase_pet(8, "fox", "Рыжуха", 50) == (True, "ok")
    ok, _ = await db.buy_item(8, "pet_hat", 8)
    assert ok is True
    owned, equipped = await db.pet_cosmetic_sets(8)
    assert "pet_hat" in owned
    assert "pet_hat" in equipped
    yesterday = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    await db.execute(
        "UPDATE pets SET hunger = 100, thirst = 100, last_tick_at = ?, farm_milli = 0 WHERE user_id = 8",
        (yesterday,),
    )
    settled = await db.settle_pet(8)
    assert settled is not None
    assert int(settled["earned_milli"]) == 24 * (50 + COSMETIC_BONUS_MILLI["pet_hat"])
    toggled, status = await db.toggle_pet_cosmetic(8, "pet_hat")
    assert toggled is True
    assert status == "снят"
    _owned, equipped = await db.pet_cosmetic_sets(8)
    assert "pet_hat" not in equipped


async def test_event_pay_is_unique(tmp_path: Path) -> None:
    from community_bot.database import Database

    db = Database(tmp_path / "event.db")
    await db.initialize()
    await db.ensure_user(3, telegram_name="Guest")
    await db.add_cookies(3, 40, "test")
    await db.save_event_offer("e1", -100, 10, "Билет", 10, 1, title="Вечер", body="встреча")
    ok, error = await db.add_rsvp("e1", 3, 10)
    assert ok is True
    again, error = await db.add_rsvp("e1", 3, 10)
    assert again is False
    assert "уже" in error.casefold()
    assert await db.has_event_rsvp("e1", 3) is True
    offer = await db.get_event_offer("e1")
    assert offer is not None
    assert int(offer["price"]) == 10
