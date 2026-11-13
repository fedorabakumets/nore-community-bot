from __future__ import annotations

import html

from community_bot.domain import reputation_tier
from community_bot.profile_fill import profile_fill_percent


def cabinet_text(
    user: dict[str, object], pet: dict[str, object] | None, *, unread: int = 0, restricted_threshold: int = 0,
) -> str:
    name = str(user.get("profile_name") or user.get("telegram_name") or "Участник")[:60]
    reputation = int(user.get("reputation") or 0)
    tier = reputation_tier(reputation, restricted_threshold)
    lines = [
        "👤 <b>Личный кабинет</b>",
        html.escape(name),
        "",
        f"🍪 Доступно: <b>{int(user.get('cookies') or 0)} 🍪</b>",
        f"{tier.emoji} Репутация: {reputation}% · {tier.label}",
        f"🪪 Профиль заполнен на {profile_fill_percent(user)}%",
    ]
    debt = int(user.get("cookie_debt") or 0)
    if debt:
        lines.append(f"💳 Просроченный долг: <b>{debt} 🍪</b> · погасить в кошельке")
    if pet:
        status = "в экспедиции" if pet.get("expedition_until") else "дома"
        lines.append(f"🐾 {html.escape(str(pet['name'])[:24])} · {status}")
    else:
        lines.append("🐾 Питомца пока нет")
    if unread:
        lines.append(f"🔔 Новых уведомлений: {unread}")
    return "\n".join(lines)
