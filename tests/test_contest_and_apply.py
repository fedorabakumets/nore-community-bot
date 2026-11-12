from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import Chat, ChatMemberBanned, ChatMemberLeft, ChatMemberMember, ChatMemberUpdated, User

from community_bot.access import miniapp_allowed, private_allowed
from community_bot.contest import contest_join_keyboard, contest_text
from community_bot.database import Database
from community_bot.helpers import application_block_reason
from community_bot.keyboards import admin_panel_keyboard, private_menu_keyboard
from community_bot.permissions import DEFAULT_STAFF_ROLES, PERM_CONTEST, PERM_ROLES_EDIT
from community_bot.routers.group import community_membership_changed


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


async def test_ban_resets_progress_and_requires_a_new_approved_application(tmp_path: Path) -> None:
    db = Database(tmp_path / "ban.db")
    await db.initialize()
    await db.ensure_user(7, "member", "Старое имя")
    await db.ensure_user(8)
    settings = SimpleNamespace(is_owner=lambda uid: False, moderator_ids=frozenset())
    answers = {"name": "Имя", "birth_date": "2000-01-01"}
    old = await db.create_application(7, answers)
    assert await db.decide_application(old, 8, "approved", None)
    await db.execute("UPDATE users SET cookies=70, cookie_debt=20, warnings=2, role='admin' WHERE user_id=7")
    await db.unlock_achievement(7, "test")
    await db.unlock_achievement(8, "other")
    await db.set_bot_state("nora_records:7", "{}")
    await db.execute("UPDATE users SET cookies=30 WHERE user_id=8")
    game_id, _ = await db.create_staked_game(-100123, "poker", 8, 10)
    joined, _ = await db.join_staked_game(game_id, 7)
    assert joined

    await db.reset_banned_user(7, None)
    user = await db.get_user(7)
    assert user["profile_name"] is user["birth_date"] is None
    assert user["cookies"] == user["cookie_debt"] == user["warnings"] == user["reputation"] == 0
    assert user["role"] == "member"
    assert not await db.fetchone("SELECT 1 FROM achievements WHERE user_id=7")
    assert await db.fetchone("SELECT 1 FROM achievements WHERE user_id=8")
    assert (await db.get_party_game(game_id))["status"] == "cancelled"
    assert (await db.get_user(8))["cookies"] == 30
    assert await db.get_bot_state("nora_records:7") is None
    assert (await db.get_application(old))["status"] == "reset"
    assert not await db.decide_application(old, 8, "approved", None)
    assert await db.fetchone("SELECT 1 FROM transactions WHERE user_id=7 AND kind='ban_reset' AND amount=-70")
    await db.restore_daily_reputation(datetime.now(UTC).date())
    assert (await db.get_user(7))["reputation"] == 0
    ban = await db.ban_reset_state(7)
    assert await application_block_reason(db, 7) == "Анкету можно заполнить после разбана."
    assert not await db.create_application(7, answers, ban_version=ban["version"])
    assert not await miniapp_allowed(db, settings, 7)

    await db.release_ban_reset(7)
    assert await application_block_reason(db, 7) is None
    assert not await private_allowed(db, settings, 7)
    assert not await db.create_application(7, answers)
    new = await db.create_application(7, answers, ban_version=ban["version"])
    assert new and new != old
    assert not await miniapp_allowed(db, settings, 7)
    assert await db.decide_application(new, 8, "approved", None)
    assert await private_allowed(db, settings, 7)
    assert await miniapp_allowed(db, settings, 7)
    assert (await db.get_user(7))["birth_date"] == "2000-01-01"

    await db.reset_banned_user(7, (datetime.now(UTC) - timedelta(seconds=1)).timestamp())
    assert await application_block_reason(db, 7) is None
    assert not await db.create_application(7, answers, ban_version=ban["version"])


async def test_telegram_ban_and_unban_require_reapplication_but_bot_kick_does_not(tmp_path: Path) -> None:
    db = Database(tmp_path / "membership.db")
    await db.initialize()
    await db.ensure_user(7)
    settings = SimpleNamespace(community_chat_id=-100123)
    chat = Chat(id=settings.community_chat_id, type="supergroup")
    member = User(id=7, first_name="Участник", is_bot=False)
    moderator = User(id=8, first_name="Модератор", is_bot=False)
    bot_user = User(id=9, first_name="Нора", is_bot=True)
    bot = AsyncMock()
    original = ChatMemberMember(user=member)
    banned = ChatMemberBanned(user=member, until_date=0)
    left = ChatMemberLeft(user=member)

    async def change(actor, before, after):
        event = ChatMemberUpdated(chat=chat, from_user=actor, date=datetime.now(UTC),
                                  old_chat_member=before, new_chat_member=after)
        await community_membership_changed(event, db, settings, bot)

    await change(bot_user, original, banned)
    assert not await db.ban_reset_state(7)
    await change(moderator, original, banned)
    assert db.ban_is_active(await db.ban_reset_state(7))
    await change(moderator, banned, left)
    assert not db.ban_is_active(await db.ban_reset_state(7))
    await change(member, left, original)
    bot.ban_chat_member.assert_awaited_once()
    bot.unban_chat_member.assert_awaited_once_with(chat.id, member.id, only_if_banned=True)
    assert not db.ban_is_active(await db.ban_reset_state(7))


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
