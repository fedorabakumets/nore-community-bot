"""Private-to-NORA reactions on archived community messages.

These reactions do NOT impersonate Telegram user reactions: the Bot API has
no method for setting them on behalf of arbitrary group members.
"""
from __future__ import annotations

import json
from typing import Iterable

from aiohttp import web

from community_bot.staff_chat import staff_allowed
from community_bot.staff_chat_live import emit

ALLOWED_EMOJIS = (
    "❤️", "😂", "🔥", "👍", "🥲", "👀", "🍪", "🎧", "🤝", "💀",
)
MAX_USER_REACTIONS = 3


async def reactions_for(db, chat_id: int, message_ids: Iterable[int], uid: int) -> dict[int, list[dict]]:
    """One bounded query for all visible messages. No per-message DB calls."""
    ids = list(dict.fromkeys(x for x in message_ids if type(x) is int and x > 0))[:100]
    if not ids:
        return {}
    slots = ",".join("?" for _ in ids)
    rows = await db.fetchall(
        f"""SELECT message_id, emoji, COUNT(*) amount,
                   MAX(CASE WHEN user_id=? THEN 1 ELSE 0 END) mine
            FROM staff_chat_reactions
            WHERE chat_id=? AND message_id IN ({slots})
            GROUP BY message_id, emoji
            ORDER BY amount DESC, emoji""",
        (uid, chat_id, *ids),
    )
    result: dict[int, list[dict]] = {}
    for row in rows:
        mid = int(row["message_id"])
        result.setdefault(mid, []).append({
            "emoji": row["emoji"],
            "count": int(row["amount"]),
            "mine": bool(row["mine"]),
        })
    return result


async def set_reaction(request: web.Request) -> web.Response:
    """Idempotent desired state. An explicit active flag avoids double-tap races."""
    db, settings = request.app["db"], request.app["settings"]
    uid = request["actor"]["id"]
    if not await staff_allowed(db, settings, uid):
        return web.json_response({"error": "Реакции доступны только команде Норы"}, status=403)
    chat_id = settings.community_chat_id
    if type(chat_id) is not int:
        return web.json_response({"error": "Чат Норы не настроен"}, status=503)
    if request.content_length and request.content_length > 2048:
        return web.json_response({"error": "Слишком большой запрос"}, status=413)
    try:
        payload = await request.json()
    except (ValueError, TypeError, json.JSONDecodeError):
        return web.json_response({"error": "Некорректный запрос"}, status=400)
    if not isinstance(payload, dict) or set(payload) != {"message_id", "emoji", "active"}:
        return web.json_response({"error": "Некорректные параметры"}, status=400)
    mid, emoji, active = payload["message_id"], payload["emoji"], payload["active"]
    if (type(mid) is not int or mid <= 0
            or not isinstance(emoji, str) or emoji not in ALLOWED_EMOJIS
            or type(active) is not bool):
        return web.json_response({"error": "Некорректная реакция"}, status=400)

    changed = False
    async with db.connect() as conn:
        # Hold a write lock for the existence and per-user limit checks.
        await conn.execute("BEGIN IMMEDIATE")
        msg = await (await conn.execute(
            "SELECT 1 FROM staff_chat_messages WHERE chat_id=? AND message_id=?",
            (chat_id, mid),
        )).fetchone()
        if not msg:
            await conn.rollback()
            return web.json_response({"error": "Сообщение уже удалено"}, status=404)
        existing = await (await conn.execute(
            "SELECT 1 FROM staff_chat_reactions "
            "WHERE chat_id=? AND message_id=? AND user_id=? AND emoji=?",
            (chat_id, mid, uid, emoji),
        )).fetchone()
        if active and not existing:
            count = await (await conn.execute(
                "SELECT COUNT(*) FROM staff_chat_reactions "
                "WHERE chat_id=? AND message_id=? AND user_id=?",
                (chat_id, mid, uid),
            )).fetchone()
            if int(count[0]) >= MAX_USER_REACTIONS:
                await conn.rollback()
                return web.json_response(
                    {"error": "Можно выбрать не больше трёх реакций на сообщение"},
                    status=409,
                )
            await conn.execute(
                "INSERT INTO staff_chat_reactions(chat_id,message_id,user_id,emoji) "
                "VALUES(?,?,?,?)",
                (chat_id, mid, uid, emoji),
            )
            changed = True
        elif not active and existing:
            await conn.execute(
                "DELETE FROM staff_chat_reactions "
                "WHERE chat_id=? AND message_id=? AND user_id=? AND emoji=?",
                (chat_id, mid, uid, emoji),
            )
            changed = True
        await conn.commit()
    if changed:
        emit(db, "reaction", [mid])
    summary = await reactions_for(db, chat_id, [mid], uid)
    return web.json_response({
        "ok": True, "message_id": mid, "reactions": summary.get(mid, []),
    })
