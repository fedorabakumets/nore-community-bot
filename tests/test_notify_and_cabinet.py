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
    assert "menu:shop" in data
    assert "menu:wallet" in data
    assert "menu:question" in data
    assert len(data) == len(set(data))
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
    assert "бронзы" in text
    markup = compact_profile_keyboard(user)
    labels = [button.text for row in markup.inline_keyboard for button in row]
    assert any(text.startswith("Имя") and "✓" in text for text in labels)
    assert any("Возраст" in text and "✓" in text for text in labels)
    assert any("Варны" in text for text in labels)
    assert not any("Почему предупреждение" in text for text in labels)


async def test_notify_default_off_and_digest(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from community_bot.database import Database

    db = Database(Path(tmp_path) / "notify.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="A")
    await db.ensure_user(2, telegram_name="B")

    sent_notices = []

    async def send(bot, db, user_id, sender, title, details, target, *, event_key):
        sent_notices.append((user_id, title, details))

    monkeypatch.setattr("community_bot.notify.send_service_notification", send)
    bot = object()
    assert await db.notify_channel_on(1, "pet") is False
    assert await emit(bot, db, 1, "pet", "голод") is False
    assert sent_notices == []
    assert await db.notify_unread_count(1) == 0

    assert await db.notify_toggle_enabled(1, "pet") is True
    assert await emit(bot, db, 1, "pet", "голод") is True
    assert sent_notices == [(1, CHANNELS["pet"][0], "голод")]
    assert await db.notify_unread_count(1) == 1

    sent_notices.clear()
    assert await db.notify_toggle_digest(1, "games") is True
    assert await db.notify_toggle_enabled(1, "games") is True
    assert await emit(bot, db, 1, "games", "ваш ход") is True
    assert sent_notices == []
    pending = await db.notify_pending_digest()
    assert any(row["text"] == "ваш ход" for row in pending)
    sent = await deliver_digests(bot, db)
    assert sent == 1
    assert sent_notices == [(1, "Дайджест за день", "• ваш ход")]
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
