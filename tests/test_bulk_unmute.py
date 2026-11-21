from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.methods import SendMessage
from aiogram.types import ChatMemberBanned, ChatMemberMember, ChatMemberRestricted, ChatPermissions, Update, User
from test_nora_commands_release import message
from test_studio_rsvp import TelegramSession

from community_bot.command_registry import restore_defaults
from community_bot.config import load_settings
from community_bot.database import Database
from community_bot.main import create_dispatcher


@pytest.fixture
async def dispatcher():
    dp = create_dispatcher()
    try:
        yield dp
    finally:
        await dp.storage.close()
        for router in dp.sub_routers:
            router._parent_router = None


@pytest.mark.parametrize(("uid", "chat_id", "allowed"), [
    (7, -100123, True),
    (7, 7, True),
    (8, -100123, False),
    (7, -100999, False),
])
async def test_bulk_unmute_runs_only_for_staff_in_community_or_dm(
    tmp_path, monkeypatch, dispatcher, uid, chat_id, allowed,
):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("BOT_TOKEN", "123456:test")
    monkeypatch.setenv("OWNER_ID", "1")
    monkeypatch.setenv("COMMUNITY_CHAT_ID", "-100123")
    monkeypatch.setenv("MODERATOR_IDS", "")
    monkeypatch.setattr("community_bot.access.sync_menu", AsyncMock())
    settings = load_settings()
    restore_defaults()

    db = Database(tmp_path / "bulk-unmute.sqlite")
    await db.initialize()
    for user_id in range(7, 12):
        await db.ensure_user(user_id, telegram_name=f"Участник {user_id}")
    await db.set_role(7, "moderator")
    await db.set_role(11, "moderator")

    def user(user_id):
        return User(id=user_id, is_bot=False, first_name=f"Участник {user_id}")

    def restricted(user_id):
        return ChatMemberRestricted(
            user=user(user_id), is_member=True, until_date=0,
            **dict.fromkeys(ChatPermissions.model_fields, False),
        )

    async def member(group_id, user_id):
        assert group_id == settings.community_chat_id
        if user_id == bot.id:
            return SimpleNamespace(status="administrator", can_restrict_members=True)
        if user_id == 10:
            return ChatMemberBanned(user=user(user_id), until_date=0)
        if user_id in {9, 11}:
            return restricted(user_id)
        return ChatMemberMember(user=user(user_id))

    permissions = ChatPermissions(can_send_messages=False, can_send_photos=False, can_invite_users=True)
    session = TelegramSession()
    async with Bot(settings.bot_token, session=session) as bot:
        get_chat = AsyncMock(return_value=SimpleNamespace(type="supergroup", permissions=permissions))
        set_permissions = AsyncMock(return_value=True)
        restrict = AsyncMock(return_value=True)
        monkeypatch.setattr(bot, "get_chat", get_chat)
        monkeypatch.setattr(bot, "get_chat_member", AsyncMock(side_effect=member))
        monkeypatch.setattr(bot, "set_chat_permissions", set_permissions)
        monkeypatch.setattr(bot, "restrict_chat_member", restrict)

        event = message("Нора размут всех", uid=uid, chat_id=chat_id)
        await dispatcher.feed_update(bot, Update(update_id=1, message=event), db=db, settings=settings)
        replies = [call.text for call in session.calls if isinstance(call, SendMessage)]

        if allowed:
            get_chat.assert_awaited_once_with(settings.community_chat_id)
            set_permissions.assert_awaited_once_with(
                settings.community_chat_id, permissions.model_copy(update={"can_send_messages": True}),
                use_independent_chat_permissions=True,
            )
            restrict.assert_awaited_once()
            assert restrict.await_args.args == (settings.community_chat_id, 9)
            assert all(restrict.await_args.kwargs["permissions"].model_dump().values())
            assert "Личных мутов снято: 1." in replies[0]
            assert "Пропущено по рангу или статусу допуска: 1." in replies[0]
            audit = await db.fetchone("SELECT actor_id, action FROM admin_audit_log WHERE action = 'unmute_all'")
            assert audit == {"actor_id": uid, "action": "unmute_all"}
        else:
            get_chat.assert_not_awaited()
            set_permissions.assert_not_awaited()
            restrict.assert_not_awaited()
            assert replies == (["Недостаточно прав для этой команды."] if chat_id == -100123 else [])
