"""Check that the multipart story reconstructs the exact uploaded MP4."""
import hashlib

from community_bot import dedzytwo_story


def test_dedzytwo_video_integrity(tmp_path, monkeypatch):
    monkeypatch.setattr(dedzytwo_story, "TARGET", tmp_path / "dedzytwo.mp4")
    output = dedzytwo_story._assemble()
    assert output.stat().st_size == dedzytwo_story.EXPECTED_SIZE
    assert hashlib.sha256(output.read_bytes()).hexdigest() == dedzytwo_story.EXPECTED_SHA256
    assert dedzytwo_story._assemble() == output


async def test_story_like_is_permanent_and_announced_only_once(tmp_path):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from community_bot.database import Database
    from community_bot.social_likes import count

    db = Database(tmp_path / "story-likes.db")
    await db.initialize()
    await db.ensure_user(7, telegram_name="Анна")
    await db.ensure_user(8, telegram_name="Артист")
    await db.execute("UPDATE users SET username='dedzytwo' WHERE user_id=8")
    bot = SimpleNamespace(send_message=AsyncMock())

    class Request(dict):
        def __init__(self):
            super().__init__(actor={"id": 7, "username": "nora_fan", "first_name": "Анна"})
            self.app = {
                "db": db,
                "bot": bot,
                "settings": SimpleNamespace(community_chat_id=-100987654321),
            }

    request = Request()
    first = json.loads((await dedzytwo_story.like(request)).body)
    assert first["created"] is True and first["announced"] is True
    assert (await count(db, 8)) == 1
    msg = bot.send_message.call_args
    assert msg.args[0] == -100987654321
    assert '@nora_fan</a> лайкнул сторис' in msg.args[1]
    assert '@dedzytwo</a>' in msg.args[1]
    assert msg.kwargs["parse_mode"] == "HTML"

    # A reload or even a reset of today's allowance must not re-like the story.
    await db.set_bot_state("likes_sent_day:7", "")
    second = json.loads((await dedzytwo_story.like(request)).body)
    state = json.loads((await dedzytwo_story.status(request)).body)
    assert second == {"ok": True, "liked": True, "created": False}
    assert state == {"liked": True}
    assert (await count(db, 8)) == 1
    bot.send_message.assert_awaited_once()


async def test_simultaneous_story_likes_credit_and_announce_once(tmp_path):
    import asyncio
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from community_bot.database import Database
    from community_bot.social_likes import count

    db = Database(tmp_path / "story-concurrent.db")
    await db.initialize()
    await db.ensure_user(7, telegram_name="Анна")
    await db.ensure_user(8, telegram_name="Артист")
    await db.execute("UPDATE users SET username='dedzytwo' WHERE user_id=8")
    bot = SimpleNamespace(send_message=AsyncMock())

    class Request(dict):
        def __init__(self):
            super().__init__(actor={"id": 7, "first_name": "Анна"})
            self.app = {"db": db, "bot": bot,
                        "settings": SimpleNamespace(community_chat_id=-100987654321)}

    first, second = await asyncio.gather(
        dedzytwo_story.like(Request()), dedzytwo_story.like(Request()),
    )
    flags = [json.loads(first.body)["created"], json.loads(second.body)["created"]]
    assert sorted(flags) == [False, True]
    assert (await count(db, 8)) == 1
    bot.send_message.assert_awaited_once()
