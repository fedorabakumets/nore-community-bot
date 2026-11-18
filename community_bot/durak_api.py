"""Member-scoped snapshots and long-poll updates on the existing Mini App HTTP transport."""
from __future__ import annotations

import asyncio
import json
import re
import time
import weakref

from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web

from community_bot import durak_rooms as rooms
from community_bot import durak_rules as rules
from community_bot.friends_api import deliver_notice


def _summary(row):
    return {"id": row["id"], "host": row["host"], "host_name": row["host_name"], "config": json.loads(row["config"]),
            "count": row["count"], "status": row["status"], "updated": row["updated"]}


SUMMARY = """
    SELECT r.id,r.host,r.config,r.status,r.updated,r.created,
           COALESCE(NULLIF(u.profile_name,''),NULLIF(u.telegram_name,''),u.username,'Участник') AS host_name,
           (SELECT COUNT(*) FROM durak_members m WHERE m.room=r.id) AS count
    FROM durak_rooms r JOIN users u ON u.user_id=r.host
"""


async def menu(db, uid, *, before=None):
    cutoff, last_id = (None, "") if before is None else before
    async with db.connect() as conn:
        await conn.execute("BEGIN")
        balance, restriction = await rooms._wallet(conn, uid)
        public = await rooms.rows(conn, SUMMARY + """
            WHERE r.status='waiting' AND json_extract(r.config,'$.private')=0 AND r.deadline>?
              AND NOT EXISTS(SELECT 1 FROM durak_members m JOIN mini_friend_blocks b ON
                (b.blocker_id=m.uid AND b.blocked_id=?) OR (b.blocked_id=m.uid AND b.blocker_id=?)
                WHERE m.room=r.id)
              AND (? IS NULL OR (r.created,r.id)<(?,?))
            ORDER BY r.created DESC,r.id DESC LIMIT 41
        """, (time.time(), uid, uid, cutoff, cutoff, last_id))
        mine = await rooms.rows(conn, SUMMARY + """
            JOIN durak_members own ON own.room=r.id WHERE own.uid=?
            ORDER BY own.active DESC,r.updated DESC LIMIT 40
        """, (uid,))
        invites = await rooms.rows(conn, SUMMARY + """
            JOIN durak_invites i ON i.room=r.id WHERE i.uid=? AND r.status='waiting' AND r.deadline>?
            ORDER BY r.updated DESC LIMIT 40
        """, (uid, time.time()))
        active = await rooms.one(conn, "SELECT room FROM durak_members WHERE uid=? AND active=1", (uid,))
        valid_invites = [_summary(row) for row in invites if await rooms._invited(conn, row["id"], uid)]
        next_page = None
        if len(public) > 40:
            next_page = f"{public[39]['created']}_{public[39]['id']}"
        return {"open": [_summary(row) for row in public[:40]], "next": next_page,
                "mine": [_summary(row) for row in mine], "invites": valid_invites, "balance": balance,
                "restriction": restriction, "active": active["room"] if active else None}


async def snapshot(db, rid, uid, after=-1):
    async with db.connect() as conn:
        await conn.execute("BEGIN")
        r = await rooms._room(conn, rid)
        members = await rooms._members(conn, rid)
        own = next((m for m in members if m["uid"] == uid), None)
        if own is None:
            raise ValueError("Ты не участвуешь в этой партии")
        g = r["game"]
        public = [{"id": m["uid"], "seat": m["seat"], "name": m["name"], "avatar": bool(m["avatar"]),
                   "reserved": m["reserved"], "payout": m["payout"]} for m in members]
        invited = []
        if r["status"] == "waiting":
            invited = [x["uid"] for x in await rooms.rows(conn, "SELECT uid FROM durak_invites WHERE room=?", (rid,))]
        return {"id": rid, "host": r["host"], "config": r["config"], "status": r["status"], "rev": r["rev"],
                "deadline": r["deadline"], "now": time.time(), "own": own["seat"],
                "members": public, "invited": invited,
                "code": r["code"] if r["status"] == "waiting" else None, "result": r["result"],
                "game": rules.public_view(g, own["seat"]) if g else None,
                "frames": [f for f in r["frames"] if f["rev"] > after] if after >= 0 else []}


class Updates:
    """Wake only watchers of the changed table. SQLite remains the source of truth."""
    def __init__(self):
        self.events = weakref.WeakValueDictionary()
        self.next_due = 0
        self.cleanup_at = 0
        self.watchers = {}

    def event(self, rid):
        event = self.events.get(rid)
        if event is None:
            event = self.events[rid] = asyncio.Event()
        return event

    def notify(self, rid):
        event = self.events.pop(rid, None)
        if event:
            event.set()
        self.next_due = 0

    async def restore(self, db, now):
        # A deployment or outage cannot cost a disconnected player a turn.
        async with db.connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            await conn.execute("""
                UPDATE durak_rooms SET deadline=MIN(expires,MAX(deadline,?+CASE
                    WHEN json_extract(game,'$.phase')='review' THEN ?
                    WHEN json_extract(config,'$.speed')='fast' THEN ? ELSE ? END)),rev=rev+1
                WHERE status='playing'
            """, (now, rules.REVIEW_SECONDS, rules.SECONDS["fast"], rules.SECONDS["normal"]))
            await conn.commit()

    async def tick(self, db, now=None):
        now = time.time() if now is None else now
        if now >= self.cleanup_at:
            await db.execute("DELETE FROM durak_rooms WHERE status IN ('finished','cancelled') AND updated<?",
                             (now - rooms.HISTORY_TTL,))
            self.cleanup_at = now + 86400
        if now < self.next_due:
            return
        # Mark the cache first: a concurrent command must be able to invalidate it during an await.
        self.next_due = float("inf")
        try:
            due = await db.fetchall("SELECT id FROM durak_rooms WHERE status IN ('waiting','playing') "
                                    "AND deadline<=? ORDER BY deadline LIMIT 48", (now,))
            for row in due:
                if await rooms.expire(db, row["id"], now):
                    self.notify(row["id"])
            first = await db.fetchone(
                "SELECT MIN(deadline) AS t FROM durak_rooms WHERE status IN ('waiting','playing')")
            self.next_due = min(self.next_due, first["t"] or float("inf"))
        except BaseException:
            self.next_due = 0
            raise


async def index(request):
    before = request.query.get("before")
    cursor = None
    if before:
        match = re.fullmatch(r"(\d{1,12}(?:\.\d{1,9})?)_([a-f0-9]{16})", before)
        if not match:
            raise ValueError("Обнови список столов")
        cursor = (float(match[1]), match[2])
    return web.json_response(await menu(request.app["db"], request["actor"]["id"], before=cursor))


async def preview(request):
    body = await request.json()
    code = body.get("code") if isinstance(body, dict) else None
    if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{22}", code):
        raise ValueError("Проверь код приглашения")
    async with request.app["db"].connect() as conn:
        await conn.execute("BEGIN")
        row = await rooms.one(conn, SUMMARY + " WHERE r.code=? AND r.status='waiting' AND r.deadline>?",
                              (code, time.time()))
        if not row or await rooms._blocked(conn, row["id"], request["actor"]["id"]):
            raise ValueError("Приглашение истекло или стол уже занят")
        return web.json_response(_summary(row))


async def table(request):
    rid, uid = request.match_info["rid"], request["actor"]["id"]
    after = int(request.query.get("after", request.query.get("since", -1)))
    db, updates = request.app["db"], request.app["durak_updates"]
    event = updates.event(rid)
    view = await snapshot(db, rid, uid, after)
    if "after" not in request.query or after != view["rev"] or view["status"] not in rooms.LIVE:
        return web.json_response(view)
    # One pending watch per authenticated tab/user; replacing a background tab cannot grow watchers indefinitely.
    slot = (uid, rid)
    if slot in updates.watchers:
        return web.json_response({"rev": after, "unchanged": True, "retry": 2})
    updates.watchers[slot] = True
    try:
        try:
            await asyncio.wait_for(event.wait(), timeout=20)
        except TimeoutError:
            pass
        latest = await snapshot(db, rid, uid, after)
        if latest["rev"] == after:
            return web.json_response({"rev": after, "unchanged": True})
        return web.json_response(latest)
    finally:
        updates.watchers.pop(slot, None)


async def link(request):
    rid, uid = request.match_info["rid"], request["actor"]["id"]
    async with request.app["db"].connect() as conn:
        row = await rooms.one(conn, """SELECT r.code FROM durak_rooms r JOIN durak_members m ON m.room=r.id
                               WHERE r.id=? AND m.uid=? AND m.active=1 AND r.status='waiting'""", (rid, uid))
    if not row:
        raise ValueError("Приглашать можно из открытой комнаты")
    bot = request.app["bot"]
    if not bot or not (name := (await bot.me()).username):
        raise ValueError("Ссылка Telegram сейчас недоступна. Можно скопировать код стола")
    return web.json_response({"url": f"https://t.me/{name}?startapp=nora_d_{row['code']}"})


async def action(request):
    if request.content_length and request.content_length > 4096:
        raise ValueError("Слишком большая команда")
    body = await request.json()
    db, uid = request.app["db"], request["actor"]["id"]
    try:
        rid, notice = await rooms.command(db, uid, body)
    except rooms.Conflict as exc:
        if isinstance(body, dict) and isinstance(body.get("room"), str):
            request.app["durak_updates"].notify(body["room"])
        return web.json_response({"error": str(exc)}, status=409)
    request.app["durak_updates"].notify(rid)
    if notice:
        bot = request.app["bot"]
        markup = None
        if bot:
            try:
                name = (await bot.me()).username
            except (TelegramAPIError, OSError, TimeoutError):
                name = None
            if name:
                markup = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="Посмотреть стол", url=f"https://t.me/{name}?startapp=nora_i_{rid}")
                ]])
        await deliver_notice(bot, db, *notice, reply_markup=markup)
    return web.json_response({"id": rid})


def register(app):
    app["durak_updates"] = Updates()
    app.router.add_get("/api/durak", index)
    app.router.add_post("/api/durak/preview", preview)
    app.router.add_post("/api/durak/action", action)
    app.router.add_get("/api/durak/room/{rid}", table)
    app.router.add_get("/api/durak/room/{rid}/link", link)
