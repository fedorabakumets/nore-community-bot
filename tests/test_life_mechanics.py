from types import SimpleNamespace

from community_bot.aliases import parse_trigger, remainder_text
from community_bot.keyboards import shop_category_keyboard
from community_bot.life import (
    WARN_KICK_AT,
    WARN_MUTE_AT,
    gift_item_from_args,
    matches_stop_word,
    vitrine_active,
)
from community_bot.shop_catalog import BASE_SHOP_PRICES, GIFTABLE_ITEMS
from community_bot.updates import community_announcement, latest_update, staff_announcement


def test_gift_aliases_and_remainder() -> None:
    assert gift_item_from_args("щит") == "rep_shield"
    assert gift_item_from_args(["плащ"]) == "immunity_24h"
    assert gift_item_from_args("набор") == "season_pack"
    assert remainder_text("подарить щит") == "щит"
    assert parse_trigger("розыгрыш итог") == ("lotterydraw", "")


def test_warn_ladder_thresholds() -> None:
    assert WARN_MUTE_AT == 3
    assert WARN_KICK_AT == 5


def test_vitrine_and_stop_words() -> None:
    assert vitrine_active(None, None) is True
    assert vitrine_active("0", None) is False
    assert vitrine_active("3", "2000-01-01T00:00:00+00:00") is False
    assert matches_stop_word("это спам здесь", ["спам"]) == "спам"
    assert matches_stop_word("привет", ["спам"]) is None


def test_public_update_omits_staff_and_has_member_copy() -> None:
    item = latest_update()
    pin = community_announcement(item)
    staff = staff_announcement(item)
    assert item.number == 18
    assert "Обновление №18" in pin
    assert "Админское" not in pin
    assert "обложк" in pin.casefold() and "пиксель" in pin.casefold()
    assert "Витрина после выбора" not in pin
    assert "Админское обновление №18" in staff
    assert "Monocraft" in staff
    assert len(pin) <= 1024


def test_shop_gift_buttons_exist() -> None:
    prices = {key: 10 for key in BASE_SHOP_PRICES}
    markup = shop_category_keyboard("reputation", prices)
    data = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert "shop:g:rep_shield" in data
    assert GIFTABLE_ITEMS & {"rep_shield", "season_pack"}


async def test_gift_buy_applies_to_target(tmp_path) -> None:
    from pathlib import Path

    from community_bot.database import Database

    db = Database(Path(tmp_path) / "gift.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Giver")
    await db.ensure_user(2, telegram_name="Target")
    await db.add_cookies(1, 50, "test")
    ok, error = await db.buy_item(1, "rep_shield", 12, target_id=2)
    assert ok is True, error
    assert int((await db.get_user(1))["cookies"]) == 38
    assert int((await db.get_user(2))["hate_shields"]) == 1
    assert int((await db.get_user(1))["hate_shields"]) == 0


async def test_season_pack_and_lottery(tmp_path) -> None:
    from pathlib import Path

    from community_bot.database import Database

    db = Database(Path(tmp_path) / "life.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="One")
    await db.ensure_user(2, telegram_name="Two")
    await db.add_cookies(1, 80, "test")
    await db.add_cookies(2, 80, "test")
    assert (await db.purchase_pet(1, "cat", "Булочка", 10))[0]
    ok, _ = await db.buy_item(1, "season_pack", 28)
    assert ok is True
    assert int((await db.get_user(1))["hate_shields"]) == 1
    await db.add_cookies(1, 40, "topup")

    lottery_id, error = await db.create_lottery(-100, 1, 5)
    assert lottery_id, error
    ok, _, count = await db.join_lottery(lottery_id, 1)
    assert ok is True and count == 1
    ok, _, count = await db.join_lottery(lottery_id, 2)
    assert ok is True and count == 2
    before = {1: int((await db.get_user(1))["cookies"]), 2: int((await db.get_user(2))["cookies"])}
    ok, error, result = await db.draw_lottery(lottery_id)
    assert ok is True, error
    assert result is not None
    assert result["pot"] == 10
    winner_id = int(result["winner_id"])
    other_id = 2 if winner_id == 1 else 1
    assert int((await db.get_user(winner_id))["cookies"]) == before[winner_id] + 10
    assert int((await db.get_user(other_id))["cookies"]) == before[other_id]


async def test_vitrine_stock_and_achievements(tmp_path) -> None:
    from pathlib import Path

    from community_bot.database import Database
    from community_bot.life import unlock

    db = Database(Path(tmp_path) / "vit.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Buyer")
    await db.add_cookies(1, 40, "test")
    await db.set_bot_state("shop_featured", "rep_shield")
    await db.set_bot_state("shop_featured_stock", "1")
    ok, _ = await db.buy_item(1, "rep_shield", 12)
    assert ok is True
    await db.consume_vitrine("rep_shield")
    assert await db.get_bot_state("shop_featured") == ""
    title = await unlock(db, 1, "shop_first")
    assert title == "Покупатель"
    user = await db.get_user(1)
    assert user["profile_title"] == "Покупатель"
    assert await unlock(db, 1, "shop_first") is None


async def test_staff_update_goes_to_panel_users_only(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from community_bot.database import Database
    from community_bot.main import announce_latest_update

    db = Database(Path(tmp_path) / "staff.db")
    await db.initialize()
    await db.ensure_user(10, telegram_name="Owner")
    await db.set_role(10, "owner")
    await db.ensure_user(20, telegram_name="Member")
    dms: list[tuple[int, str]] = []

    class FakeBot:
        async def send_message(self, chat_id, text, **kwargs):
            dms.append((chat_id, text))
            return SimpleNamespace(message_id=1, text=text, reply_markup=kwargs.get("reply_markup"))

        async def send_photo(self, chat_id, photo, **kwargs):
            dms.append((chat_id, kwargs.get("caption") or ""))
            return SimpleNamespace(message_id=2, text=kwargs.get("caption"), reply_markup=kwargs.get("reply_markup"))

        async def pin_chat_message(self, chat_id, message_id, disable_notification=True):
            return None

        async def unpin_chat_message(self, chat_id, message_id):
            return None

    async def fake_publish(_db, _item):
        return None

    monkeypatch.setattr("community_bot.main.publish_member_update", fake_publish)

    async def no_staff(_db, _item):
        return None

    monkeypatch.setattr("community_bot.main.publish_staff_update", no_staff)
    settings = SimpleNamespace(community_chat_id=-100)
    await announce_latest_update(FakeBot(), db, settings)
    chats = [chat_id for chat_id, _ in dms]
    assert 10 in chats
    assert 20 not in chats
    staff_texts = [text for chat_id, text in dms if chat_id == 10]
    public = [text for chat_id, text in dms if chat_id == -100]
    assert staff_texts and "Админское" in staff_texts[0]
    assert public and "Админское" not in public[0]
    assert "Обновление №18" in public[0]
