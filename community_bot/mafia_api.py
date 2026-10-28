"""Private, free Mini App Mafia. SQLite owns roles, clocks and every transition."""

from __future__ import annotations

import hashlib
import html
import json
import re
import secrets
import time
from collections import Counter
from datetime import UTC, datetime

from aiohttp import web

SCHEMA = """
CREATE TABLE IF NOT EXISTS mini_mafia_rooms (
    id TEXT PRIMARY KEY, host_id INTEGER NOT NULL REFERENCES users(user_id),
    title TEXT NOT NULL, status TEXT NOT NULL, phase TEXT NOT NULL,
    deadline REAL NOT NULL, state_json TEXT NOT NULL,
    created_at REAL NOT NULL, updated_at REAL NOT NULL, finished_at REAL
);
CREATE INDEX IF NOT EXISTS mini_mafia_due ON mini_mafia_rooms(status,deadline);
CREATE TABLE IF NOT EXISTS mini_mafia_members (
    room_id TEXT NOT NULL REFERENCES mini_mafia_rooms(id),
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    active INTEGER NOT NULL DEFAULT 1, joined_at REAL NOT NULL,
    PRIMARY KEY(room_id,user_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS mini_mafia_one_room ON mini_mafia_members(user_id) WHERE active=1;
CREATE TABLE IF NOT EXISTS mini_mafia_invites (
    room_id TEXT NOT NULL REFERENCES mini_mafia_rooms(id),
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    sender_id INTEGER NOT NULL REFERENCES users(user_id),
    status TEXT NOT NULL DEFAULT 'pending', created_at REAL NOT NULL,
    PRIMARY KEY(room_id,user_id)
);
CREATE INDEX IF NOT EXISTS mini_mafia_invitations ON mini_mafia_invites(user_id,status);
CREATE TABLE IF NOT EXISTS mini_mafia_requests (
    user_id INTEGER NOT NULL REFERENCES users(user_id), request_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL, room_id TEXT, message TEXT NOT NULL, created_at REAL NOT NULL,
    PRIMARY KEY(user_id,request_id)
);
"""

TIMINGS = {"night": 60, "discussion": 90, "vote": 45}
LOBBY_SECONDS = 3600
MAX_GAME_SECONDS = 7200
ROLE_INFO = [
    {"id": "civilian", "name": "Мирный житель", "description": "Слушай, замечай противоречия и ищи мафию на суде."},
    {"id": "mafia", "name": "Мафия", "description": "Ночью обсуждайте цель в тайном чате и выбирайте жертву."},
    {
        "id": "detective",
        "name": "Комиссар",
        "description": "Каждую ночь проверяй одного другого игрока. Ответ видишь только ты.",
    },
    {"id": "doctor", "name": "Доктор", "description": "Защищай одного игрока за ночь. Себя — один раз за партию."},
]
RULES = {
    "min_players": 5,
    "max_players": 12,
    "timings": TIMINGS,
    "roles": ROLE_INFO,
    "sections": [
        {
            "title": "Бесплатно и вместе",
            "text": "5–12 человек. Ставок и наград в печеньках нет. "
            "Создатель приглашает друзей, все отмечают готовность. Роли раздаются случайно, хозяин их не выбирает.",
        },
        {
            "title": "Состав города",
            "text": "5 игроков: мафия, комиссар и 3 мирных. С 6 добавляется доктор, "
            "с 8 игроков — вторая мафия, с 11 — третья. Остальные — мирные жители.",
        },
        {
            "title": "Ночь · 60 секунд",
            "text": "Мафия голосует за жертву: равенство голосов означает отсутствие убийства. "
            "Доктор защищает выбранного игрока; нельзя лечить одного человека две ночи подряд, себя — только раз. "
            "Комиссар получает личный ответ, принадлежит ли проверенный мафии. Выбор можно менять до конца ночи.",
        },
        {
            "title": "День и суд",
            "text": "90 секунд обсуждения, затем 45 секунд голосования. Можно пропустить. "
            "На суде выбывает единственный лидер голосования; равенство или победа пропуска — без казни. "
            "Пропущенный ход считается воздержанием. Голоса можно менять до конца суда.",
        },
        {
            "title": "Тайна и общение",
            "text": "Роли открываются всем только в финале. Мафия знает свою команду. "
            "Ночью живые общаются только в тайном чате мафии; днём — в общем. "
            "Выбывшие могут писать в отдельный чат призраков, который живые не видят.",
        },
        {
            "title": "Победа",
            "text": "Город побеждает, когда мафии не осталось. Мафия — когда её не меньше, чем мирных. "
            "Выход из начавшейся партии означает сдачу. Комнаты без старта закрываются через час, "
            "партии без финала через 2 часа завершаются ничьей.",
        },
        {
            "title": "Если закрыл приложение",
            "text": "Таймеры продолжаются на сервере. Вернись в игру, чтобы продолжить. "
            "Пропущенные ночные действия не выбираются за тебя. При перезапуске Норы партия восстанавливается.",
        },
    ],
}


class Conflict(ValueError):
    """An expired screen or conflicting membership must be refreshed."""


def _ms(value):
    return int(value * 1000) if value is not None else None


def _id(value):
    if type(value) is not int or value <= 0:
        raise ValueError("Выбери участника из списка")
    return value


def _stamp(now):
    return datetime.fromtimestamp(now, UTC).isoformat()


async def _one(conn, query, params=()):
    row = await (await conn.execute(query, params)).fetchone()
    return dict(row) if row else None


async def _rows(conn, query, params=()):
    return [dict(row) for row in await (await conn.execute(query, params)).fetchall()]


async def _load(conn, room_id):
    room = await _one(conn, "SELECT * FROM mini_mafia_rooms WHERE id=?", (room_id,))
    if room:
        room["state"] = json.loads(room.pop("state_json"))
    return room


async def _save(conn, room, now):
    await conn.execute(
        "UPDATE mini_mafia_rooms SET host_id=?,status=?,phase=?,deadline=?,state_json=?,updated_at=?,finished_at=? "
        "WHERE id=?",
        (
            room["host_id"],
            room["status"],
            room["phase"],
            room["deadline"],
            json.dumps(room["state"], ensure_ascii=False),
            now,
            room.get("finished_at"),
            room["id"],
        ),
    )


def _log(room, text, now):
    room["state"]["timeline"].append({"text": text, "at": _ms(now)})
    room["state"]["timeline"] = room["state"]["timeline"][-150:]


def _players(room):
    return room["state"]["players"]


def _alive(room):
    return [p for p in _players(room).values() if p["alive"] and not p["left"]]


def _phase(room, phase, now):
    room["phase"] = phase
    room["state"]["phase_token"] = secrets.token_urlsafe(18)
    room["deadline"] = now + TIMINGS.get(phase, 0)
    if phase in TIMINGS and room["status"] == "active":
        room["deadline"] = min(room["deadline"], room["state"]["started_at"] + MAX_GAME_SECONDS)
    room["state"]["actions"] = {}
    room["state"]["votes"] = {}


async def _finish(conn, room, winner, now, cancelled=False):
    from community_bot.friends_api import inbox_in_connection

    room["status"] = "cancelled" if cancelled else "finished"
    room["finished_at"] = now
    room["state"]["winner"] = winner
    _phase(room, "finished", now)
    text = {
        "town": "Город победил: вся мафия найдена.",
        "mafia": "Мафия победила: город под её контролем.",
        "draw": "Ничья: время партии истекло.",
        None: "Комната закрыта.",
    }[winner]
    _log(room, text, now)
    await conn.execute("UPDATE mini_mafia_members SET active=0 WHERE room_id=?", (room["id"],))
    await conn.execute(
        "UPDATE mini_mafia_invites SET status='expired' WHERE room_id=? AND status='pending'", (room["id"],)
    )
    if not cancelled:
        for uid in _players(room):
            await inbox_in_connection(conn, int(uid), f"Мафия · {html.escape(room['title'])}. {text}")


async def _check_win(conn, room, now):
    alive = _alive(room)
    mafias = sum(p["role"] == "mafia" for p in alive)
    if not mafias:
        await _finish(conn, room, "town", now)
        return True
    if mafias >= len(alive) - mafias:
        await _finish(conn, room, "mafia", now)
        return True
    return False


def _unique_leader(values):
    counts = Counter(values)
    if not counts:
        return None
    ranked = counts.most_common()
    return ranked[0][0] if len(ranked) == 1 or ranked[0][1] > ranked[1][1] else None


async def _advance(conn, room, now):
    """Use persisted deadlines, not request arrival time, so polling cannot extend a phase."""
    if room["status"] == "lobby":
        if room["deadline"] <= now:
            await _finish(conn, room, None, room["deadline"], cancelled=True)
        return
    if room["status"] != "active":
        return
    state = room["state"]
    # At most 114 timed phases fit in 2 h. A bounded catch-up finishes even after a long restart.
    for _ in range(128):
        if room["status"] != "active" or room["deadline"] > now:
            break
        at = room["deadline"]
        if at >= state["started_at"] + MAX_GAME_SECONDS:
            await _finish(conn, room, "draw", at)
            break
        alive = _alive(room)
        alive_ids = {p["id"] for p in alive}
        actions = state["actions"]
        if room["phase"] == "night":
            targets = [
                actions[str(p["id"])]
                for p in alive
                if p["role"] == "mafia" and str(p["id"]) in actions and actions[str(p["id"])] in alive_ids
            ]
            victim = _unique_leader(targets)
            healed = set()
            for p in alive:
                target = actions.get(str(p["id"]))
                if target not in alive_ids:
                    if p["role"] == "doctor":
                        p["last_heal"] = None
                    continue
                if p["role"] == "doctor":
                    healed.add(target)
                    p["last_heal"] = target
                    if target == p["id"]:
                        p["self_healed"] = True
                elif p["role"] == "detective":
                    checked = _players(room)[str(target)]
                    p["investigations"].append(
                        {
                            "round": state["round"],
                            "target_id": target,
                            "name": checked["name"],
                            "mafia": checked["role"] == "mafia",
                        }
                    )
            # Not healing on an intervening night breaks the consecutive-target restriction.
            for p in alive:
                if p["role"] == "doctor" and str(p["id"]) not in actions:
                    p["last_heal"] = None
            if victim is not None and victim not in healed:
                _players(room)[str(victim)]["alive"] = False
                _log(room, f"Утро {state['round']}: не проснулся игрок {_players(room)[str(victim)]['name']}.", at)
            else:
                _log(room, f"Утро {state['round']}: все пережили ночь.", at)
            if not await _check_win(conn, room, at):
                _phase(room, "discussion", at)
                _log(room, "Город обсуждает подозрения. Общий чат открыт.", at)
        elif room["phase"] == "discussion":
            _phase(room, "vote", at)
            _log(room, "Суд: выбери подозреваемого или воздержись.", at)
        elif room["phase"] == "vote":
            ballots = [
                target
                for voter, target in state["votes"].items()
                if int(voter) in alive_ids and (target is None or target in alive_ids)
            ]
            target = _unique_leader(ballots)
            counts = Counter(ballots)
            tally = "; ".join(
                f"{_players(room)[str(uid)]['name'] if uid is not None else 'пропуск'}: {count}"
                for uid, count in counts.items()
            )
            if target is not None:
                _players(room)[str(target)]["alive"] = False
                _log(room, f"Суд: {_players(room)[str(target)]['name']} покидает город. Голоса: {tally}.", at)
            else:
                _log(room, "Суд: никто не изгнан." + (f" Голоса: {tally}." if tally else " Все воздержались."), at)
            if not await _check_win(conn, room, at):
                state["round"] += 1
                _phase(room, "night", at)
                _log(room, f"Ночь {state['round']}. Город засыпает.", at)


async def tick(db, now=None):
    now = time.time() if now is None else now
    # Single worker and write transactions also make simultaneous API/background ticks harmless.
    due = await db.fetchall(
        "SELECT id FROM mini_mafia_rooms WHERE status IN ('lobby','active') AND deadline<=? "
        "ORDER BY deadline LIMIT 100",
        (now,),
    )
    for item in due:
        async with db.connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            room = await _load(conn, item["id"])
            await _advance(conn, room, now)
            await _save(conn, room, now)
            await conn.commit()


def _targets(room, own):
    if room["status"] != "active" or not own["alive"] or own["left"]:
        return []
    alive = _alive(room)
    if room["phase"] == "vote":
        return [p["id"] for p in alive if p["id"] != own["id"]]
    if room["phase"] != "night":
        return []
    if own["role"] == "mafia":
        return [p["id"] for p in alive if p["role"] != "mafia"]
    if own["role"] == "detective":
        return [p["id"] for p in alive if p["id"] != own["id"]]
    if own["role"] == "doctor":
        return [
            p["id"]
            for p in alive
            if p["id"] != own.get("last_heal") and (p["id"] != own["id"] or not own.get("self_healed"))
        ]
    return []


def _view(room, uid):
    own = _players(room).get(str(uid))
    if not own:
        raise ValueError("Эта комната доступна только её участникам")
    finished = room["status"] == "finished"
    state = room["state"]
    visible = {"public"}
    if own["role"] == "mafia" or finished:
        visible.add("mafia")
    if not own["alive"] or own["left"] or finished:
        visible.add("ghost")
    public_players = []
    for p in _players(room).values():
        role_visible = finished or p["id"] == uid or (own["role"] == "mafia" and p["role"] == "mafia")
        public_players.append({k: p[k] for k in ("id", "name", "ready", "alive", "left")})
        public_players[-1].update(
            role=p["role"] if role_visible else None,
            voted=str(p["id"]) in state["votes"] if room["phase"] == "vote" else False,
        )
    return {
        "id": room["id"],
        "title": room["title"],
        "status": room["status"],
        "host_id": room["host_id"],
        "phase": room["phase"],
        "phase_token": state["phase_token"],
        "round": state["round"],
        "deadline": _ms(room["deadline"]),
        "winner": state.get("winner"),
        "players": public_players,
        "timeline": state["timeline"],
        "self": {
            **{k: own[k] for k in ("id", "role", "alive", "ready", "left", "investigations")},
            "night_target": state["actions"].get(str(uid)),
            "vote_target": state["votes"].get(str(uid)),
            "voted": str(uid) in state["votes"],
        },
        "messages": [m for m in state["messages"] if m["channel"] in visible][-150:],
        "available_targets": _targets(room, own),
        "inviteable": room["status"] == "lobby" and not own["left"],
    }


async def read_status(db, uid, now=None, room_id=None):
    now = time.time() if now is None else now
    await tick(db, now)
    async with db.connect() as conn:
        await conn.execute("BEGIN")
        if room_id:
            room = await _load(conn, room_id)
            if room is None or str(uid) not in _players(room):
                raise ValueError("Комната не найдена")
        else:
            member = await _one(conn, "SELECT room_id FROM mini_mafia_members WHERE user_id=? AND active=1", (uid,))
            room = await _load(conn, member["room_id"]) if member else None
        invites = await _rows(
            conn,
            "SELECT i.room_id,r.title,i.sender_id,r.state_json FROM mini_mafia_invites i "
            "JOIN mini_mafia_rooms r ON r.id=i.room_id WHERE i.user_id=? AND i.status='pending' "
            "AND r.status='lobby' AND r.deadline>? ORDER BY i.created_at DESC LIMIT 30",
            (uid, now),
        )
        from community_bot.friends_api import accepted_in_connection

        clean_invites = []
        for invite in invites:
            if not await accepted_in_connection(conn, uid, invite["sender_id"]):
                continue
            state = json.loads(invite["state_json"])
            sender = state["players"].get(str(invite["sender_id"]))
            if sender and not sender["left"]:
                clean_invites.append(
                    {
                        "room_id": invite["room_id"],
                        "title": invite["title"],
                        "sender_name": sender["name"],
                        "players_count": sum(not p["left"] for p in state["players"].values()),
                    }
                )
        recent = await _rows(
            conn,
            "SELECT r.id,r.title,r.status,r.finished_at,r.state_json FROM mini_mafia_rooms r "
            "JOIN mini_mafia_members m ON m.room_id=r.id WHERE m.user_id=? "
            "AND r.status IN ('finished','cancelled') ORDER BY r.finished_at DESC LIMIT 8",
            (uid,),
        )
        for item in recent:
            item["winner"] = json.loads(item.pop("state_json")).get("winner")
            item["finished_at"] = _ms(item["finished_at"])
        enabled = await _one(conn, "SELECT enabled FROM feature_flags WHERE key='games'")
        return {
            "server_now": _ms(now),
            "enabled": bool(enabled and enabled["enabled"]),
            "rules": RULES,
            "room": _view(room, uid) if room else None,
            "invites": clean_invites,
            "recent": recent,
        }


def _new_player(user):
    return {
        "id": int(user["user_id"]),
        "name": str(user.get("profile_name") or user.get("telegram_name") or "Игрок")[:80],
        "role": None,
        "ready": False,
        "alive": True,
        "left": False,
        "investigations": [],
        "last_heal": None,
        "self_healed": False,
    }


async def _new_room(conn, uid, body, now):
    member = await _one(conn, "SELECT room_id FROM mini_mafia_members WHERE user_id=? AND active=1", (uid,))
    if member:
        raise Conflict("Ты уже участвуешь в комнате. Вернись в неё или сначала выйди")
    count = await _one(
        conn, "SELECT COUNT(*) AS n FROM mini_mafia_rooms WHERE host_id=? AND created_at>?", (uid, now - 600)
    )
    if count["n"] >= 3:
        raise ValueError("Можно создать не больше трёх комнат за 10 минут")
    count = await _one(conn, "SELECT COUNT(*) AS n FROM mini_mafia_rooms WHERE status IN ('lobby','active')")
    if count["n"] >= 100:
        raise ValueError("Сейчас слишком много комнат. Попробуй чуть позже")
    title = body.get("title", "Ночная Нора")
    if not isinstance(title, str) or not 2 <= len(title.strip()) <= 60:
        raise ValueError("Название комнаты — от 2 до 60 символов")
    title = title.strip()
    user = await _one(conn, "SELECT user_id,profile_name,telegram_name FROM users WHERE user_id=?", (uid,))
    room = {
        "id": secrets.token_urlsafe(16),
        "host_id": uid,
        "title": title,
        "status": "lobby",
        "phase": "lobby",
        "deadline": now + LOBBY_SECONDS,
        "created_at": now,
        "finished_at": None,
        "state": {
            "round": 0,
            "phase_token": secrets.token_urlsafe(18),
            "players": {str(uid): _new_player(user)},
            "actions": {},
            "votes": {},
            "messages": [],
            "timeline": [],
            "winner": None,
        },
    }
    _log(room, "Комната открыта. Приглашай друзей: нужно 5–12 игроков.", now)
    await conn.execute(
        "INSERT INTO mini_mafia_rooms(id,host_id,title,status,phase,deadline,state_json,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (
            room["id"],
            uid,
            title,
            "lobby",
            "lobby",
            room["deadline"],
            json.dumps(room["state"], ensure_ascii=False),
            now,
            now,
        ),
    )
    await conn.execute(
        "INSERT INTO mini_mafia_members(room_id,user_id,joined_at) VALUES(?,?,?)", (room["id"], uid, now)
    )
    return room


async def _respond(conn, db, settings, room, uid, body, now):
    from community_bot.access import miniapp_allowed
    from community_bot.friends_api import accepted_in_connection

    invite = await _one(conn, "SELECT * FROM mini_mafia_invites WHERE room_id=? AND user_id=?", (room["id"], uid))
    if not invite or invite["status"] != "pending" or room["status"] != "lobby":
        raise Conflict("Приглашение уже закрыто")
    if type(body.get("accept")) is not bool:
        raise ValueError("Выбери принять или отклонить приглашение")
    if not body["accept"]:
        await conn.execute(
            "UPDATE mini_mafia_invites SET status='declined' WHERE room_id=? AND user_id=?", (room["id"], uid)
        )
        return "Приглашение отклонено"
    sender = _players(room).get(str(invite["sender_id"]))
    if not sender or sender["left"] or not await accepted_in_connection(conn, uid, invite["sender_id"]):
        raise Conflict("Приглашение больше не действует. Приглашать могут только друзья из этой комнаты")
    if not await miniapp_allowed(db, settings, uid):
        raise ValueError("Миниапка пока доступна от роли модератора")
    member = await _one(conn, "SELECT room_id FROM mini_mafia_members WHERE user_id=? AND active=1", (uid,))
    if member:
        raise Conflict("Сначала выйди из текущей комнаты")
    if len(_alive(room)) >= 12:
        raise Conflict("В комнате уже 12 игроков")
    user = await _one(conn, "SELECT user_id,profile_name,telegram_name FROM users WHERE user_id=?", (uid,))
    _players(room)[str(uid)] = _new_player(user)
    for p in _players(room).values():
        p["ready"] = False
    room["state"]["phase_token"] = secrets.token_urlsafe(18)
    await conn.execute(
        "INSERT INTO mini_mafia_members(room_id,user_id,joined_at) VALUES(?,?,?) "
        "ON CONFLICT(room_id,user_id) DO UPDATE SET active=1,joined_at=excluded.joined_at",
        (room["id"], uid, now),
    )
    await conn.execute(
        "UPDATE mini_mafia_invites SET status='accepted' WHERE room_id=? AND user_id=?", (room["id"], uid)
    )
    _log(room, f"{_players(room)[str(uid)]['name']} присоединился. Подтвердите готовность новым составом.", now)
    return "Ты в комнате. Отметь готовность, когда будешь готов начать"


async def _invite(conn, db, settings, room, uid, body, now):
    from community_bot.access import miniapp_allowed
    from community_bot.friends_api import accepted_in_connection, inbox_in_connection

    target = _id(body.get("user_id"))
    if room["status"] != "lobby" or target == uid:
        raise ValueError("Приглашения доступны в комнате до начала игры")
    if not await accepted_in_connection(conn, uid, target):
        raise ValueError("Сначала добавь этого участника в друзья")
    if not await miniapp_allowed(db, settings, target):
        raise ValueError("У друга пока нет доступа к миниапке")
    if str(target) in _players(room) and not _players(room)[str(target)]["left"]:
        raise Conflict("Друг уже в комнате")
    previous = await _one(
        conn, "SELECT status FROM mini_mafia_invites WHERE room_id=? AND user_id=?", (room["id"], target)
    )
    if previous:
        raise Conflict("Этому другу приглашение в данную комнату уже отправляли")
    count = await _one(conn, "SELECT COUNT(*) AS n FROM mini_mafia_invites WHERE room_id=?", (room["id"],))
    if count["n"] >= 50:
        raise ValueError("Лимит приглашений этой комнаты достигнут")
    await conn.execute(
        "INSERT INTO mini_mafia_invites(room_id,user_id,sender_id,created_at) VALUES(?,?,?,?)",
        (room["id"], target, uid, now),
    )
    text = (
        f"{html.escape(_players(room)[str(uid)]['name'])} зовёт в бесплатную Мафию «{html.escape(room['title'])}». "
        "Открой Интерактив → Игры → Мафия, чтобы принять приглашение."
    )
    notice = await inbox_in_connection(conn, target, text)
    return {"id": notice, "uid": target, "text": text}


async def _start(conn, db, settings, room, uid, now):
    from community_bot.access import miniapp_allowed

    if room["host_id"] != uid or room["status"] != "lobby":
        raise ValueError("Начать может только создатель комнаты")
    players = _alive(room)
    if not 5 <= len(players) <= 12 or not all(p["ready"] for p in players):
        raise Conflict("Нужно 5–12 игроков, и каждый должен подтвердить готовность")
    for p in players:
        if not await miniapp_allowed(db, settings, p["id"]):
            raise Conflict("Один из участников больше не имеет доступа к миниапке. Пусть выйдет из комнаты")
    mafias = 1 if len(players) < 8 else 2 if len(players) < 11 else 3
    roles = ["mafia"] * mafias + ["detective"] + (["doctor"] if len(players) >= 6 else [])
    roles += ["civilian"] * (len(players) - len(roles))
    secrets.SystemRandom().shuffle(roles)
    for p, role in zip(players, roles, strict=True):
        p["role"] = role
    room["status"] = "active"
    room["state"]["started_at"] = now
    room["state"]["round"] = 1
    _phase(room, "night", now)
    _log(room, "Партия началась. Роли распределены случайно. Ночь 1.", now)
    await conn.execute(
        "UPDATE mini_mafia_invites SET status='expired' WHERE room_id=? AND status='pending'", (room["id"],)
    )


async def _leave(conn, room, own, now):
    own["left"] = True
    own["alive"] = False
    own["ready"] = False
    await conn.execute("UPDATE mini_mafia_members SET active=0 WHERE room_id=? AND user_id=?", (room["id"], own["id"]))
    await conn.execute(
        "UPDATE mini_mafia_invites SET status='revoked' WHERE room_id=? AND sender_id=? AND status='pending'",
        (room["id"], own["id"]),
    )
    _log(room, f"{own['name']} вышел из комнаты" + (" и сдался." if room["status"] == "active" else "."), now)
    present = [p for p in _players(room).values() if not p["left"]]
    if not present:
        await _finish(
            conn, room, "draw" if room["status"] == "active" else None, now, cancelled=room["status"] == "lobby"
        )
    elif room["status"] == "active":
        await _check_win(conn, room, now)
    else:
        for p in present:
            p["ready"] = False
        room["state"]["phase_token"] = secrets.token_urlsafe(18)
    if present and room["host_id"] == own["id"]:
        room["host_id"] = present[0]["id"]
        _log(room, f"Новый хозяин комнаты — {present[0]['name']}.", now)


def _chat(room, own, body, now):
    channel = body.get("channel", "public")
    text = body.get("text")
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 600:
        raise ValueError("Сообщение — от 1 до 600 символов")
    text = text.strip()
    if own["left"] or room["status"] not in {"lobby", "active"}:
        raise ValueError("Чат этой комнаты закрыт")
    allowed = (
        channel == "public"
        and own["alive"]
        and room["phase"] in {"lobby", "discussion", "vote"}
        or channel == "mafia"
        and own["alive"]
        and own["role"] == "mafia"
        and room["phase"] == "night"
        or channel == "ghost"
        and not own["alive"]
        and room["status"] == "active"
    )
    if not allowed:
        raise ValueError("Сейчас этот чат тебе недоступен")
    messages = room["state"]["messages"]
    previous = next((m for m in reversed(messages) if m["user_id"] == own["id"]), None)
    if previous and previous["at"] > _ms(now - 1.5):
        raise ValueError("Подожди пару секунд перед следующим сообщением")
    messages.append(
        {
            "id": secrets.token_hex(8),
            "user_id": own["id"],
            "name": own["name"],
            "channel": channel,
            "text": text,
            "at": _ms(now),
        }
    )
    room["state"]["messages"] = messages[-500:]


async def apply_action(db, settings, uid, body, now=None):
    """Returns (focus room, user message, optional notice); no external I/O inside the write transaction."""
    now = time.time() if now is None else now
    if not isinstance(body, dict):
        raise ValueError("Некорректное действие")
    action_name = body.get("action")
    actions = {"create", "invite", "respond", "ready", "start", "leave", "cancel", "chat", "night", "vote"}
    request_id = body.get("request_id")
    if (
        action_name not in actions
        or not isinstance(request_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", request_id)
    ):
        raise ValueError("Обнови экран и повтори действие")
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    await tick(db, now)
    notice = None
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        from community_bot.access import miniapp_allowed

        if not await miniapp_allowed(db, settings, uid):
            raise ValueError("Миниапка пока доступна от роли модератора")
        if not await _one(conn, "SELECT user_id FROM users WHERE user_id=?", (uid,)):
            raise ValueError("Сначала открой личный кабинет Норы")
        previous = await _one(
            conn, "SELECT * FROM mini_mafia_requests WHERE user_id=? AND request_id=?", (uid, request_id)
        )
        if previous:
            if previous["payload_hash"] != digest:
                raise Conflict("Этот запрос уже был использован для другого действия")
            return previous["room_id"], previous["message"], None
        if action_name in {"create", "start", "invite"} or (action_name == "respond" and body.get("accept") is True):
            enabled = await _one(conn, "SELECT enabled FROM feature_flags WHERE key='games'")
            if not enabled or not enabled["enabled"]:
                raise ValueError("Игры временно выключены администрацией")
        if action_name == "create":
            room = await _new_room(conn, uid, body, now)
            message = "Комната создана. Приглашай друзей"
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
                if not body["accept"]:
                    focus = None
            else:
                own = _players(room).get(str(uid))
                if not own or own["left"]:
                    raise ValueError("Ты не участник этой комнаты")
                if body.get("phase_token") != room["state"]["phase_token"]:
                    raise Conflict("Фаза или состав комнаты изменились. Обнови игру")
                if room["status"] not in {"lobby", "active"}:
                    raise Conflict("Эта партия уже завершена")
                if action_name == "invite":
                    notice = await _invite(conn, db, settings, room, uid, body, now)
                    message = "Приглашение отправлено"
                elif action_name == "ready":
                    if room["status"] != "lobby" or type(body.get("ready")) is not bool:
                        raise ValueError("Готовность меняется до начала игры")
                    own["ready"] = body["ready"]
                    message = "Ты готов к игре" if own["ready"] else "Готовность снята"
                elif action_name == "start":
                    await _start(conn, db, settings, room, uid, now)
                    message = "Игра началась. Твоя роль доступна только тебе"
                elif action_name == "cancel":
                    if room["status"] != "lobby" or room["host_id"] != uid:
                        raise ValueError("Закрыть комнату может хозяин до начала игры")
                    await _finish(conn, room, None, now, cancelled=True)
                    message = "Комната закрыта"
                elif action_name == "leave":
                    await _leave(conn, room, own, now)
                    focus = None
                    message = "Ты вышел из комнаты"
                elif action_name == "chat":
                    _chat(room, own, body, now)
                    message = "Сообщение отправлено"
                elif action_name in {"night", "vote"}:
                    expected = "night" if action_name == "night" else "vote"
                    if room["status"] != "active" or room["phase"] != expected or not own["alive"]:
                        raise Conflict("Это действие сейчас недоступно")
                    target = body.get("target_id")
                    if target is None and action_name == "vote":
                        room["state"]["votes"][str(uid)] = None
                    else:
                        target = _id(target)
                        if target not in _targets(room, own):
                            raise ValueError("Эту цель выбрать нельзя")
                        room["state"]["actions" if action_name == "night" else "votes"][str(uid)] = target
                    message = "Выбор сохранён. Его можно изменить до конца фазы"
        await _save(conn, room, now)
        await conn.execute(
            "INSERT INTO mini_mafia_requests(user_id,request_id,payload_hash,room_id,message,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (uid, request_id, digest, focus, message, now),
        )
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

        await deliver_notice(request.app.get("bot"), db, notice["id"], notice["uid"], notice["text"])
    result = await read_status(db, uid, room_id=focus)
    return web.json_response({**result, "message": message})
