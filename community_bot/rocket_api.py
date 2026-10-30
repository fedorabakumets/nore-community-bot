"""Solo rocket: durable, actor-owned rounds and atomic cookie accounting.

The browser animates public server time only. It never supplies a multiplier or
an outcome. Active rounds disclose neither their seed nor their crash point.
"""
from __future__ import annotations

import hashlib
import math
import secrets
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from aiohttp import web

from community_bot.database import Database
from community_bot.profile_fill import profile_is_complete

SCHEMA = """
CREATE TABLE IF NOT EXISTS mini_rocket_quotes (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    bet INTEGER NOT NULL CHECK(bet BETWEEN 1 AND 100),
    auto_cents INTEGER CHECK(auto_cents BETWEEN 110 AND 1000),
    seed TEXT NOT NULL,
    commitment TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'superseded', 'launched')),
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mini_rocket_quotes_user ON mini_rocket_quotes(user_id, created_at);
CREATE TABLE IF NOT EXISTS mini_rocket_rounds (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    quote_token TEXT NOT NULL UNIQUE REFERENCES mini_rocket_quotes(token),
    bet INTEGER NOT NULL CHECK(bet BETWEEN 1 AND 100),
    auto_cents INTEGER CHECK(auto_cents BETWEEN 110 AND 1000),
    seed TEXT NOT NULL,
    commitment TEXT NOT NULL,
    crash_cents INTEGER NOT NULL CHECK(crash_cents BETWEEN 100 AND 1000),
    starts_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'cashed_out', 'crashed')),
    payout INTEGER NOT NULL DEFAULT 0 CHECK(payout BETWEEN 0 AND 1000),
    cashout_cents INTEGER CHECK(cashout_cents BETWEEN 100 AND 1000),
    finished_at REAL,
    created_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mini_rocket_active_user
    ON mini_rocket_rounds(user_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_mini_rocket_user_history ON mini_rocket_rounds(user_id, created_at DESC);
"""

MIN_BET = 1
MAX_BET = 100
MAX_CENTS = 1000
GROWTH_RATE = 0.075
COUNTDOWN_SECONDS = 3
QUOTE_SECONDS = 300
ALGORITHM = "nora-rocket-sha256-v1"
RULES = {
    "min_bet": MIN_BET,
    "max_bet": MAX_BET,
    "max_multiplier": MAX_CENTS / 100,
    "growth_rate": GROWTH_RATE,
    "countdown_seconds": COUNTDOWN_SECONDS,
    "auto_min": 1.1,
    "auto_max": 10,
    "age_min": 18,
    "theoretical_return_percent_max": 97,
    "payout_includes_bet": True,
    "description": (
        "Одиночная игра: ставка 1–100 🍪 из общего кошелька. "
        "Ставки доступны с 18 лет, при полном профиле и без открытого стартер-пака или долга. "
        "Забери печеньки до срыва; срыв может произойти сразу на ×1.00. "
        "Выплата включает ставку и округляется вниз до целой печеньки. "
        "На ×10 полёт заканчивается с автоматической выплатой. "
        "Автозабор выбирается до запуска и работает, даже если закрыть приложение. "
        "Без автозабора закрытие окна не останавливает полёт. "
        "При одновременном достижении точки срыва и автозабора ниже ×10 выигрывает срыв. "
        "Результат зависит от времени получения запроса сервером, анимация приблизительная. "
        "Теоретический возврат — не более 97%; округления уменьшают его. "
        "Это не обещание выигрыша. Обмен выигрыша на деньги не предусмотрен."
    ),
    "proof_algorithm": (
        "commitment = SHA256(seed UTF-8). H = SHA256('nora-rocket-v1:' + seed). "
        "n = integer(first 13 hex chars of H) + 1; "
        "crash_cents = min(1000, max(100, floor(97 * 2^52 / n))). "
        "1000 означает достижение лимита ×10 с выплатой; иначе это точка срыва."
    ),
}


def _now(value: float | None = None) -> float:
    return time.time() if value is None else value


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


def crash_point(seed: str) -> int:
    """Public proof algorithm, domain-separated from the pre-bet commitment."""
    digest = hashlib.sha256(("nora-rocket-v1:" + seed).encode()).hexdigest()
    draw = int(digest[:13], 16) + 1
    return min(MAX_CENTS, max(100, (97 * (1 << 52)) // draw))


def multiplier_cents(starts_at: float, now: float) -> int:
    elapsed = max(0.0, min(now - starts_at, math.log(10) / GROWTH_RATE))
    return min(MAX_CENTS, max(100, math.floor(math.exp(elapsed * GROWTH_RATE) * 100 + 1e-9)))


def _at_multiplier(starts_at: float, cents: int) -> float:
    return starts_at + math.log(cents / 100) / GROWTH_RATE


async def _one(connection, sql: str, params=()) -> dict | None:
    row = await (await connection.execute(sql, params)).fetchone()
    return dict(row) if row else None


async def _reason(connection, user: dict | None) -> str:
    if not user:
        return "Сначала открой личный кабинет Норы"
    flag = await _one(connection, "SELECT enabled FROM feature_flags WHERE key='games'")
    if not flag or not flag["enabled"]:
        return "Игры временно выключены администрацией"
    if not profile_is_complete(user):
        return "Заполни профиль на 100% в ЛК, чтобы открыть игру со ставками"
    if int(user.get("age") or 0) < 18:
        return "Ракетка со ставками доступна с 18 лет. Мафия остаётся бесплатной"
    if int(user.get("cookie_debt") or 0) > 0:
        return "Сначала верни просроченный долг по печенькам"
    active_loan = await _one(
        connection, "SELECT 1 FROM cookie_loans WHERE user_id=? AND status='active' LIMIT 1", (user["user_id"],),
    )
    if active_loan:
        return "Сначала верни НОРА — СТАРТЕР-ПАК: ставки доступны без открытых займов"
    return ""


async def _require_eligible(connection, uid: int) -> dict:
    user = await _one(connection, "SELECT * FROM users WHERE user_id=?", (uid,))
    reason = await _reason(connection, user)
    if reason:
        raise ValueError(reason)
    return user


def _auto_cents(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) not in (int, float):
        raise ValueError("Автозабор — число от 1.10 до 10.00 или без автозабора")
    try:
        decimal = Decimal(str(value))
        cents = decimal * 100
        if not decimal.is_finite() or cents != cents.to_integral_value() or not 110 <= cents <= 1000:
            raise ValueError("Автозабор — от ×1.10 до ×10.00, не больше двух знаков после точки")
        return int(cents)
    except InvalidOperation as error:
        raise ValueError("Проверь значение автозабора") from error


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not 12 <= len(value) <= 128:
        raise ValueError("Открой игру заново")
    return value


async def _finish(connection, row: dict, cents: int | None, finished_at: float) -> dict:
    payout = row["bet"] * cents // 100 if cents is not None else 0
    state = "cashed_out" if cents is not None else "crashed"
    cursor = await connection.execute(
        "UPDATE mini_rocket_rounds SET status=?,payout=?,cashout_cents=?,finished_at=? "
        "WHERE id=? AND status='active'",
        (state, payout, cents, finished_at, row["id"]),
    )
    if cursor.rowcount:
        if payout:
            await connection.execute(
                "UPDATE users SET cookies=cookies+?,updated_at=? WHERE user_id=?",
                (payout, _iso(finished_at), row["user_id"]),
            )
            await connection.execute(
                "INSERT INTO transactions(user_id,amount,kind,details,created_at) VALUES (?,?,'rocket_payout',?,?)",
                (row["user_id"], payout, "round:" + row["id"], _iso(finished_at)),
            )
        row.update(status=state, payout=payout, cashout_cents=cents, finished_at=finished_at)
    return row


async def _settle(connection, row: dict, now: float) -> dict:
    """Settle owed payouts even when games/access/profile has since changed."""
    if row["status"] != "active" or now < row["starts_at"]:
        return row
    crash_cents, auto_cents = row["crash_cents"], row["auto_cents"]
    if auto_cents is not None and (auto_cents < crash_cents or auto_cents == crash_cents == MAX_CENTS):
        auto_at = _at_multiplier(row["starts_at"], auto_cents)
        if now >= auto_at:
            return await _finish(connection, row, auto_cents, auto_at)
    crash_at = _at_multiplier(row["starts_at"], crash_cents)
    if now >= crash_at:
        return await _finish(connection, row, MAX_CENTS if crash_cents == MAX_CENTS else None, crash_at)
    return row


async def _settle_user(connection, uid: int, now: float) -> dict | None:
    row = await _one(connection, "SELECT * FROM mini_rocket_rounds WHERE user_id=? AND status='active'", (uid,))
    return await _settle(connection, row, now) if row else None


def _public(row: dict, now: float) -> dict:
    state = row["status"]
    if state == "active":
        state = "countdown" if now < row["starts_at"] else "flying"
    cents = multiplier_cents(row["starts_at"], now)
    if state == "cashed_out":
        cents = row["cashout_cents"]
    elif state == "crashed":
        cents = row["crash_cents"]
    return {
        "id": row["id"], "status": state, "bet": row["bet"],
        "auto_cashout": row["auto_cents"] / 100 if row["auto_cents"] is not None else None,
        "starts_at": row["starts_at"], "current_multiplier": cents / 100,
        "payout": row["payout"],
        "cashout_multiplier": row["cashout_cents"] / 100 if row["cashout_cents"] is not None else None,
        "commitment": row["commitment"], "finished_at": row["finished_at"],
        "proof": None if row["status"] == "active" else {
            "seed": row["seed"], "crash_multiplier": row["crash_cents"] / 100, "algorithm": ALGORITHM,
        },
    }


def _message(row: dict, now: float) -> str:
    if row["status"] == "crashed":
        return f"Срыв на ×{row['crash_cents'] / 100:.2f}. Ставка {row['bet']} 🍪 проиграна"
    if row["status"] == "cashed_out":
        return f"Забрано {row['payout']} 🍪 на ×{row['cashout_cents'] / 100:.2f}. Ставка уже включена"
    return "Запуск через 3 секунды" if now < row["starts_at"] else "Полёт продолжается"


async def _result(connection, row: dict, now: float) -> dict:
    user = await _one(connection, "SELECT cookies FROM users WHERE user_id=?", (row["user_id"],))
    return {
        "ok": True, "message": _message(row, now), "round": _public(row, now),
        "balance": user["cookies"], "server_time": now,
    }


async def get_status(db: Database, uid: int, *, now: float | None = None) -> dict:
    async with db.connect() as connection:
        await connection.execute("BEGIN IMMEDIATE")
        stamp = _now(now)
        await _settle_user(connection, uid, stamp)
        user = await _one(connection, "SELECT * FROM users WHERE user_id=?", (uid,))
        reason = await _reason(connection, user)
        active = await _one(
            connection, "SELECT * FROM mini_rocket_rounds WHERE user_id=? AND status='active'", (uid,),
        )
        rows = await (await connection.execute(
            "SELECT * FROM mini_rocket_rounds WHERE user_id=? AND status!='active' "
            "ORDER BY created_at DESC,id DESC LIMIT 10", (uid,),
        )).fetchall()
        await connection.commit()
    return {
        "server_time": stamp, "balance": user["cookies"] if user else 0,
        "eligible": not bool(reason), "reason": reason, "rules": RULES,
        "round": _public(active, stamp) if active else None,
        "history": [_public(dict(row), stamp) for row in rows],
    }


async def prepare_round(
    db: Database, uid: int, bet: Any, auto_cashout: Any = None, *, now: float | None = None,
) -> dict:
    if type(bet) is not int or not MIN_BET <= bet <= MAX_BET:
        raise ValueError("Ставка — целое число от 1 до 100 🍪")
    auto_cents = _auto_cents(auto_cashout)
    async with db.connect() as connection:
        await connection.execute("BEGIN IMMEDIATE")
        stamp = _now(now)
        previous = await _settle_user(connection, uid, stamp)
        if previous and previous["status"] == "active":
            raise ValueError("Полёт уже идёт. Сначала заверши текущий")
        user = await _require_eligible(connection, uid)
        if user["cookies"] < bet:
            raise ValueError("Недостаточно печенек для этой ставки")
        recent = await _one(
            connection, "SELECT COUNT(*) AS n FROM mini_rocket_quotes WHERE user_id=? AND created_at>?",
            (uid, stamp - 60),
        )
        if recent["n"] >= 20:
            raise ValueError("Слишком много подтверждений. Подожди минуту")
        await connection.execute(
            "UPDATE mini_rocket_quotes SET status='superseded' WHERE user_id=? AND status='pending'", (uid,),
        )
        token, seed = secrets.token_urlsafe(32), secrets.token_hex(32)
        commitment = hashlib.sha256(seed.encode()).hexdigest()
        await connection.execute(
            "INSERT INTO mini_rocket_quotes(token,user_id,bet,auto_cents,seed,commitment,created_at,expires_at) "
            "VALUES (?,?,?,?,?,?,?,?)", (token, uid, bet, auto_cents, seed, commitment, stamp, stamp + QUOTE_SECONDS),
        )
        await connection.commit()
    return {
        "token": token, "bet": bet, "auto_cashout": auto_cents / 100 if auto_cents is not None else None,
        "expires_at": stamp + QUOTE_SECONDS, "commitment": commitment, "rules": RULES,
    }


async def launch_round(db: Database, uid: int, token: Any, *, now: float | None = None) -> dict:
    token = _identifier(token)
    async with db.connect() as connection:
        await connection.execute("BEGIN IMMEDIATE")
        stamp = _now(now)
        quote = await _one(connection, "SELECT * FROM mini_rocket_quotes WHERE token=? AND user_id=?", (token, uid))
        if not quote:
            raise ValueError("Подтверждение не найдено. Выбери ставку заново")
        # An uncertain HTTP response is safe to retry, including after expiry.
        previous = await _one(connection, "SELECT * FROM mini_rocket_rounds WHERE quote_token=?", (token,))
        if previous:
            previous = await _settle(connection, previous, stamp)
            result = await _result(connection, previous, stamp)
            await connection.commit()
            return result
        if quote["status"] != "pending" or quote["expires_at"] <= stamp:
            raise ValueError("Подтверждение устарело. Выбери ставку заново")
        previous = await _settle_user(connection, uid, stamp)
        if previous and previous["status"] == "active":
            raise ValueError("Полёт уже идёт. Сначала заверши текущий")
        await _require_eligible(connection, uid)
        cursor = await connection.execute(
            "UPDATE users SET cookies=cookies-?,updated_at=? WHERE user_id=? AND cookies>=? AND cookie_debt=0",
            (quote["bet"], _iso(stamp), uid, quote["bet"]),
        )
        if cursor.rowcount != 1:
            raise ValueError("Баланс изменился. Для этой ставки не хватает печенек")
        round_id = secrets.token_urlsafe(18)
        await connection.execute(
            "INSERT INTO mini_rocket_rounds(id,user_id,quote_token,bet,auto_cents,seed,commitment,"
            "crash_cents,starts_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (round_id, uid, token, quote["bet"], quote["auto_cents"], quote["seed"], quote["commitment"],
             crash_point(quote["seed"]), stamp + COUNTDOWN_SECONDS, stamp),
        )
        await connection.execute("UPDATE mini_rocket_quotes SET status='launched' WHERE token=?", (token,))
        await connection.execute(
            "INSERT INTO transactions(user_id,amount,kind,details,created_at) VALUES (?,?,'rocket_bet',?,?)",
            (uid, -quote["bet"], "round:" + round_id, _iso(stamp)),
        )
        row = await _one(connection, "SELECT * FROM mini_rocket_rounds WHERE id=?", (round_id,))
        result = await _result(connection, row, stamp)
        await connection.commit()
    return result


async def cashout_round(db: Database, uid: int, round_id: Any, *, now: float | None = None) -> dict:
    round_id = _identifier(round_id)
    async with db.connect() as connection:
        await connection.execute("BEGIN IMMEDIATE")
        stamp = _now(now)
        row = await _one(connection, "SELECT * FROM mini_rocket_rounds WHERE id=? AND user_id=?", (round_id, uid))
        if not row:
            raise ValueError("Этот полёт недоступен")
        row = await _settle(connection, row, stamp)
        if row["status"] == "active":
            if stamp < row["starts_at"]:
                raise ValueError("Ракетка ещё не взлетела")
            row = await _finish(connection, row, multiplier_cents(row["starts_at"], stamp), stamp)
        result = await _result(connection, row, stamp)
        await connection.commit()
    return result


async def tick(db: Database, now: float | None = None) -> int:
    """Call on startup and every second; no poller or access permission required."""
    async with db.connect() as connection:
        await connection.execute("BEGIN IMMEDIATE")
        stamp = _now(now)
        rows = await (await connection.execute(
            "SELECT * FROM mini_rocket_rounds WHERE status='active' AND starts_at<=? ORDER BY starts_at LIMIT 500",
            (stamp,),
        )).fetchall()
        count = 0
        for record in rows:
            row = await _settle(connection, dict(record), stamp)
            count += row["status"] != "active"
        await connection.commit()
    return count


async def _body(request, allowed: set[str]) -> dict:
    body = await request.json()
    if not isinstance(body, dict) or set(body) - allowed:
        raise ValueError("Проверь параметры игры")
    return body


async def status(request):
    return web.json_response(await get_status(request.app["db"], request["actor"]["id"]))


async def prepare(request):
    body = await _body(request, {"bet", "auto_cashout"})
    return web.json_response(await prepare_round(
        request.app["db"], request["actor"]["id"], body.get("bet"), body.get("auto_cashout"),
    ))


async def launch(request):
    body = await _body(request, {"token"})
    return web.json_response(await launch_round(request.app["db"], request["actor"]["id"], body.get("token")))


async def cashout(request):
    body = await _body(request, {"round_id"})
    return web.json_response(await cashout_round(request.app["db"], request["actor"]["id"], body.get("round_id")))
