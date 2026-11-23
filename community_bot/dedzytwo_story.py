"""Dedicated DJ Dedzytwo story video and its existing profile-like action."""
from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import re
import os
import tempfile
from pathlib import Path

from aiohttp import web

PARTS = Path(__file__).parent.parent / "assets" / "stories" / "dedzytwo"
POSTER = Path(__file__).parent.parent / "assets" / "stories" / "dedzytwo-poster-20261123.jpg"
TARGET = Path(tempfile.gettempdir()) / "nora-dedzytwo-52986d0e-20261123.mp4"
EXPECTED_PARTS = 15
EXPECTED_SIZE = 8_597_446
EXPECTED_SHA256 = "52986d0e5b4952cb4cfcdde6d9b7279e0c8d442c6763e3323d0b0774e4e6a629"
ASSEMBLY_LOCK = asyncio.Lock()
logger = logging.getLogger(__name__)
STORY_LIKE_PREFIX = "story_like:dedzytwo:"


def _like_key(actor_id: int) -> str:
    return f"{STORY_LIKE_PREFIX}{actor_id}"



def _assemble() -> Path:
    """Reassemble the original binary chunks once, then use HTTP range support."""
    if TARGET.is_file() and TARGET.stat().st_size == EXPECTED_SIZE:
        return TARGET
    file_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=TARGET.parent, prefix="nora-dj-", suffix=".tmp", delete=False) as output:
            file_name = output.name
            digest = hashlib.sha256()
            size = 0
            for index in range(EXPECTED_PARTS):
                with (PARTS / f"{index:02d}.part").open("rb") as part:
                    while block := part.read(1024 * 1024):
                        output.write(block)
                        digest.update(block)
                        size += len(block)
        if size != EXPECTED_SIZE or digest.hexdigest() != EXPECTED_SHA256:
            raise ValueError("Story video integrity check failed")
        os.replace(file_name, TARGET)
    finally:
        if file_name and os.path.exists(file_name):
            os.unlink(file_name)
    return TARGET


async def video(request: web.Request) -> web.StreamResponse:
    try:
        async with ASSEMBLY_LOCK:
            path = await asyncio.to_thread(_assemble)
    except (OSError, ValueError) as exc:
        raise web.HTTPServiceUnavailable(text="Видео истории временно недоступно") from exc
    return web.FileResponse(path, headers={"Content-Type": "video/mp4", "Cache-Control": "public, max-age=86400"})


async def poster(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(POSTER, headers={"Cache-Control": "public, max-age=86400"})


async def status(request: web.Request) -> web.Response:
    """Restore a viewer's one-time like state on every story opening."""
    liked = bool(await request.app["db"].get_bot_state(_like_key(request["actor"]["id"])))
    return web.json_response({"liked": liked})


async def like(request: web.Request) -> web.Response:
    """Give the profile one like per story viewer, and announce new likes once."""
    from community_bot.friends_api import _recipient
    from community_bot.social_likes import ALREADY_PROFILE_LIKED, ONCE_LIKED, count, give

    db = request.app["db"]
    actor = request["actor"]
    actor_id = int(actor["id"])
    target_id = await _recipient(db, "@dedzytwo")
    key = _like_key(actor_id)

    # Still checked atomically in give(): this fast path makes retries idempotent.
    if await db.get_bot_state(key):
        return web.json_response({"ok": True, "liked": True, "created": False})

    error = await give(db, actor_id, target_id, once_key=key)
    if error in (ONCE_LIKED, ALREADY_PROFILE_LIKED):
        return web.json_response({"ok": True, "liked": True, "created": False})
    if error:
        raise ValueError(error)

    settings = request.app["settings"]
    bot = request.app.get("bot")
    chat_id = getattr(settings, "community_chat_id", 0)
    announced = False
    if bot is not None and chat_id:
        username = actor.get("username")
        # Telegram initData is signed, but escaped before HTML rendering.
        name = ("@" + username if isinstance(username, str)
                and re.fullmatch(r"[A-Za-z0-9_]{5,32}", username)
                else "@" + str(actor.get("first_name") or "участник").lstrip("@"))
        message = (
            f'❤️ <a href="tg://user?id={actor_id}">{html.escape(name)}</a>'
            f' лайкнул сторис <a href="tg://user?id={target_id}">@dedzytwo</a>'
        )
        try:
            await bot.send_message(chat_id, message, parse_mode="HTML")
            announced = True
        except Exception:
            # Never re-credit or re-announce a committed like on HTTP retry.
            logger.exception("Could not announce Dedzytwo story like in community chat")

    return web.json_response({
        "ok": True, "liked": True, "created": True,
        "announced": announced, "likes": await count(db, target_id),
    })
