"""Durable Mini App game deadlines; no extra Telegram dispatcher or poller."""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


async def settle(db):
    from community_bot import mafia_api, rocket_api, sea_api

    # A broken room must not stop another player's payout or the bot event loop.
    for name, tick in (
        ("rocket", rocket_api.tick),
        ("mafia", mafia_api.tick),
        ("sea", sea_api.tick),
    ):
        try:
            await tick(db)
        except Exception:
            logger.exception("Interactive deadline settlement failed: %s", name)


async def lifecycle(app):
    """Restore persisted deadlines before HTTP serves; stop gracefully with aiohttp."""
    from community_bot.game_lobby_posts import cleanup, purge_acceptances
    from community_bot.group_message_close import purge_ownership

    await settle(app['db'])
    durak = app.get('durak_updates')
    if durak:
        await durak.restore(app['db'], time.time())
        await durak.tick(app['db'])

    async def run():
        while True:
            await asyncio.sleep(1)
            await settle(app['db'])
            if durak:
                try:
                    await durak.tick(app['db'])
                except Exception:
                    logger.exception('Durak deadline settlement failed')

    async def retire_posts():
        next_purge = 0.0
        while True:
            try:
                await cleanup(app['db'], app.get('bot'))
                now = time.time()
                if now >= next_purge:
                    await purge_acceptances(app['db'], now)
                    await purge_ownership(app['db'], now)
                    next_purge = now + 3600
            except Exception:
                logger.exception('Game lobby post cleanup failed')
            await asyncio.sleep(1)

    tasks = [
        asyncio.create_task(run(), name='nora-interactive-deadlines'),
        asyncio.create_task(retire_posts(), name='nora-game-lobby-posts'),
    ]
    logger.info('Interactive games ready: persisted deadlines and payouts restored')
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
