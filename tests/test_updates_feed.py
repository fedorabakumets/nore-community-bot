from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.enums import ChatMemberStatus

from community_bot import updates_feed
from community_bot.community_scope import CommunityScopeMiddleware


class FakeDB:
    def __init__(self):
        self.state = {}

    async def get_bot_state(self, key):
        return self.state.get(key)

    async def set_bot_state(self, key, value):
        self.state[key] = value

    async def execute(self, query, params):
        self.state.pop(params[0], None)


def group(username="noranoranoranoranora", chat_id=-100123):
    return SimpleNamespace(type="supergroup", username=username, id=chat_id)


async def test_publish_once_and_edit(monkeypatch):
    monkeypatch.setenv("UPDATES_CHAT_ID", "@noranoranoranoranora")
    monkeypatch.setattr(updates_feed, "is_production", lambda: True)
    db = FakeDB()
    bot = AsyncMock()
    bot.get_chat.return_value = group()
    bot.send_rich_message.return_value = SimpleNamespace(message_id=42)
    settings = SimpleNamespace(community_chat_id=-100999)
    await updates_feed.run(db, settings, bot)
    await updates_feed.run(db, settings, bot)
    assert bot.send_rich_message.await_count == 1
    assert bot.send_rich_message.call_args.args == (-100123,)
    assert bot.pin_chat_message.await_count == 1
    changed = dict(updates_feed.POSTS[0], revision="2")
    monkeypatch.setattr(updates_feed, "POSTS", (changed,))
    await updates_feed.run(db, settings, bot)
    bot.edit_message_text.assert_awaited_once()
    assert bot.edit_message_text.call_args.kwargs["message_id"] == 42
    assert bot.send_rich_message.await_count == 1


async def test_no_publish_to_primary_or_wrong_chat(monkeypatch):
    monkeypatch.setattr(updates_feed, "is_production", lambda: True)
    monkeypatch.setenv("UPDATES_CHAT_ID", "@noranoranoranoranora")
    bot = AsyncMock()
    db = FakeDB()
    bot.get_chat.return_value = group(chat_id=-100999)
    await updates_feed.run(db, SimpleNamespace(community_chat_id=-100999), bot)
    bot.get_chat.return_value = group(username="different")
    await updates_feed.run(db, SimpleNamespace(community_chat_id=-100999), bot)
    bot.send_rich_message.assert_not_awaited()


async def test_feed_ignored_without_leaving_other_groups(monkeypatch):
    monkeypatch.setenv("UPDATES_CHAT_ID", "@noranoranoranoranora")
    monkeypatch.setattr(updates_feed, "run", AsyncMock())
    handler = AsyncMock()
    bot = AsyncMock()
    db = FakeDB()
    data = {"event_chat": group(), "settings": SimpleNamespace(community_chat_id=-100999),
            "bot": bot, "db": db}
    event = SimpleNamespace(my_chat_member=SimpleNamespace(
        new_chat_member=SimpleNamespace(status=ChatMemberStatus.ADMINISTRATOR),
    ))
    middleware = CommunityScopeMiddleware()
    await middleware(handler, event, data)
    updates_feed.run.assert_awaited_once()
    handler.assert_not_awaited()
    bot.leave_chat.assert_not_awaited()
    data["event_chat"] = group(username="unrelated")
    await middleware(handler, event, data)
    bot.leave_chat.assert_awaited_once()


async def test_uncertain_delivery_does_not_duplicate(monkeypatch):
    monkeypatch.setenv("UPDATES_CHAT_ID", "@noranoranoranoranora")
    monkeypatch.setattr(updates_feed, "is_production", lambda: True)
    db = FakeDB()
    bot = AsyncMock()
    bot.get_chat.return_value = group()
    bot.send_rich_message.side_effect = TimeoutError()
    settings = SimpleNamespace(community_chat_id=-100999)
    await updates_feed.run(db, settings, bot)
    await updates_feed.run(db, settings, bot)
    assert bot.send_rich_message.await_count == 1


async def test_channel_publish_and_membership(monkeypatch):
    monkeypatch.setenv("UPDATES_CHAT_ID", "@noranoranoranoranora")
    monkeypatch.setattr(updates_feed, "is_production", lambda: True)
    chat = group()
    chat.type = "channel"
    bot = AsyncMock()
    bot.get_chat.return_value = chat
    bot.send_rich_message.return_value = SimpleNamespace(message_id=42)
    db = FakeDB()
    settings = SimpleNamespace(community_chat_id=-100999)
    event = SimpleNamespace(my_chat_member=SimpleNamespace(
        new_chat_member=SimpleNamespace(status=ChatMemberStatus.ADMINISTRATOR),
    ))
    handler = AsyncMock()
    await CommunityScopeMiddleware()(handler, event, {
        "event_chat": chat, "settings": settings, "db": db, "bot": bot,
    })
    bot.send_rich_message.assert_awaited_once()
    handler.assert_not_awaited()
    bot.leave_chat.assert_not_awaited()
