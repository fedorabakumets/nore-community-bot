from __future__ import annotations

from datetime import date

from community_bot.config import Settings
from community_bot.database import Database
from community_bot.domain import reputation_tier
from community_bot.helpers import is_immunity_active, pet_guard_reputation


async def change_community_reputation(
    db: Database,
    settings: Settings,
    actor: dict[str, object],
    target: dict[str, object],
    delta: int,
    local_date: date,
) -> tuple[bool, str, int | None, str | None]:
    actor_id = int(actor["user_id"])
    target_id = int(target["user_id"])
    if actor_id == target_id:
        return False, "Нельзя менять репутацию самому себе.", None, None
    if delta == 0:
        return False, "Нет изменения репутации.", None, None
    tier = reputation_tier(int(actor["reputation"]), settings.restricted_reputation_threshold)
    if tier.daily_actions == 0:
        return False, "Ваш уровень репутации не позволяет влиять на других участников.", None, None
    if delta < 0 and not tier.can_minus:
        return False, "Бронза может только поддержать (+реп). Минус доступен с серебра.", None, None
    used = await db.reputation_actions_today(actor_id, local_date)
    if used >= tier.daily_actions:
        return False, f"Дневной лимит исчерпан: {tier.daily_actions} действий.", None, None
    if await db.reputation_action_today_for_target(actor_id, target_id, local_date):
        return False, "Этого человека сегодня уже отмечали. Завтра можно снова.", None, None
    if delta < 0 and is_immunity_active(target.get("hate_immunity_until")):
        return False, "У пользователя действует иммунитет от понижения репутации.", None, None
    applied = delta
    extra: str | None = None
    if delta < 0 and await db.consume_hate_shield(target_id):
        applied = 0
        extra = "🛡 Щит поглотил −реп."
    else:
        applied, extra = await pet_guard_reputation(db, target_id, delta, local_date)
    new_value = await db.apply_reputation(actor_id, target_id, applied, local_date)
    if applied == 0:
        text = f"Репутация не изменилась, сейчас {new_value}."
    else:
        sign = "+" if applied > 0 else ""
        text = f"Репутация изменена на {sign}{applied}, теперь {new_value}."
        from community_bot.profile_fill import profile_is_complete, reputation_cap

        if applied > 0 and new_value <= int(target["reputation"]) and not profile_is_complete(target):
            extra = ((extra + "\n") if extra else "") + (
                f"Карточка не на 100% — репутацию нельзя поднять выше {reputation_cap(target)} (серебро)."
            )
        elif applied > 0 and new_value < int(target["reputation"]) + applied and not profile_is_complete(target):
            extra = ((extra + "\n") if extra else "") + (
                "Упёрлись в потолок серебра: сначала заполните профиль на 100%."
            )
    return True, text, new_value, extra
