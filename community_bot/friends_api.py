"""Mutual Mini App friendships: consent, private lists, blocks and durable invites."""

from __future__ import annotations

import html
import logging
import re
import secrets
import time
from datetime import UTC, datetime

from aiohttp import web

logger = logging.getLogger(__name__)
MAX_FRIENDS = 100
MAX_PENDING = 20
MAX_REQUESTS_HOUR = 10
COOLDOWN_SECONDS = 24 * 3600
PENDING_SECONDS = 7 * 24 * 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS mini_friendships (
    low_id INTEGER NOT NULL REFERENCES users(user_id),
    high_id INTEGER NOT NULL REFERENCES users(user_id),
    requester_id INTEGER NOT NULL REFERENCES users(user_id),
    status TEXT NOT NULL CHECK(status IN ('pending','accepted','closed')),
    token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    cooldown_until REAL NOT NULL DEFAULT 0,
    expires_at REAL NOT NULL,
    PRIMARY KEY(low_id, high_id),
    CHECK(low_id < high_id),
    CHECK(requester_id = low_id OR requester_id = high_id)
);
CREATE INDEX IF NOT EXISTS idx_mini_friends_high ON mini_friendships(high_id,status);
CREATE TABLE IF NOT EXISTS mini_friend_blocks (
    blocker_id INTEGER NOT NULL REFERENCES users(user_id),
    blocked_id INTEGER NOT NULL REFERENCES users(user_id),
    token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(blocker_id,blocked_id),
    CHECK(blocker_id <> blocked_id)
);
CREATE TABLE IF NOT EXISTS mini_friend_request_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    target_id INTEGER NOT NULL REFERENCES users(user_id),
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mini_friend_request_rate
    ON mini_friend_request_log(user_id,created_at);
"""


def _iso(now: float) -> str:
    return datetime.fromtimestamp(now, UTC).isoformat()


def _pair(uid: int, other: int) -> tuple[int, int]:
    return min(uid, other), max(uid, other)


async def eligible(db, settings, uid: int) -> bool:
    from community_bot.access import miniapp_allowed

    return await miniapp_allowed(db, settings, uid)


async def _one(connection, sql, params=()):
    row = await (await connection.execute(sql, params)).fetchone()
    return dict(row) if row else None


async def accepted_in_connection(connection, uid: int, other: int) -> bool:
    """Check inside a game write transaction, so removing a friend wins atomically."""
    if uid == other:
        return False
    relation = await _one(
        connection,
        "SELECT 1 FROM mini_friendships WHERE low_id=? AND high_id=? AND status='accepted'",
        _pair(uid, other),
    )
    block = await _one(
        connection,
        "SELECT 1 FROM mini_friend_blocks WHERE (blocker_id=? AND blocked_id=?) "
        "OR (blocker_id=? AND blocked_id=?)",
        (uid, other, other, uid),
    )
    return bool(relation and not block)


async def accepted(db, uid: int, other: int) -> bool:
    async with db.connect() as connection:
        return await accepted_in_connection(connection, uid, other)


async def inbox_in_connection(connection, uid: int, text: str) -> int:
    """Invitation and inbox entry commit together; delivery preferences affect only DM."""
    cursor = await connection.execute(
        "INSERT INTO notify_inbox(user_id,channel,text,created_at,read,delivered) "
        "VALUES (?,'games',?,?,0,0)",
        (uid, text, _iso(time.time())),
    )
    return int(cursor.lastrowid)


async def deliver_notice(bot, db, inbox_id: int, uid: int, text: str, *, reply_markup=None, force=False) -> None:
    """Best effort after commit. Never repeat a successful action when Telegram fails."""
    if bot is None:
        return
    try:
        if not force and (not await db.notify_channel_on(uid, "games") or await db.notify_digest_on(uid, "games")):
            return
        await bot.send_message(uid, text, parse_mode="HTML", disable_notification=True, reply_markup=reply_markup)
        await db.notify_mark_delivered(inbox_id)
    except Exception as error:
        logger.warning("Friend/game invitation kept in inbox: %s", type(error).__name__)


async def _revoke_invites(connection, uid: int, other: int) -> None:
    exists = await _one(connection, "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mini_mafia_invites'")
    if exists:
        await connection.execute(
            "UPDATE mini_mafia_invites SET status='revoked' WHERE status='pending' AND "
            "((sender_id=? AND user_id=?) OR (sender_id=? AND user_id=?))",
            (uid, other, other, uid),
        )


async def _counts(connection, uid: int, now: float) -> tuple[int, int]:
    row = await _one(
        connection,
        "SELECT SUM(status='accepted') AS friends, "
        "SUM(status='pending' AND expires_at>?) AS pending FROM mini_friendships "
        "WHERE low_id=? OR high_id=?",
        (now, uid, uid),
    )
    return int(row["friends"] or 0), int(row["pending"] or 0)


async def snapshot(db, settings, uid: int) -> dict:
    from community_bot.helpers import can_view_profile

    now = time.time()
    rows = await db.fetchall(
        "SELECT f.*,u.user_id,u.profile_name,u.telegram_name,u.username,"
        "u.avatar_file_id,u.avatar_media_type,u.profile_private FROM mini_friendships f "
        "JOIN users u ON u.user_id=CASE WHEN f.low_id=? THEN f.high_id ELSE f.low_id END "
        "WHERE (f.low_id=? OR f.high_id=?) AND "
        "(f.status='accepted' OR (f.status='pending' AND f.expires_at>?)) ORDER BY f.updated_at DESC",
        (uid, uid, uid, now),
    )
    blocks = await db.fetchall(
        "SELECT b.token,b.created_at,u.user_id,u.profile_name,u.telegram_name,u.username,"
        "u.avatar_file_id,u.avatar_media_type,u.profile_private "
        "FROM mini_friend_blocks b JOIN users u ON u.user_id=b.blocked_id "
        "WHERE b.blocker_id=? ORDER BY b.created_at DESC",
        (uid,),
    )
    result = {"friends": [], "incoming": [], "outgoing": [], "blocked": []}
    for row in [*rows, *blocks]:
        other = int(row["user_id"])
        item = {
            "id": other,
            "has_avatar": bool(row["avatar_file_id"] and row["avatar_media_type"] == "photo"
                               and await can_view_profile(db, settings, uid, row)),
            "name": row["profile_name"] or row["telegram_name"] or row["username"] or "Участник",
            "username": row["username"],
            "token": row["token"],
            "created_at": row["created_at"],
            "updated_at": row.get("updated_at", row["created_at"]),
            "available": await eligible(db, settings, other),
        }
        category = "blocked" if "status" not in row else (
            "friends" if row["status"] == "accepted" else "outgoing" if row["requester_id"] == uid else "incoming"
        )
        result[category].append(item)
    from community_bot.social_profiles import presence_map

    statuses = await presence_map(db, [p['id'] for p in result['friends']])
    for person in result['friends']:
        person['presence'] = statuses.get(person['id'], {'visible': False, 'online': False, 'last_seen': None})
    result["counts"] = {key: len(value) for key, value in result.items()}
    result["limits"] = {
        "max_friends": MAX_FRIENDS, "max_pending": MAX_PENDING,
        "requests_per_hour": MAX_REQUESTS_HOUR, "retry_after_hours": COOLDOWN_SECONDS // 3600,
    }
    return result


async def status(request):
    from community_bot.miniapp import actor

    user = await actor(request)
    return web.json_response(await snapshot(request.app["db"], request.app["settings"], user["user_id"]))


async def _recipient(db, value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 40:
        raise ValueError("Укажи точный @username или Telegram ID участника")
    value = value.strip()
    if re.fullmatch(r"[1-9][0-9]{0,15}", value):
        rows = await db.fetchall("SELECT user_id FROM users WHERE user_id=?", (int(value),))
    elif re.fullmatch(r"@?[A-Za-z][A-Za-z0-9_]{3,31}", value):
        rows = await db.fetchall(
            "SELECT user_id FROM users WHERE lower(username)=lower(?) LIMIT 2", (value.lstrip("@"),)
        )
    else:
        raise ValueError("Укажи точный @username или Telegram ID участника")
    if len(rows) != 1:
        raise ValueError("Участник не найден. Он должен сначала открыть бота; проверь @username или ID")
    return int(rows[0]["user_id"])


async def _close(connection, uid: int, other: int, now: float):
    await connection.execute(
        "UPDATE mini_friendships SET status='closed',updated_at=?,cooldown_until=? "
        "WHERE low_id=? AND high_id=?",
        (_iso(now), now + COOLDOWN_SECONDS, *_pair(uid, other)),
    )
    await _revoke_invites(connection, uid, other)


async def mutate(db, settings, uid: int, body: dict) -> tuple[str, list[tuple[int, int, str]]]:
    """Change one own relationship; return optional committed inbox deliveries."""
    if not isinstance(body, dict):
        raise ValueError("Ожидается действие с другом")
    command = body.get("action")
    if command not in {"request", "accept", "decline", "cancel", "remove", "block", "unblock"}:
        raise ValueError("Неизвестное действие с другом")
    if command == "request":
        other = await _recipient(db, body.get("recipient"))
    else:
        other = body.get("target_id")
        if type(other) is not int or not 0 < other < 10**16:
            raise ValueError("Выбери участника из своего списка")
    if uid == other:
        raise ValueError("Себя добавлять в друзья не нужно")
    now, notice = time.time(), []
    async with db.connect() as connection:
        await connection.execute("BEGIN IMMEDIATE")
        if not await eligible(db, settings, uid):
            raise ValueError("Миниапка пока доступна от роли модератора")
        relation = await _one(
            connection, "SELECT * FROM mini_friendships WHERE low_id=? AND high_id=?", _pair(uid, other)
        )
        own_block = await _one(
            connection, "SELECT * FROM mini_friend_blocks WHERE blocker_id=? AND blocked_id=?", (uid, other)
        )
        any_block = await _one(
            connection, "SELECT 1 FROM mini_friend_blocks WHERE (blocker_id=? AND blocked_id=?) "
            "OR (blocker_id=? AND blocked_id=?)", (uid, other, other, uid),
        )
        if command == "unblock":
            if not own_block:
                return "Участник уже разблокирован", []
            if body.get("token") != own_block["token"]:
                raise ValueError("Список изменился. Открой друзей заново")
            await connection.execute("DELETE FROM mini_friend_blocks WHERE blocker_id=? AND blocked_id=?", (uid, other))
            message = "Блокировка снята. Дружба автоматически не восстанавливается"
        elif command == "block":
            if own_block:
                return "Участник уже заблокирован", []
            if not relation:
                raise ValueError("Выбери участника из своего списка")
            count = await _one(connection, "SELECT COUNT(*) AS n FROM mini_friend_blocks WHERE blocker_id=?", (uid,))
            if count["n"] >= 200:
                raise ValueError("В списке уже 200 блокировок. Сначала убери ненужную")
            await connection.execute(
                "INSERT INTO mini_friend_blocks(blocker_id,blocked_id,token,created_at) VALUES (?,?,?,?)",
                (uid, other, secrets.token_urlsafe(18), _iso(now)),
            )
            await _close(connection, uid, other, now)
            message = "Запросы дружбы и приглашения от участника заблокированы"
        elif any_block:
            raise ValueError("Запросы и приглашения этому участнику недоступны")
        elif command == "request":
            if not await eligible(db, settings, other):
                raise ValueError("У участника пока нет доступа к миниапке: она открыта от роли модератора")
            if relation and relation["status"] == "accepted":
                return "Вы уже друзья", []
            if relation and relation["status"] == "pending" and relation["expires_at"] > now:
                return ("Запрос уже отправлен" if relation["requester_id"] == uid
                        else "У тебя уже есть входящий запрос от этого участника. Прими его в списке"), []
            if relation and relation["cooldown_until"] > now:
                raise ValueError("После отмены или удаления новый запрос можно отправить через 24 часа")
            for participant in (uid, other):
                friends, pending = await _counts(connection, participant, now)
                if friends >= MAX_FRIENDS or pending >= MAX_PENDING:
                    raise ValueError("Достигнут лимит: 100 друзей или 20 ожидающих запросов у одного из участников")
            recent = await _one(
                connection, "SELECT COUNT(*) AS n FROM mini_friend_request_log WHERE user_id=? AND created_at>?",
                (uid, now - 3600),
            )
            if recent["n"] >= MAX_REQUESTS_HOUR:
                raise ValueError("Можно отправить не больше 10 новых запросов в час. Попробуй позже")
            await connection.execute(
                "INSERT INTO mini_friendships(low_id,high_id,requester_id,status,token,created_at,updated_at,"
                "cooldown_until,expires_at) VALUES (?,?,?,'pending',?,?,?,0,?) "
                "ON CONFLICT(low_id,high_id) DO UPDATE SET requester_id=excluded.requester_id,status='pending',"
                "token=excluded.token,created_at=excluded.created_at,updated_at=excluded.updated_at,"
                "cooldown_until=0,expires_at=excluded.expires_at",
                (*_pair(uid, other), uid, secrets.token_urlsafe(18), _iso(now), _iso(now), now + PENDING_SECONDS),
            )
            await connection.execute(
                "INSERT INTO mini_friend_request_log(user_id,target_id,created_at) VALUES (?,?,?)", (uid, other, now)
            )
            me = await _one(connection, "SELECT profile_name,telegram_name FROM users WHERE user_id=?", (uid,))
            name = html.escape(me["profile_name"] or me["telegram_name"] or "Участник")
            text = (f"{name} хочет добавить тебя в друзья. "
                    "Открой Коммьюнити → Друзья, чтобы принять или отклонить запрос.")
            notice.append((await inbox_in_connection(connection, other, text), other, text))
            message = "Запрос отправлен. Дружба появится после подтверждения"
        else:
            if not relation or body.get("token") != relation["token"]:
                raise ValueError("Список изменился. Открой друзей заново")
            if command in {"accept", "decline"} and relation["requester_id"] == uid:
                raise ValueError("Подтвердить или отклонить запрос может только получатель")
            if command == "cancel" and relation["requester_id"] != uid:
                raise ValueError("Отменить можно только свой исходящий запрос")
            if command == "accept":
                if relation["status"] == "accepted":
                    return "Вы уже друзья", []
                if relation["status"] != "pending" or relation["expires_at"] <= now:
                    raise ValueError("Запрос уже закрыт или истёк. Открой друзей заново")
                if not await eligible(db, settings, other):
                    raise ValueError("У участника больше нет доступа к миниапке")
                for participant in (uid, other):
                    if (await _counts(connection, participant, now))[0] >= MAX_FRIENDS:
                        raise ValueError("У одного из участников уже 100 друзей")
                await connection.execute(
                    "UPDATE mini_friendships SET status='accepted',updated_at=? WHERE low_id=? AND high_id=?",
                    (_iso(now), *_pair(uid, other)),
                )
                me = await _one(connection, "SELECT profile_name,telegram_name FROM users WHERE user_id=?", (uid,))
                name = html.escape(me["profile_name"] or me["telegram_name"] or "Участник")
                text = f"{name} принял(а) запрос дружбы. Теперь можно взаимодействовать друг с другом."
                notice.append((await inbox_in_connection(connection, other, text), other, text))
                message = "Теперь вы друзья — можно играть вместе"
            else:
                expected = "accepted" if command == "remove" else "pending"
                if relation["status"] == "closed":
                    return "Запрос или дружба уже закрыты", []
                if relation["status"] != expected:
                    raise ValueError("Список изменился. Открой друзей заново")
                await _close(connection, uid, other, now)
                message = {"remove": "Участник удалён из друзей", "decline": "Запрос отклонён",
                           "cancel": "Запрос отменён"}[command]
        await connection.commit()
    return message, notice


async def action(request):
    from community_bot.miniapp import actor

    user = await actor(request)
    message, notices = await mutate(request.app["db"], request.app["settings"], user["user_id"], await request.json())
    for inbox_id, uid, text in notices:
        await deliver_notice(request.app.get("bot"), request.app["db"], inbox_id, uid, text)
    return web.json_response({"ok": True, "message": message})
