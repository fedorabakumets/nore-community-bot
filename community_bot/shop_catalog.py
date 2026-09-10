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
}

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
        "intro": "Питомец и два припаса. Еда за активность приходит тихо, без лички.",
        "items": ("tamagotchi", "pet_meal", "pet_drink"),
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

VITRINE_KEYS = tuple(key for key in BASE_SHOP_PRICES if key not in {"tamagotchi"})


def shop_prices_for(user: dict[str, object], restricted_threshold: int) -> dict[str, int]:
    tier = reputation_tier(int(user["reputation"]), restricted_threshold)
    return {key: discounted_price(price, tier.discount) for key, price in BASE_SHOP_PRICES.items()}
