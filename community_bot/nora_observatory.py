"""Per-player checkpoints and one-time wallet rewards for the Observatory."""

import json
import math
from dataclasses import dataclass
from pathlib import Path

from community_bot.database import Database, utcnow

LAYOUT = json.loads((Path(__file__).with_name('web') / 'nora-observatory.json').read_text(encoding='utf-8'))
ROOM = 'observatory'
KIND = 'nora_observatory'
CHECKPOINTS = [LAYOUT['platforms'][index] for index in LAYOUT['checkpoints']]
ATTEMPT_TTL = 600


def on_platform(pose, platform, margin=.14):
    x, z, top, width, depth = platform
    return (pose.get('grounded') is True and abs(pose['y'] - .017 - top) <= .04
            and abs(pose['x'] - x) <= width / 2 + margin
            and abs(pose['z'] - z) <= depth / 2 + margin)


@dataclass
class Attempt:
    session: str
    seen: float
    checkpoint: int = 0
    last: dict | None = None
    airborne_since: float = 0
    lift_height: float = 0
    reward: int | None = None

    def advance(self, pose, now):
        landed = any(on_platform(pose, platform) for platform in LAYOUT['platforms'])
        previous = self.last
        elapsed = max(0, min(1.2, now - self.seen))
        self.seen = now
        # Respawns can only snap to the current safe landing. A new run starts there too.
        if on_platform(pose, CHECKPOINTS[self.checkpoint]):
            self.last = pose
            self.airborne_since, self.lift_height = now, pose['y']
            return True
        if previous is None or (pose.get('grounded') and not landed):
            self.last = None
            return False
        distance = math.hypot(pose['x'] - previous['x'], pose['z'] - previous['z'])
        if (distance > 3.5 * elapsed + .34
                or pose['y'] - previous['y'] > 4.6 * elapsed + .25
                or pose['y'] > self.lift_height + .85
                or (not landed and now - self.airborne_since > 1.5)):
            self.last = None
            return False
        for x, z, y, width, offset in LAYOUT['beams']:
            phase = (now + offset) % 4
            if (1.15 < phase < 2.52 and abs(pose['x'] - x) < width / 2 - .08
                    and abs(pose['z'] - z) < .12 and pose['y'] < y + .31):
                self.last = None
                return False
        self.last = pose
        if landed:
            self.airborne_since, self.lift_height = now, pose['y']
        if self.checkpoint < len(CHECKPOINTS) - 1 and on_platform(pose, CHECKPOINTS[self.checkpoint + 1]):
            self.checkpoint += 1
        return True


async def claim(database, user_id):
    async with database.connect() as db:
        await db.execute('BEGIN IMMEDIATE')
        existing = await (await db.execute(
            'SELECT 1 FROM transactions WHERE user_id = ? AND kind = ? LIMIT 1', (user_id, KIND),
        )).fetchone()
        if existing:
            return 0
        amount = LAYOUT['reward']
        await Database._add_cookies(db, user_id, amount, KIND, '', utcnow())
        await db.commit()
        return amount


async def progress(app, user_id, session, pose, now):
    attempts = app['nora_observatory']
    run = attempts.get(user_id)
    if run is None or run.session != session or now - run.seen > ATTEMPT_TTL:
        for stale in [uid for uid, active in attempts.items() if now - active.seen > ATTEMPT_TTL]:
            del attempts[stale]
        run = attempts[user_id] = Attempt(session, now)
    valid = run.advance(pose, now)
    # Concurrent HTTP retries still share the same durable award. Preserve the first
    # award confirmation in this run if a duplicate also reaches the transaction.
    if run.checkpoint == len(CHECKPOINTS) - 1 and run.reward is None:
        amount = await claim(app['db'], user_id)
        if amount or run.reward is None:
            run.reward = amount
    return {'checkpoint': run.checkpoint, 'reward': run.reward, 'reset': not valid}
