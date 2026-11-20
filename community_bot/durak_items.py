"""Durak cosmetics stored in the existing SQLite key/value store."""
from __future__ import annotations

from datetime import UTC, datetime

from community_bot.database import Database
from community_bot.friends_api import accepted_in_connection, inbox_in_connection
from community_bot.sea_api import _one as one

PRICE = 90
PARTS = {"felt": 1, "back": 2, "witch": 4}
ALL = sum(PARTS.values())


def key(uid):
    return f"durak_night:{uid}"


async def equipped(conn, uid):
    row = await one(conn, "SELECT value FROM bot_state WHERE key=?", (key(uid),))
    return int(row["value"]) if row else None


def view(mask):
    return {"owned": mask is not None, "price": PRICE,
            "equipped": {part: bool((mask or 0) & bit) for part, bit in PARTS.items()}}


async def change(db, uid, body):
    if not isinstance(body, dict):
        raise ValueError("Проверь данные комплекта")
    action = body.get("action")
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        if action == "equip":
            part, enabled = body.get("part"), body.get("enabled")
            mask = await equipped(conn, uid)
            if mask is None or not isinstance(part, str) or part not in PARTS or type(enabled) is not bool:
                raise ValueError("Выбери купленный предмет")
            bit = PARTS[part]
            await conn.execute("UPDATE bot_state SET value=? WHERE key=?",
                               (mask | bit if enabled else mask & ~bit, key(uid)))
        elif action == "buy":
            target = body.get("recipient", uid)
            if (type(target) is not int or not 0 < target < 2**63
                    or (target != uid and not await accepted_in_connection(conn, uid, target))):
                raise ValueError("Выбери друга Норы")
            if await equipped(conn, target) is not None:
                raise ValueError("Комплект уже есть у получателя")
            buyer = await one(conn, "SELECT cookies FROM users WHERE user_id=?", (uid,))
            if not buyer or buyer["cookies"] < PRICE:
                raise ValueError("Не хватает печенек")
            await Database._add_cookies(conn, uid, -PRICE, "durak_night_pack", f"recipient:{target}",
                                        datetime.now(UTC).isoformat())
            await conn.execute("INSERT INTO bot_state(key,value) VALUES(?,?)",
                               (key(target), ALL if target == uid else 0))
            if target != uid:
                await inbox_in_connection(conn, target, "Тебе подарили «Ночной комплект» для Дурака. "
                                          "Включи предметы в разделе «Дурак → Предметы».")
        else:
            raise ValueError("Неизвестное действие с комплектом")
        result = view(await equipped(conn, uid))
        balance = await one(conn, "SELECT cookies FROM users WHERE user_id=?", (uid,))
        await conn.commit()
        return {**result, "balance": balance["cookies"]}
