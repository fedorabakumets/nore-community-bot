"""Daily like allowance and received totals in the existing SQLite state store."""

from datetime import datetime
from zoneinfo import ZoneInfo

COUNT_PREFIX = "likes_received:"
DAY_PREFIX = "likes_sent_day:"
RESET_LABEL = "Сброс всех лимитов"
RESET_DESCRIPTION = "Сбрасывает сегодняшние лимиты лайков и действий с репутацией."


async def count(db, user_id: int) -> int:
    return int(await db.get_bot_state(f"{COUNT_PREFIX}{user_id}") or 0)


async def give(db, actor_id: int, target_id: int) -> str | None:
    """Spend the actor's allowance and increment the recipient's total together."""
    if actor_id == target_id:
        return "Себе поставить лайк нельзя."
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        target = await (await conn.execute(
            "SELECT profile_private FROM users WHERE user_id=?", (target_id,),
        )).fetchone()
        if target is None or target["profile_private"]:
            return "Этот профиль скрыт или недоступен."
        day = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
        updated = await conn.execute(
            "INSERT INTO bot_state(key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value WHERE bot_state.value < excluded.value",
            (f"{DAY_PREFIX}{actor_id}", day),
        )
        if not updated.rowcount:
            return "Сегодняшний лайк уже потрачен. Новый будет в полночь по Москве."
        await conn.execute(
            "INSERT INTO bot_state(key,value) VALUES (?,'1') "
            "ON CONFLICT(key) DO UPDATE SET value=CAST(bot_state.value AS INTEGER)+1",
            (f"{COUNT_PREFIX}{target_id}",),
        )
        await conn.commit()
    return None
