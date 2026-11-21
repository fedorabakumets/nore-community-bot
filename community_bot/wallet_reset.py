"""Apply the owner's one-time wallet balance reset on the designated Railway release."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from uuid import uuid4

from community_bot.database import Database, utcnow
from community_bot.release_backup import verify_requested_release_backup

RELEASE_SUBJECT = "Upgrade wallet history and reset cookie balances"
RESET_ID = "wallet-balances-20261111"
MARKER = f"maintenance:{RESET_ID}"
logger = logging.getLogger(__name__)


async def reset_wallet_balances(db: Database) -> bool:
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        if await (await conn.execute("SELECT 1 FROM bot_state WHERE key=?", (MARKER,))).fetchone():
            return False
        if not await (await conn.execute("SELECT 1 FROM users LIMIT 1")).fetchone():
            raise RuntimeError("Wallet balance reset requires an existing community")

        # Keep other writers out until the exact pre-reset state is backed up and committed.
        backup_id = f"{RESET_ID}-{uuid4().hex}"
        if not await verify_requested_release_backup(db, request=backup_id):
            raise RuntimeError("Pre-reset backup was not verified")
        target = (
            "CASE WHEN EXISTS (SELECT 1 FROM profile_completion_rewards r "
            "WHERE r.user_id=users.user_id) THEN 10 ELSE 0 END"
        )
        now = utcnow()
        await conn.execute(
            "INSERT INTO transactions(user_id,amount,kind,details,created_at) "
            f"SELECT user_id, {target}-cookies, 'wallet_reset', ?, ? FROM users WHERE cookies<>{target}",
            (RESET_ID, now),
        )
        changed = await conn.execute(
            f"UPDATE users SET cookies={target}, updated_at=? WHERE cookies<>{target}",
            (now,),
        )
        await conn.execute("INSERT INTO bot_state(key,value) VALUES(?,?)", (MARKER, backup_id))
        await conn.commit()
    logger.info("Wallet balances reset: %d accounts changed after backup verification", changed.rowcount)
    return True


def _is_on_volume(database: Path, mount: str) -> bool:
    return bool(mount) and database.is_file() and database.resolve().is_relative_to(Path(mount).resolve())


async def apply_wallet_reset_release(db: Database) -> None:
    subject = os.getenv("RAILWAY_GIT_COMMIT_MESSAGE", "").partition("\n")[0].strip()
    if (
        subject != RELEASE_SUBJECT
        or os.getenv("RAILWAY_ENVIRONMENT_NAME") != "production"
        or os.getenv("RAILWAY_GIT_BRANCH") != "cursor/nora-2-update-d133"
    ):
        return
    mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "")
    if not await asyncio.to_thread(_is_on_volume, db.path, mount):
        logger.error("Wallet balance reset skipped: database is missing from the Railway volume")
        return
    try:
        await reset_wallet_balances(db)
    except Exception as exc:
        logger.error("Wallet balance reset failed and rolled back (%s)", type(exc).__name__)
