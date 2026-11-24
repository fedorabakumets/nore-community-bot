import asyncio
import json

import pytest

from community_bot.database import Database
from community_bot.music_library import change_collection, get_collection, profile_music_button, saved_track_summary
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
    button = profile_music_button(track, 2, 1)
    assert button.text == "➕🎵"
    assert len(button.callback_data.encode()) <= 64
    assert profile_music_button(track, 2, 2).text == "🎧"
    assert profile_music_button(None, 2, 1) is None
    assert profile_music_button(None, 2, 2).text == "🎧"
    assert (await change_collection(db, 1, target_id=2, revision=track["revision"]))["saved"]
    assert not (await change_collection(db, 1, target_id=2, revision=track["revision"]))["saved"]
    await change_collection(db, 1, target_id=2, revision=track["revision"], saved=True)
    await db.reset_banned_user(1, None)
    assert await get_collection(db, 1) == {}


async def test_library_visibility_and_rich_pages(tmp_path):
    from types import SimpleNamespace

    from community_bot.aliases import parse_trigger
    from community_bot.command_registry import restore_defaults
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


async def test_legacy_music_requests_only_explain_new_commands():
    from types import SimpleNamespace
    from datetime import UTC, datetime

    from community_bot.nora import reply_for, rule_intent

    for text in ("топ чартов", "найди песню Queen", "музыка", "треки"):
        assert rule_intent(text) == {"tool": "music_help"}
        result = await reply_for("Нора " + text, SimpleNamespace(), datetime.now(UTC))
        assert "Нора песня" in result
        assert "Нора треки" in result


async def test_in_profile_library_never_leaks_private_audio(tmp_path):
    from community_bot.library_rich import library_card
    from community_bot.music_library import set_public

    db = Database(tmp_path / "profile-music.sqlite3")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Владелец")
    track = sample()
    await db.set_bot_state(track_key(1), json.dumps(track))
    await change_collection(db, 1, target_id=1, revision=track["revision"], saved=True)
    hidden = await library_card(db, 1, 1, profile=True, shared=True)
    assert not any(block.type == "audio" for block in hidden.blocks)
    assert hidden.blocks[-1].buttons[0].callback_data == "mlib:back:1"
    private = await library_card(db, 1, 1, profile=True)
    assert any(block.type == "audio" for block in private.blocks)
    assert private.blocks[-1].buttons[0].callback_data == "mlib:back:1"
    await set_public(db, 1, True)
    public = await library_card(db, 1, 1, profile=True, shared=True)
    assert any(block.type == "audio" for block in public.blocks)
    assert not any(button.callback_data.startswith(("mlib:p_del:", "mlib:p_public:"))
                   for block in public.blocks if block.type == "buttons" for button in block.buttons)


async def test_owner_profile_opens_in_place_and_duplicates_only_from_group(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aiogram.types import Chat, Message, User

    from community_bot import library_rich

    db = Database(tmp_path / "profile-open.sqlite3")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Владелец")
    await db.ensure_user(2, telegram_name="Гость")
    await db.bind_ui_owner(-100123, 10, 1, "profile")
    monkeypatch.setattr(library_rich, "allowed_actor", AsyncMock(return_value=True))
    edit = AsyncMock()
    deliver = AsyncMock()
    monkeypatch.setattr(Message, "edit_text", edit)
    monkeypatch.setattr(library_rich, "deliver", deliver)
    settings = SimpleNamespace(community_chat_id=-100123)
    callback = SimpleNamespace(
        data="mlib:open:1", from_user=User(id=1, first_name="Владелец", is_bot=False),
        message=Message(message_id=10, date=1725000000, chat=Chat(id=-100123, type="supergroup")),
        bot=SimpleNamespace(), answer=AsyncMock(),
    )
    await library_rich.library_callback(callback, db, settings)
    edit.assert_awaited_once()
    deliver.assert_awaited_once_with(callback.bot, db, 1, 1)
    assert edit.await_args.kwargs["rich_message"].blocks[-1].buttons[0].callback_data == "mlib:back:1"
    edit.reset_mock()
    deliver.reset_mock()
    callback.message = Message(message_id=11, date=1725000000, chat=Chat(id=1, type="private"))
    await library_rich.library_callback(callback, db, settings)
    edit.assert_awaited_once()
    deliver.assert_not_awaited()


async def test_share_track_checks_access_and_sends_native_audio(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from aiogram.enums import ChatMemberStatus
    from community_bot.social_profiles import share_track

    db = Database(tmp_path / "share-music.sqlite3")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Участник")
    await db.ensure_user(2, telegram_name="Другой")
    await db.execute("UPDATE users SET reputation=70 WHERE user_id=1")
    track = sample()
    await db.set_bot_state(track_key(1), json.dumps(track))
    await db.set_bot_state(track_key(2), json.dumps(track))
    await db.update_profile(2, "profile_private", 1)
    bot = SimpleNamespace(
        get_chat_member=AsyncMock(return_value=SimpleNamespace(status=ChatMemberStatus.MEMBER)),
        get_chat=AsyncMock(return_value=SimpleNamespace(permissions=None)),
        send_audio=AsyncMock(),
    )

    class Request(dict):
        async def json(self):
            return self.payload

    req = Request(actor={"id": 1})
    req.app = {"db": db, "bot": bot, "settings": SimpleNamespace(
        community_chat_id=-100123, restricted_reputation_threshold=50,
    )}
    req.payload = {"source": "/api/profile/track", "revision": "b" * 32}
    assert (await share_track(req)).status == 404
    req.payload = {"source": "/api/people/2/track", "revision": track["revision"]}
    assert (await share_track(req)).status == 404
    req.payload["source"] = "/api/profile/track"
    bot.get_chat_member.return_value = SimpleNamespace(
        status=ChatMemberStatus.RESTRICTED, is_member=True, can_send_messages=False, can_send_audios=False,
    )
    assert (await share_track(req)).status == 403
    bot.get_chat_member.return_value = SimpleNamespace(status=ChatMemberStatus.MEMBER)
    await db.execute("UPDATE users SET reputation=49 WHERE user_id=1")
    assert (await share_track(req)).status == 403
    bot.send_audio.assert_not_awaited()
    await db.execute("UPDATE users SET reputation=70 WHERE user_id=1")
    assert (await share_track(req)).status == 200
    bot.send_audio.assert_awaited_once()
    assert bot.send_audio.call_args.kwargs["audio"] == track["file_id"]
    assert bot.send_audio.call_args.kwargs["chat_id"] == -100123
    assert (await share_track(req)).status == 429
    bot.send_audio.assert_awaited_once()


async def test_now_playing_collection_status_add_and_private_source(tmp_path):
    from types import SimpleNamespace

    from community_bot.social_profiles import current_track_collection

    db = Database(tmp_path / "now-playing.sqlite3")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Первый")
    await db.ensure_user(2, telegram_name="Второй")
    track = sample()
    await db.set_bot_state(track_key(1), json.dumps(track))
    await db.set_bot_state(track_key(2), json.dumps(track))
    await db.update_profile(2, "profile_private", 1)

    class Request(dict):
        async def json(self):
            return self.query

    req = Request(actor={"id": 1})
    req.app = {"db": db, "settings": SimpleNamespace()}
    req.query = {"source": "/api/profile/track", "revision": track["revision"]}
    req.method = "GET"
    assert not json.loads((await current_track_collection(req)).body)["saved"]
    req.method = "POST"
    first, second = await asyncio.gather(current_track_collection(req), current_track_collection(req))
    assert json.loads(first.body) == json.loads(second.body)
    assert json.loads(first.body)["saved"]
    key = json.loads(first.body)["id"]
    assert await get_collection(db, 1) == {key: track}
    req.method = "GET"
    req.query["source"] = "/api/music-library/" + key
    assert json.loads((await current_track_collection(req)).body)["saved"]
    req.query["source"] = "/api/people/2/track"
    assert (await current_track_collection(req)).status == 404
    req.query = {"source": "/api/profile/track", "revision": "b" * 32}
    assert (await current_track_collection(req)).status == 404
