from community_bot.keyboards import compact_profile_keyboard, private_menu_keyboard
from community_bot.notify import CHANNELS, deliver_digests, emit, notices_keyboard, notices_text
from community_bot.profile_fill import cabinet_profile_text, profile_fill_percent


def test_menu_has_unread_badge_and_no_duplicates() -> None:
    data = [button.callback_data for row in private_menu_keyboard(unread=2).inline_keyboard for button in row]
    labels = [button.text for row in private_menu_keyboard(unread=2).inline_keyboard for button in row]
    assert "menu:profile" in data
    assert "menu:pet" in data
    assert "menu:notices" in data
    assert any("Уведомления (2)" in text for text in labels)
    assert "menu:shop" not in data
    assert "menu:wallet" not in data
    assert "menu:question" not in data
    assert "menu:verify" not in data


def test_cabinet_profile_is_short_and_has_fields() -> None:
    user = {
        "user_id": 5,
        "profile_name": "Нора",
        "telegram_name": "Nora",
        "age": 22,
        "hobbies": "",
        "profile_bio": "",
        "avatar_file_id": "",
        "bio_warning": 1,
        "profile_private": 0,
    }
    assert profile_fill_percent(user) == 40
    text = cabinet_profile_text(user)
    assert "40%" in text
    assert "серебра" in text
    assert "Предупреждение" in text
    assert "синее" not in text.casefold()
    markup = compact_profile_keyboard(user)
    labels = [button.text for row in markup.inline_keyboard for button in row]
    assert any(text.startswith("Имя") and "✓" in text for text in labels)
    assert any("Возраст" in text and "✓" in text for text in labels)
    assert any("Почему предупреждение" in text for text in labels)


async def test_notify_default_off_and_digest(tmp_path) -> None:
    from pathlib import Path

    from community_bot.database import Database

    db = Database(Path(tmp_path) / "notify.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="A")
    await db.ensure_user(2, telegram_name="B")

    class Bot:
        def __init__(self) -> None:
            self.sent: list[tuple[int, str]] = []

        async def send_message(self, user_id: int, text: str, parse_mode: str | None = None):
            del parse_mode
            self.sent.append((user_id, text))

    bot = Bot()
    assert await db.notify_channel_on(1, "pet") is False
    assert await emit(bot, db, 1, "pet", "голод") is False
    assert bot.sent == []
    assert await db.notify_unread_count(1) == 0

    assert await db.notify_toggle_enabled(1, "pet") is True
    assert await emit(bot, db, 1, "pet", "голод") is True
    assert bot.sent == [(1, "голод")]
    assert await db.notify_unread_count(1) == 1

    bot.sent.clear()
    assert await db.notify_toggle_digest(1, "games") is True
    assert await db.notify_toggle_enabled(1, "games") is True
    assert await emit(bot, db, 1, "games", "ваш ход") is True
    assert bot.sent == []
    pending = await db.notify_pending_digest()
    assert any(row["text"] == "ваш ход" for row in pending)
    sent = await deliver_digests(bot, db)
    assert sent == 1
    assert bot.sent and "Дайджест" in bot.sent[0][1]
    assert await db.notify_pending_digest() == []

    await db.notify_toggle_enabled(2, "shop")
    assert await db.list_channel_subscribers("shop") == [2]
    assert await db.list_channel_subscribers("pet") == [1]


async def test_vitrine_close_flag(tmp_path) -> None:
    from pathlib import Path

    from community_bot.database import Database

    db = Database(Path(tmp_path) / "vit.db")
    await db.initialize()
    await db.set_bot_state("shop_featured", "rep_shield")
    await db.set_bot_state("shop_featured_stock", "1")
    assert await db.consume_vitrine("rep_shield") is True
    assert await db.get_bot_state("shop_featured") == ""
    await db.set_bot_state("shop_featured", "rep_shield")
    await db.set_bot_state("shop_featured_stock", "2")
    assert await db.consume_vitrine("rep_shield") is False
    assert await db.get_bot_state("shop_featured_stock") == "1"


def test_notices_copy_lists_channels() -> None:
    text = notices_text({}, [], 0)
    for label, _hint in CHANNELS.values():
        assert label.split()[1] in text or label in text
    assert "выкл" in text
    markup = notices_keyboard({})
    data = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert "n:ch:pet" in data
    assert "n:dg:games" in data
    assert "n:read" in data
