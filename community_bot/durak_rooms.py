"""Durable table rooms, reservations and settlement in NORA's SQLite wallet."""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from community_bot import barricade_rules as barricade
from community_bot import durak_items as items
from community_bot import durak_rules as rules
from community_bot.database import Database
from community_bot.friends_api import accepted_in_connection, inbox_in_connection
from community_bot.rocket_api import stake_restriction
from community_bot.sea_api import _one as one
from community_bot.sea_api import _rows as rows

SCHEMA = """
CREATE TABLE IF NOT EXISTS durak_rooms (
    id TEXT PRIMARY KEY, host INTEGER NOT NULL REFERENCES users(user_id), code TEXT UNIQUE NOT NULL,
    config TEXT NOT NULL, status TEXT NOT NULL, rev INTEGER NOT NULL DEFAULT 0,
    deadline REAL NOT NULL, expires REAL NOT NULL, updated REAL NOT NULL, created REAL NOT NULL,
    game TEXT, frames TEXT NOT NULL DEFAULT '[]', result TEXT
);
CREATE INDEX IF NOT EXISTS durak_due ON durak_rooms(status,deadline);
CREATE INDEX IF NOT EXISTS durak_recent ON durak_rooms(updated);
CREATE INDEX IF NOT EXISTS durak_created ON durak_rooms(host,created);
CREATE INDEX IF NOT EXISTS durak_public ON durak_rooms(created DESC,id DESC)
    WHERE status='waiting' AND json_extract(config,'$.private')=0;
CREATE TABLE IF NOT EXISTS durak_members (
    room TEXT NOT NULL REFERENCES durak_rooms(id) ON DELETE CASCADE, uid INTEGER NOT NULL REFERENCES users(user_id),
    seat INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1, reserved INTEGER NOT NULL, payout INTEGER,
    PRIMARY KEY (room,uid), UNIQUE(room,seat)
);
CREATE UNIQUE INDEX IF NOT EXISTS durak_one_active ON durak_members(uid) WHERE active=1;
CREATE INDEX IF NOT EXISTS durak_history ON durak_members(uid,room);
CREATE TABLE IF NOT EXISTS durak_invites (
    room TEXT NOT NULL REFERENCES durak_rooms(id) ON DELETE CASCADE, uid INTEGER NOT NULL REFERENCES users(user_id),
    sender INTEGER NOT NULL REFERENCES users(user_id), notice_id INTEGER, PRIMARY KEY(room,uid)
);
CREATE INDEX IF NOT EXISTS durak_incoming ON durak_invites(uid);
CREATE TABLE IF NOT EXISTS durak_commands (
    uid INTEGER NOT NULL, nonce TEXT NOT NULL, digest TEXT NOT NULL,
    room TEXT NOT NULL REFERENCES durak_rooms(id) ON DELETE CASCADE, PRIMARY KEY(uid,nonce)
);
CREATE INDEX IF NOT EXISTS durak_command_room ON durak_commands(room);
"""
LOBBY_TTL = 3600
GAME_TTL = 6 * 3600
HISTORY_TTL = 90 * 86400
QUICK_TTL = 300
GAME_KIND = "CASE WHEN json_valid(r.config) THEN COALESCE(json_extract(r.config,'$.game'),'durak') ELSE 'durak' END"
LIVE = ("waiting", "playing")
logger = logging.getLogger(__name__)


class Conflict(ValueError):
    pass


@dataclass(frozen=True)
class QuickLobby:
    stake: int


def dump(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _load(row):
    if not row:
        raise ValueError("Стол недоступен")
    for key in ("config", "game", "frames", "result"):
        row[key] = json.loads(row[key]) if row[key] else None
    return row


async def _room(conn, rid, game=None):
    row = await one(conn, f"SELECT r.*,{GAME_KIND} AS kind FROM durak_rooms r WHERE id=?", (rid,))
    if row and game is not None and row["kind"] != game:
        row = None
    return _load(row)


async def _members(conn, rid):
    return await rows(conn, """
        SELECT m.*,COALESCE(NULLIF(u.profile_name,''),NULLIF(u.telegram_name,''),u.username,'Участник') AS name,
               (u.avatar_file_id IS NOT NULL AND u.avatar_media_type='photo' AND u.profile_private=0) AS avatar
        FROM durak_members m JOIN users u ON u.user_id=m.uid WHERE m.room=? ORDER BY m.seat
    """, (rid,))


async def _wallet(conn, uid):
    user = await one(conn, "SELECT * FROM users WHERE user_id=?", (uid,))
    reason = await stake_restriction(conn, user, age_message="Игры со ставкой доступны с 18 лет")
    if await one(conn, "SELECT 1 FROM bot_state WHERE key='durak_paused' AND value='1'"):
        reason = "Столы временно закрыты на обслуживание"
    return (user or {}).get("cookies", 0), reason


async def _eligible(conn, uid, stake):
    balance, reason = await _wallet(conn, uid)
    if reason:
        raise ValueError(reason)
    if balance < stake:
        raise ValueError(f"Для ставки нужно {stake} печенек, на балансе {balance}")


async def _entry(conn, uid, stake):
    if await one(conn, "SELECT 1 FROM durak_members WHERE uid=? AND active=1", (uid,)):
        raise Conflict("У тебя уже есть стол. Вернуться к нему можно в «Мои игры»")
    await _eligible(conn, uid, stake)


async def _money(conn, uid, amount, kind, room, now):
    await Database._add_cookies(conn, uid, amount, room["kind"] + "_" + kind, "room:" + room["id"],
                                datetime.fromtimestamp(now, UTC).isoformat())


async def _seat(conn, r, uid, seat, now):
    stake = r["config"]["stake"]
    await _entry(conn, uid, stake)
    reserved = 0 if r["kind"] == "barricade" else stake
    await conn.execute("INSERT INTO durak_members(room,uid,seat,reserved) VALUES(?,?,?,?)",
                       (r["id"], uid, seat, reserved))
    if reserved:
        await _money(conn, uid, -reserved, "bet", r, now)


def _barricade_config(values, quick):
    if not isinstance(values, dict) or values.keys() != {"stake"}:
        raise ValueError("Выбери ставку")
    stake = values["stake"]
    if type(stake) is not int or not 5 <= stake <= 10000:
        raise ValueError("Ставка от 5 до 10 000 печенек")
    return {"game": "barricade", "stake": stake, "players": 2, "private": not quick, "quick": quick}


async def _create(conn, uid, values, now, *, game, quick=False):
    if game == "durak" and quick:
        if not isinstance(values, dict) or values.keys() != {"stake"}:
            raise ValueError("Выбери ставку")
        config = {**rules.settings(values), "quick": True}
    else:
        config = rules.settings(values) if game == "durak" else _barricade_config(values, quick)
    if quick:
        await _entry(conn, uid, config["stake"])
        candidates = await rows(conn, f"""
            SELECT r.*,{GAME_KIND} AS kind FROM durak_rooms r
            WHERE r.status='waiting' AND r.host!=? AND r.deadline>? AND {GAME_KIND}=?
              AND json_extract(r.config,'$.quick')=1 AND json_extract(r.config,'$.stake')=?
            ORDER BY r.created,r.id
        """, (uid, now, game, config["stake"]))
        for row in candidates:
            if await _blocked(conn, row["id"], uid):
                continue
            candidate = _load(row)
            try:
                await _eligible(conn, candidate["host"], config["stake"] if game == "barricade" else 0)
            except ValueError:
                await _finish(conn, candidate, now, cancel="unfunded")
                await _save(conn, candidate, now)
                continue
            await _join(conn, candidate, uid, None, now, quick=True)
            return candidate
    ttl = QUICK_TTL if quick else LOBBY_TTL
    rid = secrets.token_hex(8)
    count = await one(conn, "SELECT COUNT(*) AS n FROM durak_rooms WHERE host=? AND created>?", (uid, now - 600))
    if count["n"] >= 10:
        raise ValueError("За десять минут можно создать до десяти столов")
    await conn.execute("""
        INSERT INTO durak_rooms(id,host,code,config,status,deadline,expires,created,updated)
        VALUES(?,?,?,?,'waiting',?,?,?,?)
    """, (rid, uid, secrets.token_urlsafe(16), dump(config), now + ttl, now + ttl, now, now))
    room = await _room(conn, rid)
    await _seat(conn, room, uid, 0, now)
    return room


async def _blocked(conn, rid, uid):
    return await one(conn, """
        SELECT 1 FROM durak_members m JOIN mini_friend_blocks b ON
        (b.blocker_id=m.uid AND b.blocked_id=?) OR (b.blocked_id=m.uid AND b.blocker_id=?)
        WHERE m.room=? LIMIT 1
    """, (uid, uid, rid))


async def _invited(conn, rid, uid):
    invite = await one(conn, """
        SELECT i.sender FROM durak_invites i JOIN durak_members m ON m.room=i.room AND m.uid=i.sender
        WHERE i.room=? AND i.uid=? AND m.active=1
    """, (rid, uid))
    return invite and await accepted_in_connection(conn, uid, invite["sender"])


async def _join(conn, r, uid, code, now, *, quick=False):
    if r["status"] != "waiting" or await _blocked(conn, r["id"], uid):
        raise Conflict("Стол больше недоступен для входа")
    if quick and not r["config"].get("quick"):
        raise ValueError("Этот стол недоступен для быстрого входа")
    if r["config"].get("quick") and not quick:
        raise ValueError("Этот стол доступен через быстрый поиск")
    if r["config"]["private"] and code != r["code"] and not await _invited(conn, r["id"], uid):
        raise ValueError("Для приватного стола нужно приглашение")
    members = await _members(conn, r["id"])
    occupied = {m["seat"] for m in members}
    seats = r["config"]["players"]
    free = next((i for i in range(seats) if i not in occupied), None)
    if free is None:
        raise Conflict("Все места заняты")
    await _seat(conn, r, uid, free, now)
    if r["kind"] == "barricade":
        stake = r["config"]["stake"]
        await _eligible(conn, r["host"], stake)
        for player in (r["host"], uid):
            await _money(conn, player, -stake, "bet", r, now)
        await conn.execute("UPDATE durak_members SET reserved=? WHERE room=?", (stake, r["id"]))
        r.update(status="playing", game=barricade.start(), expires=now + GAME_TTL,
                 deadline=now + barricade.TURN_SECONDS)
        await conn.execute("DELETE FROM durak_invites WHERE room=?", (r["id"],))
    elif len(occupied) + 1 == seats:
        r.update(status="playing", game=rules.deal(r["config"]), expires=now + GAME_TTL)
        r["game"]["table_cosmetics"] = (await items.equipped(conn, r["host"]) or 0) & (
            items.PARTS["felt"] | items.PARTS["back"])
        r["deadline"] = now + rules.SECONDS[r["config"]["speed"]]
        await conn.execute("DELETE FROM durak_invites WHERE room=?", (r["id"],))


async def _finish(conn, r, now, *, cancel=None):
    members = await _members(conn, r["id"])
    result = {"reason": cancel, "loser": None, "forfeit": []} if cancel else r["game"]["result"]
    recipients = [m for m in members if cancel or (m["seat"] != result["loser"] and m["seat"] not in result["forfeit"])]
    total = sum(m["reserved"] for m in members)
    # Equal shares; whole-cookie remainder follows the recorded exit order, then seat order.
    order = [] if cancel else r["game"]["out"][:]
    order.extend(m["seat"] for m in members if m["seat"] not in order)
    recipients.sort(key=lambda m: order.index(m["seat"]))
    if cancel:
        paid = {m["uid"]: m["reserved"] for m in members}
        r["game"] = None
    else:
        share, remainder = divmod(total, len(recipients))
        paid = {m["uid"]: share + int(i < remainder) for i, m in enumerate(recipients)}
    for m in members:
        amount = paid.get(m["uid"], 0)
        if amount:
            refund = cancel or (result["reason"] == "draw" and not result["forfeit"])
            await _money(conn, m["uid"], amount, "refund" if refund else "win", r, now)
        await conn.execute("UPDATE durak_members SET active=0,reserved=0,payout=? WHERE room=? AND uid=?",
                           (amount, r["id"], m["uid"]))
    await conn.execute("DELETE FROM durak_invites WHERE room=?", (r["id"],))
    r.update(status="cancelled" if cancel else "finished", result=result, deadline=0)


async def _update_turn(conn, r, now, previous, previous_phase):
    g = r["game"]
    if g["phase"] == "finished":
        await _finish(conn, r, now)
    elif g["phase"] == "review":
        if previous_phase != "review":
            r["deadline"] = min(r["expires"], now + rules.REVIEW_SECONDS)
    elif rules.turn(g) != previous or g["phase"] != previous_phase or any(
        e["kind"] in ("discard", "collect", "defend", "timeout", "surrender") for e in g["events"]
    ):
        r["deadline"] = min(r["expires"], now + rules.SECONDS[r["config"]["speed"]])


def can_undo(r, seat, now):
    entry = r["game"].get("undo") if r["status"] == "playing" else None
    return bool(entry and entry["rev"] == r["rev"] and entry["seat"] == seat
                and now < min(entry["deadline"], r["deadline"]))


async def _play(conn, r, seat, move, now):
    g = r["game"]
    if r["kind"] == "barricade":
        barricade.play(g, seat, move)
        if g.get("result"):
            await _finish(conn, r, now)
        else:
            r["deadline"] = min(r["expires"], now + barricade.TURN_SECONDS)
        return
    if move == {"kind": "undo"}:
        if not can_undo(r, seat, now):
            raise Conflict("Этот ход уже нельзя отменить")
        entry = g.pop("undo")
        cards = [e["card"] for e in g["journal"][entry["index"]:]]
        rules.rewind(g, entry["index"])
        r["deadline"] = min(entry["deadline"], r["deadline"])
        g["events"] = [{"kind": "undo", "seat": seat, "cards": cards}]
        return
    g.pop("undo", None)
    previous, phase = rules.turn(g), g["phase"]
    deadline, index = r["deadline"], len(g["journal"])
    rules.play(g, seat, move)
    await _update_turn(conn, r, now, previous, phase)
    if (g["phase"] not in ("finished", "review") and g["events"]
            and all(e["kind"] in ("attack", "defend", "transfer") for e in g["events"])):
        g["undo"] = {"rev": r["rev"] + 1, "seat": seat, "deadline": deadline, "index": index}


async def _leave(conn, r, uid, m, now, *, cancel=False):
    if r["status"] == "waiting":
        if uid == r["host"]:
            await _finish(conn, r, now, cancel="cancelled")
        elif cancel:
            raise ValueError("Закрыть стол может только создатель")
        else:
            await _money(conn, uid, m["reserved"], "refund", r, now)
            await conn.execute("DELETE FROM durak_members WHERE room=? AND uid=?", (r["id"], uid))
            await conn.execute("DELETE FROM durak_invites WHERE room=? AND (uid=? OR sender=?)", (r["id"], uid, uid))
    elif r["status"] == "playing" and not cancel and r["kind"] == "barricade":
        barricade.finish(r["game"], m["seat"], "surrender")
        await _finish(conn, r, now)
    elif r["status"] == "playing" and not cancel:
        g = r["game"]
        previous, phase = rules.turn(g), g["phase"]
        rules.forfeit(g, m["seat"], "surrender")
        await conn.execute("UPDATE durak_members SET active=0 WHERE room=? AND uid=?", (r["id"], uid))
        await _update_turn(conn, r, now, previous, phase)
    else:
        raise ValueError("Партия уже началась или завершена")


async def _invite(conn, r, uid, target):
    if r["status"] != "waiting" or r["config"].get("quick") or type(target) is not int or target <= 0:
        raise ValueError("Выбери друга для приглашения в лобби")
    if not await accepted_in_connection(conn, uid, target) or await _blocked(conn, r["id"], target):
        raise ValueError("Приглашение доступно друзьям Норы")
    if await one(conn, "SELECT 1 FROM durak_members WHERE room=? AND uid=?", (r["id"], target)):
        raise ValueError("Друг уже за столом")
    cursor = await conn.execute("INSERT OR IGNORE INTO durak_invites(room,uid,sender) VALUES(?,?,?)",
                                (r["id"], target, uid))
    if not cursor.rowcount:
        raise Conflict("Приглашение уже отправлено")
    sender = await one(conn, "SELECT COALESCE(NULLIF(profile_name,''),telegram_name) AS name FROM users "
                       "WHERE user_id=?",
                       (uid,))
    game = "Баррикаду" if r["kind"] == "barricade" else "Дурака"
    text = f"{html.escape(sender['name'] or 'Друг')} зовёт сыграть в {game} на {r['config']['stake']} 🍪."
    if r["kind"] == "durak":
        text += " Открой Игры → Дурак → Мои игры."
    notice = await inbox_in_connection(conn, target, text)
    await conn.execute("UPDATE durak_invites SET notice_id=? WHERE room=? AND uid=?", (notice, r["id"], target))
    return notice, target, text


async def _save(conn, r, now):
    r["rev"] += 1
    # Frames contain only public movements; dealt/drawn faces are never recorded in the stream.
    if r["game"] and r["game"].get("events"):
        r["frames"].append({"rev": r["rev"], "events": r["game"]["events"]})
    r["frames"] = r["frames"][-20:]
    keep_board = r["status"] == "playing" or (r["kind"] == "barricade" and r["game"])
    await conn.execute("""
        UPDATE durak_rooms SET status=?,rev=?,deadline=?,expires=?,updated=?,game=?,frames=?,result=? WHERE id=?
    """, (r["status"], r["rev"], r["deadline"], r["expires"], now,
          dump(r["game"]) if keep_board else None, dump(r["frames"]),
          dump(r["result"]) if r["result"] else None, r["id"]))


async def _expire(conn, r, now):
    if r["status"] not in LIVE or r["deadline"] > now:
        return False
    if r["status"] == "waiting" or now >= r["expires"]:
        await _finish(conn, r, now, cancel="expired" if r["status"] == "waiting" else "technical")
    elif r["kind"] == "barricade":
        barricade.finish(r["game"], r["game"]["turn"], "timeout")
        await _finish(conn, r, now)
    else:
        g = r["game"]
        previous, phase = rules.turn(g), g["phase"]
        if phase == "review":
            g["events"] = []
            rules.close_round(g)
        elif (phase == "throw" and previous is None) or rules.forced_take(g):
            g["events"] = []
            rules.advance(g)
        else:
            rules.forfeit(g, previous, "timeout")
            await conn.execute("UPDATE durak_members SET active=0 WHERE room=? AND seat=?", (r["id"], previous))
        await _update_turn(conn, r, now, previous, phase)
    await _save(conn, r, now)
    return True


async def resume_forced_round(conn, r, now):
    g = r["game"]
    phase, player = g["phase"], rules.turn(g)
    if now >= r["expires"] or not ((phase == "throw" and player is None) or rules.forced_take(g)):
        return
    g["events"] = []
    rules.advance(g)
    await _update_turn(conn, r, now, player, phase)
    await _save(conn, r, now)


async def expire(db, rid, now):
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        row = await one(conn, f"SELECT r.*,{GAME_KIND} AS kind FROM durak_rooms r WHERE id=?", (rid,))
        if not row or row["status"] not in LIVE or row["deadline"] > now:
            return False
        await conn.execute("SAVEPOINT expire_durak")
        try:
            changed = await _expire(conn, _load(dict(row)), now)
        except (ValueError, KeyError, TypeError, IndexError):
            # A damaged game snapshot cannot prevent refunding independently stored reservations.
            # Undo any partial settlement before using the existing wallet and member seats.
            await conn.execute("ROLLBACK TO expire_durak")
            row.update(game=None, frames=[], result=None)
            await _finish(conn, row, now, cancel="technical")
            await _save(conn, row, now)
            changed = True
            logger.error("Durak room %s cancelled after an unreadable game state", rid)
        await conn.execute("RELEASE expire_durak")
        await conn.commit()
        return changed


async def leave_on_account_reset(conn, uid, now):
    # Resolve even an already forfeited seat before the account's wallet is reset.
    unsettled = await rows(conn, f"""
        SELECT r.id,r.rev,r.expires,{GAME_KIND} AS kind FROM durak_rooms r
        JOIN durak_members m ON m.room=r.id WHERE m.uid=? AND (m.active=1 OR m.reserved>0)
          AND r.status IN ('playing','waiting')
    """, (uid,))
    for r in unsettled:
        r.update(game=None, frames=[])
        await _finish(conn, r, now, cancel="account_reset")
        await _save(conn, r, now)
    await conn.execute("DELETE FROM durak_invites WHERE uid=? OR sender=?", (uid, uid))


async def pause_and_refund(db):
    """Close admission and refund every outstanding seat before reverting to an older app."""
    now = time.time()
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        await conn.execute("INSERT OR REPLACE INTO bot_state(key,value) VALUES('durak_paused','1')")
        count = 0
        while batch := await rows(conn, f"SELECT id,rev,expires,{GAME_KIND} AS kind FROM durak_rooms r "
                                  "WHERE status IN ('waiting','playing') LIMIT 50"):
            for room in batch:
                room.update(game=None, frames=[])
                await _finish(conn, room, now, cancel="maintenance")
                await _save(conn, room, now)
                count += 1
        await conn.commit()
    return count


async def command(db, uid, body, *, now=None, game="durak"):
    now = time.time() if now is None else now
    if not isinstance(body, dict) or len(dump(body)) > 2048:
        raise ValueError("Некорректная команда")
    nonce = body.get("nonce")
    if not isinstance(nonce, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{16,64}", nonce):
        raise ValueError("Обнови экран и повтори действие")
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    action, notice = body.get("action"), None
    fields = {"create": {"config"}, "quick": {"config"}, "join": {"room", "code"}, "join-quick": {"room"},
              "invite": {"room", "friend"}, "leave": {"room", "rev"}, "cancel": {"room", "rev"},
              "move": {"room", "rev", "move"}}
    if game == "barricade":
        fields["decline"] = {"room"}
    if not isinstance(action, str) or action not in fields or body.keys() - (fields[action] | {"action", "nonce"}):
        raise ValueError("Неизвестные параметры команды")
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        old = await one(conn, f"SELECT c.room,c.digest,{GAME_KIND} AS kind FROM durak_commands c "
                        "JOIN durak_rooms r ON r.id=c.room WHERE c.uid=? AND c.nonce=?", (uid, nonce))
        if old:
            if old["digest"] != digest or old["kind"] != game:
                raise Conflict("Эта команда уже использована")
            return old["room"], None
        if action in ("create", "quick"):
            r = await _create(conn, uid, body.get("config"), now, game=game, quick=action == "quick")
            if action == "quick" and r["status"] == "waiting":
                notice = QuickLobby(r["config"]["stake"])
        else:
            rid = body.get("room")
            if not isinstance(rid, str) or len(rid) > 32:
                raise ValueError("Выбери стол")
            r = await _room(conn, rid, game)
            if await _expire(conn, r, now):
                await conn.commit()
                raise Conflict("Время истекло, состояние стола обновилось")
            if action in ("join", "join-quick"):
                await _join(conn, r, uid, body.get("code"), now, quick=action == "join-quick")
            elif action == "decline":
                cursor = await conn.execute("DELETE FROM durak_invites WHERE room=? AND uid=?", (rid, uid))
                if not cursor.rowcount:
                    raise ValueError("Приглашение больше не действует")
            else:
                m = await one(conn, "SELECT * FROM durak_members WHERE room=? AND uid=? AND active=1", (rid, uid))
                if not m:
                    raise ValueError("Ты не участвуешь в этой партии")
                if action == "invite":
                    notice = await _invite(conn, r, uid, body.get("friend"))
                elif action in ("leave", "cancel", "move"):
                    if type(body.get("rev")) is not int or body["rev"] != r["rev"]:
                        raise Conflict("Стол уже изменился. Выбери действие ещё раз")
                    if action != "move":
                        await _leave(conn, r, uid, m, now, cancel=action == "cancel")
                    elif r["status"] == "playing":
                        await _play(conn, r, m["seat"], body.get("move"), now)
                    else:
                        raise Conflict("Партия ещё не началась или уже завершена")
                else:
                    raise ValueError("Неизвестное действие")
        await _save(conn, r, now)
        await conn.execute("INSERT INTO durak_commands(uid,nonce,digest,room) VALUES(?,?,?,?)",
                           (uid, nonce, digest, r["id"]))
        await conn.commit()
    return r["id"], notice
