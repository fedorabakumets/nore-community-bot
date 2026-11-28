"""The artist page for NORA's bundled dedzytwo releases."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

from aiogram.types import FSInputFile
from aiohttp import web

from community_bot.dedzytwo_playlist import ASSETS, COVER_URL, artist_tracks
from community_bot.music_library import add_resolved_tracks, public_track, track_id

SOURCE = "/api/music-library/artist/"
PREFIX = "dedzytwo:"
CHANNEL = "https://t.me/thededzzyDJ"


@lru_cache(maxsize=1)
def releases():
    tracks = {}
    for song in artist_tracks():
        if not isinstance(song.media, FSInputFile):
            continue
        path = Path(song.media.path)
        if path.parent != ASSETS or not path.is_file():
            continue
        file_id = PREFIX + path.name
        track = {
            "file_id": file_id, "mime": "audio/mpeg", "title": song.title,
            "artist": song.performer or "dedzytwo", "duration": song.duration or 0,
            "revision": sha256(file_id.encode()).hexdigest()[:32], "cover": COVER_URL,
        }
        tracks[track_id(track)] = track
    return tracks


@lru_cache(maxsize=1)
def release_paths():
    return {
        track["file_id"]: ASSETS / track["file_id"].removeprefix(PREFIX)
        for track in releases().values()
    }


def resolve(source, revision):
    track = releases().get(source.removeprefix(SOURCE))
    return track if track and track["revision"] == revision else None


async def artist_page(request):
    from community_bot.dedzytwo_story import _recipient_id

    db, uid = request.app["db"], request["actor"]["id"]
    try:
        profile = await _recipient_id(db, remember=False)
    except ValueError:
        profile = None
    if profile and profile != uid and await db.fetchone(
        "SELECT 1 FROM mini_friend_blocks WHERE (blocker_id=? AND blocked_id=?) "
        "OR (blocker_id=? AND blocked_id=?)", (uid, profile, profile, uid),
    ):
        profile = None
    return web.json_response({
        "profile_id": profile,
        "channel": CHANNEL,
        "tracks": [public_track(key, track) for key, track in releases().items()],
    })


async def save_all(request):
    entries, added = await add_resolved_tracks(
        request.app["db"], request["actor"]["id"], list(releases().values()),
    )
    return web.json_response({
        "added": added,
        "tracks": [public_track(key, track) for key, track in reversed(list(entries.items()))],
    })


async def audio(request):
    track = resolve(request.path, request.query.get("v"))
    path = release_paths().get(track["file_id"]) if track else None
    if not path or not path.is_file():
        raise web.HTTPNotFound()
    if request.query.get("check") == "1":
        return web.Response(status=204)
    return web.FileResponse(path, headers={"Content-Type": "audio/mpeg", "Cache-Control": "no-store"})
