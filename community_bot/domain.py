from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

ROLE_LEVELS = {"member": 0, "moderator": 40, "admin": 70, "owner": 100}
ROLE_LABELS = {
    "member": "участник",
    "moderator": "модератор",
    "admin": "админ",
    "owner": "владелец",
}

POSITIVE_REPUTATION_PHRASES = {
    "+",
    "+реп",
    "поддерживаю",
    "обожаю",
    "целую",
    "обнимаю",
    "люблю",
}
NEGATIVE_REPUTATION_PHRASES = {
    "-",
    "-реп",
    "хуйня",
    "ударить",
    "пнуть",
    "ненавижу",
    "пошел нахуй",
    "пошёл нахуй",
}


@dataclass(frozen=True, slots=True)
class ReputationTier:
    key: str
    emoji: str
    label: str
    discount: int
    daily_actions: int


def reputation_tier(value: int, restricted_threshold: int = 0) -> ReputationTier:
    if value < restricted_threshold:
        return ReputationTier("restricted", "🔞", "ограничен", 0, 0)
    if value >= 90:
        return ReputationTier("gold", "🥇", "золото", 20, 5)
    if value >= 70:
        return ReputationTier("silver", "🥈", "серебро", 10, 3)
    return ReputationTier("bronze", "🥉", "бронза", 0, 0)


def discounted_price(base_price: int, discount: int) -> int:
    if base_price <= 0:
        return 0
    return max(1, (base_price * (100 - discount) + 99) // 100)


def normalize_phrase(text: str) -> str:
    return " ".join(text.casefold().strip().split())


def reputation_delta(text: str) -> int | None:
    phrase = normalize_phrase(text)
    if phrase in POSITIVE_REPUTATION_PHRASES:
        return 5
    if phrase in NEGATIVE_REPUTATION_PHRASES:
        return -5
    return None


_DURATION_RE = re.compile(r"^(\d+)([mhdwмчдн])$", re.IGNORECASE)


def parse_duration(raw: str) -> timedelta | None:
    match = _DURATION_RE.fullmatch(raw.strip())
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2).casefold()
    if value <= 0:
        return None
    if unit in {"m", "м"}:
        return timedelta(minutes=value)
    if unit in {"h", "ч"}:
        return timedelta(hours=value)
    if unit in {"d", "д"}:
        return timedelta(days=value)
    return timedelta(weeks=value)


def transfer_amount(text: str) -> int | None:
    match = re.fullmatch(
        r"\s*(?:перевести|передать)\s+(\d+)\s+(?:печен(?:ек|ьки|ья)|🍪)\s*",
        text,
        re.IGNORECASE,
    )
    return int(match.group(1)) if match else None
