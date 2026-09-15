from __future__ import annotations

from community_bot.domain import discounted_price, reputation_tier
from community_bot.pet_cosmetics import COSMETIC_ITEMS, COSMETIC_ORDER

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
    "pet_hat": COSMETIC_ITEMS["pet_hat"]["label"],
    "pet_scarf": COSMETIC_ITEMS["pet_scarf"]["label"],
    "pet_glasses": COSMETIC_ITEMS["pet_glasses"]["label"],
}

BASE_SHOP_PRICES = {
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
    "pet_hat": 8,
    "pet_scarf": 8,
    "pet_glasses": 10,
}

NO_REPUTATION_DISCOUNT = {"event_pass"}

IMMUNITY_HOURS = {
    "immunity_24h": 24,
}

TITLE_ITEMS = {
    "title_owl": "Ночная сова",
    "title_regular": "Завсегдатай",
    "title_star": "Звезда норы",
}

SHOP_CATEGORIES = {
    "pets": {
        "title": "🐾 Тамагочи",
        "intro": "Питомец, припасы и сезонный набор (щит + обед).",
        "items": ("tamagotchi", "pet_meal", "pet_drink", "season_pack"),
    },
    "cosmetics": {
        "title": "🎨 Кастомизация",
        "intro": (
            "Шапки, шарфы и очки для тамагочи. "
            "После покупки наденьте предмет — он меняет фото и даёт бонус к фарму."
        ),
        "items": COSMETIC_ORDER,
    },
    "reputation": {
        "title": "🏅 Репутация",
        "intro": "Плюс к репутации, щит на один −реп, плащ на сутки и прощение варнов.",
        "items": (
            "restore_rep",
            "reset_limits",
            "rep_shield",
            "immunity_24h",
            "forgive",
        ),
    },
    "profile": {
        "title": "✨ Профиль",
        "intro": "Косметика карточки и титулы, которые видно всем.",
        "items": (
            "custom_status",
            "video_avatar",
            "private_profile",
            "ornate_profile",
            "title_owl",
            "title_regular",
            "title_star",
        ),
    },
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

VITRINE_KEYS = tuple(key for key in BASE_SHOP_PRICES if key not in {"tamagotchi"})


def item_discount(item: str, tier_discount: int) -> int:
    if item in NO_REPUTATION_DISCOUNT:
        return 0
    return tier_discount


def shop_prices_for(user: dict[str, object], restricted_threshold: int) -> dict[str, int]:
    tier = reputation_tier(int(user["reputation"]), restricted_threshold)
    return {
        key: discounted_price(price, item_discount(key, tier.discount))
        for key, price in BASE_SHOP_PRICES.items()
    }
