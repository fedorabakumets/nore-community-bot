"""Check that the multipart story reconstructs the exact uploaded MP4."""
import hashlib

from community_bot import dedzytwo_story


def test_dedzytwo_video_integrity(tmp_path, monkeypatch):
    monkeypatch.setattr(dedzytwo_story, "TARGET", tmp_path / "dedzytwo.mp4")
    output = dedzytwo_story._assemble()
    assert output.stat().st_size == dedzytwo_story.EXPECTED_SIZE
    assert hashlib.sha256(output.read_bytes()).hexdigest() == dedzytwo_story.EXPECTED_SHA256
    assert dedzytwo_story._assemble() == output


async def _story_test_context(tmp_path, *, fail_first_send=False):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from community_bot.database import Database

    db = Database(tmp_path / "story-likes.db")
    await db.initialize()
    await db.ensure_user(7, telegram_name="Анна")
    await db.ensure_user(8, telegram_name="Артист")
    await db.execute("UPDATE users SET username='dedzytwo' WHERE user_id=8")
    bot = SimpleNamespace(send_message=AsyncMock())
    if fail_first_send:
        bot.send_message.side_effect = [RuntimeError("temporary Telegram failure"), None]

    class Request(dict):
        def __init__(self):
            super().__init__(actor={"id": 7, "username": "nora_fan", "first_name": "Анна"})
            self.app = {
                "db": db,
                "bot": bot,
                "settings": SimpleNamespace(community_chat_id=-100987654321),
            }

    return db, bot, Request()


async def test_like_once_per_limit_cycle_and_announces_after_reset(tmp_path):
    import json
    from datetime import UTC, datetime

    from community_bot.social_likes import count

    db, bot, req = await _story_test_context(tmp_path)
    first = json.loads((await dedzytwo_story.like(req)).body)
    assert first["created"] is True and first["announced"] is True
    assert (await count(db, 8)) == 1
    msg = bot.send_message.call_args
    assert msg.args[0] == -100987654321
    assert "@nora_fan</a> лайкнул сторис" in msg.args[1]
    assert "@dedzytwo</a>" in msg.args[1]
    assert msg.kwargs["parse_mode"] == "HTML"
    assert json.loads((await dedzytwo_story.status(req)).body) == {"liked": True}

    duplicate = json.loads((await dedzytwo_story.like(req)).body)
    assert duplicate == {"ok": True, "liked": True, "created": False}
    assert (await count(db, 8)) == 1
    bot.send_message.assert_awaited_once()

    # Use the real reset_limits shop effect, not a made-up test-only reset.
    async with db.connect() as connection:
        await connection.execute("BEGIN IMMEDIATE")
        assert await db._apply_shop_effect(
            connection, 7, "reset_limits", datetime.now(UTC).isoformat(),
        ) is None
        await connection.commit()
    assert json.loads((await dedzytwo_story.status(req)).body) == {"liked": False}

    after_reset = json.loads((await dedzytwo_story.like(req)).body)
    assert after_reset["created"] is True and after_reset["announced"] is True
    assert (await count(db, 8)) == 2
    assert bot.send_message.await_count == 2
    assert json.loads((await dedzytwo_story.status(req)).body) == {"liked": True}


async def test_parallel_clicks_credit_and_announce_once(tmp_path):
    import asyncio
    import json

    from community_bot.social_likes import count

    db, bot, request = await _story_test_context(tmp_path)
    first, second = await asyncio.gather(
        dedzytwo_story.like(request), dedzytwo_story.like(request),
    )
    flags = [json.loads(first.body)["created"], json.loads(second.body)["created"]]
    assert sorted(flags) == [False, True]
    assert (await count(db, 8)) == 1
    bot.send_message.assert_awaited_once()
    assert await db.fetchall(
        "SELECT key FROM bot_state WHERE key GLOB 'story_notice:dedzytwo:*'"
    ) == []


async def test_failed_telegram_announcement_is_retried_without_extra_like(tmp_path):
    import json

    from community_bot.social_likes import count

    db, bot, req = await _story_test_context(tmp_path, fail_first_send=True)
    first = json.loads((await dedzytwo_story.like(req)).body)
    assert first["created"] is True and first["announced"] is False
    assert first["notification_pending"] is True
    assert (await count(db, 8)) == 1

    # Reopening the story retries the pending notification but not the like.
    assert json.loads((await dedzytwo_story.status(req)).body) == {"liked": True}
    assert bot.send_message.await_count == 2
    assert (await count(db, 8)) == 1
    assert await db.fetchall(
        "SELECT key FROM bot_state WHERE key GLOB 'story_notice:dedzytwo:*'"
    ) == []


async def test_preexisting_profile_like_is_not_counted_twice(tmp_path):
    import json

    from community_bot.social_likes import count, give

    db, bot, req = await _story_test_context(tmp_path)
    assert await give(db, 7, 8) is None
    response = json.loads((await dedzytwo_story.like(req)).body)
    assert response == {"ok": True, "liked": True, "created": False}
    assert (await count(db, 8)) == 1
    bot.send_message.assert_not_awaited()
