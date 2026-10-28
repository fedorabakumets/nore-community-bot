"""Season-one physical collectible: free entry and one irreversible, server-side draw."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from datetime import UTC, datetime

from aiohttp import web

from community_bot.helpers import has_permission
from community_bot.permissions import PERM_ADMIN_PANEL, PERM_CONTEST
from community_bot.profile_fill import profile_is_complete

ITEM = "season1-crimson-guardian"
TITLE = "Багровый Страж Норы"
SCHEMA = """
CREATE TABLE IF NOT EXISTS seasonal_raffles (
 id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','drawn')),
 winner_id INTEGER REFERENCES users(user_id), drawn_at TEXT, drawn_by INTEGER REFERENCES users(user_id),
 entry_count INTEGER, entries_digest TEXT
);
INSERT OR IGNORE INTO seasonal_raffles(id) VALUES('season1-crimson-guardian');
CREATE TABLE IF NOT EXISTS seasonal_entries (
 raffle_id TEXT NOT NULL REFERENCES seasonal_raffles(id), user_id INTEGER NOT NULL REFERENCES users(user_id),
 joined_at TEXT NOT NULL, PRIMARY KEY(raffle_id,user_id)
);
CREATE TABLE IF NOT EXISTS seasonal_draw_tokens (
 token TEXT PRIMARY KEY, actor_id INTEGER NOT NULL REFERENCES users(user_id),
 entries_digest TEXT NOT NULL, expires_at REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0
);
"""


async def can_manage(db, settings, uid):
    return await has_permission(db, settings, uid, PERM_ADMIN_PANEL) and await has_permission(
        db, settings, uid, PERM_CONTEST
    )


async def one(conn, sql, args=()):
    row = await (await conn.execute(sql, args)).fetchone()
    return dict(row) if row else None


def fingerprint(ids):
    return hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()


async def snapshot(db, settings, uid):
    async with db.connect() as conn:
        await conn.execute("BEGIN")
        row = await one(conn, "SELECT * FROM seasonal_raffles WHERE id=?", (ITEM,))
        joined = await one(conn, "SELECT 1 FROM seasonal_entries WHERE raffle_id=? AND user_id=?", (ITEM, uid))
        count = await one(conn, "SELECT COUNT(*) n FROM seasonal_entries WHERE raffle_id=?", (ITEM,))
        user = await one(conn, "SELECT * FROM users WHERE user_id=?", (uid,))
        winner = await one(conn, "SELECT profile_name,telegram_name FROM users WHERE user_id=?", (row["winner_id"],))
    return {
        "id": ITEM,
        "title": TITLE,
        "season": 1,
        "status": row["status"],
        "joined": bool(joined),
        "count": count["n"],
        "image": "/seasonal/guardian-season1.jpg",
        "author": "Buffy Crochet",
        "author_url": "https://t.me/buffy_crochet",
        "eligible": bool(user and profile_is_complete(user)),
        "can_manage": await can_manage(db, settings, uid),
        "winner": (winner["profile_name"] or winner["telegram_name"]) if winner else None,
        "won": row["winner_id"] == uid,
        "drawn_at": row["drawn_at"],
    }


async def join(db, uid):
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        row = await one(conn, "SELECT status FROM seasonal_raffles WHERE id=?", (ITEM,))
        existing = await one(conn, "SELECT 1 FROM seasonal_entries WHERE raffle_id=? AND user_id=?", (ITEM, uid))
        if existing:
            return "Вы участвуете. Одна заявка — один шанс"
        if row["status"] != "open":
            raise ValueError("Розыгрыш завершён, новые заявки не принимаются")
        user = await one(conn, "SELECT * FROM users WHERE user_id=?", (uid,))
        if not user or not profile_is_complete(user):
            raise ValueError("Заполни профиль на 100% в ЛК, чтобы участвовать")
        await conn.execute("INSERT INTO seasonal_entries VALUES(?,?,?)", (ITEM, uid, datetime.now(UTC).isoformat()))
        await conn.commit()
    return "Заявка принята! Вы участвуете в розыгрыше"


async def prepare_draw(db, settings, uid):
    if not await can_manage(db, settings, uid):
        raise web.HTTPForbidden()
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        if not await can_manage(db, settings, uid):
            raise web.HTTPForbidden()
        row = await one(conn, "SELECT status FROM seasonal_raffles WHERE id=?", (ITEM,))
        ids = [
            r[0]
            for r in await (
                await conn.execute("SELECT user_id FROM seasonal_entries WHERE raffle_id=? ORDER BY user_id", (ITEM,))
            ).fetchall()
        ]
        if row["status"] != "open":
            raise ValueError("Победитель уже определён. Повторный выбор запрещён")
        if not ids:
            raise ValueError("Пока нет участников")
        token = secrets.token_urlsafe(32)
        await conn.execute("DELETE FROM seasonal_draw_tokens WHERE expires_at<? OR consumed=1", (time.time(),))
        await conn.execute(
            "INSERT INTO seasonal_draw_tokens VALUES(?,?,?,?,0)", (token, uid, fingerprint(ids), time.time() + 300)
        )
        await conn.commit()
    return {"token": token, "count": len(ids), "title": TITLE}


async def draw(db, settings, uid, token):
    if not await can_manage(db, settings, uid):
        raise web.HTTPForbidden()
    if not isinstance(token, str) or not 20 <= len(token) <= 100:
        raise ValueError("Открой подтверждение итогов заново")
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        if not await can_manage(db, settings, uid):
            raise web.HTTPForbidden()
        intent = await one(conn, "SELECT * FROM seasonal_draw_tokens WHERE token=? AND actor_id=?", (token, uid))
        raffle = await one(conn, "SELECT * FROM seasonal_raffles WHERE id=?", (ITEM,))
        if raffle["status"] != "open":
            raise ValueError("Победитель уже определён. Повторный выбор запрещён")
        if not intent or intent["consumed"] or intent["expires_at"] <= time.time():
            raise ValueError("Подтверждение устарело или принадлежит другому администратору")
        ids = [
            r[0]
            for r in await (
                await conn.execute("SELECT user_id FROM seasonal_entries WHERE raffle_id=? ORDER BY user_id", (ITEM,))
            ).fetchall()
        ]
        if not ids or fingerprint(ids) != intent["entries_digest"]:
            raise ValueError("Список участников изменился. Открой подтверждение заново")
        winner = ids[secrets.randbelow(len(ids))]
        now = datetime.now(UTC).isoformat()
        await conn.execute(
            "UPDATE seasonal_raffles SET status='drawn',winner_id=?,drawn_at=?,drawn_by=?,"
            "entry_count=?,entries_digest=? WHERE id=?",
            (winner, now, uid, len(ids), fingerprint(ids), ITEM),
        )
        await conn.execute("UPDATE seasonal_draw_tokens SET consumed=1 WHERE token=?", (token,))
        await conn.execute(
            "INSERT INTO notify_inbox(user_id,channel,text,created_at,read,delivered) VALUES(?,'shop',?,?,0,0)",
            (
                winner,
                f"Вы выиграли «{TITLE}» — эксклюзив 1 сезона! "
                "Свяжитесь с командой Норы, чтобы договориться о получении игрушки.",
                now,
            ),
        )
        await conn.commit()
    return winner


async def status(request):
    from community_bot.miniapp import actor

    user = await actor(request)
    return web.json_response(await snapshot(request.app["db"], request.app["settings"], user["user_id"]))


async def participate(request):
    from community_bot.miniapp import actor

    user = await actor(request)
    message = await join(request.app["db"], user["user_id"])
    return web.json_response(
        {"message": message, "seasonal": await snapshot(request.app["db"], request.app["settings"], user["user_id"])}
    )


async def manage(request):
    from community_bot.miniapp import actor

    user = await actor(request)
    db, settings, uid = request.app["db"], request.app["settings"], user["user_id"]
    if not await can_manage(db, settings, uid):
        raise web.HTTPForbidden()
    raw = request.query.get("offset", "0")
    if not raw.isdigit() or len(raw) > 6:
        raise ValueError("Некорректная страница")
    offset = int(raw)
    entries = await db.fetchall(
        "SELECT u.user_id,u.username,u.profile_name,u.telegram_name,e.joined_at "
        "FROM seasonal_entries e JOIN users u ON u.user_id=e.user_id "
        "WHERE e.raffle_id=? ORDER BY e.joined_at,u.user_id LIMIT 21 OFFSET ?",
        (ITEM, offset),
    )
    return web.json_response(
        {
            "items": entries[:20],
            "has_more": len(entries) > 20,
            "offset": offset,
            "seasonal": await snapshot(db, settings, uid),
        }
    )


async def draw_prepare(request):
    from community_bot.miniapp import actor

    await actor(request)
    return web.json_response(await prepare_draw(request.app["db"], request.app["settings"], request["actor"]["id"]))


async def draw_confirm(request):
    from community_bot.miniapp import actor

    await actor(request)
    body = await request.json()
    if not isinstance(body, dict) or set(body) != {"token"}:
        raise ValueError("Некорректное подтверждение")
    await draw(request.app["db"], request.app["settings"], request["actor"]["id"], body["token"])
    return web.json_response(
        {
            "message": "Победитель определён. Итог сохранён",
            "seasonal": await snapshot(request.app["db"], request.app["settings"], request["actor"]["id"]),
        }
    )
