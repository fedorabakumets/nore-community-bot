"""Dedicated DJ Dedzytwo story video and its existing profile-like action."""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import os
import re
import secrets
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
ANNOUNCEMENT_LOCK = asyncio.Lock()
logger = logging.getLogger(__name__)
NOTICE_PREFIX = "story_notice:dedzytwo:"
TARGET_USERNAME = "ourcreator"
TARGET_PROFILE_NAME = "dedzyTWO"
TARGET_ID_KEY = "story_owner:dedzytwo:user_id"



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


async def _recipient_id(db) -> int:
    """Resolve the DJ's actual NORA profile once, then keep its stable Telegram ID.

    Telegram usernames can be missing or stale in our database. The Mini App's
    visible name comes from users.profile_name, not users.username.
    """
    cached = await db.get_bot_state(TARGET_ID_KEY)
    if cached and cached.isdecimal():
        person = await db.get_user(int(cached))
        if person:
            return int(person["user_id"])

    rows = await db.fetchall(
        "SELECT user_id, username, profile_name, telegram_name FROM users "
        "WHERE lower(trim(COALESCE(profile_name, '')))=? "
        "OR lower(trim(COALESCE(telegram_name, '')))=? "
        "OR lower(trim(COALESCE(username, '')))=? LIMIT 10",
        (TARGET_PROFILE_NAME.casefold(), TARGET_PROFILE_NAME.casefold(),
         TARGET_USERNAME.casefold()),
    )
    by_profile = [p for p in rows if str(p.get("profile_name") or "").strip().casefold()
                  == TARGET_PROFILE_NAME.casefold()]
    by_telegram_name = [p for p in rows if str(p.get("telegram_name") or "").strip().casefold()
                        == TARGET_PROFILE_NAME.casefold()]
    # A custom NORA name is more precise than a Telegram first name.
    by_display = by_profile if by_profile else by_telegram_name
    by_username = [p for p in rows if str(p.get("username") or "").strip().casefold()
                   == TARGET_USERNAME.casefold()]
    both = [p for p in by_display if p in by_username]

    if len(both) == 1:
        person = both[0]
    elif len(by_username) == 1 and not by_display:
        person = by_username[0]
    elif len(by_display) == 1 and not by_username:
        person = by_display[0]
    else:
        # Do not credit a random similarly-named profile if IDs conflict.
        logger.error(
            "Cannot safely resolve story target dedzyTWO: display matches=%s, username matches=%s",
            len(by_display), len(by_username),
        )
        raise ValueError("Не удалось однозначно найти профиль dedzyTWO в Норе")

    user_id = int(person["user_id"])
    await db.set_bot_state(TARGET_ID_KEY, str(user_id))
    return user_id


def _announcement(actor: dict, target_id: int, *, actor_profile=None, target_profile=None) -> str:
    actor_id = int(actor["id"])
    username = actor.get("username")
    # Signed Telegram initData, escaped before inserting in HTML.
    display_name = (actor_profile or {}).get("profile_name")
    name = ("@" + str(display_name).lstrip("@") if display_name
            else "@" + username if isinstance(username, str)
            and re.fullmatch(r"[A-Za-z0-9_]{5,32}", username)
            else "@" + str(actor.get("first_name") or "участник").lstrip("@"))
    recipient = (
        (target_profile or {}).get("profile_name")
        or (target_profile or {}).get("telegram_name")
        or TARGET_PROFILE_NAME
    )
    return (
        f'❤️ <a href="tg://user?id={actor_id}">{html.escape(name)}</a>'
        f' лайкнул сторис <a href="tg://user?id={target_id}">'
        f'@{html.escape(str(recipient).lstrip("@"))}</a>'
    )


async def _send_pending(app) -> int:
    """Deliver any pending like announcements without incrementing likes on retries."""
    from community_bot.group_message_close import without_group_close

    bot = app.get("bot")
    chat_id = getattr(app["settings"], "community_chat_id", 0)
    if bot is None or not chat_id:
        logger.warning("DJ story like announcements not sent: bot or community_chat_id missing")
        return 0

    sent = 0
    async with ANNOUNCEMENT_LOCK:
        rows = await app["db"].fetchall(
            "SELECT key,value FROM bot_state WHERE key GLOB ? ORDER BY key LIMIT 20",
            (NOTICE_PREFIX + "*",),
        )
        for row in rows:
            try:
                payload = json.loads(row["value"])
                text = payload["text"]
                # Send as a simple linked Telegram message; the generic Rich
                # conversion is not needed for this notification.
                with without_group_close():
                    await bot.send_message(chat_id, text, parse_mode="HTML")
                await app["db"].execute(
                    "DELETE FROM bot_state WHERE key=? AND value=?",
                    (row["key"], row["value"]),
                )
                sent += 1
            except Exception:
                # Leave the exact event in the outbox for a later view/request.
                logger.exception("Could not send DJ story like notification: %s", row["key"])
    return sent


async def notification_worker(app) -> None:
    """Retry announcements that failed on the request that credited the like."""
    while True:
        try:
            await _send_pending(app)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("DJ story announcement retry cycle failed")
        await asyncio.sleep(30)


async def status(request: web.Request) -> web.Response:
    """Like state follows the shared daily limit, including a paid reset."""
    from community_bot.social_likes import liked_today

    await _send_pending(request.app)
    target_id = await _recipient_id(request.app["db"])
    liked = await liked_today(request.app["db"], int(request["actor"]["id"]), target_id)
    return web.json_response({"liked": liked})


async def like(request: web.Request) -> web.Response:
    """Credit one profile like per limit cycle, with a durable chat announcement."""
    from community_bot.social_likes import ALREADY_PROFILE_LIKED, count, give

    db = request.app["db"]
    actor = request["actor"]
    target_id = await _recipient_id(db)
    notice_key = NOTICE_PREFIX + secrets.token_hex(16)
    notification = (
        notice_key,
        json.dumps({
            "text": _announcement(
                actor, target_id,
                actor_profile=await db.get_user(int(actor["id"])),
                target_profile=await db.get_user(target_id),
            ),
        }, ensure_ascii=False),
    )
    error = await give(db, int(actor["id"]), target_id, notice=notification)
    if error and error != ALREADY_PROFILE_LIKED:
        raise ValueError(error)

    # Exactly one accepted like creates a pending event. Repeats can only
    # retry an unsent announcement, never enqueue another one.
    await _send_pending(request.app)
    if error == ALREADY_PROFILE_LIKED:
        return web.json_response({"ok": True, "liked": True, "created": False})

    pending = bool(await db.get_bot_state(notice_key))
    return web.json_response({
        "ok": True, "liked": True, "created": True,
        "announced": not pending, "notification_pending": pending,
        "likes": await count(db, target_id),
    })
