from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from community_bot.domain import transfer_commission_percent

LOAN_PRINCIPAL = 100
LOAN_DAYS = 7

TRANSACTION_LABELS = {
    "birthday_gift": "Подарок НОРЫ ко дню рождения",
    "profile_complete": "Бонус за заполнение профиля",
    "daily_chat": "Награда за активность в чате",
    "transfer": "Перевод",
    "admin": "Начисление администратора",
    "admin_set": "Корректировка баланса",
    "wallet_reset": "Сброс баланса",
    "community_reset": "Сброс баланса сообщества",
    "ban_reset": "Сброс баланса при бане",
    "shop": "Магазин",
    "seasonal_purchase": "Сезонный предмет",
    "sbp_payment": "Пополнение СБП",
    "roulette": "Рулетка",
    "subscription_freebie": "Халява",
    "pet_farm": "Находки питомца",
    "pet_expedition": "Экспедиция питомца",
    "pet_stage": "Этап развития питомца",
    "pet_shop": "Магазин питомца",
    "rsvp": "Мероприятие",
    "rsvp_refund": "Возврат залога за мероприятие",
    "cookie_game_stake": "Ставка в игре",
    "cookie_game_win": "Выигрыш в игре",
    "cookie_game_refund": "Возврат ставки",
    "cookie_game_restake": "Пересчёт ставки",
    "rocket_bet": "Ракетка · ставка",
    "rocket_payout": "Ракетка · выплата",
    "sea_bet": "Морской бой · ставка",
    "sea_win": "Морской бой · выигрыш",
    "sea_refund": "Морской бой · возврат ставки",
    "loan": "НОРА — СТАРТЕР-ПАК",
    "loan_repay": "Возврат стартер-пака",
    "debt_repay": "Погашение просроченного долга",
    "debt": "Долг кошелька",
    "lottery": "Розыгрыш",
    "lottery_win": "Выигрыш розыгрыша",
    "contest_win": "Приз конкурса",
}

HISTORY_FILTERS = {"all": "Все", "incoming": "Поступления", "outgoing": "Списания", "transfers": "Переводы"}

TRANSACTION_SOURCES = {
    "birthday_gift": "Нора",
    "profile_complete": "Нора · профиль",
    "daily_chat": "Нора · активность сообщества",
    "wallet_reset": "Нора · сброс кошельков",
    "community_reset": "Нора · перезапуск сообщества",
    "ban_reset": "Нора · модерация",
    "shop": "Магазин Норы",
    "pet_shop": "Магазин питомцев",
    "seasonal_purchase": "Сезонный магазин",
    "sbp_payment": "СБП",
    "subscription_freebie": "Нора · подписка на канал",
    "pet_farm": "Твой питомец",
    "pet_expedition": "Твой питомец",
    "rsvp": "Мероприятия Норы",
    "rsvp_refund": "Мероприятия Норы",
    "cookie_game_stake": "Игры Норы",
    "cookie_game_win": "Игры Норы",
    "cookie_game_refund": "Игры Норы",
    "cookie_game_restake": "Игры Норы",
    "roulette": "Рулетка",
    "rocket_bet": "Ракетка",
    "rocket_payout": "Ракетка",
    "sea_bet": "Морской бой",
    "sea_win": "Морской бой",
    "sea_refund": "Морской бой",
    "loan": "Кошелёк Норы",
    "loan_repay": "Кошелёк Норы",
    "debt_repay": "Кошелёк Норы",
    "debt": "Кошелёк Норы",
    "lottery": "Розыгрыш Норы",
    "lottery_win": "Розыгрыш Норы",
    "contest_win": "Конкурс Норы",
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
        return "Питомца пока нет. Завести его можно в магазине."
    name = str(pet.get("name") or "Питомец")
    until = str(pet.get("expedition_until") or "")
    if until:
        return f"🗺 {name} сейчас в экспедиции и ищет редкие находки."
    return (
        f"🐾 {name} — питомец сообщества. Печеньки он приносит только из экспедиции "
        f"(раз в 24 часа), сам по себе не фармит."
    )


def pet_farm_rate_line(pet: dict[str, object] | None, equipped: list[str] | tuple[str, ...] | set[str] = ()) -> str:
    del equipped
    return pet_status_line(pet)


def _transaction_reference(details: str, prefix: str) -> int | None:
    match = re.fullmatch(re.escape(prefix) + r"([1-9][0-9]{0,18})", details)
    if match and (value := int(match[1])) <= 2**63 - 1:
        return value
    return None


def _transaction_party(row: dict) -> tuple[str, int | None]:
    kind, details = row["kind"], row.get("details") or ""
    if kind == "transfer":
        if row["amount"] < 0:
            return "Кому", _transaction_reference(details, "to:")
        return "От кого", _transaction_reference(details, "from:")
    if kind in {"admin", "admin_set"}:
        return "Администратор", _transaction_reference(details, "by:")
    if kind in {"shop", "pet_shop"} and "->" in details:
        return "Кому подарок", _transaction_reference(details.partition("->")[2], "")
    return "", None


async def describe_transactions(db, rows: list[dict]) -> list[dict]:
    parties = [_transaction_party(row) for row in rows]
    user_ids = sorted({user_id for _, user_id in parties if user_id is not None})
    names = {}
    if user_ids:
        placeholders = ",".join("?" for _ in user_ids)
        people = await db.fetchall(
            "SELECT user_id, profile_name, telegram_name, username FROM users "
            f"WHERE user_id IN ({placeholders})",
            tuple(user_ids),
        )
        for person in people:
            name = (person["profile_name"] or person["telegram_name"] or "").strip()[:120]
            handle = f"@{person['username']}" if person["username"] else f"ID {person['user_id']}"
            names[person["user_id"]] = f"{name} ({handle})" if name and name.casefold() != handle.casefold() else handle
    return [
        transaction_item(row, (role, names.get(user_id) or (f"ID {user_id}" if user_id else "нет данных")))
        for row, (role, user_id) in zip(rows, parties, strict=True)
    ]


def transaction_item(row: dict, party: tuple[str, str] | None = None) -> dict:
    from community_bot.shop_catalog import ITEM_LABELS

    kind = str(row["kind"])
    label = TRANSACTION_LABELS.get(kind, "Другая операция")
    amount = int(row["amount"])
    details = str(row.get("details") or "")
    if kind in {"shop", "pet_shop"}:
        sku, _, target = details.partition("->")
        extra_labels = {"support": "Поддержка проекта", "event_pass": "Оплата мероприятия"}
        label = ITEM_LABELS.get(sku, extra_labels.get(sku, label))
        if target.isdigit():
            label = "Подарок: " + label
    elif kind == "seasonal_purchase" and details:
        label = "Сезонный предмет: " + details
    elif kind == "transfer":
        label = "Перевод отправлен" if amount < 0 else "Перевод получен"
    elif kind == "wallet_reset" and amount > 0:
        label = "Восстановление бонуса профиля при сбросе"
    elif kind == "loan_repay" and ";debt:" in details:
        debt = details.rsplit(";debt:", 1)[1]
        if re.fullmatch(r"[1-9][0-9]{0,18}", debt):
            label += f" · в долг перешло {debt} 🍪"
    date = str(row["created_at"])
    try:
        stamp = datetime.fromisoformat(date)
        date = (stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)).isoformat()
    except ValueError:
        pass
    if party is None:
        role, user_id = _transaction_party(row)
        party = role, f"ID {user_id}" if user_id else "нет данных"
    role, name = party
    source = f"{role}: {name}" if role else TRANSACTION_SOURCES.get(kind, "Источник не указан")
    return {"id": row.get("id"), "kind": kind, "amount": amount, "label": label[:160], "source": source, "date": date}


def transaction_line(row: dict, timezone: str = "Europe/Moscow") -> str:
    item = row if "source" in row else transaction_item(row)
    amount = item["amount"]
    sign = f"+{amount}" if amount > 0 else str(amount)
    try:
        when = datetime.fromisoformat(item["date"]).astimezone(ZoneInfo(timezone)).strftime("%d.%m.%Y, %H:%M")
    except ValueError:
        when = item["date"][:16].replace("T", " ")
    return (
        f"<b>{sign} 🍪</b> · {html.escape(item['label'])}\n"
        f"{html.escape(item['source'])}\n<i>{html.escape(when)}</i>"
    )
