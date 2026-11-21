"""Automatic admissions, chat invites and command scopes."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from community_bot.database import Database
from community_bot.main import configure_commands
from community_bot.onboarding_invites import (
    BROADCAST_MARKER,
    accept_waiting_applications,
    broadcast_entry_once,
    entry_keyboard,
    entry_text,
)
from community_bot.routers.group import auto_approve_join_request


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
    assert "чат" in entry_text().lower()
    invalid = SimpleNamespace(community_invite_url="javascript:alert(1)")
    assert entry_keyboard(invalid).inline_keyboard == []


async def test_one_time_broadcast_is_per_recipient_and_has_entry_button(tmp_path):
    db = Database(tmp_path / "invites.db")
    await db.initialize()
    await db.ensure_user(7)
    await db.ensure_user(8)
    client = bot()
    assert await broadcast_entry_once(client, db, settings()) == (2, 0)
    assert client.send_message.await_count == 2
    sent = client.send_message.call_args_list[0]
    assert sent.kwargs["parse_mode"] == "HTML"
    assert sent.kwargs["reply_markup"].inline_keyboard[0][0].url == "https://t.me/+NoraTest"
    assert await db.get_bot_state(f"{BROADCAST_MARKER}7") == "sent"
    assert await broadcast_entry_once(client, db, settings()) == (0, 0)
    assert client.send_message.await_count == 2


async def test_existing_pending_applications_are_approved_and_not_broadcast_twice(tmp_path):
    db = Database(tmp_path / "approved.db")
    await db.initialize()
    await db.ensure_user(99)
    await db.ensure_user(7)
    application_id = await db.create_application(7, {"name": "Анна"})
    client = bot()
    assert await accept_waiting_applications(client, db, settings()) == 1
    assert await db.has_approved_application(7)
    assert (await db.get_application(application_id))["status"] == "approved"
    assert await db.get_bot_state(f"{BROADCAST_MARKER}7") == "sent"
    assert await accept_waiting_applications(client, db, settings()) == 0
    assert await broadcast_entry_once(client, db, settings()) == (1, 0)


async def test_chat_join_requests_accepted_only_after_questionnaire(tmp_path):
    db = Database(tmp_path / "join.db")
    await db.initialize()
    await db.ensure_user(7)
    client = bot()
    req = SimpleNamespace(
        chat=SimpleNamespace(id=-100123456),
        from_user=SimpleNamespace(id=7),
    )
    await auto_approve_join_request(req, db, settings(), client)
    client.approve_chat_join_request.assert_not_awaited()
    application_id = await db.create_application(7, {"name": "Анна"})
    await db.decide_application(application_id, 99, "approved", None)
    await auto_approve_join_request(req, db, settings(), client)
    client.approve_chat_join_request.assert_awaited_once_with(-100123456, 7)
