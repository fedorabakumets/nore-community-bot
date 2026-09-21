from __future__ import annotations

from community_bot.domain import transfer_commission_percent

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
    "pet_expedition": "Экспедиция тамагочи",
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


def pet_status_line(pet: dict[str, object] | None) -> str:
    if not pet:
        return "Тамагочи нет. Завести можно в магазине — это талисман, который ищет редкие вещи."
    name = str(pet.get("name") or "Тамагочи")
    until = str(pet.get("expedition_until") or "")
    if until:
        return f"🗺 {name} сейчас в экспедиции и ищет редкие находки."
    return (
        f"🐾 {name} — талисман сообщества. Печеньки он приносит только из экспедиции "
        f"(раз в 24 часа), сам по себе не фармит."
    )


def pet_farm_rate_line(pet: dict[str, object] | None, equipped: list[str] | tuple[str, ...] | set[str] = ()) -> str:
    del equipped
    return pet_status_line(pet)


def transaction_line(row: dict[str, object]) -> str:
    kind = str(row["kind"])
    label = TRANSACTION_LABELS.get(kind, kind)
    amount = int(row["amount"])
    sign = f"+{amount}" if amount > 0 else str(amount)
    when = str(row["created_at"])[:16].replace("T", " ")
    return f"{when} · {sign} 🍪 · {label}"
