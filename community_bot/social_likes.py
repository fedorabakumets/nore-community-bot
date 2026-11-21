"""Daily like allowance and received totals in the existing SQLite state store."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

COUNT_PREFIX = "likes_received:"
DAY_PREFIX = "likes_sent_day:"
RESET_LABEL = "Сброс всех лимитов"
RESET_DESCRIPTION = "Сбрасывает сегодняшние лимиты лайков, действий с репутацией и скачиваний видео или музыки."


async def count(db, user_id: int) -> int:
    return int(await db.get_bot_state(f"{COUNT_PREFIX}{user_id}") or 0)


async def give(db, actor_id: int, target_id: int, *, reaction_message: tuple[int, int] | None = None) -> str | None:
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
        key = f"{DAY_PREFIX}{actor_id}"
        row = await (await conn.execute("SELECT value FROM bot_state WHERE key=?", (key,))).fetchone()
        # The old daily limit stored the date alone, with no recipient to carry over.
        saved = json.loads(row["value"]) if row and row["value"].startswith("{") else {}
        recipients = saved["recipients"] if saved.get("day") == day else []
        if target_id in recipients:
            return "Ты уже поставил лайк этому участнику сегодня. Можно снова после полуночи по Москве."
        if reaction_message is not None:
            chat_id, message_id = reaction_message
            claimed = await conn.execute(
                "INSERT INTO bot_state(key,value) VALUES (?,'1') ON CONFLICT(key) DO NOTHING",
                (f"likes_from_reaction:{chat_id}:{message_id}:{actor_id}",),
            )
            if not claimed.rowcount:
                return "Нора уже засчитала твою реакцию на это сообщение."
        recipients.append(target_id)
        await conn.execute(
            "INSERT INTO bot_state(key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps({"day": day, "recipients": recipients}, separators=(",", ":"))),
        )
        await conn.execute(
            "INSERT INTO bot_state(key,value) VALUES (?,'1') "
            "ON CONFLICT(key) DO UPDATE SET value=CAST(bot_state.value AS INTEGER)+1",
            (f"{COUNT_PREFIX}{target_id}",),
        )
        await conn.commit()
    return None
