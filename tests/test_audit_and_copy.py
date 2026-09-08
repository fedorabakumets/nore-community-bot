from community_bot.aliases import is_command_trigger, parse_trigger
from community_bot.audit import classify_status, format_audit_row, parse_moderation_args
from community_bot.keyboards import private_menu_keyboard
from community_bot.posting import parse_button_lines, render_post
from community_bot.texts import GROUP_COMMANDS_TEXT, STORE_HELP_TEXT
from community_bot.updates import latest_update, updates_text


def test_parse_trigger_slash_and_russian_alias() -> None:
    assert parse_trigger("/commands@bot") == ("commands", "")
    assert parse_trigger("команды") == ("commands", "")
    assert parse_trigger("Профиль") == ("profile", "")
    assert parse_trigger("магазин") == ("shop", "")
    assert parse_trigger("блэкджек 10") == ("blackjack", "10")
    assert parse_trigger("купить печеньки") == ("buycookies", "")
    assert parse_trigger("мут 30m спам") == ("mute", "30m спам")
    assert parse_trigger("привет") is None
    assert parse_trigger("/команды") == ("commands", "")
    assert parse_trigger("команды!") == ("commands", "")
    assert parse_trigger("Команды") == ("commands", "")
    assert is_command_trigger("халява")
    assert is_command_trigger("обновления")
    from community_bot.aliases import is_command_message

    assert is_command_message("/неизвестная")
    assert is_command_message("команды")
    assert not is_command_message("привет всем")


def test_moderation_status_red_yellow_green() -> None:
    duration, reason, explicit = parse_moderation_args("/mute 30m спам в чате")
    assert explicit is True
    assert reason == "спам в чате"
    assert duration.total_seconds() == 30 * 60
    assert classify_status("mute", reason=reason, default_duration=not explicit) == "green"
    assert classify_status("mute", reason="", default_duration=True) == "red"
    duration, reason, explicit = parse_moderation_args("мут спам")
    assert explicit is False
    assert reason == "спам"
    assert classify_status("mute", reason=reason, default_duration=not explicit) == "yellow"
    assert classify_status("unban", target="123", target_name="") == "yellow"
    assert classify_status("unmute", target="1", target_name="Анна") == "green"
    assert classify_status("delete_message", reason="фильтр ссылок") == "green"
    assert classify_status("chat_mute") == "yellow"


def test_audit_row_shows_name_not_raw_id() -> None:
    text = format_audit_row(
        {
            "actor_id": 1,
            "actor_name": "Анна",
            "action": "mute",
            "target": "2",
            "target_name": "Борис",
            "reason": "спам",
            "details": "30 мин",
            "status": "green",
            "created_at": "2026-09-08T10:00:00+00:00",
        }
    )
    assert "Анна" in text
    assert "Мут" in text
    assert "Борис" in text
    assert "🟢" in text
    assert "1" not in text.split("Анна")[0]


def test_commands_help_hides_staff_and_has_aliases() -> None:
    lowered = GROUP_COMMANDS_TEXT.casefold()
    assert "«команды»" in GROUP_COMMANDS_TEXT
    assert "«магазин»" in GROUP_COMMANDS_TEXT
    assert "«обновления»" in GROUP_COMMANDS_TEXT
    for leaked in ("/mute", "/warn", "/kick", "/ban", "/unban", "/givecookies", "/role"):
        assert leaked not in lowered
    assert "тамагочи" in STORE_HELP_TEXT.casefold()
    assert "приватный" in STORE_HELP_TEXT.casefold()
    assert "кастомн" in STORE_HELP_TEXT.casefold()


def test_post_templates_and_buttons() -> None:
    html = render_post("announce", "Собрание в субботу")
    assert "ОБЪЯВЛЕНИЕ" in html
    assert "Собрание в субботу" in html
    buttons, error = parse_button_lines("Магазин | https://t.me/nore | green\nПравила | https://example.com | blue")
    assert error is None
    assert len(buttons) == 2
    assert buttons[0]["style"] == "success"
    bad, err = parse_button_lines("без ссылки")
    assert not bad
    assert err


def test_updates_block_and_menu_button() -> None:
    latest = latest_update()
    assert latest.number == 3
    text = updates_text()
    assert "№3" in text
    assert "Журнал" in text
    markup = private_menu_keyboard()
    labels = [button.text for row in markup.inline_keyboard for button in row]
    assert "✨ Обновления" in labels


async def test_audit_log_persists_names_and_status(tmp_path) -> None:
    from pathlib import Path

    from community_bot.database import Database

    db = Database(Path(tmp_path) / "audit.db")
    await db.initialize()
    await db.ensure_user(10, telegram_name="Анна")
    await db.ensure_user(20, telegram_name="Борис")
    await db.log_admin_action(10, "mute", "20", "30 мин", reason="спам", actor_name="Анна", target_name="Борис")
    await db.log_admin_action(10, "warn", "20", reason="")
    rows = await db.recent_admin_actions()
    mute = next(row for row in rows if row["action"] == "mute")
    warn = next(row for row in rows if row["action"] == "warn")
    assert mute["actor_name"] == "Анна"
    assert mute["target_name"] == "Борис"
    assert mute["status"] == "green"
    assert warn["status"] == "red"


async def test_get_pet_still_returns_row_if_settle_fails(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from community_bot.database import Database

    db = Database(Path(tmp_path) / "pet.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Хозяин")
    await db.add_cookies(1, 80, "test")
    assert (await db.purchase_pet(1, "cat", "Булочка", 50))[0] is True

    async def boom(_user_id: int):
        raise RuntimeError("settle failed")

    monkeypatch.setattr(db, "settle_pet", boom)
    pet = await db.get_pet(1)
    assert pet is not None
    assert pet["name"] == "Булочка"
