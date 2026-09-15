from __future__ import annotations

from community_bot.domain import transfer_commission_percent
from community_bot.pet_cosmetics import pet_hourly_milli

LOAN_PRINCIPAL = 100
LOAN_DAYS = 7

TRANSACTION_LABELS = {
    "transfer": "Перевод",
    "admin_set": "Админ: баланс",
    "shop": "Магазин",
    "sbp_payment": "Пополнение СБП",
    "roulette": "Рулетка",
    "subscription_freebie": "Халява",
    "pet_farm": "Фарм тамагочи",
    "pet_shop": "Магазин питомца",
    "rsvp": "Мероприятие",
    "cookie_game_stake": "Ставка в игре",
    "cookie_game_win": "Выигрыш в игре",
    "cookie_game_refund": "Возврат ставки",
    "cookie_game_restake": "Пересчёт ставки",
    "loan": "Кредит кошелька",
    "loan_repay": "Погашение кредита",
    "debt": "Долг кошелька",
    "lottery": "Розыгрыш",
    "lottery_win": "Выигрыш розыгрыша",
    "contest_win": "Приз конкурса",
}


def loan_interest_percent(reputation: int, restricted_threshold: int = 0) -> int:
    return transfer_commission_percent(reputation, restricted_threshold)


def wallet_net(user: dict[str, object]) -> int:
    return int(user.get("cookies") or 0) - int(user.get("cookie_debt") or 0)


def after_commission(amount: int, percent: int) -> int:
    return max(0, amount * (100 - percent) // 100)


def loan_repay_amount(principal: int, interest_percent: int) -> int:
    return principal + (principal * interest_percent + 99) // 100


def pet_farm_rate_line(pet: dict[str, object] | None, equipped: list[str] | tuple[str, ...] | set[str] = ()) -> str:
    if not pet:
        return "Тамагочи нет — фарм 🍪 выключен. Завести можно в магазине."
    hunger = int(pet["hunger"])
    thirst = int(pet["thirst"])
    if hunger == 0 or thirst == 0 or int(pet.get("sleeping") or 0):
        return f"💤 {pet['name']} спит от голода или жажды и сейчас не фармит."
    milli_per_hour = pet_hourly_milli(pet, equipped)
    per_day = milli_per_hour * 24 / 1000
    from community_bot.pet_cosmetics import cosmetic_bonus_milli

    add = cosmetic_bonus_milli(equipped)
    extra = f", кастом +{add}/ч" if add else ""
    return (
        f"🐾 {pet['name']} фармит ≈ <b>{per_day:.1f} 🍪/сутки</b> "
        f"({milli_per_hour}/1000 🍪 в час{extra}). Сытость {hunger}, жажда {thirst}."
    )


def transaction_line(row: dict[str, object]) -> str:
    kind = str(row["kind"])
    label = TRANSACTION_LABELS.get(kind, kind)
    amount = int(row["amount"])
    sign = f"+{amount}" if amount > 0 else str(amount)
    when = str(row["created_at"])[:16].replace("T", " ")
    return f"{when} · {sign} 🍪 · {label}"
