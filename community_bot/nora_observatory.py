"""Shared storm hazards, personal progress and the one-time Memory reward."""

import json
import math
from dataclasses import dataclass
from pathlib import Path

from community_bot.database import Database, utcnow

LAYOUT = json.loads((Path(__file__).with_name('web') / 'nora-observatory.json').read_text(encoding='utf-8'))
ROOM = 'observatory'
KIND = 'nora_observatory'
SAFE = LAYOUT['safe']
FINISH = len(SAFE) - 1
ATTEMPT_TTL = 600


def near(pose, point, radius):
    return math.hypot(pose['x'] - point[0], pose['z'] - point[1]) <= radius


def danger_at(pose, now):
    for x, z, radius, period, offset in LAYOUT['strikes']:
        phase = (now + offset) % period
        if period - .72 <= phase < period - .10 and near(pose, (x, z), radius - .12):
            return 'Удар молнии. Ты снова у контрольной точки.'
    for z, span, period, offset, radius in LAYOUT['guardians']:
        phase = (now + offset) % period / period
        x = span * (1 - 4 * abs(.5 - phase))
        if near(pose, (x, z), radius - .12):
            return 'Страж настиг тебя. Выжди, пока он пройдёт мимо.'
    return ''


@dataclass
class Attempt:
    session: str
    seen: float
    checkpoint: int = 0
    last: dict | None = None
    bells: int = 0
    action: int = 0
    notice: str = ''
    notice_until: float = 0
    ritual_since: float | None = None
    reward: int | None = None

    def advance(self, pose, now, interaction=None):
        previous = self.last
        elapsed = min(1.2, max(0, now - self.seen))
        if now - self.seen > 1.2:
            self.ritual_since = None
        self.seen = now
        if now >= self.notice_until:
            self.notice = ''
        if interaction is not None and interaction['serial'] > self.action:
            self.action = interaction['serial']
        else:
            interaction = None
        if self.checkpoint == FINISH:
            return True
        grounded = pose.get('grounded') is True and pose['y'] <= .06
        if previous is None and not (grounded and near(pose, SAFE[self.checkpoint], 1.1)):
            return False
        danger = danger_at(pose, now)
        gate = LAYOUT['gates'][self.checkpoint] if self.checkpoint < len(LAYOUT['gates']) else None
        crossed_gate = gate is not None and pose['z'] < gate + .25
        blocked = any(abs(pose['x'] - x) < width / 2 - .05 and abs(pose['z'] - z) < depth / 2 - .05
                      for x, z, width, depth in LAYOUT['walls'])
        moved_too_far = previous is not None and not near(pose, (previous['x'], previous['z']), 3.5 * elapsed + .34)
        if danger or crossed_gate or blocked or moved_too_far:
            self.last = None
            self.ritual_since = None
            if self.checkpoint == 1:
                self.bells = 0
            if danger:
                self.notice = danger
                self.notice_until = now + 3.5
            return False
        self.last = pose
        if interaction and grounded:
            relic = interaction['id']
            if near(pose, LAYOUT['relics'][relic], 1.55):
                self.use(relic, now)
        if self.checkpoint == FINISH - 1 and grounded and near(pose, SAFE[FINISH], 1.28):
            if self.ritual_since is None:
                self.ritual_since = now
                self.notice = ''
            if now - self.ritual_since >= LAYOUT['ritualSeconds']:
                self.checkpoint = FINISH
        else:
            self.ritual_since = None
        return True

    def use(self, relic, now):
        if (self.checkpoint, relic) in ((0, 'seal'), (2, 'lantern')):
            self.checkpoint += 1
            self.notice = ''
        elif self.checkpoint == 1 and relic in LAYOUT['bellOrder']:
            if relic == LAYOUT['bellOrder'][self.bells]:
                self.bells += 1
                self.notice = ''
                if self.bells == len(LAYOUT['bellOrder']):
                    self.checkpoint += 1
            else:
                self.bells = 0
                self.notice = 'Звон оборвался. Начни порядок заново.'
                self.notice_until = now + 3.5


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


async def progress(app, user_id, session, pose, now, interaction=None):
    attempts = app['nora_observatory']
    run = attempts.get(user_id)
    if run is None or run.session != session or now - run.seen > ATTEMPT_TTL:
        for stale in [uid for uid, active in attempts.items() if now - active.seen > ATTEMPT_TTL]:
            del attempts[stale]
        run = attempts[user_id] = Attempt(session, now)
    valid = run.advance(pose, now, interaction)
    # Concurrent HTTP retries still share the same durable award. Preserve the first
    # award confirmation in this run if a duplicate also reaches the transaction.
    if run.checkpoint == FINISH and run.reward is None:
        amount = await claim(app['db'], user_id)
        if amount or run.reward is None:
            run.reward = amount
    hold = None if run.ritual_since is None else max(0, math.ceil(LAYOUT['ritualSeconds'] - now + run.ritual_since))
    return {'checkpoint': run.checkpoint, 'reward': run.reward, 'reset': not valid,
            'bells': run.bells, 'action': run.action, 'notice': run.notice, 'hold': hold}
