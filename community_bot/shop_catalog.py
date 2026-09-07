from __future__ import annotations

from community_bot.domain import discounted_price, reputation_tier

ITEM_LABELS = {
    "restore_rep": "Восстановить репутацию",
    "reset_limits": "Сброс лимитов репутации",
    "forgive": "Прости меня…",
    "immunity_1h": "Иммунитет · 1 час",
    "immunity_6h": "Иммунитет · 6 часов",
    "immunity_24h": "Иммунитет · 24 часа",
    "immunity_72h": "Иммунитет · 3 дня",
    "custom_status": "Кастомный статус",
    "video_avatar": "Видео-аватар профиля",
    "tamagotchi": "Завести тамагочи",
    "pet_snack": "Перекус питомцу +10",
    "pet_meal": "Обед питомцу +35",
    "pet_feast": "Пир питомцу +70",
    "pet_water": "Вода питомцу +25",
    "pet_drink": "Большая поилка +70",
}

BASE_SHOP_PRICES = {
    "restore_rep": 5,
    "reset_limits": 10,
    "forgive": 50,
    "immunity_1h": 4,
    "immunity_6h": 8,
    "immunity_24h": 10,
    "immunity_72h": 22,
    "custom_status": 5,
    "video_avatar": 10,
    "tamagotchi": 50,
    "pet_snack": 1,
    "pet_meal": 3,
    "pet_feast": 5,
    "pet_water": 2,
    "pet_drink": 5,
}

IMMUNITY_HOURS = {
    "immunity_1h": 1,
    "immunity_6h": 6,
    "immunity_24h": 24,
    "immunity_72h": 72,
}

SHOP_CATEGORIES = {
    "pets": {
        "title": "🐾 Тамагочи",
        "intro": "Корм, вода и новый питомец. Яркие кнопки — это полка с вкусностями.",
        "items": ("tamagotchi", "pet_snack", "pet_meal", "pet_feast", "pet_water", "pet_drink"),
    },
    "reputation": {
        "title": "🏅 Репутация",
        "intro": "Восстановление репутации, прощение и иммунитет на разное время.",
        "items": (
            "restore_rep",
            "reset_limits",
            "forgive",
            "immunity_1h",
            "immunity_6h",
            "immunity_24h",
            "immunity_72h",
        ),
    },
    "profile": {
        "title": "✨ Профиль",
        "intro": "Косметика карточки: статус и видео-аватар.",
        "items": ("custom_status", "video_avatar"),
    },
}

PET_SUPPLIES = {
    "pet_snack": ("food", 10, "Перекус"),
    "pet_meal": ("food", 35, "Обед"),
    "pet_feast": ("food", 70, "Пир"),
    "pet_water": ("water", 25, "Вода"),
    "pet_drink": ("water", 70, "Большая поилка"),
}


def shop_prices_for(user: dict[str, object], restricted_threshold: int) -> dict[str, int]:
    tier = reputation_tier(int(user["reputation"]), restricted_threshold)
    return {key: discounted_price(price, tier.discount) for key, price in BASE_SHOP_PRICES.items()}
