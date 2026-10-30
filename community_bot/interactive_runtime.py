"""Durable Mini App game deadlines; no extra Telegram dispatcher or poller."""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


async def settle(db):
    from community_bot import mafia_api, rocket_api

    # A broken room must not stop another player's payout or the bot event loop.
    for name, tick in (("rocket", rocket_api.tick), ("mafia", mafia_api.tick)):
        try:
            await tick(db)
        except Exception:
            logger.exception("Interactive deadline settlement failed: %s", name)


async def lifecycle(app):
    """Restore persisted deadlines before HTTP serves; stop gracefully with aiohttp."""
    await settle(app['db'])

    async def run():
        while True:
            await asyncio.sleep(1)
            await settle(app['db'])

    task = asyncio.create_task(run(), name='nora-interactive-deadlines')
    logger.info('Interactive games ready: persisted deadlines and payouts restored')
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
