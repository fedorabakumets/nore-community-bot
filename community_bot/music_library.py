"""Personal saved audio references, independent of the public profile track."""
from __future__ import annotations

import hashlib
import json
import re

from community_bot.profile_track import track_key, track_summary

PREFIX = "gprofile:save:"


def collection_key(uid):
    return f"music_library:{uid}"


def track_id(track):
    return hashlib.sha256(track["file_id"].encode()).hexdigest()


async def get_collection(db, uid):
    raw = await db.get_bot_state(collection_key(uid))
    return json.loads(raw) if raw else {}


def public_track(key, track):
    return {"id": key, **track_summary(track)}


async def saved_track_summary(db, uid, track):
    if not track:
        return None
    key = track_id(track)
    return {**public_track(key, track), "saved": key in await get_collection(db, uid)}


async def change_collection(db, uid, *, target_id=None, revision=None, key=None, saved=None):
    """Atomically save/remove a current profile track or remove a library entry.

    Only the caller's collection changes. A stale profile revision cannot save a
    replacement track by accident. Explicit states make Mini App retries idempotent.
    """
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        row = await (await conn.execute(
            "SELECT value FROM bot_state WHERE key=?", (collection_key(uid),),
        )).fetchone()
        entries = json.loads(row["value"]) if row else {}
        track = None
        if target_id is not None:
            row = await (await conn.execute(
                "SELECT value FROM bot_state WHERE key=?", (track_key(target_id),),
            )).fetchone()
            track = json.loads(row["value"]) if row else None
            if not track or track["revision"] != revision:
                raise ValueError("Трек профиля изменился. Открой профиль заново.")
            key = track_id(track)
        elif saved is not False or not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError("Некорректный трек.")
        should_save = key not in entries if saved is None else saved
        if should_save:
            if key not in entries:
                entries[key] = track
        else:
            entries.pop(key, None)
        await conn.execute(
            "INSERT INTO bot_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (collection_key(uid), json.dumps(entries, ensure_ascii=False)),
        )
        await conn.commit()
    return {"id": key, "saved": should_save}


def save_button(track, target_id):
    from aiogram.types import InputRichBlockButtons, RichMessageButton

    return InputRichBlockButtons(align="center", buttons=[
        RichMessageButton(text="+", callback_data=f"{PREFIX}{target_id}:{track['revision']}"),
    ])
