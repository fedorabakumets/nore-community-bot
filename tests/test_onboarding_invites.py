"""Manual admissions, chat invites and command scopes."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from community_bot.database import Database
from community_bot.main import configure_commands
from community_bot.onboarding_invites import entry_keyboard
from community_bot.routers.group import community_join_request
from community_bot.routers.life import captcha_join_request, captcha_ok
from community_bot.routers.private import _notify_application_decision


def settings():
    return SimpleNamespace(
        owner_id=99,
        is_owner=lambda uid: uid == 99,
        moderator_ids=frozenset(),
        reviewers=frozenset({99}),
        community_chat_id=-100123456,
        community_invite_url="https://t.me/+NoraTest",
    )


def bot():
    return SimpleNamespace(
        me=AsyncMock(return_value=SimpleNamespace(username="nora_community_bot")),
        send_message=AsyncMock(),
        approve_chat_join_request=AsyncMock(),
    )


async def test_command_menu_keeps_commands_only_in_community_chat():
    client = SimpleNamespace(delete_my_commands=AsyncMock(), set_my_commands=AsyncMock())
    await configure_commands(client, -100123456)
    private = [call for call in client.set_my_commands.call_args_list
               if call.kwargs['scope'].type == 'all_private_chats']
    group = [call for call in client.set_my_commands.call_args_list
             if call.kwargs['scope'].type == 'chat']
    assert len(private) == len(group) == 2
    assert all([command.command for command in call.args[0]] == ['start'] for call in private)
    assert all([command.command for command in call.args[0]] == ['commands'] for call in group)


def test_invite_card_has_real_join_button_and_no_invalid_link():
    markup = entry_keyboard(settings(), bot_username="nora_community_bot")
    assert markup.inline_keyboard[0][0].url == "https://t.me/+NoraTest"
    assert markup.inline_keyboard[1][0].url.endswith("?startapp")
    invalid = SimpleNamespace(community_invite_url="javascript:alert(1)")
    assert entry_keyboard(invalid).inline_keyboard == []


async def test_chat_join_requests_stay_pending_even_with_an_approved_questionnaire(tmp_path, monkeypatch):
    db = Database(tmp_path / "join.db")
    await db.initialize()
    await db.ensure_user(7)
    client = bot()
    remember = AsyncMock()
    monkeypatch.setattr("community_bot.referral_campaign.remember_request", remember)
    req = SimpleNamespace(
        chat=SimpleNamespace(id=-100123456),
        from_user=SimpleNamespace(id=7),
        invite_link=SimpleNamespace(invite_link=settings().community_invite_url),
        approve=AsyncMock(),
        decline=AsyncMock(),
    )
    await captcha_join_request(req, db, client, settings())
    await community_join_request(req, db, settings())
    application_id = await db.create_application(7, {"name": "Анна"})
    await db.decide_application(application_id, 99, "approved", None)
    await community_join_request(req, db, settings())
    assert remember.await_count == 2
    req.approve.assert_not_awaited()
    req.decline.assert_not_awaited()
    client.approve_chat_join_request.assert_not_awaited()


async def test_legacy_captcha_button_does_not_approve_telegram_join(tmp_path):
    db = Database(tmp_path / "captcha.db")
    await db.initialize()
    client = bot()
    client.restrict_chat_member = AsyncMock()
    await db.add_captcha(7, -100123456)
    callback = SimpleNamespace(
        data="captcha:ok:-100123456", from_user=SimpleNamespace(id=7), message=None, answer=AsyncMock(),
    )
    await captcha_ok(callback, db, client, settings())
    client.restrict_chat_member.assert_awaited_once()
    client.approve_chat_join_request.assert_not_awaited()


async def test_manual_admission_accepts_pending_telegram_join(tmp_path):
    db = Database(tmp_path / "pending_join.db")
    await db.initialize()
    await db.ensure_user(7)
    application_id = await db.create_application(7, {"name": "Анна"})
    client = bot()
    await _notify_application_decision(client, db, settings(), application_id, 99, "approved", None)
    client.approve_chat_join_request.assert_not_awaited()
    await db.decide_application(application_id, 99, "approved", None)
    await _notify_application_decision(client, db, settings(), application_id, 99, "approved", None)
    client.approve_chat_join_request.assert_awaited_once_with(-100123456, 7)
    assert client.send_message.await_count >= 2
