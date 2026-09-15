from __future__ import annotations

import html
from typing import Any

from community_bot.domain import AUTO_REPUTATION_CAP

PROFILE_BLOCKS: tuple[tuple[str, str], ...] = (
    ("profile_name", "Имя"),
    ("age", "Возраст"),
    ("hobbies", "Увлечения"),
    ("profile_bio", "Описание"),
    ("avatar_file_id", "Аватар"),
)


def _filled(user: dict[str, Any], field: str) -> bool:
    value = user.get(field)
    if field == "age":
        try:
            return 14 <= int(value) <= 120
        except (TypeError, ValueError):
            return False
    return bool(str(value or "").strip())


def profile_block_states(user: dict[str, Any]) -> list[tuple[str, str, bool]]:
    return [(field, label, _filled(user, field)) for field, label in PROFILE_BLOCKS]


def profile_fill_percent(user: dict[str, Any]) -> int:
    states = profile_block_states(user)
    if not states:
        return 0
    done = sum(1 for *_, filled in states if filled)
    return round(100 * done / len(states))


def profile_is_complete(user: dict[str, Any]) -> bool:
    return profile_fill_percent(user) >= 100


def reputation_cap(user: dict[str, Any]) -> int:
    if profile_is_complete(user):
        return 100
    return AUTO_REPUTATION_CAP


def bio_is_filled(user: dict[str, Any]) -> bool:
    return _filled(user, "profile_bio")


def profile_notices(user: dict[str, Any]) -> list[str]:
    notices: list[str] = []
    if profile_fill_percent(user) < 100:
        notices.append(
            f"🪪 Профиль заполнен на {profile_fill_percent(user)}%. "
            "Репутацию нельзя поднять выше бронзы, пока карточка не будет на 100%."
        )
    return notices


def cabinet_profile_text(user: dict[str, Any]) -> str:
    percent = profile_fill_percent(user)
    name = str(user.get("profile_name") or user.get("telegram_name") or user.get("user_id") or "")
    lines = [
        f"<b>Профиль</b> · {html.escape(name)} · {percent}%",
        f"<code>{progress_bar(percent)}</code>",
        f"{percent}% заполнения. Без 100% репутация не выше бронзы.",
    ]
    return "\n".join(lines)


def verification_text(user: dict[str, Any]) -> str:
    percent = profile_fill_percent(user)
    lines = [
        "🪪 <b>Верификация профиля</b>",
        "",
        f"Заполнено: <b>{percent}%</b>",
        f"<code>{progress_bar(percent)}</code>",
        "",
    ]
    chunk = 100 // max(1, len(PROFILE_BLOCKS))
    for _field, label, filled in profile_block_states(user):
        mark = "✅" if filled else "❌"
        share = chunk if filled else 0
        lines.append(f"{mark} {label} · {share}% / {chunk}%")
    lines.append("")
    if percent >= 100:
        lines.append("Карточка полная — репутацию можно поднимать до золота.")
    else:
        lines.append("Пока карточка не на 100%, репутация не поднимается выше бронзы (69).")
    return "\n".join(lines)


def notices_text(user: dict[str, Any]) -> str:
    lines = ["🔔 <b>Уведомления профиля</b>", ""]
    notices = profile_notices(user)
    if notices:
        lines.extend(notices)
    else:
        lines.append("Пока тихо — заполненность и предупреждения в порядке.")
    return "\n".join(lines)


def progress_bar(percent: int, size: int = 10) -> str:
    filled = round(max(0, min(100, percent)) / 100 * size)
    return "█" * filled + "░" * (size - filled)
