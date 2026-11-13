"""Owner-requested one-time reset for the November 2026 community restart.

Runs only in the existing startup, before polling/jobs. Never starts another bot.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from contextlib import closing
from dataclasses import replace

from community_bot.database import utcnow
from community_bot.profile_maintenance import checked_backup

REQUEST = 'community-reset-20261104'
MARKER = 'maintenance:' + REQUEST
# Ромочка: account confirmed by the owner's profile screenshot for this reset.
RETAINED_OWNER_ID = 406719727
logger = logging.getLogger(__name__)


def _done(path):
    if not path.is_file():
        return False
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='bot_state'").fetchone():
            return False
        return bool(conn.execute('SELECT 1 FROM bot_state WHERE key=?', (MARKER,)).fetchone())


async def prepare_reset(db):
    """Consistent SQLite backup + restore check BEFORE any schema initialization."""
    if await asyncio.to_thread(_done, db.path):
        return
    if RETAINED_OWNER_ID <= 0:
        raise RuntimeError('Confirm the retained owner Telegram ID before releasing this reset')
    if db.path.is_file():
        await asyncio.to_thread(checked_backup, db.path, REQUEST)


async def apply_reset(db, settings, *, owner_id=None):
    if await db.get_bot_state(MARKER):
        return False
    owner_id = RETAINED_OWNER_ID if owner_id is None else owner_id
    if owner_id <= 0 or owner_id not in settings.owner_ids:
        raise ValueError('Retained Telegram account must be a confirmed existing owner')
    # Also protects direct maintenance calls, not just the normal startup path.
    backup = await asyncio.to_thread(checked_backup, db.path, REQUEST)
    now, stamp = time.time(), utcnow()
    async with db.connect() as conn:
        await conn.execute('BEGIN IMMEDIATE')
        if await (await conn.execute('SELECT 1 FROM bot_state WHERE key=?', (MARKER,))).fetchone():
            return False
        # Settle outstanding staked Sea games before zeroing; later expiry cannot
        # restore old balances. Keep game/financial history and cancel pending UI quotes.
        from community_bot.sea_api import _finish, _load, _save

        rooms = await (await conn.execute(
            "SELECT id FROM mini_sea_rooms WHERE status NOT IN ('finished','cancelled')")).fetchall()
        for room in rooms:
            state = await _load(conn, room['id'])
            await _finish(conn, state, None, now, cancelled=True)
            await _save(conn, state, now)
        await conn.execute("UPDATE party_games SET status='cancelled',updated_at=?,completed_at=? "
                           "WHERE status IN ('lobby','active')", (stamp, stamp))
        await conn.execute("UPDATE roulette_games SET status='cancelled',completed_at=? "
                           "WHERE status='pending'", (stamp,))
        await conn.execute("UPDATE mini_rocket_quotes SET status='superseded' WHERE status='pending'")
        await conn.execute("UPDATE mini_rocket_rounds SET status='crashed',payout=0,finished_at=? "
                           "WHERE status='active'", (now,))
        await conn.execute("UPDATE wallet_intents SET status='cancelled' WHERE status='pending'")
        # Preserve the ledger: a reset is an explicit balancing transaction.
        await conn.execute(
            "INSERT INTO transactions(user_id,amount,kind,details,created_at) "
            "SELECT user_id,-cookies,'community_reset',?,? FROM users WHERE cookies<>0", (REQUEST, stamp))
        await conn.execute("UPDATE users SET cookies=0,role=CASE WHEN user_id=? THEN 'owner' ELSE 'member' END,"
                           "updated_at=?", (owner_id, stamp))
        await conn.execute('DELETE FROM pets')
        # Remember the configured principal, so old OWNER_IDS/MODERATOR_IDS cannot
        # resurrect privileges on subsequent startups. Newly assigned DB roles work normally.
        await conn.execute('INSERT INTO bot_state(key,value) VALUES(?,?)',
                           (MARKER, json.dumps({'owner_id': owner_id, 'backup': backup.name})))
        await conn.execute(
            "INSERT INTO admin_audit_log(actor_id,action,target,details,created_at) VALUES(?,?,?,?,?)",
            (owner_id, 'community_reset', 'all',
             'Cookies zeroed; pets removed; only confirmed owner retained; ' + backup.name, stamp))
        await conn.commit()
    logger.info('Community reset applied once; backup verified; confirmed owner retained')
    return True


async def reset_settings(db, settings):
    value = await db.get_bot_state(MARKER)
    if not value:
        return settings
    owner_id = int(json.loads(value)['owner_id'])
    return replace(settings, owner_id=owner_id, owner_ids=frozenset({owner_id}), moderator_ids=frozenset())
