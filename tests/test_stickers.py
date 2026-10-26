import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import FSInputFile

from community_bot.database import Database
from community_bot.ephemeral import current_reply_ttl, reply_ttl
from community_bot.stickers import STICKER_PACK_URL, send_context_sticker, send_pack_invitation


@pytest.fixture
async def sticker_db(tmp_path, monkeypatch):
    import community_bot.stickers as stickers

    assets = tmp_path / "stickers"
    assets.mkdir()
    for kind in ("update", "event", "morning"):
        (assets / f"{kind}.webp").write_bytes(b"isolated test file")
    monkeypatch.setattr(stickers, "_ASSETS", assets)
    db = Database(tmp_path / "stickers.db")
    await db.initialize()
    return db


async def test_concurrent_context_sticker_is_sent_once_and_dedup_survives_restart(sticker_db):
    bot = SimpleNamespace(send_sticker=AsyncMock(return_value=SimpleNamespace(message_id=101)))
    results = await asyncio.gather(*(
        send_context_sticker(bot, sticker_db, -100123, "update", 10) for _ in range(2)
    ))
    assert results == [True, True]
    bot.send_sticker.assert_awaited_once()
    assert await send_context_sticker(bot, Database(sticker_db.path), -100123, "update", 10)
    bot.send_sticker.assert_awaited_once()
    assert await send_context_sticker(bot, sticker_db, -100123, "update", 11)
    assert bot.send_sticker.await_count == 2
    assert isinstance(bot.send_sticker.call_args.kwargs["sticker"], FSInputFile)


async def test_telegram_failure_does_not_mark_delivery_and_can_be_retried(sticker_db):
    bot = SimpleNamespace(send_sticker=AsyncMock(side_effect=RuntimeError("API failed")))
    assert not await send_context_sticker(bot, sticker_db, -100123, "event", 10)
    assert await sticker_db.get_bot_state("context_sticker:event:-100123:10") is None
    bot.send_sticker.side_effect = None
    bot.send_sticker.return_value = SimpleNamespace(message_id=101)
    assert await send_context_sticker(bot, sticker_db, -100123, "event", 10)


async def test_failed_context_sticker_is_retried_from_persistent_outbox_after_restart(sticker_db):
    from community_bot.stickers import retry_pending_stickers

    failing_bot = SimpleNamespace(send_sticker=AsyncMock(side_effect=RuntimeError("API failed")))
    assert not await send_context_sticker(failing_bot, sticker_db, -100123, "morning", 10)
    pending_key = "context_sticker_pending:morning:-100123:10"
    assert await sticker_db.get_bot_state(pending_key)
    restarted_db = Database(sticker_db.path)
    recovered_bot = SimpleNamespace(send_sticker=AsyncMock(return_value=SimpleNamespace(message_id=55)))
    await retry_pending_stickers(recovered_bot, restarted_db)
    recovered_bot.send_sticker.assert_awaited_once()
    assert await sticker_db.get_bot_state(pending_key) == ""
    await retry_pending_stickers(recovered_bot, restarted_db)
    recovered_bot.send_sticker.assert_awaited_once()


async def test_update_sticker_failure_does_not_block_post_and_outbox_delivers_later(sticker_db, monkeypatch):
    from community_bot import main
    from community_bot.stickers import retry_pending_stickers
    from community_bot.updates import announcement_key, latest_update

    monkeypatch.setattr(main, "cover_path_for", lambda item: None)
    monkeypatch.setattr(main, "publish_member_update", AsyncMock(return_value="https://telegra.ph/test"))
    monkeypatch.setattr(main, "publish_staff_update", AsyncMock(return_value=None))
    monkeypatch.setattr(main, "notify_staff_update", AsyncMock())
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=60)),
        send_sticker=AsyncMock(side_effect=RuntimeError("sticker API failed")),
        pin_chat_message=AsyncMock(),
    )
    await main.announce_latest_update(bot, sticker_db, SimpleNamespace(community_chat_id=-100123))
    bot.pin_chat_message.assert_awaited_once()
    assert await sticker_db.get_bot_state("last_announced_update") == announcement_key(latest_update())
    bot.send_sticker.side_effect = None
    bot.send_sticker.return_value = SimpleNamespace(message_id=61)
    await retry_pending_stickers(bot, Database(sticker_db.path))
    assert bot.send_sticker.await_count == 2
    bot.send_message.assert_awaited_once()


async def test_context_sticker_is_protected_from_group_auto_deletion(sticker_db):
    async def send(**kwargs):
        assert current_reply_ttl() is None
        assert kwargs["disable_notification"] is True
        return SimpleNamespace(message_id=101)

    with reply_ttl(30):
        assert await send_context_sticker(SimpleNamespace(send_sticker=send), sticker_db, -100123, "morning", 10)
        assert current_reply_ttl() == 30


async def test_missing_asset_or_fake_bot_does_not_break_successful_post(sticker_db, monkeypatch, tmp_path):
    import community_bot.stickers as stickers

    assert not await send_context_sticker(SimpleNamespace(), sticker_db, -100123, "event", 10)
    monkeypatch.setattr(stickers, "_ASSETS", tmp_path / "missing")
    assert not await send_context_sticker(SimpleNamespace(), sticker_db, -100123, "event", 10)
    assert not await send_context_sticker(SimpleNamespace(), sticker_db, -100123, "unknown", 10)


async def test_pack_invitation_link_still_works_when_preview_is_unavailable():
    message = SimpleNamespace(answer=AsyncMock(), chat=SimpleNamespace(id=-100123))
    bot = SimpleNamespace(get_sticker_set=AsyncMock(side_effect=RuntimeError("pack preview failed")))
    assert await send_pack_invitation(message, bot)
    markup = message.answer.call_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].url == STICKER_PACK_URL
    assert "Бабушка" in message.answer.call_args.args[0]


async def test_pack_preview_uses_existing_public_pack_sticker_and_keeps_it_in_chat():
    message = SimpleNamespace(answer=AsyncMock(), chat=SimpleNamespace(id=-100123))

    async def send(**kwargs):
        assert current_reply_ttl() is None
        assert kwargs["sticker"] == "existing-pack-file-id"

    bot = SimpleNamespace(
        get_sticker_set=AsyncMock(return_value=SimpleNamespace(stickers=[SimpleNamespace(file_id="existing-pack-file-id")])),
        send_sticker=send,
    )
    with reply_ttl(30):
        assert await send_pack_invitation(message, bot)
        assert current_reply_ttl() == 30


class StudioState:
    def __init__(self, **data):
        from community_bot.states import AdminFlow

        self.state = AdminFlow.post_preview.state
        self.data = data

    async def get_state(self):
        return self.state

    async def get_data(self):
        return dict(self.data)

    async def set_state(self, state):
        self.state = state.state

    async def update_data(self, **data):
        self.data.update(data)

    async def set_data(self, data):
        self.data = dict(data)

    async def clear(self):
        self.state = None
        self.data = {}


async def test_event_post_sticker_poll_order_and_poll_retry_does_not_duplicate_sticker(sticker_db, monkeypatch):
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import SendMessage

    from community_bot.routers import private

    order = []

    async def post(*args):
        order.append("post")
        return SimpleNamespace(message_id=20)

    async def sticker(**kwargs):
        order.append("sticker")
        return SimpleNamespace(message_id=21)

    async def poll(*args):
        order.append("poll")
        if order.count("poll") == 1:
            raise TelegramBadRequest(method=SendMessage(chat_id=-100123, text="test"), message="test API failure")

    monkeypatch.setattr(private, "_admin_callback", AsyncMock(return_value=True))
    monkeypatch.setattr("community_bot.posting.send_studio_post", post)
    monkeypatch.setattr("community_bot.posting.send_studio_poll", poll)
    monkeypatch.setattr("community_bot.notify.fanout", AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=1, full_name="Админ"), answer=AsyncMock(),
        message=SimpleNamespace(answer=AsyncMock()),
    )
    settings = SimpleNamespace(community_chat_id=-100123)
    bot = SimpleNamespace(send_sticker=sticker)
    state = StudioState(post_template="event", post_body="Встреча в субботу", post_poll={"question": "Идём?"})
    await private._admin_post_send(callback, state, sticker_db, settings, bot)
    assert order == ["post", "sticker", "poll"]
    await private._admin_post_send(callback, state, sticker_db, settings, bot)
    assert order == ["post", "sticker", "poll", "poll"]
    assert (await sticker_db.list_studio_events())[0]["message_id"] == 20


async def test_failed_studio_post_and_preview_never_emit_context_sticker(sticker_db, monkeypatch):
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import SendMessage

    from community_bot.routers import private

    monkeypatch.setattr(private, "_admin_callback", AsyncMock(return_value=True))
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=1, full_name="Админ"), answer=AsyncMock(),
        message=SimpleNamespace(answer=AsyncMock(), chat=SimpleNamespace(id=1)),
    )
    bot = SimpleNamespace(send_sticker=AsyncMock())
    state = StudioState(post_template="event", post_body="Встреча", post_rsvp="e-test")
    sent = AsyncMock(return_value=SimpleNamespace(message_id=20))
    monkeypatch.setattr("community_bot.posting.send_studio_post", sent)
    await private._show_post_preview(callback.message, await state.get_data(), bot)
    bot.send_sticker.assert_not_awaited()
    sent.side_effect = TelegramBadRequest(method=SendMessage(chat_id=-100123, text="test"), message="test failure")
    await private._admin_post_send(callback, state, sticker_db, SimpleNamespace(community_chat_id=-100123), bot)
    bot.send_sticker.assert_not_awaited()
    assert await sticker_db.list_studio_events() == []


async def test_update_announcement_sticker_is_not_duplicated_on_startup(sticker_db, monkeypatch):
    from community_bot import main

    order = []

    async def post(*args, **kwargs):
        order.append("post")
        return SimpleNamespace(message_id=30)

    async def sticker(**kwargs):
        order.append("sticker")
        return SimpleNamespace(message_id=31)

    async def pin(*args, **kwargs):
        order.append("pin")

    monkeypatch.setattr(main, "cover_path_for", lambda item: None)
    monkeypatch.setattr(main, "publish_member_update", AsyncMock(return_value="https://telegra.ph/test"))
    monkeypatch.setattr(main, "publish_staff_update", AsyncMock(return_value=None))
    monkeypatch.setattr(main, "notify_staff_update", AsyncMock())
    bot = SimpleNamespace(send_message=post, send_sticker=sticker, pin_chat_message=pin)
    settings = SimpleNamespace(community_chat_id=-100123)
    await main.announce_latest_update(bot, sticker_db, settings)
    assert order == ["post", "sticker", "pin"]
    await main.announce_latest_update(bot, sticker_db, settings)
    assert order == ["post", "sticker", "pin"]


async def test_morning_pin_retry_keeps_single_followup_sticker(sticker_db):
    from community_bot.morning import _pin_morning

    bot = SimpleNamespace(
        send_sticker=AsyncMock(return_value=SimpleNamespace(message_id=41)),
        pin_chat_message=AsyncMock(side_effect=[RuntimeError("pin failed"), None]),
    )
    assert not await _pin_morning(bot, sticker_db, -100123, 40, "2026-10-26")
    assert await _pin_morning(bot, sticker_db, -100123, 40, "2026-10-26")
    bot.send_sticker.assert_awaited_once()
    assert await sticker_db.get_bot_state("morning_digest_day") == "2026-10-26"
