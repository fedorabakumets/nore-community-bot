from __future__ import annotations

from datetime import UTC, datetime

from community_bot.database import Database
from community_bot.shop_catalog import ITEM_LABELS

GIFT_ALIASES = {
    "щит": "rep_shield",
    "плащ": "immunity_24h",
    "обед": "pet_meal",
    "поилка": "pet_drink",
    "набор": "season_pack",
    "прощение": "forgive",
    "реп": "restore_rep",
    "репутацию": "restore_rep",
}

ACHIEVEMENTS = {
    "first_plus": ("Первый плюс", "Выдали первое +реп в чате"),
    "first_pet": ("Хозяин норки", "Завели тамагочи"),
    "messages_100": ("Голос норы", "100 сообщений за всё время"),
    "shop_first": ("Покупатель", "Первая покупка в магазине"),
    "gift_first": ("Щедрая лапа", "Подарили товар другому"),
    "expedition": ("Следопыт", "Питомец сходил в экспедицию"),
    "lottery": ("В котле", "Вошли в розыгрыш"),
}

WARN_MUTE_AT = 3
WARN_KICK_AT = 5
WARN_MUTE_HOURS = 24


def gift_item_from_args(raw: str | list[str] | None) -> str | None:
    if isinstance(raw, list):
        raw = " ".join(raw)
    token = " ".join((raw or "").casefold().split())
    if token in GIFT_ALIASES:
        return GIFT_ALIASES[token]
    for key, label in ITEM_LABELS.items():
        if token and token in label.casefold():
            return key
    if token in ITEM_LABELS:
        return token
    return None


def achievement_lines(slugs: list[str]) -> str:
    if not slugs:
        return ""
    labels = [ACHIEVEMENTS[slug][0] for slug in slugs if slug in ACHIEVEMENTS]
    if not labels:
        return ""
    return "🏅 " + " · ".join(labels)


async def unlock(db: Database, user_id: int, slug: str) -> str | None:
    if slug not in ACHIEVEMENTS:
        return None
    if not await db.unlock_achievement(user_id, slug):
        return None
    title, _ = ACHIEVEMENTS[slug]
    return title


def vitrine_active(stock: str | None, until: str | None) -> bool:
    if until:
        try:
            if datetime.fromisoformat(until) <= datetime.now(UTC):
                return False
        except ValueError:
            return False
    if stock == "0":
        return False
    return True


def matches_stop_word(text: str, words: list[str]) -> str | None:
    hay = f" {(text or '').casefold()} "
    for word in words:
        needle = str(word).casefold()
        if needle and needle in hay:
            return word
    return None


def title_for_item(item: str) -> str:
    return ITEM_LABELS.get(item, item)
