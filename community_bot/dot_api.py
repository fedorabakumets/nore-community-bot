"""DOT ranked flights: one-use server tickets and deterministic server replay."""
from __future__ import annotations

import asyncio
import json
import secrets
import shutil
import time
from pathlib import Path

from aiohttp import web

SCHEMA = """
CREATE TABLE IF NOT EXISTS mini_dot_sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    seed INTEGER NOT NULL,
    issued_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    result_cookies INTEGER,
    result_passed INTEGER,
    new_record INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS mini_dot_sessions_user ON mini_dot_sessions(user_id, issued_at);
CREATE INDEX IF NOT EXISTS mini_dot_sessions_expiry ON mini_dot_sessions(expires_at);
CREATE TABLE IF NOT EXISTS mini_dot_records (
    user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    cookies INTEGER NOT NULL CHECK(cookies >= 0),
    passed INTEGER NOT NULL CHECK(passed >= 0),
    achieved_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS mini_dot_rank ON mini_dot_records(cookies DESC, passed DESC, achieved_at, user_id);
"""
MAX_TICKS = 432_000
TICKET_TTL = 86_400
RUNNER = Path(__file__).with_name("dot_replay.mjs")
REPLAY_LIMIT = asyncio.Semaphore(2)


async def one(connection, sql, params=()):
    row = await (await connection.execute(sql, params)).fetchone()
    return dict(row) if row else None


async def issue(db, uid, now=None):
    now = time.time() if now is None else now
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        await conn.execute("DELETE FROM mini_dot_sessions WHERE expires_at<?", (now,))
        recent = await one(conn, "SELECT COUNT(*) n FROM mini_dot_sessions WHERE user_id=? AND issued_at>?",
                           (uid, now - 60))
        if recent["n"] >= 60:
            raise ValueError("Слишком много попыток. Попробуй через минуту.")
        token, seed = secrets.token_urlsafe(24), secrets.randbits(32)
        await conn.execute(
            "INSERT INTO mini_dot_sessions(token,user_id,seed,issued_at,expires_at) VALUES(?,?,?,?,?)",
            (token, uid, seed, now, now + TICKET_TTL),
        )
        await conn.commit()
    return {"token": token, "seed": seed}


def validate_input(body):
    if not isinstance(body, dict):
        raise ValueError("Некорректная запись полёта")
    token, ticks, flaps = body.get("token"), body.get("ticks"), body.get("flaps")
    if (not isinstance(token, str) or len(token) != 32 or type(ticks) is not int
            or not 1 <= ticks <= MAX_TICKS or not isinstance(flaps, list)
            or not 1 <= len(flaps) <= ticks or flaps[0] != 0):
        raise ValueError("Некорректная запись полёта")
    previous = -1
    for tick in flaps:
        if type(tick) is not int or not previous < tick < ticks:
            raise ValueError("Некорректные прыжки")
        previous = tick
    return token, ticks, flaps


async def replay(seed, ticks, flaps):
    deno = shutil.which("deno")
    node = shutil.which("node")
    if deno:
        command = [deno, "run", "--quiet", "--no-prompt", str(RUNNER)]
    elif node:
        command = [node, str(RUNNER)]
    else:
        raise web.HTTPServiceUnavailable(text="DOT verifier unavailable")
    async with REPLAY_LIMIT:
        process = await asyncio.create_subprocess_exec(
            *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            output, _ = await asyncio.wait_for(
                process.communicate(json.dumps({"seed": seed, "ticks": ticks, "flaps": flaps}).encode()),
                timeout=12,
            )
        except (TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
                await process.communicate()
            raise
    if process.returncode:
        raise ValueError("Не удалось подтвердить траекторию полёта")
    result = json.loads(output)
    if (result.get("ticks") != ticks or type(result.get("cookies")) is not int
            or type(result.get("passed")) is not int or not 0 <= result["cookies"] <= result["passed"] + 1):
        raise ValueError("Некорректный результат полёта")
    return result


async def finish(db, uid, body, now=None):
    token, ticks, flaps = validate_input(body)
    now = time.time() if now is None else now
    async with db.connect() as conn:
        session = await one(conn, "SELECT * FROM mini_dot_sessions WHERE token=? AND user_id=?", (token, uid))
    if not session or session["expires_at"] < now:
        raise ValueError("Сессия DOT истекла")
    if session["used"]:
        return bool(session["new_record"])
    if ticks / 120 > now - session["issued_at"] + 2:
        raise ValueError("Неверная продолжительность полёта")
    try:
        result = await replay(session["seed"], ticks, flaps)
    except TimeoutError:
        raise ValueError("Проверка полёта заняла слишком много времени") from None
    cookies, passed = result["cookies"], result["passed"]
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        current = await one(conn, "SELECT * FROM mini_dot_sessions WHERE token=? AND user_id=?", (token, uid))
        if not current:
            raise ValueError("Сессия DOT истекла")
        if current["used"]:
            return bool(current["new_record"])
        best = await one(conn, "SELECT cookies,passed FROM mini_dot_records WHERE user_id=?", (uid,))
        improved = best is None or (cookies, passed) > (best["cookies"], best["passed"])
        if improved:
            await conn.execute(
                "INSERT INTO mini_dot_records(user_id,cookies,passed,achieved_at) VALUES(?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET cookies=excluded.cookies,passed=excluded.passed,"
                "achieved_at=excluded.achieved_at", (uid, cookies, passed, now),
            )
        await conn.execute(
            "UPDATE mini_dot_sessions SET used=1,result_cookies=?,result_passed=?,new_record=? WHERE token=?",
            (cookies, passed, int(improved), token),
        )
        await conn.commit()
    return improved


async def leaderboard(db, settings, uid):
    from community_bot.helpers import can_view_profile
    from community_bot.role_prefixes import prefix_for

    order = "cookies DESC,passed DESC,achieved_at ASC,user_id ASC"
    async with db.connect() as conn:
        await conn.execute("BEGIN")
        top = [dict(row) for row in await (await conn.execute(
            f"SELECT * FROM mini_dot_records ORDER BY {order} LIMIT 3"
        )).fetchall()]
        mine = await one(conn, "SELECT * FROM mini_dot_records WHERE user_id=?", (uid,))
        rank = None
        if mine:
            count = await one(conn, """
                SELECT COUNT(*) n FROM mini_dot_records
                WHERE cookies>? OR (cookies=? AND passed>?)
                OR (cookies=? AND passed=? AND achieved_at<?)
                OR (cookies=? AND passed=? AND achieved_at=? AND user_id<?)
            """, (mine["cookies"], mine["cookies"], mine["passed"], mine["cookies"], mine["passed"],
                  mine["achieved_at"], mine["cookies"], mine["passed"], mine["achieved_at"], uid))
            rank = count["n"] + 1
        await conn.commit()

    async def public(record, place):
        target_id = record["user_id"]
        target = await db.get_user(target_id)
        blocked = target_id != uid and await db.fetchone(
            "SELECT 1 FROM mini_friend_blocks WHERE (blocker_id=? AND blocked_id=?) "
            "OR (blocker_id=? AND blocked_id=?)", (uid, target_id, target_id, uid))
        row = {"rank": place, "cookies": record["cookies"], "passed": record["passed"],
               "self": target_id == uid, "id": None, "name": "Участник", "has_avatar": False, "prefix": None}
        if target and not blocked:
            row.update(id=target_id, name=target["profile_name"] or target["telegram_name"] or "Участник",
                       prefix=await prefix_for(db, settings, target_id))
            row["has_avatar"] = bool(target["avatar_file_id"] and target["avatar_media_type"] == "photo"
                                     and await can_view_profile(db, settings, uid, target))
        return row

    leaders = [await public(row, i + 1) for i, row in enumerate(top)]
    own = next((row for row in leaders if row["self"]), None)
    if mine and own is None:
        own = await public(mine, rank)
    return {"top": leaders, "self": own}


async def start_handler(request):
    return web.json_response(await issue(request.app["db"], request["actor"]["id"]))


async def top_handler(request):
    return web.json_response(await leaderboard(request.app["db"], request.app["settings"], request["actor"]["id"]))


async def finish_handler(request):
    if request.content_length and request.content_length > 2_000_000:
        raise web.HTTPRequestEntityTooLarge(max_size=2_000_000, actual_size=request.content_length)
    db, settings, uid = request.app["db"], request.app["settings"], request["actor"]["id"]
    improved = await finish(db, uid, await request.json())
    result = await leaderboard(db, settings, uid)
    result["new_record"] = improved
    return web.json_response(result)


def register(app):
    app.router.add_post("/api/dot/start", start_handler)
    app.router.add_get("/api/dot/top", top_handler)
    app.router.add_post("/api/dot/finish", finish_handler)
