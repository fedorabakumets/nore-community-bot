from pathlib import Path

from community_bot.contest import contest_join_keyboard, contest_text
from community_bot.database import Database
from community_bot.helpers import application_block_reason
from community_bot.keyboards import admin_panel_keyboard, private_menu_keyboard
from community_bot.permissions import DEFAULT_STAFF_ROLES, PERM_CONTEST, PERM_ROLES_EDIT


def test_apply_hidden_when_requested() -> None:
    shown = [button.callback_data for row in private_menu_keyboard().inline_keyboard for button in row]
    hidden = [
        button.callback_data
        for row in private_menu_keyboard(show_apply=False).inline_keyboard
        for button in row
    ]
    assert "menu:apply" not in shown
    assert "menu:apply" not in hidden
    assert "menu:question" in hidden
    assert "menu:shop" in shown
    assert "menu:wallet" in shown
    assert "menu:verify" not in shown
    assert "menu:profile" in shown
    assert "menu:pet" in shown
    assert "menu:notices" in shown


def test_contest_button_only_with_permission() -> None:
    admin_perms = list(DEFAULT_STAFF_ROLES[2][3])
    owner = [button.callback_data for row in admin_panel_keyboard(["*"]).inline_keyboard for button in row]
    admin = [button.callback_data for row in admin_panel_keyboard(admin_perms).inline_keyboard for button in row]
    assert "admin:contest" in owner
    assert "admin:contest" not in admin
    assert PERM_CONTEST not in admin_perms
    assert PERM_ROLES_EDIT not in admin_perms


def test_participate_button_turns_into_count() -> None:
    start = contest_join_keyboard(7, 0).inline_keyboard[0][0]
    joined = contest_join_keyboard(7, 3).inline_keyboard[0][0]
    assert start.text == "Участвовать"
    assert start.callback_data == "contest:join:7"
    assert joined.text == "Участвуете (3)"
    assert joined.callback_data == "contest:join:7"
    text = contest_text(50, "До пятницы.")
    assert "50" in text
    assert "До пятницы." in text
    assert "Участники ничего не платят" in text


async def test_approved_application_cannot_be_resubmitted(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Анна")
    first = await db.create_application(1, {"name": "Анна"})
    assert first
    assert await db.create_application(1, {"name": "Дубль"}) == 0
    await db.decide_application(first, 9, "approved", None)
    assert await db.has_approved_application(1)
    assert "проходил" in (await application_block_reason(db, 1) or "")
    assert await db.create_application(1, {"name": "Ещё раз"}) == 0


async def test_rejected_application_can_be_sent_again(tmp_path: Path) -> None:
    db = Database(tmp_path / "app2.db")
    await db.initialize()
    await db.ensure_user(2, telegram_name="Борис")
    first = await db.create_application(2, {"name": "Борис"})
    await db.decide_application(first, 9, "rejected", "нет")
    assert await application_block_reason(db, 2) is None
    second = await db.create_application(2, {"name": "Борис"})
    assert second and second != first


async def test_cookie_contest_join_count_and_draw(tmp_path: Path) -> None:
    db = Database(tmp_path / "contest.db")
    await db.initialize()
    await db.ensure_user(10, telegram_name="Владелец")
    await db.ensure_user(11, telegram_name="Аня")
    await db.ensure_user(12, telegram_name="Боря")
    contest_id, error = await db.create_cookie_contest(-100, 10, 40, "тело")
    assert contest_id, error
    ok, _, count = await db.join_cookie_contest(contest_id, 11)
    assert ok is True
    assert count == 1
    ok, err, count = await db.join_cookie_contest(contest_id, 11)
    assert ok is False
    assert "уже" in err.casefold()
    assert count == 1
    ok, _, count = await db.join_cookie_contest(contest_id, 12)
    assert ok is True
    assert count == 2
    ok, _, result = await db.draw_cookie_contest(contest_id)
    assert ok is True
    assert result is not None
    assert result["players"] == 2
    assert result["prize"] == 40
    winner = await db.get_user(int(result["winner_id"]))
    assert winner is not None
    assert int(winner["cookies"]) == 40
    again, error = await db.create_cookie_contest(-100, 10, 10, "ещё")
    assert again
    assert error == "ok"
