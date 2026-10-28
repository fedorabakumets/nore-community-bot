"""Public profile visits and foreground-only Mini App presence, never Telegram online status."""

from __future__ import annotations

import asyncio
import re
import time
from io import BytesIO

from aiogram.exceptions import TelegramAPIError
from aiohttp import web

from community_bot.friends_api import _recipient, accepted
from community_bot.helpers import can_view_profile, effective_role, role_title

SCHEMA = """
CREATE TABLE IF NOT EXISTS mini_presence (
 user_id INTEGER NOT NULL REFERENCES users(user_id), session TEXT NOT NULL,
 seq INTEGER NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)), seen_at REAL NOT NULL,
 PRIMARY KEY(user_id,session)
);
CREATE INDEX IF NOT EXISTS mini_presence_seen ON mini_presence(user_id,seen_at);
CREATE TABLE IF NOT EXISTS mini_presence_settings (
 user_id INTEGER PRIMARY KEY REFERENCES users(user_id), hidden INTEGER NOT NULL CHECK(hidden IN (0,1))
);
"""
TTL = 60


async def privacy(db, uid):
    row = await db.fetchone("SELECT hidden FROM mini_presence_settings WHERE user_id=?", (uid,))
    return bool(row and row["hidden"])


async def heartbeat(db, uid, session, seq, active, now=None):
    if (
        not isinstance(session, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", session)
        or type(seq) is not int
        or not 0 <= seq <= 2**31 - 1
        or type(active) is not bool
    ):
        raise ValueError("Некорректный статус активности")
    now = time.time() if now is None else now
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        if not await (await conn.execute("SELECT 1 FROM users WHERE user_id=?", (uid,))).fetchone():
            raise ValueError("Сначала открой личный кабинет")
        row = await (
            await conn.execute("SELECT seq FROM mini_presence WHERE user_id=? AND session=?", (uid, session))
        ).fetchone()
        if row and row["seq"] >= seq:
            return
        if not row and not active:
            return
        if not row:
            # A user cannot grow the presence table by opening arbitrary session IDs.
            await conn.execute(
                "DELETE FROM mini_presence WHERE user_id=? AND session NOT IN "
                "(SELECT session FROM mini_presence WHERE user_id=? ORDER BY seen_at DESC LIMIT 4)",
                (uid, uid),
            )
        await conn.execute(
            "INSERT INTO mini_presence VALUES(?,?,?,?,?) ON CONFLICT(user_id,session) DO UPDATE SET "
            "seq=excluded.seq,active=excluded.active,seen_at=excluded.seen_at",
            (uid, session, seq, int(active), now),
        )
        await conn.commit()


async def presence_map(db, ids, now=None):
    if not ids:
        return {}
    now = time.time() if now is None else now
    marks = ",".join("?" for _ in ids)
    rows = await db.fetchall(
        "SELECT u.user_id,u.profile_private,COALESCE(s.hidden,0) hidden,MAX(p.seen_at) last_seen,"
        "MAX(CASE WHEN p.active=1 AND p.seen_at>? THEN 1 ELSE 0 END) online "
        "FROM users u LEFT JOIN mini_presence p ON p.user_id=u.user_id "
        "LEFT JOIN mini_presence_settings s ON s.user_id=u.user_id "
        f"WHERE u.user_id IN ({marks}) GROUP BY u.user_id",
        (now - TTL, *ids),
    )
    return {
        row["user_id"]: {
            "visible": not bool(row["hidden"] or row["profile_private"]),
            "online": bool(row["online"]) if not row["hidden"] and not row["profile_private"] else False,
            "last_seen": row["last_seen"] if not row["hidden"] and not row["profile_private"] else None,
        }
        for row in rows
    }


async def status(request):
    return web.json_response({"hidden": await privacy(request.app["db"], request["actor"]["id"]), "ttl": TTL})


async def update(request):
    body = await request.json()
    if not isinstance(body, dict):
        raise ValueError("Некорректный запрос активности")
    db, uid = request.app["db"], request["actor"]["id"]
    if not await db.get_user(uid):
        from community_bot.miniapp import actor

        await actor(request)
    if set(body) == {"hidden"} and type(body["hidden"]) is bool:
        await db.execute(
            "INSERT INTO mini_presence_settings VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET hidden=excluded.hidden",
            (uid, int(body["hidden"])),
        )
    elif set(body) == {"session", "seq", "active"}:
        await heartbeat(db, uid, body["session"], body["seq"], body["active"])
    else:
        raise ValueError("Некорректные поля активности")
    return web.json_response({"ok": True})


async def target_for(request):
    db, uid = request.app["db"], request["actor"]["id"]
    raw = request.match_info.get("user_id")
    if raw is None:
        target = await _recipient(db, request.query.get("recipient"))
    elif not raw.isdigit() or len(raw) > 16 or int(raw) <= 0:
        raise web.HTTPNotFound()
    else:
        target = int(raw)
    row = await db.get_user(target)
    if not row:
        raise web.HTTPNotFound()
    block = await db.fetchone(
        "SELECT 1 FROM mini_friend_blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)",
        (uid, target, target, uid),
    )
    if block and uid != target:
        raise web.HTTPNotFound()
    return row


async def profile(request):
    from community_bot.domain import reputation_tier
    from community_bot.profile_fill import profile_fill_percent

    db, uid, settings = request.app["db"], request["actor"]["id"], request.app["settings"]
    target = await target_for(request)
    friend = await accepted(db, uid, target["user_id"])
    result = {
        "id": target["user_id"],
        "name": target["profile_name"] or target["telegram_name"] or "Участник",
        "username": target["username"],
        "friend": friend,
        "hidden": True,
    }
    if not await can_view_profile(db, settings, uid, target):
        return web.json_response(result)
    tier = reputation_tier(target["reputation"], settings.restricted_reputation_threshold)
    presence = (
        (await presence_map(db, [target["user_id"]]))[target["user_id"]]
        if friend or uid == target["user_id"]
        else {"visible": False, "online": False, "last_seen": None}
    )
    result.update(
        hidden=False,
        private=bool(target["profile_private"]),
        age=target["age"],
        bio=target["profile_bio"],
        hobbies=target["hobbies"],
        reputation=target["reputation"],
        tier=tier.label,
        fill_percent=profile_fill_percent(target),
        role=await role_title(db, await effective_role(db, settings, target["user_id"])),
        has_avatar=bool(target["avatar_file_id"] and target["avatar_media_type"] == "photo"),
        presence=presence,
    )
    return web.json_response(result)


async def avatar(request):
    from community_bot.miniapp import normalized_photo

    target = await target_for(request)
    if not await can_view_profile(request.app["db"], request.app["settings"], request["actor"]["id"], target):
        raise web.HTTPForbidden()
    if not target["avatar_file_id"] or target["avatar_media_type"] != "photo" or request.app["bot"] is None:
        raise web.HTTPNotFound()
    try:
        output = BytesIO()
        await request.app["bot"].download(target["avatar_file_id"], destination=output)
        photo = await asyncio.to_thread(normalized_photo, output.getvalue())
        fresh = await target_for(request)
        if not await can_view_profile(request.app["db"], request.app["settings"], request["actor"]["id"], fresh):
            raise web.HTTPForbidden()
    except (TelegramAPIError, ValueError):
        raise web.HTTPNotFound() from None
    return web.Response(body=photo, content_type="image/jpeg")
