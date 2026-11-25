"""DOT ranked flights: one-use server tickets and deterministic server replay."""
from __future__ import annotations

import asyncio
import json
import hashlib
import secrets
import shutil
import time
from pathlib import Path
from datetime import datetime, timezone

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
CREATE TABLE IF NOT EXISTS mini_dot_reward_results (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    reward INTEGER NOT NULL CHECK(reward >= 0),
    world_record INTEGER NOT NULL DEFAULT 0,
    limit_reached INTEGER NOT NULL DEFAULT 0,
    awarded_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS mini_dot_reward_window ON mini_dot_reward_results(user_id, awarded_at) WHERE reward > 0;
CREATE TABLE IF NOT EXISTS mini_dot_credits (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    amount INTEGER NOT NULL CHECK(amount >= 0)
);
CREATE TABLE IF NOT EXISTS mini_dot_grants (
    grant_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    amount INTEGER NOT NULL CHECK(amount > 0)
);
CREATE TABLE IF NOT EXISTS mini_dot_wallet (
    user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
    equipped TEXT NOT NULL DEFAULT 'red'
);
CREATE TABLE IF NOT EXISTS mini_dot_skins (
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    skin TEXT NOT NULL,
    PRIMARY KEY(user_id, skin)
);
CREATE TABLE IF NOT EXISTS mini_dot_lives (
    user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0)
);
CREATE TABLE IF NOT EXISTS mini_dot_life_purchases (
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    purchase_id TEXT NOT NULL,
    PRIMARY KEY(user_id, purchase_id)
);
CREATE TABLE IF NOT EXISTS mini_dot_revives (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    tick INTEGER NOT NULL,
    prefix_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mini_dot_intro_seen (
    user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    seen_at REAL NOT NULL
);
"""
MAX_TICKS = 432_000
TICKET_TTL = 86_400
REWARD_WINDOW = 86_400
REWARD_LIMIT = 2
SKINS = {"red": 0, "mint": 1000, "ice": 1000, "violet": 1000}
LIFE_PRICE = 1500
COOKIE_RATE = 10
RULES_V2_PREFIX = "DOTv2_"
RUNNER = Path(__file__).with_name("dot_replay.mjs")
REPLAY_LIMIT = asyncio.Semaphore(2)


async def one(connection, sql, params=()):
    row = await (await connection.execute(sql, params)).fetchone()
    return dict(row) if row else None


async def issue(db, uid, now=None, rules=1):
    now = time.time() if now is None else now
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        await conn.execute("DELETE FROM mini_dot_revives WHERE token IN (SELECT token FROM mini_dot_sessions WHERE expires_at<?)", (now,))
        await conn.execute("DELETE FROM mini_dot_sessions WHERE expires_at<?", (now,))
        recent = await one(conn, "SELECT COUNT(*) n FROM mini_dot_sessions WHERE user_id=? AND issued_at>?",
                           (uid, now - 60))
        if recent["n"] >= 60:
            raise ValueError("Слишком много попыток. Попробуй через минуту.")
        token, seed = secrets.token_urlsafe(24), secrets.randbits(32)
        if rules == 2:
            token = RULES_V2_PREFIX + secrets.token_urlsafe(24)[:26]
        else:
            while token.startswith(RULES_V2_PREFIX):
                token = secrets.token_urlsafe(24)
        await conn.execute(
            "INSERT INTO mini_dot_sessions(token,user_id,seed,issued_at,expires_at) VALUES(?,?,?,?,?)",
            (token, uid, seed, now, now + TICKET_TTL),
        )
        seen = await one(conn, "SELECT 1 FROM mini_dot_intro_seen WHERE user_id=?", (uid,))
        await conn.commit()
    return {"token": token, "seed": seed, "intro_seen": bool(seen), "rules": rules}


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


async def replay(seed, ticks, flaps, revive_tick=None, rules=1):
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
                process.communicate(json.dumps({"seed": seed, "ticks": ticks, "flaps": flaps, "reviveTick": revive_tick, "rules": rules}).encode()),
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


async def reward_result(conn, session):
    row = await one(conn, "SELECT reward,world_record,limit_reached FROM mini_dot_reward_results WHERE token=?",
                    (session["token"],))
    credit = await one(conn, "SELECT amount FROM mini_dot_credits WHERE token=?", (session["token"],))
    return {"new_record": bool(session["new_record"]), "dot_earned": credit["amount"] if credit else 0,
            "reward": row["reward"] if row else 0,
            "world_record": bool(row and row["world_record"]), "limit_reached": bool(row and row["limit_reached"])}


def flight_hash(flaps):
    return hashlib.sha256(json.dumps(flaps, separators=(",", ":")).encode()).hexdigest()


async def revive(db, uid, body, now=None):
    token, ticks, flaps = validate_input(body)
    now = time.time() if now is None else now
    prefix = flight_hash(flaps)
    async with db.connect() as conn:
        session = await one(conn, "SELECT * FROM mini_dot_sessions WHERE token=? AND user_id=?", (token, uid))
        if not session or session["used"] or session["expires_at"] < now:
            raise ValueError("Сессия DOT истекла")
        existing = await one(conn, "SELECT * FROM mini_dot_revives WHERE token=?", (token,))
        if existing:
            if existing["tick"] != ticks or existing["prefix_hash"] != prefix:
                raise ValueError("Вторая жизнь уже использована")
            return await shop_state(conn, uid)
    if ticks / 120 > now - session["issued_at"] + 2:
        raise ValueError("Неверная продолжительность полёта")
    try:
        if token.startswith(RULES_V2_PREFIX):
            await replay(session["seed"], ticks, flaps, rules=2)
        else:
            await replay(session["seed"], ticks, flaps)
    except TimeoutError:
        raise ValueError("Проверка полёта заняла слишком много времени") from None
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        current = await one(conn, "SELECT * FROM mini_dot_sessions WHERE token=? AND user_id=?", (token, uid))
        if not current or current["used"] or current["expires_at"] < now:
            raise ValueError("Сессия DOT истекла")
        existing = await one(conn, "SELECT * FROM mini_dot_revives WHERE token=?", (token,))
        if existing:
            if existing["tick"] != ticks or existing["prefix_hash"] != prefix:
                raise ValueError("Вторая жизнь уже использована")
        else:
            changed = await conn.execute("UPDATE mini_dot_lives SET balance=balance-1 WHERE user_id=? AND balance>0", (uid,))
            if changed.rowcount != 1:
                raise ValueError("Нет второй жизни")
            await conn.execute("INSERT INTO mini_dot_revives VALUES(?,?,?,?)", (token, uid, ticks, prefix))
        state = await shop_state(conn, uid)
        await conn.commit()
        return state


async def finish(db, uid, body, now=None):
    token, ticks, flaps = validate_input(body)
    fixed_now = now
    now = time.time() if now is None else now
    async with db.connect() as conn:
        session = await one(conn, "SELECT * FROM mini_dot_sessions WHERE token=? AND user_id=?", (token, uid))
        if not session or session["expires_at"] < now:
            raise ValueError("Сессия DOT истекла")
        if session["used"]:
            return await reward_result(conn, session)
        revived = await one(conn, "SELECT * FROM mini_dot_revives WHERE token=?", (token,))
    revive_tick = body.get("revive_tick")
    if revive_tick is not None:
        if (type(revive_tick) is not int or not revived or revived["tick"] != revive_tick
                or not 0 < revive_tick < ticks
                or revived["prefix_hash"] != flight_hash([f for f in flaps if f < revive_tick])):
            raise ValueError("Возрождение не подтверждено")
    elif revived and (ticks != revived["tick"] or flight_hash(flaps) != revived["prefix_hash"]):
        raise ValueError("Возрождение не подтверждено")
    if ticks / 120 > now - session["issued_at"] + 2:
        raise ValueError("Неверная продолжительность полёта")
    try:
        if token.startswith(RULES_V2_PREFIX):
            result = await replay(session["seed"], ticks, flaps, revive_tick, rules=2)
        else:
            result = await replay(session["seed"], ticks, flaps, revive_tick) if revive_tick is not None else await replay(session["seed"], ticks, flaps)
    except TimeoutError:
        raise ValueError("Проверка полёта заняла слишком много времени") from None
    cookies, passed = result["cookies"], result["passed"]
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        current = await one(conn, "SELECT * FROM mini_dot_sessions WHERE token=? AND user_id=?", (token, uid))
        now = time.time() if fixed_now is None else fixed_now
        if not current or current["expires_at"] < now:
            raise ValueError("Сессия DOT истекла")
        if current["used"]:
            return await reward_result(conn, current)
        current_revive = await one(conn, "SELECT * FROM mini_dot_revives WHERE token=?", (token,))
        if current_revive != revived:
            raise ValueError("Состояние полёта изменилось")
        best = await one(conn, "SELECT cookies,passed FROM mini_dot_records WHERE user_id=?", (uid,))
        world = await one(conn, "SELECT MAX(cookies) AS score FROM mini_dot_records")
        world_record = cookies > max(0, world["score"] or 0)
        improved = best is None or (cookies, passed) > (best["cookies"], best["passed"])
        recent = await one(conn, "SELECT COUNT(*) AS n FROM mini_dot_reward_results "
                           "WHERE user_id=? AND reward>0 AND awarded_at>?", (uid, now - REWARD_WINDOW))
        limit_reached = world_record and recent["n"] >= REWARD_LIMIT
        reward = cookies if world_record and not limit_reached else 0
        # Every verified flight earns DOT-only currency, once per session.
        await conn.execute("INSERT INTO mini_dot_credits(token,user_id,amount) VALUES(?,?,?)", (token, uid, cookies))
        await conn.execute(
            "INSERT INTO mini_dot_wallet(user_id,balance) VALUES(?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET balance=balance+excluded.balance",
            (uid, cookies),
        )
        # Record, wallet and one-use settlement share the same write transaction.
        if reward:
            stamp = datetime.fromtimestamp(now, timezone.utc).isoformat()
            await conn.execute("UPDATE users SET cookies=cookies+?,updated_at=? WHERE user_id=?",
                               (reward, stamp, uid))
            await conn.execute(
                "INSERT INTO transactions(user_id,amount,kind,details,created_at) VALUES(?,?,?,?,?)",
                (uid, reward, "dot_record", "DOT: мировой рекорд", stamp),
            )
        await conn.execute(
            "INSERT INTO mini_dot_reward_results(token,user_id,reward,world_record,limit_reached,awarded_at) "
            "VALUES(?,?,?,?,?,?)", (token, uid, reward, int(world_record), int(limit_reached), now),
        )
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
    return {"new_record": improved, "dot_earned": cookies, "reward": reward, "world_record": world_record,
            "limit_reached": limit_reached}


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


async def shop_state(conn, uid):
    wallet = await one(conn, "SELECT balance,equipped FROM mini_dot_wallet WHERE user_id=?", (uid,))
    rows = await (await conn.execute("SELECT skin FROM mini_dot_skins WHERE user_id=?", (uid,))).fetchall()
    owned = {"red"} | {row["skin"] for row in rows}
    life = await one(conn, "SELECT balance FROM mini_dot_lives WHERE user_id=?", (uid,))
    user = await one(conn, "SELECT cookies FROM users WHERE user_id=?", (uid,))
    return {"balance": wallet["balance"] if wallet else 0,
            "cookie_balance": user["cookies"] if user else 0,
            "cookie_prices": {key: price // COOKIE_RATE for key, price in SKINS.items()},
            "cookie_life_price": LIFE_PRICE // COOKIE_RATE,
            "equipped": wallet["equipped"] if wallet else "red",
            "owned": [skin for skin in SKINS if skin in owned], "prices": SKINS,
            "lives": life["balance"] if life else 0, "life_price": LIFE_PRICE}


async def spend_dot(conn, uid, price, currency, item):
    if currency == "cookies":
        price //= COOKIE_RATE
        stamp = datetime.now(timezone.utc).isoformat()
        changed = await conn.execute(
            "UPDATE users SET cookies=cookies-?,updated_at=? WHERE user_id=? AND cookies>=?",
            (price, stamp, uid, price),
        )
        if changed.rowcount != 1:
            raise ValueError("Недостаточно печенек Норы")
        await conn.execute(
            "INSERT INTO transactions(user_id,amount,kind,details,created_at) VALUES(?,?,?,?,?)",
            (uid, -price, "dot_shop", f"DOT: {item}", stamp),
        )
    else:
        changed = await conn.execute(
            "UPDATE mini_dot_wallet SET balance=balance-? WHERE user_id=? AND balance>=?",
            (price, uid, price),
        )
        if changed.rowcount != 1:
            raise ValueError("Недостаточно крошек DOT")


async def shop(db, uid, action=None, skin=None, purchase_id=None, currency="crumbs"):
    if currency not in ("crumbs", "cookies"):
        raise ValueError("Неизвестная валюта DOT")
    if action == "buy_life":
        if not isinstance(purchase_id, str) or not 16 <= len(purchase_id) <= 80:
            raise ValueError("Некорректная покупка DOT")
        async with db.connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            inserted = await conn.execute("INSERT OR IGNORE INTO mini_dot_life_purchases VALUES(?,?)", (uid, purchase_id))
            if inserted.rowcount == 1:
                await spend_dot(conn, uid, LIFE_PRICE, currency, "Вторая жизнь")
                await conn.execute("INSERT INTO mini_dot_lives VALUES(?,1) ON CONFLICT(user_id) DO UPDATE SET balance=balance+1", (uid,))
            state = await shop_state(conn, uid)
            await conn.commit()
            return state
    if action is not None and (action not in ("buy", "equip") or not isinstance(skin, str) or skin not in SKINS):
        raise ValueError("Неизвестный товар DOT")
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE" if action else "BEGIN")
        if action:
            await conn.execute("INSERT OR IGNORE INTO mini_dot_wallet(user_id) VALUES(?)", (uid,))
            state = await shop_state(conn, uid)
            if skin not in state["owned"]:
                if action != "buy":
                    raise ValueError("Сначала купи этот цвет")
                await spend_dot(conn, uid, SKINS[skin], currency, f"Цвет {skin}")
                await conn.execute("INSERT INTO mini_dot_skins(user_id,skin) VALUES(?,?)", (uid, skin))
            await conn.execute("UPDATE mini_dot_wallet SET equipped=? WHERE user_id=?", (skin, uid))
        state = await shop_state(conn, uid)
        await conn.commit()
        return state


async def grant_owner_dot_cookies(db, uid, owner_id):
    if not owner_id or uid != owner_id:
        return False
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        inserted = await conn.execute(
            "INSERT OR IGNORE INTO mini_dot_grants(grant_id,user_id,amount) VALUES(?,?,?)",
            ("owner-dot-4000-2026-11-25", uid, 4000),
        )
        if inserted.rowcount != 1:
            await conn.commit()
            return False
        await conn.execute(
            "INSERT INTO mini_dot_wallet(user_id,balance) VALUES(?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET balance=balance+excluded.balance",
            (uid, 4000),
        )
        await conn.commit()
        return True


async def shop_handler(request):
    db, uid = request.app["db"], request["actor"]["id"]
    await grant_owner_dot_cookies(db, uid, request.app["settings"].owner_id)
    if request.method == "GET":
        return web.json_response(await shop(db, uid))
    body = await request.json()
    if not isinstance(body, dict) or body.get("action") not in ("buy", "equip", "buy_life"):
        raise ValueError("Некорректное действие магазина DOT")
    return web.json_response(await shop(db, uid, body["action"], body.get("skin"), body.get("purchase_id"), body.get("currency", "crumbs")))


async def revive_handler(request):
    if request.content_length and request.content_length > 2_000_000:
        raise web.HTTPRequestEntityTooLarge(max_size=2_000_000, actual_size=request.content_length)
    return web.json_response(await revive(request.app["db"], request["actor"]["id"], await request.json()))


async def start_handler(request):
    body = await request.json() if request.can_read_body else {}
    rules = 2 if isinstance(body, dict) and body.get("rules") == 2 else 1
    return web.json_response(await issue(request.app["db"], request["actor"]["id"], rules=rules))


async def top_handler(request):
    return web.json_response(await leaderboard(request.app["db"], request.app["settings"], request["actor"]["id"]))


async def finish_handler(request):
    if request.content_length and request.content_length > 2_000_000:
        raise web.HTTPRequestEntityTooLarge(max_size=2_000_000, actual_size=request.content_length)
    db, settings, uid = request.app["db"], request.app["settings"], request["actor"]["id"]
    settlement = await finish(db, uid, await request.json())
    result = await leaderboard(db, settings, uid)
    result.update(settlement)
    return web.json_response(result)


async def intro_handler(request):
    db, uid = request.app["db"], request["actor"]["id"]
    async with db.connect() as conn:
        await conn.execute("INSERT OR IGNORE INTO mini_dot_intro_seen(user_id,seen_at) VALUES(?,?)",
                           (uid, time.time()))
        await conn.commit()
    return web.json_response({"ok": True})


async def reset_leaderboard_once(db):
    """Archive the old DOT leaderboard and reset it exactly once, atomically."""
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        archive = await one(
            conn, "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='mini_dot_records_before_20261125_reset'",
        )
        if archive:
            await conn.commit()
            return False
        await conn.execute(
            "CREATE TABLE mini_dot_records_before_20261125_reset AS SELECT * FROM mini_dot_records"
        )
        await conn.execute("DELETE FROM mini_dot_records")
        await conn.commit()
        return True


async def reset_leaderboard_at_startup(app):
    await reset_leaderboard_once(app["db"])


def register(app):
    app.on_startup.append(reset_leaderboard_at_startup)
    app.router.add_get("/api/dot/shop", shop_handler)
    app.router.add_post("/api/dot/shop", shop_handler)
    app.router.add_post("/api/dot/intro", intro_handler)
    app.router.add_post("/api/dot/start", start_handler)
    app.router.add_get("/api/dot/top", top_handler)
    app.router.add_post("/api/dot/finish", finish_handler)
    app.router.add_post("/api/dot/revive", revive_handler)
