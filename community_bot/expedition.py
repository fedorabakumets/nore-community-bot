from __future__ import annotations

import html
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

logger = logging.getLogger(__name__)

# Duration of one expedition and the cooldown before the next send.
EXPEDITION_DURATION = timedelta(hours=24)

# Weights are in ten-thousandths: 1 unit = 0.01%. Must sum to 10_000.
# 10 cookies is exactly 0.01% as required.
COOKIE_WEIGHTS: dict[int, int] = {
    1: 4000,
    2: 2500,
    3: 1500,
    4: 1000,
    5: 600,
    6: 250,
    7: 100,
    8: 40,
    9: 9,
    10: 1,
}

WEIGHT_TOTAL = sum(COOKIE_WEIGHTS.values())
if WEIGHT_TOTAL != 10_000:
    raise RuntimeError(f"COOKIE_WEIGHTS must sum to 10000, got {WEIGHT_TOTAL}")
if COOKIE_WEIGHTS.get(10) != 1:
    raise RuntimeError("10 cookies must have probability 0.01%")


@dataclass(frozen=True, slots=True)
class ExpeditionLoot:
    """One find from an expedition. kind is extendable: cookies, item, title, achievement, merch."""

    kind: str
    amount: int = 0
    sku: str = ""
    title: str = ""

    def label(self) -> str:
        if self.title:
            return self.title
        if self.kind == "cookies":
            from community_bot.domain import cookies_phrase

            return f"{cookies_phrase(self.amount)} 🍪"
        if self.sku:
            return self.sku
        return "награда"

    def to_json(self) -> dict[str, object]:
        return {"kind": self.kind, "amount": self.amount, "sku": self.sku, "title": self.title}

    @classmethod
    def from_mapping(cls, raw: object) -> ExpeditionLoot | None:
        if not isinstance(raw, dict):
            return None
        kind = str(raw.get("kind") or "").strip() or "cookies"
        return cls(
            kind=kind,
            amount=int(raw.get("amount") or 0),
            sku=str(raw.get("sku") or ""),
            title=str(raw.get("title") or ""),
        )


def roll_expedition_loot() -> ExpeditionLoot:
    ticket = secrets.randbelow(WEIGHT_TOTAL)
    acc = 0
    for amount, weight in COOKIE_WEIGHTS.items():
        acc += weight
        if ticket < acc:
            return ExpeditionLoot(kind="cookies", amount=amount)
    return ExpeditionLoot(kind="cookies", amount=1)


def parse_loot(raw: str | None) -> ExpeditionLoot | None:
    if not raw:
        return None
    try:
        return ExpeditionLoot.from_mapping(json.loads(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def expedition_until_iso(now: datetime | None = None) -> str:
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return (moment.astimezone(UTC) + EXPEDITION_DURATION).isoformat()


def remaining_label(until_iso: str, timezone: str) -> str:
    try:
        until = datetime.fromisoformat(until_iso)
        if until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        zone = ZoneInfo(timezone)
        now = datetime.now(zone)
        left = until.astimezone(zone) - now
        seconds = int(left.total_seconds())
        if seconds <= 0:
            return "вот-вот вернётся"
        hours, rem = divmod(seconds, 3600)
        minutes = rem // 60
        if hours:
            return f"ещё {hours} ч {minutes} мин"
        return f"ещё {minutes} мин"
    except (ValueError, TypeError):
        return "в пути"


def result_text(
    *,
    pet_name: str,
    species_words: dict[str, str],
    loot: ExpeditionLoot,
    mention: str | None = None,
) -> str:
    name = html.escape(pet_name)
    returned = species_words.get("returned") or "вернулся"
    prize = html.escape(loot.label())
    who = f" к {mention}" if mention else ""
    return (
        f"🗺 <b>{name}</b> {returned} из экспедиции{who}.\n"
        f"Результат: питомец сыскал награду.\n"
        f"Находка: <b>{prize}</b>."
    )


async def announce_expedition_result(
    bot,
    db,
    settings,
    user_id: int,
    pet: dict[str, object],
    loot: ExpeditionLoot,
) -> bool:
    """Send one group + one DM notice. Idempotent via claim_expedition_notice."""
    claimed = await db.claim_expedition_notice(user_id)
    if not claimed:
        return False
    from community_bot.helpers import user_link
    from community_bot.pets_talk import pet_pronouns

    words = pet_pronouns(str(pet.get("species") or ""))
    pet_name = str(pet.get("name") or "Питомец")
    owner = await db.get_user(user_id)
    owner_name = str(
        (owner or {}).get("profile_name")
        or (owner or {}).get("telegram_name")
        or (owner or {}).get("username")
        or user_id
    )
    mention = user_link(user_id, owner_name)
    chat_text = result_text(pet_name=pet_name, species_words=words, loot=loot, mention=mention)
    dm_text = result_text(pet_name=pet_name, species_words=words, loot=loot)
    if settings.community_chat_id:
        try:
            await bot.send_message(settings.community_chat_id, chat_text, parse_mode="HTML")
        except Exception:
            logger.exception("Не удалось написать в чат о возвращении тамагочи %s", user_id)
    try:
        await bot.send_message(user_id, dm_text, parse_mode="HTML")
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.info("Личка о возвращении тамагочи недоступна user=%s", user_id)
    except Exception:
        logger.exception("Не удалось написать в личку о возвращении тамагочи %s", user_id)
    return True
