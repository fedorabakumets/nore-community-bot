"""Compact staff-chat admin controls for existing NORA user statistics.

The signed Mini App auth middleware identifies the actor. Permissions and target
rank are rechecked on every request; never trust fields hidden by the browser.
"""
from __future__ import annotations

import logging

from aiohttp import web

from community_bot.audit import person_label
from community_bot.database import utcnow
from community_bot.helpers import can_manage_user, has_permission
from community_bot.permissions import PERM_USERS_COOKIES, PERM_USERS_EDIT
from community_bot.social_likes import COUNT_PREFIX
from community_bot.staff_chat import staff_allowed

logger = logging.getLogger(__name__)

BOUNDS = {
    "cookies": (0, 1_000_000),
    "reputation": (-20, 100),
    "likes": (0, 1_000_000),
}


def _error(message: str, status: int = 400) -> web.Response:
    return web.json_response(
        {"error": message}, status=status, headers={"Cache-Control": "no-store"}
    )


def _positive_id(raw: object) -> int | None:
    if isinstance(raw, str) and raw.isdecimal() and 1 <= len(raw) <= 12:
        value = int(raw)
        return value if value > 0 else None
    if type(raw) is int and 0 < raw < 10**12:
        return raw
    return None


async def _access(request: web.Request):
    db, settings = request.app["db"], request.app["settings"]
    actor_id = request["actor"]["id"]
    if not await staff_allowed(db, settings, actor_id):
        return None, _error("Раздел доступен только команде Норы", 403)
    can_cookies = await has_permission(db, settings, actor_id, PERM_USERS_COOKIES)
    can_profile = await has_permission(db, settings, actor_id, PERM_USERS_EDIT)
    return (db, settings, actor_id, can_cookies, can_profile), None


async def _target(db, settings, actor_id: int, target_id: int):
    user = await db.get_user(target_id)
    if not user:
        return None, _error("Участник с таким Telegram ID не найден", 404)
    if not await can_manage_user(db, settings, actor_id, target_id):
        return None, _error("Недостаточно прав для изменения этого профиля", 403)
    return user, None


async def _summary(db, user: dict) -> dict:
    target_id = int(user["user_id"])
    value = await db.get_bot_state(f"{COUNT_PREFIX}{target_id}")
    return {
        "id": target_id,
        "name": str(person_label(user, str(target_id)))[:80],
        "cookies": int(user.get("cookies") or 0),
        "reputation": int(user.get("reputation") or 0),
        "likes": max(0, int(value or 0)),
    }


async def capabilities(request: web.Request) -> web.Response:
    access, denied = await _access(request)
    if denied is not None:
        return denied
    db, settings, actor_id, can_cookies, can_profile = access
    response = {
        "can_open": True, "can_cookies": can_cookies,
        "can_profile": can_profile, "can_likes": can_profile,
    }
    raw_id = request.query.get("target_id")
    if raw_id is not None:
        if not (can_cookies or can_profile):
            return _error("Нет прав редактировать пользователей", 403)
        target_id = _positive_id(raw_id)
        if target_id is None:
            return _error("Укажи корректный Telegram ID")
        user, error = await _target(db, settings, actor_id, target_id)
        if error is not None:
            return error
        response["target"] = await _summary(db, user)
    return web.json_response(response, headers={"Cache-Control": "no-store"})


async def change(request: web.Request) -> web.Response:
    access, denied = await _access(request)
    if denied is not None:
        return denied
    db, settings, actor_id, can_cookies, can_profile = access
    if request.content_length is not None and request.content_length > 1024:
        return _error("Слишком большой запрос", 413)
    try:
        data = await request.json()
    except (ValueError, TypeError):
        return _error("Некорректный запрос")
    if not isinstance(data, dict) or set(data) != {
        "target_id", "metric", "value", "expected", "confirmed"
    }:
        return _error("Некорректные поля")
    metric = data["metric"]
    if not isinstance(metric, str) or metric not in BOUNDS:
        return _error("Неизвестный показатель")
    if metric == "cookies" and not can_cookies:
        return _error("Нет прав изменять печеньки", 403)
    if metric != "cookies" and not can_profile:
        return _error("Нет прав изменять этот показатель", 403)
    target_id = _positive_id(data["target_id"])
    value, expected = data["value"], data["expected"]
    if (target_id is None or type(value) is not int or type(expected) is not int
            or data["confirmed"] is not True):
        return _error("Некорректные данные подтверждения")
    minimum, maximum = BOUNDS[metric]
    if not minimum <= value <= maximum:
        return _error(f"Допустимый диапазон: {minimum}…{maximum}")
    if not minimum <= expected <= maximum:
        return _error("Устаревшие исходные данные")
    user, error = await _target(db, settings, actor_id, target_id)
    if error is not None:
        return error
    if value == expected:
        return _error("Значение не изменилось")

    actor = await db.get_user(actor_id)
    actor_name = person_label(actor, str(actor_id))
    target_name = person_label(user, str(target_id))
    now = utcnow()
    async with db.connect() as connection:
        await connection.execute("BEGIN IMMEDIATE")
        if metric == "likes":
            key = f"{COUNT_PREFIX}{target_id}"
            row = await (await connection.execute(
                "SELECT value FROM bot_state WHERE key=?", (key,)
            )).fetchone()
            current = max(0, int(row["value"])) if row else 0
        else:
            row = await (await connection.execute(
                f"SELECT {metric} AS value FROM users WHERE user_id=?", (target_id,)
            )).fetchone()
            current = int(row["value"]) if row else None
        if current != expected:
            await connection.rollback()
            return _error("Показатель уже изменился. Обнови данные", 409)
        if metric == "likes":
            await connection.execute(
                "INSERT INTO bot_state(key,value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
        else:
            await connection.execute(
                f"UPDATE users SET {metric}=?,updated_at=? WHERE user_id=?",
                (value, now, target_id),
            )
            if metric == "cookies":
                await connection.execute(
                    "INSERT INTO transactions(user_id, amount, kind, details, created_at) "
                    "VALUES (?, ?, 'admin_set', ?, ?)",
                    (target_id, value-current, f"by:{actor_id}", now),
                )
        audit = await connection.execute(
            "INSERT INTO admin_audit_log("
            "actor_id,action,target,details,reason,status,actor_name,target_name,created_at"
            ") VALUES (?,?,?,?,?,?,?,?,?)",
            (actor_id, f"user_{metric}", str(target_id),
             f"Mini App · тестовый чат: {current} → {value}",
             "Изменение показателя через админку чата", "", actor_name,
             target_name, now),
        )
        audit_id = audit.lastrowid
        await connection.commit()

    if metric in {"cookies", "reputation"} and request.app.get("bot"):
        try:
            from community_bot.widget_notifications import Sender, send_service_notification
            text = (
                f"Баланс установлен: {value} 🍪."
                if metric == "cookies" else f"Репутация установлена: {value}."
            )
            await send_service_notification(
                request.app["bot"], db, target_id, Sender(),
                "Изменение баланса" if metric == "cookies" else "Изменение репутации",
                text, "history" if metric == "cookies" else "reputation",
                event_key=f"admin:{audit_id}",
            )
        except Exception:
            logger.exception("Staff chat admin update succeeded; profile notice failed")
    refreshed = await db.get_user(target_id)
    return web.json_response(
        {"ok": True, "target": await _summary(db, refreshed)},
        headers={"Cache-Control": "no-store"},
    )
