from types import SimpleNamespace

from community_bot.helpers import ornate_profile_text, pet_guard_reputation, profile_text
from community_bot.keyboards import (
    BTN_MENU,
    BTN_SHOP,
    BTN_TICKET,
    BTN_WALLET,
    STYLE_CLOSE,
    STYLE_FUN,
    STYLE_GO,
    main_private_keyboard,
)
from community_bot.permissions import (
    PERM_MUTE,
    dump_permissions,
    parse_permissions,
    role_has_permission,
    slugify_role,
)
from community_bot.routers.cookie_games import _hand_value
from community_bot.shop_catalog import SHOP_CATEGORIES


def test_persistent_keyboard_is_cabinet_four_buttons() -> None:
    rows = main_private_keyboard().keyboard
    assert rows[0][0].text == BTN_MENU
    assert rows[0][0].style == STYLE_FUN
    assert rows[0][1].text == BTN_SHOP
    assert rows[0][1].style == STYLE_GO
    assert rows[1][0].text == BTN_WALLET
    assert getattr(rows[1][0], "style", None) in {None, ""}
    assert rows[1][1].text == BTN_TICKET
    assert rows[1][1].style == STYLE_CLOSE


def test_shop_profile_shelf_has_privacy_and_ornate() -> None:
    items = SHOP_CATEGORIES["profile"]["items"]
    assert "private_profile" in items
    assert "title_owl" in items


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
    from community_bot.permissions import PERM_ADMIN_PANEL, PERM_MUTE, PERM_PURGE

    db = Database(Path(tmp_path) / "roles.db")
    await db.initialize()
    roles = {row["slug"]: row for row in await db.list_staff_roles()}
    assert "owner" in roles
    assert "*" in roles["owner"]["permissions"]
    assert PERM_MUTE in roles["moderator"]["permissions"]
    assert PERM_PURGE not in roles["moderator"]["permissions"]
    assert PERM_PURGE in roles["admin"]["permissions"]
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
    assert delta == 5
    assert line is None

    monkeypatch.setattr("community_bot.helpers.secrets.randbelow", lambda _: 0)
    delta, line = await pet_guard_reputation(db, 1, -5)
    assert delta == -5
    assert line is None

    await db.execute("UPDATE pets SET hunger = 10 WHERE user_id = 1")
    delta, line = await pet_guard_reputation(db, 1, -5)
    assert delta == -5
    assert line is None


def test_pet_keyboard_has_no_talk() -> None:
    from community_bot.keyboards import pet_keyboard

    labels = [button.text for row in pet_keyboard().inline_keyboard for button in row]
    assert all("Поговорить" not in text for text in labels)


def test_member_announcement_omits_staff() -> None:
    from community_bot.updates import community_announcement, latest_update, member_details_nodes, member_details_text

    item = latest_update()
    pin = community_announcement(item)
    details = member_details_text(item)
    nodes = str(member_details_nodes(item))
    assert "Обновление №11" in pin
    assert len(pin) <= 1024
    assert "Админ" not in pin
    assert "четыре комнаты" not in details.casefold()
    assert "Админка" not in nodes
    assert "личный кабинет" in details.casefold() or "кабинет" in details.casefold()
    assert "мафия" in details.casefold()
    assert "Пример." in details
    assert "Обновление №11" in details
    from community_bot.updates import staff_announcement

    staff = staff_announcement(item)
    assert "справка" in staff.casefold()
    assert staff not in pin
    assert "bio_warning" in staff or "вечное" in staff.casefold()


async def test_reputation_bronze_and_once_per_target(tmp_path) -> None:
    from datetime import date
    from pathlib import Path

    from community_bot.database import Database
    from community_bot.reputation import change_community_reputation

    db = Database(Path(tmp_path) / "rep.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Actor")
    await db.ensure_user(2, telegram_name="Target")
    await db.ensure_user(3, telegram_name="Other")
    settings = SimpleNamespace(restricted_reputation_threshold=0)
    today = date(2026, 9, 11)

    await db.execute("UPDATE users SET reputation = 60 WHERE user_id = 1")
    actor = await db.get_user(1)
    target = await db.get_user(2)
    ok, text, _, _ = await change_community_reputation(db, settings, actor, target, -5, today)
    assert ok is False
    assert "Бронза" in text

    ok, _, new_value, _ = await change_community_reputation(db, settings, actor, target, 5, today)
    assert ok is True
    assert new_value == 75

    await db.execute("UPDATE users SET reputation = 80 WHERE user_id = 1")
    actor = await db.get_user(1)
    other = await db.get_user(3)
    ok, msg, _, _ = await change_community_reputation(db, settings, actor, target, 5, today)
    assert ok is False
    assert "сегодня" in msg.casefold()
    ok, _, new_value, _ = await change_community_reputation(db, settings, actor, other, 5, today)
    assert ok is True
    assert new_value == 75


async def test_hate_shield_absorbs_one_minus(tmp_path) -> None:
    from datetime import date
    from pathlib import Path

    from community_bot.database import Database
    from community_bot.reputation import change_community_reputation

    db = Database(Path(tmp_path) / "shield.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Actor")
    await db.ensure_user(2, telegram_name="Target")
    await db.add_cookies(2, 20, "test")
    ok, _ = await db.buy_item(2, "rep_shield", 12)
    assert ok is True
    settings = SimpleNamespace(restricted_reputation_threshold=0)
    actor = await db.get_user(1)
    target = await db.get_user(2)
    ok, _, new_value, extra = await change_community_reputation(
        db, settings, actor, target, -5, date(2026, 9, 11)
    )
    assert ok is True
    assert extra and "Щит" in extra
    assert new_value == 70
    assert int((await db.get_user(2))["hate_shields"]) == 0


async def test_announce_pins_telegraph_or_falls_back_to_dm(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from community_bot.database import Database
    from community_bot.main import announce_latest_update

    db = Database(Path(tmp_path) / "announce.db")
    await db.initialize()
    sent: list[SimpleNamespace] = []
    pinned: list[int] = []

    class FakeBot:
        async def send_message(self, chat_id, text, **kwargs):
            message = SimpleNamespace(
                message_id=7 + len(sent),
                text=text,
                reply_markup=kwargs.get("reply_markup"),
            )
            sent.append(message)
            return message

        async def send_photo(self, chat_id, photo, **kwargs):
            message = SimpleNamespace(
                message_id=7 + len(sent),
                text=kwargs.get("caption"),
                caption=kwargs.get("caption"),
                reply_markup=kwargs.get("reply_markup"),
            )
            sent.append(message)
            return message

        async def pin_chat_message(self, chat_id, message_id, disable_notification=True):
            pinned.append(message_id)

        async def unpin_chat_message(self, chat_id, message_id):
            return None

    async def fake_publish(_db, _item):
        return "https://telegra.ph/NORA"

    monkeypatch.setattr("community_bot.main.publish_member_update", fake_publish)
    settings = SimpleNamespace(community_chat_id=-100)
    await announce_latest_update(FakeBot(), db, settings)
    assert pinned == [7]
    assert "Админ" not in sent[0].text
    assert "Обновление №11" in sent[0].text
    assert sent[0].reply_markup.inline_keyboard[0][0].url == "https://telegra.ph/NORA"
    assert await db.get_bot_state("last_announced_update") == "11:photo-v1"
    await announce_latest_update(FakeBot(), db, settings)
    assert len(sent) == 1

    await db.set_bot_state("last_announced_update", "")
    sent.clear()
    pinned.clear()

    async def no_publish(_db, _item):
        return None

    class NoPinBot(FakeBot):
        async def pin_chat_message(self, chat_id, message_id, disable_notification=True):
            raise RuntimeError("no pin rights")

    monkeypatch.setattr("community_bot.main.publish_member_update", no_publish)
    await announce_latest_update(NoPinBot(), db, settings)
    assert not pinned
    assert sent[0].reply_markup.inline_keyboard[0][0].callback_data == "updates:dm"
    assert await db.get_bot_state("last_announced_update") == "11:photo-v1"


def test_update_cover_renders_number(tmp_path) -> None:
    from pathlib import Path

    from community_bot.covers import cover_path_for
    from community_bot.updates import latest_update

    path = cover_path_for(latest_update(), cache_dir=Path(tmp_path) / "covers")
    assert path is not None
    assert path.is_file()
    assert path.stat().st_size > 1000
