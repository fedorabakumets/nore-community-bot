"""Barricade views on the authenticated Mini App transport."""
from __future__ import annotations

import asyncio
import re
import time
from collections import OrderedDict

from aiohttp import web

from community_bot import barricade_rules as rules
from community_bot import durak_rooms as rooms
from community_bot.durak_api import NO_BLOCKED_MEMBERS, SUMMARY, _summary
from community_bot.game_invitations import deliver_game_invitation

GAME = "barricade"
ONLY = f"{rooms.GAME_KIND}='barricade'"
INVITES = " JOIN durak_invites i ON i.room=r.id "
OPEN = f" WHERE {ONLY} AND r.status='waiting' AND r.deadline>?"
HEARTBEAT = 8
OFFLINE_AFTER = 20
PRESENCE = web.AppKey("barricade_presence", OrderedDict)


async def menu(db, uid):
    async with db.connect() as conn:
        await conn.execute("BEGIN")
        balance, restriction = await rooms._wallet(conn, uid)
        active = await rooms.one(conn, f"""
            SELECT r.id,{rooms.GAME_KIND} AS kind FROM durak_rooms r
              JOIN durak_members m ON m.room=r.id WHERE m.uid=? AND m.active=1
        """, (uid,))
        recent = await rooms.rows(conn, SUMMARY + " JOIN durak_members m ON m.room=r.id "
                                  f"WHERE {ONLY} AND m.uid=? ORDER BY m.active DESC,r.updated DESC LIMIT 8", (uid,))
        incoming = await rooms.rows(conn, SUMMARY + INVITES + OPEN + " AND i.uid=? AND " + NO_BLOCKED_MEMBERS
                                    + " ORDER BY r.updated DESC LIMIT 20", (time.time(), uid, uid, uid))
        invites = [_summary(r) for r in incoming if await rooms._invited(conn, r["id"], uid)]
        return {"balance": balance, "restriction": restriction, "active": active,
                "recent": [_summary(row) for row in recent], "invites": invites}


async def snapshot(db, rid, uid, *, after=-1):
    async with db.connect() as conn:
        await conn.execute("BEGIN")
        r = await rooms._room(conn, rid, GAME)
        members = await rooms._members(conn, rid)
        own = next((m["seat"] for m in members if m["uid"] == uid), None)
        if own is None:
            raise ValueError("Ты не участвуешь в этой партии")
        if after == r["rev"] and r["status"] in rooms.LIVE:
            return {"rev": after, "unchanged": True, "status": r["status"],
                    "members": [{"id": m["uid"]} for m in members]}
        invited = await rooms.rows(conn, "SELECT uid FROM durak_invites WHERE room=?", (rid,))
    g = r["game"]
    playing = r["status"] == "playing" and g["turn"] == own
    view = {key: g[key] for key in ("pawns", "stock", "walls", "turn")} if g else None
    if view:
        view["moves"] = rules.moves(g, own) if playing else []
        view["wall_options"] = rules.wall_options(g, own) if playing else []
    return {
        "id": rid, "rev": r["rev"], "status": r["status"], "config": r["config"],
        "deadline": r["deadline"], "now": time.time(), "own": own, "board": view,
        "result": r["result"], "invited": [row["uid"] for row in invited],
        "members": [{"id": m["uid"], "name": m["name"], "avatar": bool(m["avatar"]), "payout": m["payout"]}
                    for m in members],
    }


async def index(request):
    return web.json_response(await menu(request.app["db"], request["actor"]["id"]))


async def preview(request):
    body = await request.json()
    code = body.get("code") if isinstance(body, dict) else None
    if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{22}", code):
        raise ValueError("Проверь ссылку на комнату")
    async with request.app["db"].connect() as conn:
        await conn.execute("BEGIN")
        row = await rooms.one(conn, SUMMARY + OPEN + " AND r.code=? AND json_extract(r.config,'$.quick')=0",
                              (time.time(), code))
        if not row or await rooms._blocked(conn, row["id"], request["actor"]["id"]):
            raise ValueError("Приглашение истекло или партия уже началась")
        return web.json_response(_summary(row))


async def table(request):
    rid, uid = request.match_info["rid"], request["actor"]["id"]
    db, updates = request.app["db"], request.app["durak_updates"]
    seen = request.app[PRESENCE]
    after = int(request.query.get("after", -1))
    event = updates.event(rid)
    view = await snapshot(db, rid, uid, after=after)
    slot = (uid, rid)
    now = time.monotonic()
    if view["status"] in rooms.LIVE:
        # Each watch doubles as a heartbeat. Presence is advisory; the durable turn clock settles forfeits.
        restored = seen.get(slot, 0) <= now - OFFLINE_AFTER
        seen[slot] = now
        seen.move_to_end(slot)
        if restored:
            updates.wake(rid)
    if view.get("unchanged") and slot not in updates.watchers:
        updates.watchers[slot] = True
        try:
            try:
                await asyncio.wait_for(event.wait(), timeout=HEARTBEAT)
            except TimeoutError:
                pass
            view = await snapshot(db, rid, uid, after=after)
        finally:
            updates.watchers.pop(slot, None)
    elif view.get("unchanged"):
        view["retry"] = 2
    now = time.monotonic()
    while seen and next(iter(seen.values())) <= now - rooms.GAME_TTL:
        seen.popitem(last=False)
    presence = {}
    for member in view["members"]:
        key = (member["id"], rid)
        if key in seen:
            presence[member["id"]] = "online" if seen[key] > now - OFFLINE_AFTER else "offline"
    view["presence"] = presence
    if view.get("unchanged"):
        view.pop("members")
    return web.json_response(view)


async def link(request):
    rid, uid = request.match_info["rid"], request["actor"]["id"]
    async with request.app["db"].connect() as conn:
        row = await rooms.one(conn, f"""
            SELECT r.code FROM durak_rooms r JOIN durak_members m ON m.room=r.id
            WHERE {ONLY} AND r.id=? AND m.uid=? AND m.active=1 AND r.status='waiting'
              AND r.deadline>? AND json_extract(r.config,'$.quick')=0
        """, (rid, uid, time.time()))
    if not row:
        raise ValueError("Ссылку можно отправить из приватной комнаты")
    bot = request.app["bot"]
    if not bot or not (name := (await bot.me()).username):
        raise ValueError("Ссылка Telegram сейчас недоступна")
    return web.json_response({"url": f"https://t.me/{name}?startapp=nora_b_{row['code']}"})


async def action(request):
    if request.content_length and request.content_length > 4096:
        raise ValueError("Слишком большая команда")
    body = await request.json()
    db, uid = request.app["db"], request["actor"]["id"]
    updates = request.app["durak_updates"]
    try:
        rid, notice = await rooms.command(db, uid, body, game=GAME)
    except rooms.Conflict as exc:
        if isinstance(body, dict) and isinstance(body.get("room"), str):
            updates.notify(body["room"])
        return web.json_response({"error": str(exc)}, status=409)
    updates.notify(rid)
    if notice:
        inbox_id, recipient, _ = notice
        await deliver_game_invitation(request.app["bot"], db, request.app["settings"], GAME,
                                      rid, uid, recipient, inbox_id)
    return web.json_response({"id": rid})


def register(app):
    app[PRESENCE] = OrderedDict()
    app.router.add_get("/api/barricade", index)
    app.router.add_post("/api/barricade/preview", preview)
    app.router.add_post("/api/barricade/action", action)
    app.router.add_get(r"/api/barricade/room/{rid:[a-f0-9]{16}}", table)
    app.router.add_get(r"/api/barricade/room/{rid:[a-f0-9]{16}}/link", link)
