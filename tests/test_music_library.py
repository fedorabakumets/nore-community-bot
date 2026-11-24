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


async def test_library_visibility_and_rich_pages(tmp_path):
    from types import SimpleNamespace

    from community_bot.command_registry import restore_defaults
    from community_bot.aliases import parse_trigger
    from community_bot.library_rich import library_card
    from community_bot.music_library import can_read_library, is_public, page_entries, set_public

    restore_defaults()
    assert parse_trigger("Нора треки") == ("tracks", "")
    assert parse_trigger("Нора треки @username") == ("tracks", "@username")
    assert parse_trigger("Нора мои треки") == ("tracks", "")
    assert parse_trigger("Нора треки просто так") is None
    db = Database(tmp_path / "public-music.sqlite3")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Владелец")
    await db.ensure_user(2, telegram_name="Гость")
    settings = SimpleNamespace()
    assert not await is_public(db, 1)
    assert await can_read_library(db, settings, 1, 1)
    assert not await can_read_library(db, settings, 2, 1)
    for i in range(6):
        track = sample(f"audio-{i}", f"{i:032x}")
        await db.set_bot_state(track_key(2), json.dumps(track))
        await change_collection(db, 1, target_id=2, revision=track["revision"], saved=True)
    entries, page, pages = page_entries(await get_collection(db, 1), 0)
    assert (len(entries), page, pages) == (5, 0, 2)
    card = await library_card(db, 1, 1)
    assert sum(block.type == "audio" for block in card.blocks) == 5
    assert any(button.callback_data.startswith("mlib:del:") for block in card.blocks
               if block.type == "buttons" for button in block.buttons)
    await set_public(db, 1, True)
    assert await can_read_library(db, settings, 2, 1)
    guest_card = await library_card(db, 2, 1, 1)
    assert sum(block.type == "audio" for block in guest_card.blocks) == 1
    assert not any(button.callback_data.startswith(("mlib:del:", "mlib:public:"))
                   for block in guest_card.blocks if block.type == "buttons" for button in block.buttons)
    await db.update_profile(1, "profile_private", 1)
    assert not await can_read_library(db, settings, 2, 1)
    await db.reset_banned_user(1, None)
    assert not await is_public(db, 1)
