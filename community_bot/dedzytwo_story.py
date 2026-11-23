"""Dedicated DJ Dedzytwo story video and its existing profile-like action."""
from __future__ import annotations

import asyncio
import hashlib
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


async def like(request: web.Request) -> web.Response:
    """Delegate to the same atomic daily-likes system used by NORA profiles."""
    from community_bot.friends_api import _recipient
    from community_bot.social_likes import count, give

    db = request.app["db"]
    target_id = await _recipient(db, "@dedzytwo")
    error = await give(db, request["actor"]["id"], target_id)
    if error:
        raise ValueError(error)
    return web.json_response({"ok": True, "likes": await count(db, target_id)})
