from __future__ import annotations

from community_bot.domain import discounted_price, reputation_tier

ITEM_LABELS = {
    "restore_rep": "Поднять репутацию +10",
    "reset_limits": "Сброс лимитов репутации",
    "forgive": "Прости меня…",
    "rep_shield": "Щит на 1 удар −репа",
    "immunity_24h": "Плащ иммунитета · 24 часа",
    "custom_status": "Кастомный статус",
    "video_avatar": "Видео-аватар профиля",
    "private_profile": "Приватный профиль",
    "ornate_profile": "Кастомный профиль",
    "title_owl": "Титул «Ночная сова»",
    "title_regular": "Титул «Завсегдатай»",
    "title_star": "Титул «Звезда норы»",
    "tamagotchi": "Завести тамагочи",
    "pet_meal": "Обед питомцу +40",
    "pet_drink": "Поилка питомцу +50",
    "season_pack": "Сезонный набор: щит + обед",
}

REMOVED_COSMETIC_SKUS = ("pet_hat", "pet_scarf", "pet_glasses")

NO_REPUTATION_DISCOUNT = {"event_pass"}

IMMUNITY_HOURS = {
    "immunity_24h": 24,
}

TITLE_ITEMS = {
    "title_owl": "Ночная сова",
    "title_regular": "Завсегдатай",
    "title_star": "Звезда норы",
}

SEED_CATEGORIES = (
    {
        "slug": "pets",
        "title": "🐾 Тамагочи",
        "description": "Талисман сообщества, припасы и сезонный набор.",
        "sort_order": 10,
    },
    {
        "slug": "reputation",
        "title": "🏅 Репутация",
        "description": "Плюс к репутации, щит на один −реп, плащ на сутки и прощение варнов.",
        "sort_order": 20,
    },
    {
        "slug": "profile",
        "title": "✨ Профиль",
        "description": "Косметика карточки и титулы, которые видно всем.",
        "sort_order": 30,
    },
)

SEED_ITEMS = (
    {"sku": "tamagotchi", "category_slug": "pets", "title": ITEM_LABELS["tamagotchi"], "sort_order": 10},
    {"sku": "pet_meal", "category_slug": "pets", "title": ITEM_LABELS["pet_meal"], "sort_order": 20},
    {"sku": "pet_drink", "category_slug": "pets", "title": ITEM_LABELS["pet_drink"], "sort_order": 30},
    {"sku": "season_pack", "category_slug": "pets", "title": ITEM_LABELS["season_pack"], "sort_order": 40},
    {"sku": "restore_rep", "category_slug": "reputation", "title": ITEM_LABELS["restore_rep"], "sort_order": 10},
    {"sku": "reset_limits", "category_slug": "reputation", "title": ITEM_LABELS["reset_limits"], "sort_order": 20},
    {"sku": "rep_shield", "category_slug": "reputation", "title": ITEM_LABELS["rep_shield"], "sort_order": 30},
    {"sku": "immunity_24h", "category_slug": "reputation", "title": ITEM_LABELS["immunity_24h"], "sort_order": 40},
    {"sku": "forgive", "category_slug": "reputation", "title": ITEM_LABELS["forgive"], "sort_order": 50},
    {"sku": "custom_status", "category_slug": "profile", "title": ITEM_LABELS["custom_status"], "sort_order": 10},
    {"sku": "video_avatar", "category_slug": "profile", "title": ITEM_LABELS["video_avatar"], "sort_order": 20},
    {"sku": "private_profile", "category_slug": "profile", "title": ITEM_LABELS["private_profile"], "sort_order": 30},
    {"sku": "ornate_profile", "category_slug": "profile", "title": ITEM_LABELS["ornate_profile"], "sort_order": 40},
    {"sku": "title_owl", "category_slug": "profile", "title": ITEM_LABELS["title_owl"], "sort_order": 50},
    {"sku": "title_regular", "category_slug": "profile", "title": ITEM_LABELS["title_regular"], "sort_order": 60},
    {"sku": "title_star", "category_slug": "profile", "title": ITEM_LABELS["title_star"], "sort_order": 70},
)

# Kept for tests and fallbacks that still expect a category → items map.
SHOP_CATEGORIES = {
    row["slug"]: {
        "title": row["title"],
        "intro": row["description"],
        "items": tuple(item["sku"] for item in SEED_ITEMS if item["category_slug"] == row["slug"]),
    }
    for row in SEED_CATEGORIES
}

PET_SUPPLIES = {
    "pet_meal": ("food", 40, "Обед"),
    "pet_drink": ("water", 50, "Поилка"),
}

GIFTABLE_ITEMS = {
    "restore_rep",
    "reset_limits",
    "forgive",
    "rep_shield",
    "immunity_24h",
    "title_owl",
    "title_regular",
    "title_star",
    "pet_meal",
    "pet_drink",
    "season_pack",
}

VITRINE_KEYS = tuple(item["sku"] for item in SEED_ITEMS if item["sku"] != "tamagotchi")

DEFAULT_SHOP_HEADER = {
    "enabled": False,
    "title": "",
    "text": "",
}


def item_discount(item: str, tier_discount: int) -> int:
    if item in NO_REPUTATION_DISCOUNT:
        return 0
    return tier_discount


def apply_shop_discounts(
    raw_prices: dict[str, int],
    user: dict[str, object],
    restricted_threshold: int,
) -> dict[str, int]:
    tier = reputation_tier(int(user["reputation"]), restricted_threshold)
    return {
        key: discounted_price(price, item_discount(key, tier.discount))
        for key, price in raw_prices.items()
        if price is not None and int(price) > 0
    }


def shop_prices_for(
    user: dict[str, object],
    restricted_threshold: int,
    prices: dict[str, int] | None = None,
) -> dict[str, int]:
    return apply_shop_discounts(prices or {}, user, restricted_threshold)


def item_label(sku: str, catalog_title: str | None = None) -> str:
    if catalog_title:
        return catalog_title
    return str(ITEM_LABELS.get(sku) or sku)


def shop_header_lines(header: dict[str, object] | None) -> str:
    if not header or not header.get("enabled"):
        return ""
    title = str(header.get("title") or "").strip()
    text = str(header.get("text") or "").strip()
    if not title and not text:
        return ""
    parts: list[str] = []
    if title:
        parts.append(title if "<" in title else f"<b>{title}</b>")
    if text:
        parts.append(text)
    return "\n".join(parts) + "\n\n"


# Sample map for tests and docs. Live prices live in SQLite and start unset.
SAMPLE_SHOP_PRICES = {
    "restore_rep": 20,
    "reset_limits": 15,
    "forgive": 50,
    "rep_shield": 12,
    "immunity_24h": 18,
    "custom_status": 5,
    "video_avatar": 10,
    "private_profile": 15,
    "ornate_profile": 25,
    "title_owl": 18,
    "title_regular": 18,
    "title_star": 30,
    "tamagotchi": 50,
    "pet_meal": 4,
    "pet_drink": 4,
    "season_pack": 28,
}

BASE_SHOP_PRICES = SAMPLE_SHOP_PRICES
