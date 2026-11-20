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

POSITIVE_SOCIAL_ACTIONS = {"обнять", "обнять обнять"}
NEGATIVE_SOCIAL_ACTIONS = {"пнуть", "пнуть пнуть", "ударить", "ударить ударить"}
LIKE_PHRASES = {"поцеловать", "поцеловать поцеловать"}

POSITIVE_REPUTATION_PHRASES = POSITIVE_SOCIAL_ACTIONS | {
    "+",
    "+реп",
    "уважаю",
    "согл",
    "согласен",
    "ты прав",
}
NEGATIVE_REPUTATION_PHRASES = NEGATIVE_SOCIAL_ACTIONS | {
    "-",
    "-реп",
    "не уважаю",
    "не согл",
    "не согласен",
    "ты не прав",
}


STARTING_REPUTATION = 69
AUTO_REPUTATION_CAP = 69
DAILY_REPUTATION_CAP = 89
REPUTATION_FLOOR = -20
RESTORE_REP_GAIN = 10


@dataclass(frozen=True, slots=True)
class ReputationTier:
    key: str
    emoji: str
    label: str
    discount: int
    daily_actions: int
    can_minus: bool
    ai_daily_requests: int


def reputation_tier(value: int, restricted_threshold: int = 0) -> ReputationTier:
    if value < restricted_threshold:
        return ReputationTier("restricted", "🔞", "ограничен", 0, 0, False, 0)
    if value >= 90:
        return ReputationTier("gold", "🥇", "золото", 10, 5, True, 100)
    if value >= 70:
        return ReputationTier("silver", "🥈", "серебро", 5, 3, True, 10)
    return ReputationTier("bronze", "🥉", "бронза", 2, 1, False, 5)


def ai_limits_text() -> str:
    return ", ".join(f"{tier.label} — {tier.ai_daily_requests}" for tier in map(reputation_tier, (0, 70, 90)))


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


def transfer_commission_percent(reputation: int, restricted_threshold: int = 0) -> int:
    key = reputation_tier(reputation, restricted_threshold).key
    if key == "gold":
        return 10
    if key == "silver":
        return 20
    return 30


PERMANENT_DURATION = timedelta(days=400)
_PERMANENT_TOKENS = {"навсегда", "perm", "forever", "перм", "навечно", "0"}


def is_permanent_duration(delta: timedelta) -> bool:
    return delta.total_seconds() >= 366 * 24 * 3600


def format_duration(delta: timedelta) -> str:
    if is_permanent_duration(delta):
        return "навсегда"
    minutes = max(1, int(delta.total_seconds() // 60))
    if minutes >= 24 * 60:
        days = minutes // (24 * 60)
        hours = (minutes % (24 * 60)) // 60
        if hours:
            return f"{days} д {hours} ч"
        return f"{days} д"
    if minutes >= 60:
        hours = minutes // 60
        rest = minutes % 60
        if rest:
            return f"{hours} ч {rest} мин"
        return f"{hours} ч"
    return f"{minutes} мин"


def parse_duration_or_permanent(raw: str) -> timedelta | None:
    token = (raw or "").strip().casefold()
    if token in _PERMANENT_TOKENS:
        return PERMANENT_DURATION
    return parse_duration(token)


def win_after_commission(gross: int, reputation: int, restricted_threshold: int = 0) -> tuple[int, int]:
    percent = transfer_commission_percent(reputation, restricted_threshold)
    net = max(0, int(gross) * (100 - percent) // 100)
    return net, percent


def ru_plural(n: int, one: str, few: str, many: str) -> str:
    value = abs(int(n)) % 100
    if 11 <= value <= 14:
        return many
    value %= 10
    if value == 1:
        return one
    if 2 <= value <= 4:
        return few
    return many


def cookie_word(n: int, *, case: str = "nom") -> str:
    if case == "gen":
        return ru_plural(n, "печеньки", "печенек", "печенек")
    if case == "acc":
        return ru_plural(n, "печеньку", "печеньки", "печенек")
    if case == "prep":
        return ru_plural(n, "печеньке", "печеньках", "печеньках")
    return ru_plural(n, "печенька", "печеньки", "печенек")


def cookies_phrase(n: int, *, case: str = "nom") -> str:
    return f"{int(n)} {cookie_word(n, case=case)}"


def transfer_amount(text: str) -> int | None:
    match = re.fullmatch(
        r"\s*(?:перевести|передать)\s+(\d+)(?:\s+(?:печен(?:ек|ьку|ьки|ька|ья)|🍪))?\s*",
        text,
        re.IGNORECASE,
    )
    return int(match.group(1)) if match else None
