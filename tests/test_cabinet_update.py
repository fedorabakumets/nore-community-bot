from types import SimpleNamespace

from community_bot.game_anim import decorate
from community_bot.keyboards import shop_category_keyboard, shop_confirm_keyboard
from community_bot.profile_fill import profile_fill_percent, profile_notices, reputation_cap, verification_text
from community_bot.shop_catalog import BASE_SHOP_PRICES
from community_bot.social_data import MAFIA_MIN, deal_mafia_roles, mafia_team


def test_empty_profile_is_capped_at_silver() -> None:
    user = {
        "profile_name": "",
        "age": None,
        "hobbies": "",
        "profile_bio": "",
        "avatar_file_id": "",
        "bio_warning": 1,
    }
    assert profile_fill_percent(user) == 0
    assert reputation_cap(user) == 89
    notices = profile_notices(user)
    assert any("вечное предупреждение" in line.casefold() for line in notices)


def test_full_profile_unlocks_gold_and_shows_blocks() -> None:
    user = {
        "profile_name": "Нора",
        "age": 22,
        "hobbies": "кино",
        "profile_bio": "живу в чате",
        "avatar_file_id": "file",
        "bio_warning": 1,
    }
    assert profile_fill_percent(user) == 100
    assert reputation_cap(user) == 100
    text = verification_text(user)
    assert "100%" in text
    assert "Имя" in text
    assert "Описание" in text
    assert "20%" in text
    notices = profile_notices(user)
    assert any("сейчас описание заполнено" in line.casefold() for line in notices)


def test_shop_buttons_always_show_cookie_price_and_confirm() -> None:
    prices = {key: 12 for key in BASE_SHOP_PRICES}
    markup = shop_category_keyboard("reputation", prices)
    labels = [button.text for row in markup.inline_keyboard for button in row]
    assert any("🍪" in text and "12" in text for text in labels)
    confirm = shop_confirm_keyboard("rep_shield", 12)
    data = [button.callback_data for row in confirm.inline_keyboard for button in row]
    assert "shop:ok:rep_shield" in data
    assert any("12 🍪" in button.text for row in confirm.inline_keyboard for button in row)


def test_mafia_deal_has_town_and_mafia() -> None:
    roles = deal_mafia_roles(MAFIA_MIN)
    assert len(roles) == MAFIA_MIN
    assert "doctor" in roles
    assert "sheriff" in roles
    assert any(mafia_team(role) for role in roles)
    assert roles.count("civilian") >= 1


def test_lobby_animation_wraps_body() -> None:
    frame = decorate("Лобби №1", 3)
    assert "Лобби №1" in frame
    assert "<code>" in frame


async def test_reputation_plus_stops_at_silver_until_profile_complete(tmp_path) -> None:
    from datetime import date
    from pathlib import Path

    from community_bot.database import Database

    db = Database(Path(tmp_path) / "cap.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Plus")
    await db.ensure_user(2, telegram_name="Empty")
    await db.execute("UPDATE users SET reputation = 87 WHERE user_id = 2")
    nxt = await db.apply_reputation(1, 2, 5, date(2026, 9, 14))
    assert nxt == 89
    gold = await db.get_user(2)
    assert int(gold["bio_warning"]) == 1
    await db.update_profile(2, "profile_name", "Маша")
    await db.update_profile(2, "age", 20)
    await db.update_profile(2, "hobbies", "игры")
    await db.update_profile(2, "profile_bio", "описание")
    await db.update_profile(2, "avatar_file_id", "photo")
    nxt = await db.apply_reputation(1, 2, 5, date(2026, 9, 15))
    assert nxt == 94


async def test_already_gold_is_not_cut_down(tmp_path) -> None:
    from datetime import date
    from pathlib import Path

    from community_bot.database import Database

    db = Database(Path(tmp_path) / "gold.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Plus")
    await db.ensure_user(2, telegram_name="Star")
    await db.execute("UPDATE users SET reputation = 95 WHERE user_id = 2")
    nxt = await db.apply_reputation(1, 2, 5, date(2026, 9, 14))
    assert nxt == 95


async def test_wallet_table_lists_cookies_and_fee() -> None:
    from community_bot.routers.wallet import wallet_text

    user = {
        "user_id": 7,
        "cookies": 40,
        "cookie_debt": 5,
        "reputation": 70,
    }

    class DummyDb:
        async def get_pet(self, user_id: int):
            return None

        async def get_active_loan(self, user_id: int):
            return None

    text = await wallet_text(DummyDb(), SimpleNamespace(restricted_reputation_threshold=0), user)
    assert "<pre>" in text
    assert "Печеньки" in text
    assert "40" in text
    assert "Долг" in text
    assert "Итого" in text
    assert "Комиссия" in text


def test_private_copy_describes_blocks_not_button_colors() -> None:
    from community_bot.texts import (
        APPLICATION_INTRO,
        GROUP_COMMANDS_TEXT,
        STORE_HELP_TEXT,
        WELCOME_MEMBER_TEXT,
        WELCOME_PENDING_TEXT,
        WELCOME_TEXT,
    )

    blob = "\n".join(
        [
            WELCOME_TEXT,
            WELCOME_PENDING_TEXT,
            WELCOME_MEMBER_TEXT,
            APPLICATION_INTRO,
            GROUP_COMMANDS_TEXT,
            STORE_HELP_TEXT,
        ]
    ).casefold()
    assert "синее" not in blob
    assert "прозрачный" not in blob
    assert "зелёный «магазин»" not in blob
    assert "красный «тикет»" not in blob
