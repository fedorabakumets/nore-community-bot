from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_SBP_PAYMENT_URL = "https://www.sberbank.com/sms/pbpn?requisiteNumber=79533571508"


def _as_int(name: str, default: int = 0) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} должен быть целым числом") from exc


def _as_int_set(name: str) -> frozenset[int]:
    values = os.getenv(name, "").replace(";", ",").split(",")
    result: set[int] = set()
    for value in values:
        value = value.strip()
        if value:
            result.add(int(value))
    return frozenset(result)


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    owner_id: int
    owner_ids: frozenset[int]
    moderator_ids: frozenset[int]
    community_chat_id: int
    database_path: Path
    welcome_cover: str | None
    event_pass_price: int
    support_price: int
    restricted_reputation_threshold: int
    timezone: str
    cookie_price_rub: int
    sbp_payment_url: str
    freebie_channel_id: int
    freebie_channel_url: str
    community_invite_url: str
    tmdb_api_key: str
    gemini_api_key: str
    groq_api_key: str

    def is_owner(self, user_id: int) -> bool:
        return user_id in self.owner_ids

    @property
    def reviewers(self) -> frozenset[int]:
        return self.moderator_ids | self.owner_ids


def load_settings() -> Settings:
    load_dotenv()
    owner_id = _as_int("OWNER_ID")
    owner_ids = frozenset(_as_int_set("OWNER_IDS") | ({owner_id} if owner_id else set()))
    community_chat_id = _as_int("COMMUNITY_CHAT_ID") or _as_int("GROUP_ID")
    settings = Settings(
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        owner_id=owner_id,
        owner_ids=owner_ids,
        moderator_ids=_as_int_set("MODERATOR_IDS"),
        community_chat_id=community_chat_id,
        database_path=Path(os.getenv("DATABASE_PATH", "data/community.db")),
        welcome_cover=os.getenv("WELCOME_COVER", "").strip() or None,
        event_pass_price=max(0, _as_int("EVENT_PASS_PRICE")),
        support_price=max(0, _as_int("SUPPORT_PRICE")),
        restricted_reputation_threshold=_as_int("RESTRICTED_REPUTATION_THRESHOLD"),
        timezone=os.getenv("TIMEZONE", "Europe/Moscow").strip(),
        cookie_price_rub=max(1, _as_int("COOKIE_PRICE_RUB", 1)),
        sbp_payment_url=os.getenv("SBP_PAYMENT_URL", "").strip() or DEFAULT_SBP_PAYMENT_URL,
        freebie_channel_id=_as_int("FREEBIE_CHANNEL_ID"),
        freebie_channel_url=os.getenv("FREEBIE_CHANNEL_URL", "").strip(),
        community_invite_url=os.getenv(
            "COMMUNITY_INVITE_URL",
            "https://t.me/+MfMowwQUlZlkMDIy",
        ).strip(),
        tmdb_api_key=os.getenv("TMDB_API_KEY", "").strip(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
    )
    if not settings.bot_token:
        raise ValueError("BOT_TOKEN не задан в .env")
    if not settings.owner_id:
        raise ValueError("OWNER_ID не задан в .env")
    return settings
