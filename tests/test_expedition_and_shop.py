from datetime import UTC, datetime, timedelta
from pathlib import Path

from community_bot.expedition import COOKIE_WEIGHTS, WEIGHT_TOTAL, parse_loot, result_text, roll_expedition_loot
from community_bot.keyboards import admin_panel_keyboard, admin_system_keyboard, pet_keyboard
from community_bot.shop_catalog import REMOVED_COSMETIC_SKUS, shop_header_lines, shop_prices_for
from community_bot.states import AdminFlow, ShopAdminFlow


def test_admin_flow_is_intact() -> None:
    assert AdminFlow.user_value
    assert AdminFlow.contest_text
    assert ShopAdminFlow.edit_value
    assert ShopAdminFlow.header_title
    assert not hasattr(ShopAdminFlow, "post_body")


def test_cookie_weights_are_skewed_and_ten_is_legendary() -> None:
    assert WEIGHT_TOTAL == 10_000
    assert COOKIE_WEIGHTS[10] == 1
    assert COOKIE_WEIGHTS[1] > COOKIE_WEIGHTS[5] > COOKIE_WEIGHTS[9]
    loot = roll_expedition_loot()
    assert loot.kind == "cookies"
    assert 1 <= loot.amount <= 10


def test_expedition_result_text_is_extendable() -> None:
    from community_bot.expedition import ExpeditionLoot

    cookies = ExpeditionLoot(kind="cookies", amount=3)
    text = result_text(pet_name="Булочка", species_words={"returned": "вернулся"}, loot=cookies)
    assert "вернулся из экспедиции" in text
    assert "3" in text
    title = ExpeditionLoot(kind="title", title="Ночной следопыт")
    rare = result_text(pet_name="Искра", species_words={"returned": "вернулась"}, loot=title)
    assert "Ночной следопыт" in rare
    assert parse_loot(None) is None


def test_shop_header_and_admin_entry() -> None:
    assert shop_header_lines({"enabled": False, "title": "Курс", "text": "1 🍪 = 1 ₽"}) == ""
    shown = shop_header_lines({"enabled": True, "title": "Курс на 21.09.2026", "text": "🍪 1 печенька = 1 ₽"})
    assert "Курс на 21.09.2026" in shown
    assert "1 печенька" in shown
    panel = [button.callback_data for row in admin_panel_keyboard(["features"]).inline_keyboard for button in row]
    assert "ashop:home" in panel
    system = [button.callback_data for row in admin_system_keyboard(["features"]).inline_keyboard for button in row]
    assert "ashop:home" in system
    pet = [button.callback_data for row in pet_keyboard().inline_keyboard for button in row]
    assert "pet:expedition" in pet
    assert not any("custom" in (data or "") for data in pet)


async def test_shop_catalog_starts_without_prices_and_supports_admin_crud(tmp_path: Path) -> None:
    from community_bot.database import Database

    db = Database(tmp_path / "shop.db")
    await db.initialize()
    priced = await db.list_shop_items(priced_only=True)
    assert priced == []
    cats = await db.list_shop_categories()
    slugs = {row["slug"] for row in cats}
    assert slugs >= {"pets", "reputation", "profile"}
    assert "cosmetics" not in slugs
    for sku in REMOVED_COSMETIC_SKUS:
        assert await db.get_shop_item(sku) is None
    header = await db.shop_header()
    assert header["enabled"] is False
    await db.set_shop_header(enabled=True, title="Курс на 21.09.2026", text="🍪 1 печенька = 1 ₽")
    header = await db.shop_header()
    assert header["enabled"] is True
    await db.upsert_shop_category("events", "🎪 Ивенты", "Сезонные призы")
    created = await db.upsert_shop_item(
        "event_pin",
        category_slug="events",
        title="Значок мероприятия",
        description="Коллекционный значок",
        price=7,
        extra_json='{"kind":"merch"}',
    )
    assert created is not None
    await db.upsert_shop_item("event_pin", category_slug="profile")
    moved = await db.get_shop_item("event_pin")
    assert moved and moved["category_slug"] == "profile"
    await db.upsert_shop_item("event_pin", enabled=0)
    hidden = await db.priced_shop_map()
    assert "event_pin" not in hidden
    await db.upsert_shop_item("event_pin", enabled=1)
    user = {"reputation": 95}
    prices = shop_prices_for(user, 0, await db.priced_shop_map())
    assert prices["event_pin"] == 7
    assert await db.delete_shop_item("event_pin") is True
    assert await db.delete_shop_category("pets") is False
    assert await db.delete_shop_category("events") is True


async def test_expedition_cooldown_and_notice_claim(tmp_path: Path) -> None:
    from community_bot.database import Database

    db = Database(tmp_path / "exp.db")
    await db.initialize()
    await db.ensure_user(4, telegram_name="Host")
    await db.add_cookies(4, 50, "test")
    assert await db.purchase_pet(4, "cat", "Булочка", 10) == (True, "ok")
    ok, error, _ = await db.start_expedition(4)
    assert ok is True, error
    again, error, _ = await db.start_expedition(4)
    assert again is False
    assert "экспедиции" in error.casefold()
    due = (datetime.now(UTC) - timedelta(seconds=2)).isoformat()
    await db.execute("UPDATE pets SET expedition_until = ? WHERE user_id = 4", (due,))
    due_rows = await db.list_due_expeditions()
    assert any(int(row["user_id"]) == 4 for row in due_rows)
    settled = await db.settle_pet(4)
    assert settled and settled.get("expedition_done")
    pending = await db.list_pending_expedition_notices()
    assert any(int(row["user_id"]) == 4 for row in pending)
    assert await db.claim_expedition_notice(4) is not None
    assert await db.claim_expedition_notice(4) is None
    assert await db.list_pending_expedition_notices() == []
