"""Member-scoped snapshots and long-poll updates on the existing Mini App HTTP transport."""
from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
import weakref
from collections import deque

from aiohttp import web

from community_bot import barricade_rules as barricade
from community_bot import durak_items as items
from community_bot import durak_rooms as rooms
from community_bot import durak_rules as rules
from community_bot.game_invitations import announce_quick_lobby, deliver_game_invitation, send_lobby_post
from community_bot.game_lobby_posts import has_live_announcement

REACTION_DURATION = 2.7
REACTION_COOLDOWN = 2.8
REACTION_RETRY_WINDOW = 60


def _summary(row):
    return {"id": row["id"], "host": row["host"], "host_name": row["host_name"], "config": json.loads(row["config"]),
            "count": row["count"], "status": row["status"], "updated": row["updated"]}


SUMMARY_FIELDS = """
    SELECT r.id,r.host,r.config,r.status,r.updated,r.created,
           COALESCE(NULLIF(u.profile_name,''),NULLIF(u.telegram_name,''),u.username,'Участник') AS host_name,
           (SELECT COUNT(*) FROM durak_members m WHERE m.room=r.id) AS count
"""
SUMMARY_FROM = " FROM durak_rooms r JOIN users u ON u.user_id=r.host "
SUMMARY = SUMMARY_FIELDS + SUMMARY_FROM
DURAK_ONLY = f"{rooms.GAME_KIND}='durak'"
NO_BLOCKED_MEMBERS = """
    NOT EXISTS(SELECT 1 FROM durak_members m JOIN mini_friend_blocks b ON
        (b.blocker_id=m.uid AND b.blocked_id=?) OR (b.blocked_id=m.uid AND b.blocker_id=?)
        WHERE m.room=r.id)
"""


async def menu(db, uid, *, before=None):
    cutoff, last_id = (None, "") if before is None else before
    async with db.connect() as conn:
        await conn.execute("BEGIN")
        balance, restriction = await rooms._wallet(conn, uid)
        public = await rooms.rows(conn, SUMMARY + " WHERE " + DURAK_ONLY + " AND " + """
            r.status='waiting' AND json_extract(r.config,'$.private')=0 AND r.deadline>?
              AND """ + NO_BLOCKED_MEMBERS + """
              AND (? IS NULL OR (r.created,r.id)<(?,?))
            ORDER BY r.created DESC,r.id DESC LIMIT 41
        """, (time.time(), uid, uid, cutoff, cutoff, last_id))
        mine = await rooms.rows(conn, SUMMARY + """
            JOIN durak_members own ON own.room=r.id WHERE """ + DURAK_ONLY + """ AND own.uid=?
            ORDER BY own.active DESC,r.updated DESC LIMIT 40
        """, (uid,))
        invites = await rooms.rows(conn, SUMMARY + """
            JOIN durak_invites i ON i.room=r.id WHERE """ + DURAK_ONLY + """ AND i.uid=?
              AND r.status='waiting' AND r.deadline>?
            ORDER BY r.updated DESC LIMIT 40
        """, (uid, time.time()))
        active = await rooms.one(conn, "SELECT m.room FROM durak_members m JOIN durak_rooms r ON r.id=m.room "
                                 "WHERE " + DURAK_ONLY + " AND m.uid=? AND m.active=1", (uid,))
        valid_invites = [_summary(row) for row in invites if await rooms._invited(conn, row["id"], uid)]
        next_page = None
        if len(public) > 40:
            next_page = f"{public[39]['created']}_{public[39]['id']}"
        return {"open": [_summary(row) for row in public[:40]], "next": next_page,
                "mine": [_summary(row) for row in mine], "invites": valid_invites, "balance": balance,
                "restriction": restriction, "active": active["room"] if active else None,
                "items": items.view(await items.equipped(conn, uid))}


async def lobbies(db, uid, *, game="durak"):
    game_filter = DURAK_ONLY if game == "durak" else f"{rooms.GAME_KIND}='barricade'"
    async with db.connect() as conn:
        await conn.execute("BEGIN")
        rows = await rooms.rows(conn, SUMMARY_FIELDS + ", own.uid IS NOT NULL AS own" + SUMMARY_FROM + """
            LEFT JOIN durak_members own ON own.room=r.id AND own.uid=? AND own.active=1
            LEFT JOIN durak_invites i ON i.room=r.id AND i.uid=?
            WHERE """ + game_filter + """ AND r.status='waiting' AND r.deadline>? AND (
                own.uid IS NOT NULL OR (
                    ((json_extract(r.config,'$.private')=0 AND COALESCE(json_extract(r.config,'$.quick'),0)=0)
                      OR i.uid IS NOT NULL)
                    AND """ + NO_BLOCKED_MEMBERS + """
                )
            )
            ORDER BY r.created DESC,r.id DESC
        """, (uid, uid, time.time(), uid, uid))
        result = []
        for row in rows:
            item = _summary(row)
            own = bool(row["own"])
            if item["config"]["private"] and not own and not await rooms._invited(conn, item["id"], uid):
                continue
            result.append({**item, "own": own})
        return result


async def snapshot(db, rid, uid, after=-1):
    async with db.connect() as conn:
        await conn.execute("BEGIN")
        r = await rooms._room(conn, rid, "durak")
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
        now = time.time()
        game = rules.public_view(g, own["seat"]) if g else None
        mask = g.get("table_cosmetics", 0) if g else (await items.equipped(conn, r["host"]) or 0)
        witch = bool((await items.equipped(conn, uid) or 0) & items.PARTS["witch"]) if g else False
        if game and rooms.can_undo(r, own["seat"], now):
            game["moves"].append({"kind": "undo"})
            game["undo_until"] = min(g["undo"]["deadline"], r["deadline"])
        return {"id": rid, "host": r["host"], "config": r["config"], "status": r["status"], "rev": r["rev"],
                "deadline": r["deadline"], "now": now, "own": own["seat"],
                "members": public, "invited": invited,
                "code": r["code"] if r["status"] == "waiting" else None, "result": r["result"],
                "game": game, "cosmetics": {"felt": bool(mask & items.PARTS["felt"]),
                                             "back": bool(mask & items.PARTS["back"]), "witch": witch},
                "frames": [f for f in r["frames"] if f["rev"] > after] if after >= 0 else []}


class Updates:
    """Wake only watchers of the changed table. SQLite remains the source of truth."""
    def __init__(self):
        self.events = weakref.WeakValueDictionary()
        self.next_due = 0
        self.cleanup_at = 0
        self.watchers = {}
        self.announcing = set()
        self.reactions = {}
        self.reaction_cleanup_at = 0

    def event(self, rid):
        event = self.events.get(rid)
        if event is None:
            event = self.events[rid] = asyncio.Event()
        return event

    def wake(self, rid):
        event = self.events.pop(rid, None)
        if event:
            event.set()

    def notify(self, rid):
        self.wake(rid)
        self.next_due = 0

    def reaction_view(self, rid, now):
        events = self.reactions.get(rid)
        return {
            "reaction_cursor": events[-1][1]["reaction_id"] if events else "",
            "reactions": [event for _, event in (events or ()) if event["expires"] > now],
            "reaction_now": now,
        }

    def react(self, rid, uid, emoji, nonce, now):
        events = self.reactions.setdefault(rid, deque())
        while events and events[0][1]["timestamp"] <= now - REACTION_RETRY_WINDOW:
            events.popleft()
        for previous_nonce, event in reversed(events):
            if event["sender_id"] != uid:
                continue
            if previous_nonce == nonce:
                if event["emoji_id"] != emoji:
                    raise rooms.Conflict("Эта реакция уже отправлена")
                return event
        if any(e["sender_id"] == uid and e["timestamp"] > now - REACTION_COOLDOWN for _, e in events):
            return None
        event = {"reaction_id": secrets.token_hex(8), "room_id": rid, "sender_id": uid, "emoji_id": emoji,
                 "timestamp": now, "expires": now + REACTION_DURATION}
        events.append((nonce, event))
        self.wake(rid)
        return event

    async def restore(self, db, now):
        # A deployment or outage cannot cost a disconnected player a turn.
        async with db.connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            await conn.execute("""
                UPDATE durak_rooms SET deadline=MIN(expires,MAX(deadline,?+CASE
                    WHEN (CASE WHEN json_valid(config) THEN json_extract(config,'$.game') END)='barricade' THEN ?
                    WHEN (CASE WHEN json_valid(game) THEN json_extract(game,'$.phase') END)='review' THEN ?
                    WHEN (CASE WHEN json_valid(config) THEN json_extract(config,'$.speed') END)='fast' THEN ?
                    ELSE ? END)),rev=rev+1
                WHERE status='playing'
            """, (now, barricade.TURN_SECONDS, rules.REVIEW_SECONDS, rules.SECONDS["fast"], rules.SECONDS["normal"]))
            active = await rooms.rows(conn, f"SELECT r.*,'durak' AS kind FROM durak_rooms r WHERE {DURAK_ONLY} "
                                      "AND status='playing' "
                                      "AND (CASE WHEN json_valid(game) THEN json_extract(game,'$.phase') END) "
                                      "IN ('throw','defend')")
            for row in active:
                await rooms.resume_forced_round(conn, rooms._load(row), now)
            await conn.commit()

    async def tick(self, db, now=None):
        now = time.time() if now is None else now
        if now >= self.reaction_cleanup_at:
            self.reactions = {rid: events for rid, events in self.reactions.items()
                              if events[-1][1]["timestamp"] > now - REACTION_RETRY_WINDOW}
            self.reaction_cleanup_at = now + REACTION_RETRY_WINDOW
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
        row = await rooms.one(conn, SUMMARY + " WHERE " + DURAK_ONLY
                              + " AND r.code=? AND r.status='waiting' AND r.deadline>?",
                              (code, time.time()))
        if not row or await rooms._blocked(conn, row["id"], request["actor"]["id"]):
            raise ValueError("Приглашение истекло или стол уже занят")
        return web.json_response(_summary(row))


async def table(request):
    rid, uid = request.match_info["rid"], request["actor"]["id"]
    after = int(request.query.get("after", request.query.get("since", -1)))
    db, updates = request.app["db"], request.app["durak_updates"]
    event = updates.event(rid)
    cursor = request.query.get("reactions")
    view = await snapshot(db, rid, uid, after)
    feed = updates.reaction_view(rid, time.time())
    if "after" not in request.query or after != view["rev"] or view["status"] not in rooms.LIVE:
        return web.json_response({**view, **feed})
    if cursor is not None and feed["reaction_cursor"] != cursor:
        return web.json_response({"rev": after, "unchanged": True, **feed})
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
        feed = updates.reaction_view(rid, time.time())
        if latest["rev"] == after:
            return web.json_response({"rev": after, "unchanged": True, **feed})
        return web.json_response({**latest, **feed})
    finally:
        updates.watchers.pop(slot, None)


async def link(request):
    rid, uid = request.match_info["rid"], request["actor"]["id"]
    async with request.app["db"].connect() as conn:
        row = await rooms.one(conn, f"""SELECT r.code FROM durak_rooms r JOIN durak_members m ON m.room=r.id
                               WHERE {DURAK_ONLY} AND r.id=? AND m.uid=? AND m.active=1
                                 AND r.status='waiting'""", (rid, uid))
    if not row:
        raise ValueError("Приглашать можно из открытой комнаты")
    bot = request.app["bot"]
    if not bot or not (name := (await bot.me()).username):
        raise ValueError("Ссылка Telegram сейчас недоступна. Можно скопировать код стола")
    return web.json_response({"url": f"https://t.me/{name}?startapp=nora_d_{row['code']}"})


async def announce(request):
    rid, uid = request.match_info["rid"], request["actor"]["id"]
    db, bot, updates = request.app["db"], request.app["bot"], request.app["durak_updates"]
    chat_id = request.app["settings"].community_chat_id
    if not bot or not chat_id:
        return web.json_response({"error": "Основной чат сейчас недоступен"}, status=503)

    row = await db.fetchone(SUMMARY_FIELDS + ", r.code" + SUMMARY_FROM + f"""
        WHERE {DURAK_ONLY} AND r.id=? AND r.host=? AND r.status='waiting' AND r.deadline>?
          AND NOT COALESCE(json_extract(r.config,'$.private'), 0)
          AND NOT COALESCE(json_extract(r.config,'$.quick'), 0)
    """, (rid, uid, time.time()))
    if not row:
        raise ValueError("В основной чат может пригласить только создатель открытого стола")
    if rid in updates.announcing:
        return web.json_response({"error": "Приглашение уже отправляется"}, status=409)

    updates.announcing.add(rid)
    try:
        if await has_live_announcement(db, "durak", rid, chat_id):
            return web.json_response({"posted": False})
        config = json.loads(row["config"])
        if not await send_lobby_post(bot, db, chat_id, "durak", rid, uid, config["stake"],
                                     row["count"], config["players"], f"nora_d_{row['code']}"):
            return web.json_response({"error": "Telegram не принял приглашение. Попробуй ещё раз"}, status=502)
        return web.json_response({"posted": True})
    finally:
        updates.announcing.discard(rid)


async def action(request):
    if request.content_length and request.content_length > 4096:
        raise ValueError("Слишком большая команда")
    body = await request.json()
    db, uid = request.app["db"], request["actor"]["id"]
    if isinstance(body, dict) and body.get("action") == "reaction":
        return await reaction(request, db, uid, body)
    try:
        rid, notice = await rooms.command(db, uid, body)
    except rooms.Conflict as exc:
        if isinstance(body, dict) and isinstance(body.get("room"), str):
            request.app["durak_updates"].notify(body["room"])
        return web.json_response({"error": str(exc)}, status=409)
    request.app["durak_updates"].notify(rid)
    if isinstance(notice, rooms.QuickLobby):
        await announce_quick_lobby(request.app["bot"], db, request.app["settings"], "durak",
                                  rid, uid, notice.stake)
    elif notice:
        inbox_id, recipient, _ = notice
        await deliver_game_invitation(
            request.app["bot"], db, request.app["settings"], "durak", rid, uid, recipient, inbox_id,
        )
    return web.json_response({"id": rid})


async def reaction(request, db, uid, body):
    rid, emoji, nonce = body.get("room"), body.get("emoji_id"), body.get("nonce")
    if (body.keys() != {"action", "room", "emoji_id", "nonce"}
            or not isinstance(rid, str) or not re.fullmatch(r"[a-f0-9]{16}", rid)
            or type(emoji) is not int or not 1 <= emoji <= 34
            or not isinstance(nonce, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{16,64}", nonce)):
        raise ValueError("Выбери эмоцию за своим столом")
    member = await db.fetchone(
        "SELECT 1 FROM durak_members m JOIN durak_rooms r ON r.id=m.room "
        f"WHERE {DURAK_ONLY} AND m.room=? AND m.uid=? AND r.status='playing'", (rid, uid))
    if not member:
        return web.json_response({"error": "Ты не участвуешь в текущей партии"}, status=403)
    if emoji > 25:
        async with db.connect() as conn:
            if not ((await items.equipped(conn, uid) or 0) & items.PARTS["witch"]):
                raise ValueError("Включи эмоции ведьмы в разделе «Предметы»")
    now = time.time()
    try:
        event = request.app["durak_updates"].react(rid, uid, emoji, nonce, now)
    except rooms.Conflict as exc:
        return web.json_response({"error": str(exc)}, status=409)
    if event is None:
        return web.json_response({"error": "Подожди перед следующей эмоцией"}, status=429)
    return web.json_response({"reactions": [event], "reaction_now": now})


async def change_items(request):
    if request.content_length and request.content_length > 4096:
        raise ValueError("Слишком большая команда")
    return web.json_response(await items.change(request.app["db"], request["actor"]["id"], await request.json()))


def register(app):
    app["durak_updates"] = Updates()
    app.router.add_get("/api/durak", index)
    app.router.add_post("/api/durak/preview", preview)
    app.router.add_post("/api/durak/action", action)
    app.router.add_post("/api/durak/items", change_items)
    app.router.add_get("/api/durak/room/{rid}", table)
    app.router.add_get("/api/durak/room/{rid}/link", link)
    app.router.add_post(r"/api/durak/room/{rid:[a-f0-9]{16}}/announce", announce)
