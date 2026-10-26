from types import SimpleNamespace

import pytest

from community_bot.database import Database
from community_bot.maintenance import REQUEST_VARIABLE, apply_requested_morning_rebuild


class Bot:
    def __init__(self):
        self.pins = {7, 99}
        self.fail_pin = False
        self.clears = 0

    async def unpin_all_chat_messages(self, chat_id):
        self.clears += 1
        self.pins.clear()

    async def pin_chat_message(self, chat_id, message_id, **kwargs):
        if self.fail_pin:
            raise RuntimeError("temporary pin error")
        self.pins.add(message_id)

    async def get_chat(self, chat_id):
        return SimpleNamespace(pinned_message=SimpleNamespace(message_id=8))


@pytest.fixture
def settings():
    return SimpleNamespace(community_chat_id=-100, timezone="Europe/Moscow")


async def test_no_pin_changes_without_explicit_request(monkeypatch, settings):
    monkeypatch.delenv(REQUEST_VARIABLE, raising=False)
    assert await apply_requested_morning_rebuild(None, None, settings)


async def test_rebuild_leaves_only_fresh_pin_and_is_once_per_request(tmp_path, monkeypatch, settings):
    monkeypatch.setenv(REQUEST_VARIABLE, "request-1")
    db = Database(tmp_path / "rebuild.db")
    await db.initialize()
    bot = Bot()
    sent = []

    async def publish(bot, db, settings, *, force):
        assert force
        sent.append(8)
        bot.pins.add(8)
        await db.set_bot_state("morning_pin_message_id", "8")
        return True

    monkeypatch.setattr("community_bot.maintenance.publish_morning_digest", publish)
    assert await apply_requested_morning_rebuild(bot, db, settings)
    assert bot.pins == {8} and sent == [8] and bot.clears == 1
    assert await db.get_bot_state("morning_rebuild_applied") == "request-1"
    bot.pins.add(55)  # A later user pin must survive subsequent scheduler passes.
    assert await apply_requested_morning_rebuild(bot, db, settings)
    assert bot.pins == {8, 55} and sent == [8] and bot.clears == 1


async def test_pin_retry_reuses_prepared_post(tmp_path, monkeypatch, settings):
    monkeypatch.setenv(REQUEST_VARIABLE, "request-retry")
    db = Database(tmp_path / "retry.db")
    await db.initialize()
    bot = Bot()
    bot.fail_pin = True
    sent = []

    async def publish(bot, db, settings, *, force):
        sent.append(8)
        await db.set_bot_state("morning_pin_message_id", "8")
        return True

    monkeypatch.setattr("community_bot.maintenance.publish_morning_digest", publish)
    assert not await apply_requested_morning_rebuild(bot, db, settings)
    assert await db.get_bot_state("morning_rebuild_applied") is None
    bot.fail_pin = False
    assert await apply_requested_morning_rebuild(bot, db, settings)
    assert sent == [8] and bot.pins == {8}


async def test_failed_publication_preserves_all_old_pins(tmp_path, monkeypatch, settings):
    monkeypatch.setenv(REQUEST_VARIABLE, "request-fail")
    db = Database(tmp_path / "failed.db")
    await db.initialize()
    bot = Bot()

    async def publish(*args, **kwargs):
        return False

    monkeypatch.setattr("community_bot.maintenance.publish_morning_digest", publish)
    assert not await apply_requested_morning_rebuild(bot, db, settings)
    assert bot.pins == {7, 99} and bot.clears == 0
    assert await db.get_bot_state("morning_rebuild_applied") is None
