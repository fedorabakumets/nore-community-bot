"""One-time profile-like grant requested by the owner for the November release."""

import asyncio
import json
import logging
import os
from uuid import uuid4

from community_bot.community_reset import RETAINED_OWNER_ID
from community_bot.release_backup import verify_requested_release_backup
from community_bot.social_likes import COUNT_PREFIX
from community_bot.wallet_reset import _is_on_volume

REQUEST = "owner-profile-likes-20261120"
MARKER = f"maintenance:{REQUEST}"
TARGET_LIKES = 50
logger = logging.getLogger(__name__)


async def grant_owner_likes(db, settings) -> bool:
    uid = RETAINED_OWNER_ID  # Previously confirmed Telegram account for Ромочка.
    if not settings.is_owner(uid):
        raise ValueError("The confirmed recipient is no longer a configured owner")
    key = f"{COUNT_PREFIX}{uid}"
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        if await (await conn.execute("SELECT 1 FROM bot_state WHERE key=?", (MARKER,))).fetchone():
            return False
        if not await (await conn.execute("SELECT 1 FROM users WHERE user_id=?", (uid,))).fetchone():
            raise ValueError("The confirmed recipient has no profile")
        row = await (await conn.execute("SELECT value FROM bot_state WHERE key=?", (key,))).fetchone()
        previous = int(row["value"]) if row else 0
        if previous >= TARGET_LIKES:
            return False

        backup_id = f"{REQUEST}-{uuid4().hex}"
        if not await verify_requested_release_backup(db, request=backup_id):
            raise RuntimeError("Pre-grant backup was not verified")
        await conn.execute(
            "INSERT INTO bot_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(TARGET_LIKES)),
        )
        await conn.execute(
            "INSERT INTO bot_state(key,value) VALUES (?,?)",
            (MARKER, json.dumps({"user_id": uid, "previous": previous, "total": TARGET_LIKES, "backup": backup_id})),
        )
        await conn.commit()
    logger.info("One-time owner profile likes granted. Total: %d", TARGET_LIKES)
    return True


async def apply_profile_likes_grant(db, settings) -> None:
    if (
        os.getenv("RAILWAY_ENVIRONMENT_NAME") != "production"
        or os.getenv("RAILWAY_GIT_BRANCH") != "cursor/nora-2-update-d133"
    ):
        return
    try:
        if not await asyncio.to_thread(_is_on_volume, db.path, os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "")):
            raise ValueError("Database is missing from the Railway volume")
        await grant_owner_likes(db, settings)
    except Exception as exc:
        logger.error("One-time owner profile like grant skipped (%s)", type(exc).__name__)
