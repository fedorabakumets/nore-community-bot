"""Морской бой: Mini App-игра с ботом бесплатно или с другом на печеньки.

Boards, shots and deadlines live in SQLite. The browser only renders the
server's view; every shot is validated and resolved in a write transaction.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime

from aiohttp import web

SCHEMA = """
CREATE TABLE IF NOT EXISTS mini_sea_rooms (
    id TEXT PRIMARY KEY, host_id INTEGER NOT NULL REFERENCES users(user_id),
    title TEXT NOT NULL, status TEXT NOT NULL, stake INTEGER NOT NULL DEFAULT 0,
    bot INTEGER NOT NULL DEFAULT 0, deadline REAL NOT NULL, state_json TEXT NOT NULL,
    created_at REAL NOT NULL, updated_at REAL NOT NULL, finished_at REAL
);
CREATE INDEX IF NOT EXISTS mini_sea_due ON mini_sea_rooms(status,deadline);
CREATE TABLE IF NOT EXISTS mini_sea_members (
    room_id TEXT NOT NULL REFERENCES mini_sea_rooms(id),
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    active INTEGER NOT NULL DEFAULT 1, joined_at REAL NOT NULL,
    PRIMARY KEY(room_id,user_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS mini_sea_one_room ON mini_sea_members(user_id) WHERE active=1;
CREATE TABLE IF NOT EXISTS mini_sea_invites (
    room_id TEXT NOT NULL REFERENCES mini_sea_rooms(id),
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    sender_id INTEGER NOT NULL REFERENCES users(user_id),
    status TEXT NOT NULL DEFAULT 'pending', created_at REAL NOT NULL,
    PRIMARY KEY(room_id,user_id)
);
CREATE INDEX IF NOT EXISTS mini_sea_invitations ON mini_sea_invites(user_id,status);
"""

SIZE = 10
SHIPS = [4, 3, 3, 2, 2, 2, 1, 1, 1, 1]
STAKE_CHOICES = (0, 5, 10, 25, 50, 100)
MAX_STAKE = 100
LOBBY_SECONDS = 3600
MOVE_SECONDS = 60
MAX_GAME_SECONDS = 3600
BOT_PAUSE = 1.5
BOT_NAME = "Нора-бот"


class Conflict(ValueError):
    """An outdated screen must be refreshed before retrying."""


RULES = {
    "size": SIZE,
    "ships": SHIPS,
    "stake_choices": list(STAKE_CHOICES),
    "max_stake": MAX_STAKE,
    "move_seconds": MOVE_SECONDS,
    "sections": [
        {
            "title": "Расстановка",
            "text": "Флот стандартный: один 4-палубный, два 3-палубных, три 2-палубных и четыре однопалубных. "
            "Корабли расставляются автоматически и не касаются друг друга — как в классических правилах.",
        },
        {
            "title": "Ход",
            "text": "Игроки по очереди стреляют по полю соперника. Попал — стреляешь снова, промах — ход переходит. "
            "На ход даётся 60 секунд; пропустил время — ход "
            "переходит сопернику. Игра против бота идёт с паузами в пару секунд.",
        },
        {
            "title": "Победа",
            "text": "Побеждает тот, кто первым потопил все 10 кораблей соперника. "
            "Комната без старта закрывается через час, партия без финала через час завершается ничьей.",
        },
        {
            "title": "С ботом и с другом",
            "text": "С ботом Норы можно играть бесплатно. С другом можно играть бесплатно "
            "или поставить одинаковое количество печенек: "
            "победитель забирает удвоенную ставку, при ничьей ставки возвращаются.",
        },
        {
            "title": "Ставки",
            "text": "Ставки доступны с 18 лет, при полном профиле и без открытого стартер-пака или долга. "
            "Ставка списывается у обоих при начале партии.",
        },
    ],
}


def _now(value: float | None = None) -> float:
    return time.time() if value is None else value


def _ms(value: float | None) -> int | None:
    return int(value * 1000) if value is not None else None


def _stamp(now: float) -> str:
    return datetime.fromtimestamp(now, UTC).isoformat()


async def _one(conn, query, params=()):
    row = await (await conn.execute(query, params)).fetchone()
    return dict(row) if row else None


async def _rows(conn, query, params=()):
    return [dict(row) for row in await (await conn.execute(query, params)).fetchall()]


def _cell(x: int, y: int) -> int:
    return y * SIZE + x


def _neighbors(index: int) -> list[int]:
    x, y = index % SIZE, index // SIZE
    result = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx or dy:
                nx, ny = x + dx, y + dy
                if 0 <= nx < SIZE and 0 <= ny < SIZE:
                    result.append(_cell(nx, ny))
    return result


def _ship_cells(x: int, y: int, size: int, horizontal: bool) -> list[int]:
    """Cells of a straight ship; the caller keeps it inside the board."""
    if horizontal:
        return [_cell(x + dx, y) for dx in range(size)]
    return [_cell(x, y + dy) for dy in range(size)]


def _can_place(cells: list[int], occupied: set[int]) -> bool:
    """A ship may not overlap another ship nor touch it, diagonals included."""
    for cell in cells:
        if cell in occupied:
            return False
        if any(neighbour in occupied for neighbour in _neighbors(cell)):
            return False
    return True


def validate_board(board: list[int], fleet: dict) -> bool:
    """Strict classic-fleet check shared by the generator and the tests.

    Confirms the exact composition (one 4-deck, two 3-deck, three 2-deck,
    four single-deck ships), exactly 20 occupied cells, straight unbroken
    hulls and a one-cell gap between every pair of ships (diagonals too).
    """
    if len(board) != SIZE * SIZE:
        return False
    if not isinstance(fleet, dict) or len(fleet) != len(SHIPS):
        return False
    if sorted(int(size) for size in fleet.values()) != sorted(SHIPS):
        return False
    cells_by_ship: dict[int, list[int]] = {}
    for index, value in enumerate(board):
        if value:
            cells_by_ship.setdefault(int(value), []).append(index)
    if set(cells_by_ship) != {int(ship_id) for ship_id in fleet}:
        return False
    for ship_id, size in fleet.items():
        cells = sorted(cells_by_ship.get(int(ship_id), []))
        if len(cells) != int(size):
            return False
        rows = {index // SIZE for index in cells}
        columns = {index % SIZE for index in cells}
        if len(rows) == 1:
            line = [index % SIZE for index in cells]
        elif len(columns) == 1:
            line = [index // SIZE for index in cells]
        else:
            return False
        if line != list(range(line[0], line[0] + len(line))):
            return False
    if sum(len(cells) for cells in cells_by_ship.values()) != sum(SHIPS):
        return False
    ship_ids = list(cells_by_ship)
    for left in range(len(ship_ids)):
        for right in range(left + 1, len(ship_ids)):
            for a in cells_by_ship[ship_ids[left]]:
                for b in cells_by_ship[ship_ids[right]]:
                    if max(abs(a % SIZE - b % SIZE), abs(a // SIZE - b // SIZE)) <= 1:
                        return False
    return True


def _fallback_board() -> tuple[list[int], dict[int, int]]:
    """Deterministic layout on alternate rows, so ships can never touch."""
    layout = [
        (0, 0, True), (0, 2, True), (0, 4, True), (0, 6, True), (0, 8, True),
        (6, 0, True), (4, 2, True), (4, 4, True), (3, 6, True), (3, 8, True),
    ]
    board = [0] * (SIZE * SIZE)
    fleet: dict[int, int] = {}
    for ship_id, (x, y, horizontal) in enumerate(layout, start=1):
        size = SHIPS[ship_id - 1]
        for cell in _ship_cells(x, y, size, horizontal):
            board[cell] = ship_id
        fleet[ship_id] = size
    return board, fleet


def place_board(rng) -> tuple[list[int], dict[int, int]]:
    """Random classic placement: every ship is straight and never touches.

    Ships are placed one by one in random spots; if a ship cannot be placed
    the whole board is regenerated. Bounded retries plus a deterministic
    fallback guarantee the function always terminates with a valid fleet.
    """
    for _ in range(80):
        board = [0] * (SIZE * SIZE)
        fleet: dict[int, int] = {}
        occupied: set[int] = set()
        complete = True
        for ship_id, size in enumerate(SHIPS, start=1):
            placed = False
            for _ in range(240):
                horizontal = rng.random() < 0.5
                if horizontal:
                    x, y = rng.randrange(SIZE - size + 1), rng.randrange(SIZE)
                else:
                    x, y = rng.randrange(SIZE), rng.randrange(SIZE - size + 1)
                cells = _ship_cells(x, y, size, horizontal)
                if not _can_place(cells, occupied):
                    continue
                for cell in cells:
                    board[cell] = ship_id
                occupied.update(cells)
                fleet[ship_id] = size
                placed = True
                break
            if not placed:
                complete = False
                break
        if complete and validate_board(board, fleet):
            return board, fleet
    return _fallback_board()


def _new_player(user) -> dict:
    board, fleet = place_board(secrets.SystemRandom())
    return {
        "id": int(user["user_id"]),
        "name": str(user.get("profile_name") or user.get("telegram_name") or "Игрок")[:80],
        "board": board,
        "fleet": fleet,
        "shots": [0] * (SIZE * SIZE),
        "ready": False,
        "left": False,
    }


def _players(room) -> dict:
    return room["state"]["players"]


def _active(room) -> list[dict]:
    return [p for p in _players(room).values() if not p["left"]]


def _player(room, pid: int):
    players = _players(room)
    if str(pid) in players:
        return players[str(pid)]
    if pid == -1:
        return players.get("bot")
    return None


def _opponent_id(room, uid: int):
    for p in _players(room).values():
        pid = int(p["id"])
        if pid != uid:
            return pid
    return None


def _ship_sunk(shots: list[int], board: list[int], ship_id) -> bool:
    """A ship is sunk only when every one of its own decks has been hit.

    Ship ids may arrive as strings after a JSON round-trip, so coerce them
    before comparing with the integer values stored in the board.
    """
    ship_id = int(ship_id)
    cells = [cell for cell, value in enumerate(board) if value == ship_id]
    return bool(cells) and all(shots[cell] == 2 for cell in cells)


def _all_sunk(shots: list[int], board: list[int]) -> bool:
    cells = [cell for cell, value in enumerate(board) if value]
    return bool(cells) and all(shots[cell] == 2 for cell in cells)


def _log(room, text: str, now: float) -> None:
    room["state"]["timeline"].append({"text": text, "at": _ms(now)})
    room["state"]["timeline"] = room["state"]["timeline"][-100:]


async def _save(conn, room, now: float) -> None:
    await conn.execute(
        "UPDATE mini_sea_rooms SET status=?,deadline=?,state_json=?,updated_at=?,finished_at=? WHERE id=?",
        (
            room["status"],
            room["deadline"],
            json.dumps(room["state"], ensure_ascii=False),
            now,
            room.get("finished_at"),
            room["id"],
        ),
    )


def _normalize_state(state: dict) -> dict:
    """JSON turns integer fleet keys into strings; restore them on load.

    Without this, `_ship_sunk` compares string ids with integer board values
    and treats every ship as sunk, so `ships_left` collapses to zero.
    """
    for player in state.get("players", {}).values():
        fleet = player.get("fleet")
        if isinstance(fleet, dict):
            player["fleet"] = {int(ship_id): int(size) for ship_id, size in fleet.items()}
        if isinstance(player.get("board"), list):
            player["board"] = [int(value) for value in player["board"]]
        if isinstance(player.get("shots"), list):
            player["shots"] = [int(value) for value in player["shots"]]
    return state


async def _load(conn, room_id: str):
    room = await _one(conn, "SELECT * FROM mini_sea_rooms WHERE id=?", (room_id,))
    if room:
        room["state"] = _normalize_state(json.loads(room.pop("state_json")))
    return room


async def _finish(conn, room, winner, now: float, *, cancelled: bool = False) -> None:
    from community_bot.friends_api import inbox_in_connection

    room["status"] = "cancelled" if cancelled else "finished"
    room["finished_at"] = now
    room["state"]["winner"] = winner
    stake = int(room["stake"] or 0)
    for p in _players(room).values():
        uid = int(p["id"])
        if uid < 0:  # bot has no wallet
            continue
        if stake and not cancelled and winner is not None and uid == winner:
            await conn.execute(
                "UPDATE users SET cookies=cookies+?,updated_at=? WHERE user_id=?", (stake * 2, _stamp(now), uid)
            )
            await conn.execute(
                "INSERT INTO transactions(user_id,amount,kind,details,created_at) VALUES (?,?, 'sea_win',?,?)",
                (uid, stake * 2, "room:" + room["id"], _stamp(now)),
            )
        elif stake and (cancelled or winner is None) and (room["state"].get("started_at") or uid == room["host_id"]):
            await conn.execute(
                "UPDATE users SET cookies=cookies+?,updated_at=? WHERE user_id=?", (stake, _stamp(now), uid)
            )
            await conn.execute(
                "INSERT INTO transactions(user_id,amount,kind,details,created_at) VALUES (?,?, 'sea_refund',?,?)",
                (uid, stake, "room:" + room["id"], _stamp(now)),
            )
    title = "Морской бой" + (f" · {room['title']}" if room["title"] else "")
    if cancelled:
        text = "Партия закрыта без результата."
    elif winner is None:
        text = "Ничья: ставки возвращены." if stake else "Ничья: время партии истекло."
    else:
        name = (_player(room, winner) or {}).get("name", "Соперник")
        text = f"Победил {name}." + (f" Забрано {stake * 2} 🍪." if stake else "")
    _log(room, text, now)
    for p in _players(room).values():
        if int(p["id"]) > 0:
            await inbox_in_connection(conn, int(p["id"]), f"{title}. {text}")
    await conn.execute("UPDATE mini_sea_members SET active=0 WHERE room_id=?", (room["id"],))
    await conn.execute(
        "UPDATE mini_sea_invites SET status='expired' WHERE room_id=? AND status='pending'", (room["id"],)
    )


def _set_turn(room, uid, now: float) -> None:
    room["state"]["turn"] = uid
    room["deadline"] = now + MOVE_SECONDS


def _eligible_reason(conn, user) -> str:
    if not user:
        return "Сначала открой личный кабинет Норы"
    if int(user.get("age") or 0) < 18:
        return "Ставки в Морском бою доступны с 18 лет. Без ставки можно играть свободно"
    if int(user.get("cookie_debt") or 0) > 0:
        return "Сначала верни просроченный долг по печенькам"
    return ""


def _apply_shot(attacker: dict, defender_board: list[int], index: int) -> tuple[bool, int | None]:
    ship_id = defender_board[index]
    attacker["shots"][index] = 2 if ship_id else 1
    attacker["last_shot"] = index
    if not ship_id:
        return False, None
    return True, (ship_id if _ship_sunk(attacker["shots"], defender_board, ship_id) else None)


def _sunk_neighbours(shots: list[int], board: list[int], fleet: dict) -> set[int]:
    """Cells around a fully sunk ship are guaranteed empty, so skip them."""
    blocked: set[int] = set()
    for ship_id in fleet:
        if _ship_sunk(shots, board, ship_id):
            blocked.update(
                neighbour
                for cell, value in enumerate(board)
                if value == int(ship_id)
                for neighbour in _neighbors(cell)
            )
    return blocked


def _bot_choice(attacker: dict, defender_board: list[int], defender_fleet: dict, rng) -> int:
    """Hunt/target: finish damaged ships first, otherwise a random free cell."""
    shots = attacker["shots"]
    blocked = _sunk_neighbours(shots, defender_board, defender_fleet or {})
    hits = [index for index, state in enumerate(shots) if state == 2]
    candidates = [
        neighbour
        for index in hits
        for neighbour in _neighbors(index)
        if shots[neighbour] == 0 and neighbour not in blocked
    ]
    if candidates:
        return rng.choice(candidates)
    free = [index for index, state in enumerate(shots) if state == 0 and index not in blocked]
    if not free:
        free = [index for index, state in enumerate(shots) if state == 0]
    return rng.choice(free)


async def _bot_shoot(conn, room, now: float) -> None:
    bot = _player(room, -1)
    victim_id = _opponent_id(room, -1)
    victim = _player(room, victim_id) if victim_id is not None else None
    if victim is None or victim["left"]:
        return
    rng = secrets.SystemRandom()
    index = _bot_choice(bot, victim["board"], victim["fleet"], rng)
    hit, sunk = _apply_shot(bot, victim["board"], index)
    label = f"{index % SIZE + 1}{chr(ord('А') + index // SIZE)}"
    if sunk:
        _log(room, f"Бот стрелял {label}: потопил корабль.", now)
    elif hit:
        _log(room, f"Бот стрелял {label}: попадание.", now)
    else:
        _log(room, f"Бот стрелял {label}: мимо.", now)
    if _all_sunk(bot["shots"], victim["board"]):
        _log(room, "Бот потопил весь флот.", now)
        await _finish(conn, room, -1, now)
    elif hit:
        room["deadline"] = now + BOT_PAUSE
    else:
        _set_turn(room, victim_id, now)


async def _advance(conn, room, now: float) -> None:
    """Persisted deadlines only: a late request can never extend a move."""
    if room["status"] == "lobby":
        if room["deadline"] <= now:
            await _finish(conn, room, None, room["deadline"], cancelled=True)
        return
    if room["status"] != "active":
        return
    state = room["state"]
    for _ in range(300):
        if room["status"] != "active" or room["deadline"] > now:
            break
        at = room["deadline"]
        if at >= state.get("started_at", now) + MAX_GAME_SECONDS:
            await _finish(conn, room, None, at)
            break
        turn = state.get("turn")
        if room["bot"] and turn == -1:
            await _bot_shoot(conn, room, at)
        else:
            player = _player(room, turn)
            if player and not player["left"]:
                _log(room, f"{player['name']} думал слишком долго — ход перешёл.", at)
            other = _opponent_id(room, turn)
            if other is None:
                await _finish(conn, room, None, at)
                break
            _set_turn(room, other, at)
            if room["bot"] and other == -1:
                room["deadline"] = at + BOT_PAUSE


async def tick(db, now: float | None = None) -> int:
    now = _now(now)
    due = await db.fetchall(
        "SELECT id FROM mini_sea_rooms WHERE status IN ('lobby','active') AND deadline<=? ORDER BY deadline LIMIT 100",
        (now,),
    )
    for item in due:
        async with db.connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            room = await _load(conn, item["id"])
            if room:
                await _advance(conn, room, now)
                await _save(conn, room, now)
            await conn.commit()
    return len(due)


async def _charge(conn, uid: int, amount: int, room_id: str, now: float) -> None:
    user = await _one(conn, "SELECT * FROM users WHERE user_id=?", (uid,))
    reason = _eligible_reason(conn, user)
    if reason:
        raise ValueError(reason)
    cursor = await conn.execute(
        "UPDATE users SET cookies=cookies-?,updated_at=? WHERE user_id=? AND cookies>=? AND cookie_debt=0",
        (amount, _stamp(now), uid, amount),
    )
    if cursor.rowcount != 1:
        raise ValueError(f"Не хватает печенек на ставку {amount} 🍪")
    await conn.execute(
        "INSERT INTO transactions(user_id,amount,kind,details,created_at) VALUES (?,?,'sea_bet',?,?)",
        (uid, -amount, "room:" + room_id, _stamp(now)),
    )


async def _new_room(conn, uid: int, body: dict, now: float) -> dict:
    member = await _one(conn, "SELECT room_id FROM mini_sea_members WHERE user_id=? AND active=1", (uid,))
    if member:
        raise Conflict("Ты уже в другой партии. Сначала заверши её или выйди")
    count = await _one(
        conn, "SELECT COUNT(*) AS n FROM mini_sea_rooms WHERE host_id=? AND created_at>?", (uid, now - 600)
    )
    if count["n"] >= 5:
        raise ValueError("Можно создать не больше пяти комнат за 10 минут")
    vs_bot = body.get("vs_bot") is True
    stake = body.get("stake", 0)
    if type(stake) is not int or stake not in STAKE_CHOICES:
        raise ValueError("Ставка — одна из: 0, 5, 10, 25, 50, 100 🍪")
    if vs_bot and stake:
        raise ValueError("С ботом можно играть только бесплатно")
    user = await _one(conn, "SELECT * FROM users WHERE user_id=?", (uid,))
    flag = await _one(conn, "SELECT enabled FROM feature_flags WHERE key='games'")
    if not flag or not flag["enabled"]:
        raise ValueError("Игры временно выключены администрацией")
    title = body.get("title") or ("Схватка с ботом" if vs_bot else "Морской бой")
    if not isinstance(title, str) or not 2 <= len(title.strip()) <= 60:
        raise ValueError("Название партии — от 2 до 60 символов")
    title = title.strip()
    password = body.get("password", "")
    if not isinstance(password, str) or len(password) > 64 or (password and len(password) < 4):
        raise ValueError("Пароль должен содержать от 4 до 64 символов")
    if vs_bot and password:
        raise ValueError("Пароль доступен только для игры с человеком")
    password_record = None
    if password:
        salt = secrets.token_hex(16)
        password_record = {"salt": salt, "hash": hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
        ).hex()}
    room_id = secrets.token_urlsafe(16)
    room = {
        "id": room_id,
        "host_id": uid,
        "title": title,
        "status": "lobby",
        "stake": stake,
        "bot": 1 if vs_bot else 0,
        "deadline": now + LOBBY_SECONDS,
        "created_at": now,
        "finished_at": None,
        "state": {
            "turn": None,
            "started_at": None,
            "players": {str(uid): _new_player(user)},
            "timeline": [],
            "winner": None,
            "password": password_record,
            "public": not vs_bot,
            "kicked": [],
        },
    }
    if vs_bot:
        bot = {
            "id": -1,
            "name": BOT_NAME,
            "board": None,
            "fleet": None,
            "shots": [0] * (SIZE * SIZE),
            "ready": True,
            "left": False,
        }
        room["state"]["players"]["bot"] = bot
    if stake:
        await _charge(conn, uid, stake, room_id, now)
    _log(
        room,
        "Комната открыта. Приглашай друга или начинай." if not vs_bot else "Комната создана. Начинай, когда готов.",
        now,
    )
    await conn.execute(
        "INSERT INTO mini_sea_rooms(id,host_id,title,status,stake,bot,deadline,state_json,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            room_id,
            uid,
            title,
            "lobby",
            stake,
            room["bot"],
            room["deadline"],
            json.dumps(room["state"], ensure_ascii=False),
            now,
            now,
        ),
    )
    await conn.execute("INSERT INTO mini_sea_members(room_id,user_id,joined_at) VALUES(?,?,?)", (room_id, uid, now))
    return room


async def _join_room(conn, room, uid: int, now: float) -> None:
    if room["status"] != "lobby" or room["bot"]:
        raise Conflict("Комната уже закрыта")
    if uid in room["state"].get("kicked", []):
        raise Conflict("Создатель исключил тебя из этой комнаты")
    if len(_active(room)) >= 2:
        raise Conflict("В комнате уже два игрока")
    if await _one(conn, "SELECT room_id FROM mini_sea_members WHERE user_id=? AND active=1", (uid,)):
        raise Conflict("Сначала заверши текущую партию Морского боя")
    host = room["host_id"]
    if await _one(conn, "SELECT 1 FROM mini_friend_blocks WHERE (blocker_id=? AND blocked_id=?) "
                  "OR (blocker_id=? AND blocked_id=?)", (uid, host, host, uid)):
        raise Conflict("Подключиться к этой комнате нельзя")
    user = await _one(conn, "SELECT * FROM users WHERE user_id=?", (uid,))
    # A player who left the lobby must not remain in the room or receive a refund.
    for key, player in list(_players(room).items()):
        if player["left"]:
            del _players(room)[key]
    _players(room)[str(uid)] = _new_player(user)
    await conn.execute(
        "INSERT INTO mini_sea_members(room_id,user_id,joined_at) VALUES(?,?,?) "
        "ON CONFLICT(room_id,user_id) DO UPDATE SET active=1,joined_at=excluded.joined_at",
        (room["id"], uid, now),
    )
    _log(room, f"{_players(room)[str(uid)]['name']} вошёл в комнату.", now)


# Bounded per-process limit supplements the expensive password hash.
_password_attempts: dict[tuple[str, int], list[float]] = {}


def _check_password(room, uid: int, value, now: float) -> None:
    record = room["state"].get("password")
    if not record:
        return
    key = (room["id"], uid)
    if len(_password_attempts) >= 4096 and key not in _password_attempts:
        for expired in [k for k, times in _password_attempts.items() if not any(t > now - 60 for t in times)]:
            del _password_attempts[expired]
        if len(_password_attempts) >= 4096:
            raise ValueError("Слишком много попыток. Попробуй через минуту")
    attempts = [t for t in _password_attempts.get(key, []) if t > now - 60]
    if len(attempts) >= 5:
        raise ValueError("Слишком много попыток. Попробуй через минуту")
    attempts.append(now)
    _password_attempts[key] = attempts
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Неверный пароль")
    digest = hashlib.scrypt(value.encode(), salt=bytes.fromhex(record["salt"]), n=16384, r=8, p=1).hex()
    if not hmac.compare_digest(digest, record["hash"]):
        raise ValueError("Неверный пароль")
    _password_attempts.pop(key, None)


async def public_lobbies(db, uid: int, *, admin: bool = False, now: float | None = None) -> list[dict]:
    now = _now(now)
    await tick(db, now)
    rows = await db.fetchall("SELECT * FROM mini_sea_rooms WHERE status='lobby' AND deadline>? "
                             "ORDER BY created_at DESC LIMIT 200", (now,))
    result = []
    async with db.connect() as conn:
        for row in rows:
            room = dict(row)
            room["state"] = _normalize_state(json.loads(room.pop("state_json")))
            players = _active(room)
            host = _player(room, room["host_id"])
            if not admin and (not room["state"].get("public") or room["bot"] or len(players) >= 2
                              or uid in room["state"].get("kicked", [])):
                continue
            if not admin and await _one(conn, "SELECT 1 FROM mini_friend_blocks WHERE "
                                       "(blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)",
                                       (uid, room["host_id"], room["host_id"], uid)):
                continue
            result.append({"id": room["id"], "title": room["title"], "host_id": room["host_id"],
                           "host_name": host["name"] if host else "Игрок", "stake": room["stake"],
                           "locked": bool(room["state"].get("password")), "players": len(players),
                           "bot": bool(room["bot"]), "public": bool(room["state"].get("public"))})
    return result


async def _respond(conn, db, settings, room, uid: int, body: dict, now: float) -> str:
    from community_bot.access import miniapp_allowed
    from community_bot.friends_api import accepted_in_connection

    invite = await _one(conn, "SELECT * FROM mini_sea_invites WHERE room_id=? AND user_id=?", (room["id"], uid))
    if not invite or invite["status"] != "pending" or room["status"] != "lobby":
        raise Conflict("Приглашение уже закрыто")
    if type(body.get("accept")) is not bool:
        raise ValueError("Выбери принять или отклонить приглашение")
    if not body["accept"]:
        await conn.execute(
            "UPDATE mini_sea_invites SET status='declined' WHERE room_id=? AND user_id=?", (room["id"], uid)
        )
        return "Приглашение отклонено"
    sender = _player(room, invite["sender_id"])
    if not sender or sender["left"] or not await accepted_in_connection(conn, uid, invite["sender_id"]):
        raise Conflict("Приглашение больше не действует. Приглашать могут только друзья из этой партии")
    if not await miniapp_allowed(db, settings, uid):
        raise ValueError("Миниапка пока доступна от роли модератора")
    await _join_room(conn, room, uid, now)
    await conn.execute("UPDATE mini_sea_invites SET status='accepted' WHERE room_id=? AND user_id=?", (room["id"], uid))
    _log(room, f"{_players(room)[str(uid)]['name']} принял приглашение. Создатель может начинать.", now)
    return "Ты в комнате. Создатель партии начнёт бой"


async def _invite(conn, db, settings, room, uid: int, body: dict, now: float) -> dict:
    from community_bot.access import miniapp_allowed
    from community_bot.friends_api import accepted_in_connection, inbox_in_connection

    target = body.get("user_id")
    if type(target) is not int or target <= 0:
        raise ValueError("Выбери друга из списка")
    if room["status"] != "lobby" or room["bot"] or target == uid:
        raise ValueError("Приглашать друзей можно до начала свободной партии")
    if not await accepted_in_connection(conn, uid, target):
        raise ValueError("Сначала добавь этого участника в друзья")
    if not await miniapp_allowed(db, settings, target):
        raise ValueError("У друга пока нет доступа к миниапке")
    if target in room["state"].get("kicked", []):
        raise Conflict("Этот участник исключён из комнаты")
    if len(_active(room)) >= 2:
        raise Conflict("В комнате уже два игрока")
    if str(target) in _players(room) and not _players(room)[str(target)]["left"]:
        raise Conflict("Друг уже в комнате")
    previous = await _one(
        conn, "SELECT status FROM mini_sea_invites WHERE room_id=? AND user_id=?", (room["id"], target)
    )
    if previous:
        raise Conflict("Этому другу приглашение в эту комнату уже отправляли")
    await conn.execute(
        "INSERT INTO mini_sea_invites(room_id,user_id,sender_id,created_at) VALUES(?,?,?,?)",
        (room["id"], target, uid, now),
    )
    text = (
        f"{_players(room)[str(uid)]['name']} зовёт в Морской бой «{room['title']}»"
        + (f" на {room['stake']} 🍪" if room["stake"] else "") + ". "
        "Открой Интерактив → Игры → Морской бой, чтобы принять."
    )
    notice = await inbox_in_connection(conn, target, text)
    await conn.execute(
        "INSERT INTO bot_state(key,value) VALUES(?,?)",
        (f"sea_notice:{notice}", room["id"]),
    )
    return {"id": notice, "uid": target, "text": text, "room_id": room["id"]}


async def _start(conn, db, settings, room, uid: int, now: float) -> str:
    from community_bot.access import miniapp_allowed

    if room["host_id"] != uid or room["status"] != "lobby":
        raise ValueError("Начать может только создатель комнаты")
    players = _active(room)
    if room["bot"]:
        if room["stake"]:
            raise ValueError("Игра с ботом на печеньки недоступна. Закрой комнату, чтобы вернуть ставку")
        if len(players) != 2:
            raise Conflict("Бот уже ждёт в комнате. Начинай, когда готов")
    else:
        if len(players) != 2 or not all(p["ready"] for p in players):
            raise Conflict("Нужно два игрока, и каждый должен подтвердить готовность")
        for p in players:
            if not await miniapp_allowed(db, settings, p["id"]):
                raise Conflict("Один из участников больше не имеет доступа к миниапке. Пусть выйдет из комнаты")
    if room["stake"] and not room["bot"]:
        opponent = next(p for p in players if p["id"] != uid)
        await _charge(conn, opponent["id"], room["stake"], room["id"], now)
    bot = _player(room, -1)
    if bot is not None:
        board, fleet = place_board(secrets.SystemRandom())
        bot["board"], bot["fleet"] = board, fleet
    room["status"] = "active"
    room["state"]["started_at"] = now
    first = uid if secrets.SystemRandom().random() < 0.5 else _opponent_id(room, uid)
    _set_turn(room, first, now)
    if first == -1:
        room["deadline"] = now + BOT_PAUSE
    first_name = (_player(room, first) or {}).get("name", BOT_NAME)
    _log(room, f"Бой начался. Флот расставлен случайно. Первым стреляет {first_name}.", now)
    await conn.execute(
        "UPDATE mini_sea_invites SET status='expired' WHERE room_id=? AND status='pending'", (room["id"],)
    )
    return "Бой начался"


async def _shoot_action(conn, room, uid: int, body: dict, now: float) -> str:
    state = room["state"]
    if room["status"] != "active":
        raise Conflict("Эта партия уже завершена")
    if state.get("turn") != uid:
        raise Conflict("Сейчас ход соперника")
    index = body.get("cell")
    if type(index) is not int or not 0 <= index < SIZE * SIZE:
        raise ValueError("Выбери клетку на поле соперника")
    attacker = _players(room)[str(uid)]
    target_id = _opponent_id(room, uid)
    defender = _player(room, target_id) if target_id is not None else None
    if defender is None or defender["left"]:
        raise Conflict("Соперник покинул партию")
    if attacker["shots"][index]:
        raise ValueError("Здесь уже стреляли, выбери другую клетку")
    hit, sunk = _apply_shot(attacker, defender["board"], index)
    label = f"{index % SIZE + 1}{chr(ord('А') + index // SIZE)}"
    if sunk:
        _log(room, f"{attacker['name']} стрелял {label}: потопил корабль.", now)
    elif hit:
        _log(room, f"{attacker['name']} стрелял {label}: попадание.", now)
    else:
        _log(room, f"{attacker['name']} стрелял {label}: мимо.", now)
    if _all_sunk(attacker["shots"], defender["board"]):
        _log(room, f"Флот {defender['name']} уничтожен.", now)
        await _finish(conn, room, uid, now)
        return "Флот соперника уничтожен — победа!"
    if hit:
        if room["bot"]:
            room["deadline"] = now + MOVE_SECONDS
        else:
            _set_turn(room, uid, now)
        return "Потопил корабль! Стреляй ещё" if sunk else "Попадание! Стреляй ещё раз"
    if room["bot"]:
        room["state"]["turn"] = target_id
        room["deadline"] = now + BOT_PAUSE
    else:
        _set_turn(room, target_id, now)
    return "Мимо. Ход переходит сопернику"


def _view(room, uid: int) -> dict:
    own = _player(room, uid)
    if not own:
        raise ValueError("Эта комната доступна только её участникам")
    finished = room["status"] in ("finished", "cancelled")
    players_out = []
    for _, p in _players(room).items():
        entry = {"id": p["id"], "name": p["name"], "left": p["left"], "ready": p["ready"]}
        if p["id"] == uid:
            enemy_shots = [0] * (SIZE * SIZE)
            enemy_board = [0] * (SIZE * SIZE)
            enemy_fleet: dict = {}
            enemy_last_shot = None
            for other in _players(room).values():
                if other["id"] != p["id"]:
                    enemy_shots = other["shots"]
                    enemy_last_shot = other.get("last_shot")
                    enemy_board = other["board"] or [0] * (SIZE * SIZE)
                    enemy_fleet = other["fleet"] or {}
            own_blocked = _sunk_neighbours(enemy_shots, p["board"], p["fleet"] or {})
            enemy_blocked = _sunk_neighbours(p["shots"], enemy_board, enemy_fleet)
            # Own fleet shows the opponent's hits and misses; own shots reveal
            # only hit/miss/sunk on the hidden enemy fleet.
            entry["board"] = [
                {
                    "ship": bool(p["board"][i]),
                    "hit": enemy_shots[i] == 2,
                    "miss": enemy_shots[i] == 1 or (i in own_blocked and not p["board"][i]),
                    "last": i == enemy_last_shot,
                }
                for i in range(SIZE * SIZE)
            ]
            sunk_ids = {s for s in (p["fleet"] or {}) if _ship_sunk(enemy_shots, p["board"], s)}
            for i, cell in enumerate(entry["board"]):
                cell["sunk"] = bool(p["board"][i] in sunk_ids)
            enemy_sunk_ids = {s for s in enemy_fleet if _ship_sunk(p["shots"], enemy_board, s)}
            entry["shots"] = [
                {
                    "fired": bool(v) or (i in enemy_blocked and not enemy_board[i]),
                    "last": i == p.get("last_shot"),
                    "hit": v == 2,
                    "sunk": bool(v == 2 and enemy_board[i] in enemy_sunk_ids),
                }
                for i, v in enumerate(p["shots"])
            ]
        elif finished:
            board = p["board"] or [0] * (SIZE * SIZE)
            entry["ships"] = [bool(board[i]) for i in range(SIZE * SIZE)]
        players_out.append(entry)
    ships_left = {}
    for _, p in _players(room).items():
        pid = int(p["id"])
        incoming = [0] * (SIZE * SIZE)
        for other in _players(room).values():
            if other["id"] != pid:
                incoming = other["shots"]
        ships_left[pid] = sum(1 for s in (p["fleet"] or {}) if not _ship_sunk(incoming, p["board"], s))
    return {
        "id": room["id"],
        "title": room["title"],
        "status": room["status"],
        "host_id": room["host_id"],
        "stake": room["stake"],
        "bot": bool(room["bot"]),
        "turn": room["state"].get("turn"),
        "deadline": _ms(room["deadline"]),
        "winner": room["state"].get("winner"),
        "started": bool(room["state"].get("started_at")),
        "players": players_out,
        "timeline": room["state"]["timeline"],
        "ships_left": ships_left,
        "inviteable": room["status"] == "lobby" and not room["bot"],
        "locked": bool(room["state"].get("password")),
    }


async def read_status(db, uid: int, now: float | None = None, room_id: str | None = None) -> dict:
    now = _now(now)
    await tick(db, now)
    async with db.connect() as conn:
        await conn.execute("BEGIN")
        if room_id:
            room = await _load(conn, room_id)
            if room is None or _player(room, uid) is None:
                raise ValueError("Комната не найдена")
        else:
            member = await _one(conn, "SELECT room_id FROM mini_sea_members WHERE user_id=? AND active=1", (uid,))
            room = await _load(conn, member["room_id"]) if member else None
        invites = await _rows(
            conn,
            "SELECT i.room_id,r.title,r.stake,i.sender_id,r.state_json FROM mini_sea_invites i "
            "JOIN mini_sea_rooms r ON r.id=i.room_id WHERE i.user_id=? AND i.status='pending' "
            "AND r.status='lobby' AND r.deadline>? ORDER BY i.created_at DESC LIMIT 30",
            (uid, now),
        )
        from community_bot.friends_api import accepted_in_connection

        clean_invites = []
        for invite in invites:
            if not await accepted_in_connection(conn, uid, invite["sender_id"]):
                continue
            sender = json.loads(invite["state_json"])["players"].get(str(invite["sender_id"]))
            if sender and not sender["left"]:
                clean_invites.append(
                    {
                        "room_id": invite["room_id"],
                        "title": invite["title"],
                        "stake": invite["stake"],
                        "sender_name": sender["name"],
                    }
                )
        recent = await _rows(
            conn,
            "SELECT r.id,r.title,r.status,r.stake,r.finished_at,r.state_json FROM mini_sea_rooms r "
            "JOIN mini_sea_members m ON m.room_id=r.id WHERE m.user_id=? "
            "AND r.status IN ('finished','cancelled') ORDER BY r.finished_at DESC LIMIT 8",
            (uid,),
        )
        for item in recent:
            item["winner"] = json.loads(item.pop("state_json")).get("winner")
            item["finished_at"] = _ms(item["finished_at"])
        user = await _one(conn, "SELECT cookies FROM users WHERE user_id=?", (uid,))
        enabled = await _one(conn, "SELECT enabled FROM feature_flags WHERE key='games'")
        return {
            "server_now": _ms(now),
            "enabled": bool(enabled and enabled["enabled"]),
            "rules": RULES,
            "balance": user["cookies"] if user else 0,
            "room": _view(room, uid) if room else None,
            "invites": clean_invites,
            "recent": recent,
        }


async def apply_action(db, settings, uid: int, body, now: float | None = None):
    """Returns (focus room, user message, optional notice)."""
    now = _now(now)
    if not isinstance(body, dict):
        raise ValueError("Некорректное действие")
    action_name = body.get("action")
    if action_name not in {
        "create", "invite", "respond", "join", "kick", "admin_close", "ready", "start", "leave", "cancel", "shoot",
    }:
        raise ValueError("Обнови экран и повтори действие")
    notice = None
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        from community_bot.access import miniapp_allowed

        if not await miniapp_allowed(db, settings, uid):
            raise ValueError("Миниапка пока доступна от роли модератора")
        if not await _one(conn, "SELECT user_id FROM users WHERE user_id=?", (uid,)):
            raise ValueError("Сначала открой личный кабинет Норы")
        if action_name in {"create", "start"}:
            flag = await _one(conn, "SELECT enabled FROM feature_flags WHERE key='games'")
            if not flag or not flag["enabled"]:
                raise ValueError("Игры временно выключены администрацией")
        if action_name == "create":
            room = await _new_room(conn, uid, body, now)
            message = "Комната создана. Приглашай друга" if not room["bot"] else "Комната создана. Начинай, когда готов"
            focus = room["id"]
        else:
            room_id = body.get("room_id")
            if not isinstance(room_id, str) or not 10 <= len(room_id) <= 64:
                raise ValueError("Комната не найдена")
            room = await _load(conn, room_id)
            if room is None:
                raise ValueError("Комната не найдена")
            await _advance(conn, room, now)
            focus = room_id
            if action_name == "respond":
                message = await _respond(conn, db, settings, room, uid, body, now)
                if not body.get("accept"):
                    focus = None
            elif action_name == "join":
                if not room["state"].get("public"):
                    raise Conflict("Комната доступна только по приглашению")
                _check_password(room, uid, body.get("password", ""), now)
                await _join_room(conn, room, uid, now)
                message = "Ты в комнате. Подтверди готовность"
            elif action_name == "admin_close":
                from community_bot.helpers import has_permission
                from community_bot.permissions import PERM_GAMES

                if not await has_permission(db, settings, uid, PERM_GAMES):
                    raise ValueError("Нет прав администратора")
                if room["status"] != "lobby":
                    raise Conflict("Можно закрыть только лобби")
                await _finish(conn, room, None, now, cancelled=True)
                focus = None
                message = "Комната закрыта"
            else:
                own = _player(room, uid)
                if not own or own["left"]:
                    raise ValueError("Ты не участник этой партии")
                if action_name == "invite":
                    notice = await _invite(conn, db, settings, room, uid, body, now)
                    message = "Приглашение отправлено"
                elif action_name == "kick":
                    target = body.get("user_id")
                    if room["host_id"] != uid or room["status"] != "lobby" or room["bot"]:
                        raise ValueError("Исключать игроков может создатель лобби")
                    if type(target) is not int or target == uid or target <= 0:
                        raise ValueError("Выбери участника")
                    kicked = _player(room, target)
                    if not kicked or kicked["left"]:
                        raise Conflict("Участник уже покинул комнату")
                    del _players(room)[str(target)]
                    room["state"].setdefault("kicked", []).append(target)
                    await conn.execute(
                        "UPDATE mini_sea_members SET active=0 WHERE room_id=? AND user_id=?", (room["id"], target)
                    )
                    await conn.execute(
                        "UPDATE mini_sea_invites SET status='expired' WHERE room_id=? AND user_id=?",
                        (room["id"], target),
                    )
                    _log(room, f"{kicked['name']} исключён из комнаты.", now)
                    message = "Участник исключён"
                elif action_name == "ready":
                    if room["status"] != "lobby":
                        raise ValueError("Готовность меняется до начала партии")
                    own["ready"] = body.get("ready") is True
                    message = "Ты готов к бою" if own["ready"] else "Готовность снята"
                elif action_name == "start":
                    message = await _start(conn, db, settings, room, uid, now)
                elif action_name == "cancel":
                    if room["host_id"] != uid or room["status"] != "lobby":
                        raise ValueError("Закрыть лобби может только его создатель")
                    await _finish(conn, room, None, now, cancelled=True)
                    focus = None
                    message = "Ты вышел, комната закрыта" + (", ставка возвращена" if room["stake"] else "")
                elif action_name == "leave":
                    own["left"] = True
                    await conn.execute(
                        "UPDATE mini_sea_members SET active=0 WHERE room_id=? AND user_id=?", (room["id"], uid)
                    )
                    if room["status"] == "lobby":
                        if room["host_id"] == uid:
                            await _finish(conn, room, None, now, cancelled=True)
                            focus = None
                            message = "Ты вышел, комната закрыта" + (", ставка возвращена" if room["stake"] else "")
                        else:
                            del _players(room)[str(uid)]
                            message = "Ты вышел из комнаты"
                    else:
                        winner = _opponent_id(room, uid)
                        await _finish(conn, room, winner, now)
                        focus = None
                        message = "Ты вышел из партии — победа засчитана сопернику"
                elif action_name == "shoot":
                    message = await _shoot_action(conn, room, uid, body, now)
        await _save(conn, room, now)
        await conn.commit()
    return focus, message, notice


async def status(request):
    from community_bot.miniapp import actor

    user = await actor(request)
    return web.json_response(
        await read_status(request.app["db"], user["user_id"], room_id=request.query.get("room_id"))
    )


async def action(request):
    from community_bot.miniapp import actor

    user = await actor(request)
    db, uid = request.app["db"], user["user_id"]
    try:
        focus, message, notice = await apply_action(db, request.app["settings"], uid, await request.json())
    except Conflict as error:
        return web.json_response({"error": str(error)}, status=409)
    if notice:
        from community_bot.friends_api import deliver_notice
        from community_bot.sea_notifications import invitation_keyboard

        await deliver_notice(
            request.app.get("bot"), db, notice["id"], notice["uid"], notice["text"],
            reply_markup=invitation_keyboard(notice["room_id"]), force=True,
        )
    result = await read_status(db, uid, room_id=focus)
    return web.json_response({**result, "message": message})
