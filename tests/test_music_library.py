import asyncio
import json

import pytest

from community_bot.database import Database
from community_bot.music_library import change_collection, get_collection, save_button, saved_track_summary
from community_bot.profile_track import get_track, track_key


def sample(file_id="audio-1", revision="a" * 32):
    return {"file_id": file_id, "revision": revision, "title": "Тест", "artist": "Нора",
            "duration": 10, "mime": "audio/mpeg"}


async def test_saved_track_is_independent_and_idempotent(tmp_path):
    db = Database(tmp_path / "music.sqlite3")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Первый")
    await db.ensure_user(2, telegram_name="Второй")
    await db.ensure_user(3, telegram_name="Третий")
    track = sample()
    await db.set_bot_state(track_key(2), json.dumps(track))
    first, second = await asyncio.gather(*(
        change_collection(db, 1, target_id=2, revision=track["revision"], saved=True)
        for _ in range(2)
    ))
    assert first == second
    key = first["id"]
    assert first["saved"]
    assert await get_collection(db, 1) == {key: track}
    assert await get_collection(db, 3) == {}
    assert await get_track(db, 1) is None
    assert await get_track(db, 2) == track
    assert (await saved_track_summary(db, 1, track))["saved"]
    assert not (await saved_track_summary(db, 3, track))["saved"]
    replacement = sample("audio-2", "b" * 32)
    await db.set_bot_state(track_key(2), json.dumps(replacement))
    with pytest.raises(ValueError):
        await change_collection(db, 1, target_id=2, revision=track["revision"], saved=True)
    assert await get_collection(db, 1) == {key: track}
    assert not (await change_collection(db, 1, key=key, saved=False))["saved"]
    assert await get_collection(db, 1) == {}


async def test_rich_toggle_shared_audio_reference(tmp_path):
    db = Database(tmp_path / "music.sqlite3")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Первый")
    await db.ensure_user(2, telegram_name="Второй")
    track = sample()
    await db.set_bot_state(track_key(2), json.dumps(track))
    block = save_button(track, 2)
    assert block.buttons[0].text == "+"
    assert len(block.buttons[0].callback_data.encode()) <= 64
    assert (await change_collection(db, 1, target_id=2, revision=track["revision"]))["saved"]
    assert not (await change_collection(db, 1, target_id=2, revision=track["revision"]))["saved"]
    await change_collection(db, 1, target_id=2, revision=track["revision"], saved=True)
    await db.reset_banned_user(1, None)
    assert await get_collection(db, 1) == {}
