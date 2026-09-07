from types import SimpleNamespace

from community_bot.helpers import ornate_profile_text, pet_guard_reputation, profile_text
from community_bot.keyboards import BTN_MENU, BTN_PROFILE, STYLE_FUN, STYLE_GO, main_private_keyboard
from community_bot.permissions import (
    PERM_MUTE,
    dump_permissions,
    parse_permissions,
    role_has_permission,
    slugify_role,
)
from community_bot.routers.cookie_games import _hand_value
from community_bot.shop_catalog import SHOP_CATEGORIES


def test_persistent_keyboard_is_profile_and_menu() -> None:
    row = main_private_keyboard().keyboard[0]
    assert row[0].text == BTN_PROFILE
    assert row[0].style == STYLE_GO
    assert row[1].text == BTN_MENU
    assert row[1].style == STYLE_FUN


def test_shop_profile_shelf_has_privacy_and_ornate() -> None:
    items = SHOP_CATEGORIES["profile"]["items"]
    assert "private_profile" in items
    assert "ornate_profile" in items


def test_permissions_roundtrip_and_wildcard() -> None:
    raw = dump_permissions([PERM_MUTE, PERM_MUTE, "*"])
    parsed = parse_permissions(raw)
    assert parsed.count(PERM_MUTE) == 1
    assert role_has_permission(["*"], "anything")
    assert role_has_permission([PERM_MUTE], PERM_MUTE)
    assert not role_has_permission([PERM_MUTE], "admin.panel")
    assert slugify_role("Старший модератор") == "starshiy_moderator"


def test_ornate_profile_uses_frame_and_status() -> None:
    user = {
        "user_id": 42,
        "profile_name": "Роман",
        "telegram_name": "Roman",
        "username": "roman",
        "role": "admin",
        "custom_status": "На стиле",
        "hobbies": "Музыка",
        "age": 24,
        "reputation": 95,
        "cookies": 250,
        "warnings": 0,
        "profile_private": 1,
        "profile_ornate": 1,
    }
    text = profile_text(user, SimpleNamespace(restricted_reputation_threshold=0))
    assert "Ｎ Ｏ Ｒ Ａ" in text
    assert "На стиле" in text
    assert "скрыт" in text
    assert "◆" in text
    fancy = ornate_profile_text(user, SimpleNamespace(restricted_reputation_threshold=0))
    assert fancy == text


def test_blackjack_hand_counts_aces() -> None:
    assert _hand_value(["AS", "KS"]) == 21
    assert _hand_value(["AS", "AC", "9H"]) == 21
    assert _hand_value(["KS", "QS", "2H"]) == 22


async def test_staff_roles_seed_and_custom_role(tmp_path) -> None:
    from pathlib import Path

    from community_bot.database import Database
    from community_bot.helpers import has_permission
    from community_bot.permissions import PERM_ADMIN_PANEL, PERM_MUTE

    db = Database(Path(tmp_path) / "roles.db")
    await db.initialize()
    roles = {row["slug"]: row for row in await db.list_staff_roles()}
    assert "owner" in roles
    assert "*" in roles["owner"]["permissions"]
    assert PERM_MUTE in roles["moderator"]["permissions"]
    assert await db.create_staff_role("helper", "Хелпер", 20, [PERM_MUTE])
    helper = await db.get_staff_role("helper")
    assert helper and helper["name"] == "Хелпер"
    await db.ensure_user(5, telegram_name="Helper")
    await db.set_role(5, "helper")
    settings = SimpleNamespace(is_owner=lambda user_id: False, owner_ids=frozenset(), moderator_ids=frozenset())
    assert await has_permission(db, settings, 5, PERM_MUTE)
    assert not await has_permission(db, settings, 5, PERM_ADMIN_PANEL)


async def test_staked_game_debits_and_refunds(tmp_path) -> None:
    from pathlib import Path

    from community_bot.database import Database

    db = Database(Path(tmp_path) / "games.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="One")
    await db.ensure_user(2, telegram_name="Two")
    await db.add_cookies(1, 50, "test")
    await db.add_cookies(2, 50, "test")
    game_id, status = await db.create_staked_game(-100, "dice", 1, 10)
    assert status == "ok" and game_id
    assert (await db.get_user(1))["cookies"] == 40
    ok, _ = await db.join_staked_game(game_id, 2, maximum=4)
    assert ok is True
    assert (await db.get_user(2))["cookies"] == 40
    assert await db.cancel_party_game(game_id, 1) is True
    assert (await db.get_user(1))["cookies"] == 50
    assert (await db.get_user(2))["cookies"] == 50


async def test_pet_guard_requires_full_belly(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from community_bot.database import Database

    db = Database(Path(tmp_path) / "pets.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Owner")
    await db.add_cookies(1, 100, "test")
    await db.purchase_pet(1, "cat", "Булочка", 50)
    await db.execute("UPDATE pets SET hunger = 80, sleeping = 0 WHERE user_id = 1")

    monkeypatch.setattr("community_bot.helpers.secrets.randbelow", lambda _: 0)
    delta, line = await pet_guard_reputation(db, 1, -5)
    assert delta == 0
    assert line and "Булочка" in line

    monkeypatch.setattr("community_bot.helpers.secrets.randbelow", lambda _: 0)
    delta, line = await pet_guard_reputation(db, 1, 5)
    assert delta == 10
    assert line and "удвоился" in line

    await db.execute("UPDATE pets SET hunger = 10 WHERE user_id = 1")
    delta, line = await pet_guard_reputation(db, 1, -5)
    assert delta == -5
    assert line is None
