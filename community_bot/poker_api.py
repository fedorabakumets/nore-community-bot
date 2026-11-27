"""Telegram-authenticated access to the Hold'em engine over a private subprocess pipe."""

import asyncio
import json
import logging
import secrets
import shutil
import time
from pathlib import Path

from aiohttp import web

from community_bot.database import Database, utcnow
from community_bot.rocket_api import stake_restriction

DIST = Path(__file__).resolve().parents[1] / "poker" / "dist"
ENGINE = DIST / "engine.mjs"
log = logging.getLogger(__name__)


class PokerEngine:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._process = None

    async def _stop(self):
        process, self._process = self._process, None
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.communicate()

    async def _start(self):
        executable = shutil.which("deno")
        if not executable:
            raise FileNotFoundError("Deno executable not found")
        self._process = await asyncio.create_subprocess_exec(
            executable, "run", "--no-prompt", str(ENGINE),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=None,
            env={},
            limit=256 * 1024,
        )

    async def request(self, payload):
        async with self._lock:
            try:
                if self._process is None or self._process.returncode is not None:
                    await self._start()
                process = self._process
                process.stdin.write(json.dumps(payload).encode("utf-8") + b"\n")
                async with asyncio.timeout(3):
                    await process.stdin.drain()
                    line = await process.stdout.readline()
                return json.loads(line)
            except asyncio.CancelledError:
                await self._stop()
                raise
            except (OSError, ValueError, TimeoutError):
                await self._stop()
                log.warning("Poker engine unavailable", exc_info=True)
                return {"status": 503, "error": "Покер пока недоступен. Попробуй чуть позже"}

    async def close(self):
        async with self._lock:
            await self._stop()


SCHEMA = """
CREATE TABLE IF NOT EXISTS poker_wallet_rooms (
    code TEXT PRIMARY KEY, secret TEXT NOT NULL, state TEXT NOT NULL,
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS poker_wallet_seats (
    uid INTEGER PRIMARY KEY REFERENCES users(user_id),
    code TEXT NOT NULL REFERENCES poker_wallet_rooms(code) ON DELETE CASCADE,
    player_id TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS poker_wallet_room_seats ON poker_wallet_seats(code);
"""
ROOM_TTL = 30 * 60
MIN_BUY_IN = 5
MAX_BUY_IN = 1000
DEFAULT_BUY_IN = 20


async def one(conn, sql, args=()):
    row = await (await conn.execute(sql, args)).fetchone()
    return dict(row) if row else None


def funds(room):
    active = bool(room.get("hand") and room["hand"]["street"] != "complete")
    result = {}
    for player in room["players"]:
        stack = player["stack"]
        committed = player["committed"] if active else 0
        if player.get("isBot") or type(stack) is not int or type(committed) is not int or min(stack, committed) < 0:
            raise RuntimeError("Invalid wallet poker stack")
        if player["id"] in result:
            raise RuntimeError("Duplicate poker seat")
        result[player["id"]] = stack + committed
    return result


async def seat_ids(conn, code):
    rows = await (await conn.execute("SELECT uid,player_id FROM poker_wallet_seats WHERE code=?", (code,))).fetchall()
    return {row["player_id"]: row["uid"] for row in rows}


async def expire_rooms(conn, now):
    rows = await (await conn.execute(
        "SELECT code,state FROM poker_wallet_rooms WHERE updated<=?", (now - ROOM_TTL,)
    )).fetchall()
    for row in rows:
        money = funds(json.loads(row["state"]))
        seats = await seat_ids(conn, row["code"])
        if set(money) != set(seats):
            raise RuntimeError("Poker escrow membership mismatch")
        # An abandoned unfinished hand is voided: return each player's own commitments.
        # Completed hands are already settled into stacks; do not count commitments twice.
        for player_id, amount in money.items():
            if amount:
                await Database._add_cookies(conn, seats[player_id], amount, "poker_expiry", row["code"], utcnow())
        await conn.execute("DELETE FROM poker_wallet_rooms WHERE code=?", (row["code"],))


async def eligible(conn, uid, amount):
    user = await one(conn, "SELECT * FROM users WHERE user_id=?", (uid,))
    reason = await stake_restriction(conn, user, age_message="Покер с печеньками доступен с 18 лет")
    if reason:
        raise ValueError(reason)
    if user["cookies"] < amount:
        raise ValueError(f"Для входа нужно {amount} печенек, на балансе {user['cookies']}")
    return user


async def leave(conn, uid, code, room):
    if not room:
        raise ValueError("Стол закрыт")
    member = await one(conn, "SELECT player_id FROM poker_wallet_seats WHERE uid=? AND code=?", (uid, code))
    if not member:
        return {"left": True, "returned": 0}
    if room.get("hand") and room["hand"]["street"] != "complete":
        raise ValueError("Дождись конца раздачи, чтобы забрать печеньки")
    money = funds(room)
    seats = await seat_ids(conn, code)
    if set(money) != set(seats):
        raise RuntimeError("Poker escrow membership mismatch")
    pid = member["player_id"]
    amount = money[pid]
    if amount:
        await Database._add_cookies(conn, uid, amount, "poker_cashout", code, utcnow())
    await conn.execute("DELETE FROM poker_wallet_seats WHERE uid=? AND code=?", (uid, code))
    room["players"] = [p for p in room["players"] if p["id"] != pid]
    if not room["players"]:
        await conn.execute("DELETE FROM poker_wallet_rooms WHERE code=?", (code,))
    else:
        if room["hostId"] == pid:
            room["hostId"] = room["players"][0]["id"]
        room["hand"] = None
        for p in room["players"]:
            p.update(hole=[], bet=0, committed=0, folded=False, allIn=False)
            p.pop("lastAction", None)
        room["version"] += 1
        await conn.execute("UPDATE poker_wallet_rooms SET state=?,updated=? WHERE code=?",
                           (json.dumps(room, separators=(",", ":")), time.time(), code))
    return {"left": True, "returned": amount}


async def wallet_action(conn, engine, uid, kind, code, body, actor):
    now = time.time()
    await expire_rooms(conn, now)
    member = await one(conn, "SELECT code,player_id FROM poker_wallet_seats WHERE uid=?", (uid,))
    if kind == "me":
        user = await one(conn, "SELECT cookies FROM users WHERE user_id=?", (uid,))
        return {"balance": user["cookies"] if user else 0, "code": member["code"] if member else None}, 200

    if kind == "create" and member:
        code, kind = member["code"], "state"
    if kind == "join" and member and member["code"] != code:
        raise ValueError("Ты уже за другим столом. Вернись к нему через меню покера")
    row = await one(conn, "SELECT * FROM poker_wallet_rooms WHERE code=?", (code,)) if code else None
    if kind != "create" and not row:
        if kind == "leave":
            return {"left": True, "returned": 0}, 200
        return {"error": "Стол закрыт или код неверный"}, 404
    old = json.loads(row["state"]) if row else None
    if kind == "leave":
        return await leave(conn, uid, code, old), 200

    is_member = bool(member and member["code"] == code)
    old_seats = await seat_ids(conn, code) if old else {}
    before = funds(old) if old else {}
    if set(before) != set(old_seats):
        raise RuntimeError("Poker escrow membership mismatch")
    if kind in {"command", "link"} and not is_member:
        return {"error": "Сначала займи место за столом"}, 403
    entering = kind == "create" or (kind == "join" and not is_member)
    amount = 0
    name = ""
    if entering:
        amount = body.get("buyIn", DEFAULT_BUY_IN) if kind == "create" else old["settings"]["buyIn"]
        if type(amount) is not int or not MIN_BUY_IN <= amount <= MAX_BUY_IN:
            raise ValueError("Выбери от 5 до 1000 печенек")
        user = await eligible(conn, uid, amount)
        name = user.get("profile_name") or actor.get("first_name") or "Участник"
    secret = row["secret"] if row else secrets.token_hex(32)
    payload = {
        "action": "state" if kind == "link" else kind,
        "uid": str(uid), "name": name, "code": code,
        "body": body if kind == "command" else None,
        "secret": secret, "savedRoom": old, "buyIn": amount if entering else None,
    }
    # The subprocess is a pure state transition. Its full state never reaches the client.
    result = await engine.request(payload)
    status = result.pop("status", 200)
    new = result.pop("privateRoom", None)
    if status != 200:
        return result, status
    if new is None:
        if entering or is_member:
            raise RuntimeError("Missing private poker state")
        return result, status
    after = funds(new)
    new_code = new["code"]
    if old and new_code != code:
        raise RuntimeError("Poker room changed identity")
    if not old and await one(conn, "SELECT 1 FROM poker_wallet_rooms WHERE code=?", (new_code,)):
        raise ValueError("Не удалось создать стол. Попробуй ещё раз")
    expected = set(before)
    if entering:
        pid = result["snapshot"]["viewerId"]
        if pid in expected or after.get(pid) != amount:
            raise RuntimeError("Invalid poker buy-in")
        expected.add(pid)
    if set(after) != expected or sum(after.values()) != sum(before.values()) + amount:
        raise RuntimeError("Poker escrow does not conserve cookies")
    # Debit and durable room update commit in a single SQLite transaction.
    if entering:
        await Database._add_cookies(conn, uid, -amount, "poker_buyin", new_code, utcnow())
    if not old or new != old or now - row["updated"] >= 15:
        await conn.execute(
            "INSERT INTO poker_wallet_rooms(code,secret,state,updated) VALUES(?,?,?,?) "
            "ON CONFLICT(code) DO UPDATE SET state=excluded.state,updated=excluded.updated",
            (new_code, secret, json.dumps(new, separators=(",", ":")), now),
        )
    if entering:
        await conn.execute("INSERT INTO poker_wallet_seats(uid,code,player_id) VALUES(?,?,?)", (uid, new_code, pid))
    return result, status


async def action(request):
    actor = request["actor"]
    kind = request.match_info.get("kind", "create" if request.method == "POST" else "state")
    if request.path.endswith("/me"):
        kind = "me"
    code = request.match_info.get("code")
    body = {}
    if kind in {"create", "command"}:
        try:
            await request.content.readexactly(4097)
        except asyncio.IncompleteReadError as error:
            try:
                body = json.loads(error.partial or b"{}")
            except (ValueError, UnicodeError):
                return web.json_response({"error": "Проверь действие"}, status=400)
            if not isinstance(body, dict):
                return web.json_response({"error": "Проверь действие"}, status=400)
        else:
            raise web.HTTPRequestEntityTooLarge(max_size=4096, actual_size=4097)
    try:
        async with request.app["db"].connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            result, status = await wallet_action(conn, request.app[ENGINE_KEY], int(actor["id"]), kind, code, body, actor)
            await conn.commit()
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=400)
    except Exception:
        log.exception("Poker wallet transaction failed")
        return web.json_response({"error": "Покер временно недоступен. Печеньки сохранены"}, status=503)
    if kind == "link" and status == 200:
        if not result.get("snapshot"):
            return web.json_response({"error": "Сначала займи место за столом"}, status=403)
        bot = request.app["bot"]
        if not bot or not (name := (await bot.me()).username):
            return web.json_response({"error": f"Приглашение недоступно. Код стола {code}"}, status=503)
        result = {"url": f"https://t.me/{name}?startapp=nora_poker_{code}"}
    return web.json_response(result, status=status)


ENGINE_KEY = web.AppKey("poker_engine", PokerEngine)


def register(app):
    engine = PokerEngine()
    app[ENGINE_KEY] = engine

    async def lifecycle(application):
        async with application["db"].connect() as conn:
            await conn.executescript(SCHEMA)
            await conn.commit()

        async def sweep():
            while True:
                try:
                    async with application["db"].connect() as conn:
                        await conn.execute("BEGIN IMMEDIATE")
                        await expire_rooms(conn, time.time())
                        await conn.commit()
                except Exception:
                    log.exception("Poker expiry failed")
                await asyncio.sleep(60)

        task = asyncio.create_task(sweep())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await engine.close()

    app.cleanup_ctx.append(lifecycle)
    if (DIST / "public").is_dir():
        app.router.add_static("/poker-assets/", DIST / "public", show_index=False)

    room = r"/api/poker/rooms/{code:[A-HJ-NP-Z2-9]{8}}"
    app.router.add_get("/api/poker/me", action)
    app.router.add_post("/api/poker/rooms", action)
    app.router.add_get(room, action)
    app.router.add_get(room + "/{kind:link}", action)
    app.router.add_post(room + "/{kind:join|command|leave}", action)
