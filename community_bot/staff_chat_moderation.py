"""Staff Chat moderation endpoints backed by NORA's existing role permissions.

No Telegram action is taken until the server has checked the actual message
author, current staff permissions, relative role rank and Telegram membership.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime, timedelta

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import ChatPermissions
from aiohttp import web

from community_bot.audit import person_label
from community_bot.helpers import can_manage_user, has_permission
from community_bot.permissions import (
    PERM_AUDIT, PERM_BAN, PERM_KICK, PERM_MUTE, PERM_PURGE, PERM_WARN,
)
from community_bot.staff_chat import discard, staff_allowed
from community_bot import staff_chat_delivery as dispatch

logger = logging.getLogger(__name__)
PERMISSION = {
    "delete": PERM_PURGE,
    "warn": PERM_WARN,
    "unwarn": PERM_WARN,
    "mute": PERM_MUTE,
    "unmute": PERM_MUTE,
    "kick": PERM_KICK,
    "ban": PERM_BAN,
    "unban": PERM_BAN,
}
DURATIONS = {
    "10m": timedelta(minutes=10),
    "1h": timedelta(hours=1),
    "12h": timedelta(hours=12),
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
}
LABELS = {
    "delete": "Удалить из Telegram", "warn": "Предупредить",
    "unwarn": "Снять предупреждение", "mute": "Замутить",
    "unmute": "Размутить", "kick": "Исключить",
    "ban": "Забанить", "unban": "Разбанить",
}


def _error(message: str, code: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=code,
                             headers={"Cache-Control": "no-store"})


async def _auth(request: web.Request):
    db, settings = request.app["db"], request.app["settings"]
    actor = request["actor"]
    uid = int(actor["id"])
    if not await staff_allowed(db, settings, uid):
        return None, _error("Раздел доступен только команде Норы", 403)
    chat_id = settings.community_chat_id
    if type(chat_id) is not int or not chat_id or request.app.get("bot") is None:
        return None, _error("Чат Норы пока недоступен", 503)
    return (db, settings, request.app["bot"], uid, chat_id), None


async def _source(db, chat_id: int, message_id: int):
    return await db.fetchone(
        """SELECT message_id,
                  CASE WHEN app_author_id > 0 THEN app_author_id ELSE user_id END AS user_id,
                  CASE WHEN app_author_id > 0 THEN app_author_name ELSE author_name END AS author_name
           FROM staff_chat_messages WHERE chat_id=? AND message_id=?""",
        (chat_id, message_id),
    )


async def _choices(db, settings, uid: int, target_id: int, target) -> list[str]:
    permissions = {
        action for action, permission in PERMISSION.items()
        if await has_permission(db, settings, uid, permission)
    }
    if not target_id or not target:
        return ["delete"] if "delete" in permissions else []
    if uid == target_id or not await can_manage_user(db, settings, uid, target_id):
        return []
    return [name for name in PERMISSION if name in permissions]


def _parse_id(value) -> int | None:
    if type(value) is int and value > 0 and value < 10**13:
        return value
    if isinstance(value, str) and value.isdecimal() and 1 <= len(value) <= 12:
        return int(value)
    return None


async def capabilities(request: web.Request) -> web.Response:
    ctx, denied = await _auth(request)
    if denied is not None:
        return denied
    db, settings, _, uid, chat_id = ctx
    mid = _parse_id(request.query.get("message_id"))
    if mid is None:
        return _error("Некорректное сообщение")
    source = await _source(db, chat_id, mid)
    if source is None:
        return _error("Сообщение отсутствует", 404)
    target_id = int(source["user_id"] or 0)
    target = await db.get_user(target_id) if target_id > 0 else None
    actions = await _choices(db, settings, uid, target_id, target)
    return web.json_response({
        "message_id": mid, "target_id": target_id if target else 0,
        "target_name": str(person_label(target, source["author_name"]))[:80],
        "warnings": int(target["warnings"] or 0) if target else 0,
        "actions": [{"id": key, "label": LABELS[key]} for key in actions],
        "can_view_audit": await has_permission(db, settings, uid, PERM_AUDIT),
    }, headers={"Cache-Control": "no-store"})


async def audit(request: web.Request) -> web.Response:
    ctx, denied = await _auth(request)
    if denied is not None:
        return denied
    db, settings, _, uid, _chat_id = ctx
    if await has_permission(db, settings, uid, PERM_AUDIT):
        rows = await db.recent_admin_actions(30)
    else:
        rows = await db.fetchall(
            """SELECT id,actor_id,action,target,details,reason,actor_name,target_name,created_at
               FROM admin_audit_log WHERE actor_id=?
               ORDER BY id DESC LIMIT 25""",
            (uid,),
        )
    return web.json_response({
        "items": [{
            "id": row["id"], "action": row["action"],
            "actor": row.get("actor_display") or row.get("actor_name") or str(row["actor_id"]),
            "target": row.get("target_display") or row.get("target_name") or str(row.get("target") or ""),
            "reason": (row.get("reason") or "")[:250],
            "details": (row.get("details") or "")[:150],
            "created_at": row["created_at"],
        } for row in rows],
        "scope": "all" if await has_permission(db, settings, uid, PERM_AUDIT) else "own",
    }, headers={"Cache-Control": "no-store"})


async def action(request: web.Request) -> web.Response:
    ctx, denied = await _auth(request)
    if denied is not None:
        return denied
    db, settings, bot, uid, chat_id = ctx
    if request.content_length is not None and request.content_length > 2048:
        return _error("Слишком большой запрос", 413)
    try:
        data = await request.json()
    except (ValueError, TypeError, json.JSONDecodeError):
        return _error("Некорректный запрос")
    if not isinstance(data, dict) or set(data) != {
        "message_id", "action", "reason", "duration", "operation_id", "confirmed"
    }:
        return _error("Некорректные поля запроса")
    mid = _parse_id(data["message_id"])
    operation = data["action"]
    duration_key = data["duration"]
    reason = data["reason"]
    if (mid is None or not isinstance(operation, str) or operation not in PERMISSION
            or not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 250
            or not isinstance(duration_key, str) or data["confirmed"] is not True):
        return _error("Укажи действие и причину (от 3 до 250 символов)")
    try:
        op_id = dispatch.validate_key(data["operation_id"])
    except ValueError:
        return _error("Некорректная операция")
    if not op_id:
        return _error("Отсутствует идентификатор действия")
    if operation in {"mute", "ban"}:
        if duration_key not in DURATIONS and not (operation == "ban" and duration_key == "forever"):
            return _error("Некорректная длительность")
    elif duration_key:
        return _error("Этому действию не требуется длительность")

    source = await _source(db, chat_id, mid)
    if not source:
        return _error("Сообщение больше недоступно", 404)
    target_id = int(source["user_id"] or 0)
    target = await db.get_user(target_id) if target_id > 0 else None
    available = await _choices(db, settings, uid, target_id, target)
    if operation not in available:
        return _error("Недостаточно прав для этого действия", 403)

    # Check actual Telegram membership even if NORA database rank appears lower.
    # A transient Bot API error fails closed, never applies punitive actions.
    if operation != "delete":
        try:
            member = await bot.get_chat_member(chat_id, target_id)
        except TelegramAPIError:
            logger.exception("Unable to verify target's Telegram membership")
            return _error("Не удалось проверить права участника в Telegram", 503)
        if member.status in {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}:
            return _error("Нельзя применить действие к администратору Telegram", 403)

    canonical = json.dumps({
        "scope": "staff-moderation-v1", "chat_id": chat_id, "message_id": mid,
        "target_id": target_id, "action": operation, "reason": reason.strip(),
        "duration": duration_key,
    }, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    result, receipt = await dispatch.claim(db, uid, op_id, digest)
    if result == "conflict":
        return _error("Идентификатор используется для другого действия", 409)
    if result == "existing":
        return web.json_response(dispatch.response_data(receipt),
                                 headers={"Cache-Control": "no-store"})
    # From this point the idempotency record is durable before a side effect.
    try:
        name = person_label(target, source["author_name"])
        action_details = f"Mini App NORA · исходное сообщение {mid}"
        if operation == "delete":
            await bot.delete_message(chat_id, mid)
            await discard(db, settings, chat_id, [mid])
            log_action = "delete_message"
            log_target = str(target_id) if target else str(mid)
        elif operation == "mute":
            await bot.restrict_chat_member(
                chat_id, target_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.now(UTC)+DURATIONS[duration_key],
            )
            log_action, log_target = "mute", str(target_id)
        elif operation == "unmute":
            from community_bot.routers.group import _full_permissions
            await bot.restrict_chat_member(
                chat_id, target_id, permissions=_full_permissions(),
            )
            log_action, log_target = "unmute", str(target_id)
        elif operation == "warn":
            warnings = await db.add_warning(target_id)
            # Existing warning ladder stays active in Mini App too.
            from community_bot.routers.life import apply_warn_ladder
            from types import SimpleNamespace
            ladder = await apply_warn_ladder(
                bot, SimpleNamespace(chat=SimpleNamespace(id=chat_id)), target_id, warnings,
            )
            action_details += f" · всего предупреждений: {warnings}{ladder}"
            log_action, log_target = "warn", str(target_id)
        elif operation == "unwarn":
            warnings = await db.remove_warning(target_id)
            action_details += f" · осталось предупреждений: {warnings}"
            log_action, log_target = "unwarn", str(target_id)
        elif operation == "kick":
            await bot.ban_chat_member(chat_id, target_id)
            await bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
            log_action, log_target = "kick", str(target_id)
        elif operation == "ban":
            extra = ({"until_date": datetime.now(UTC)+DURATIONS[duration_key]}
                     if duration_key != "forever" else {})
            await bot.ban_chat_member(chat_id, target_id, **extra)
            # Exact same ban-reset semantics as the group /ban command.
            until = extra["until_date"].timestamp() if extra else None
            await db.reset_banned_user(target_id, until)
            log_action, log_target = "ban", str(target_id)
        else:  # unban
            await bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
            await db.release_ban_reset(target_id)
            log_action, log_target = "unban", str(target_id)

        action_details += f" · {duration_key}" if duration_key else ""
        await db.log_admin_action(
            uid, log_action, log_target, action_details,
            reason=reason.strip(), target_name=name,
        )
        await dispatch.finish(db, uid, op_id, "sent")
        return web.json_response({"ok": True, "state": "sent", "operation_id": op_id,
                                  "action": operation, "message_id": mid})
    except TelegramRetryAfter as exc:
        logger.warning("Moderation rate limit: %s", exc)
        await dispatch.finish(db, uid, op_id, "uncertain", error="Ограничение Telegram")
        return _error("Telegram ограничил действия. Проверь результат перед повтором", 429)
    except TelegramAPIError:
        logger.exception("Telegram rejected moderation action")
        await dispatch.finish(db, uid, op_id, "uncertain",
                              error="Неизвестно, применилось ли действие")
        return _error("Telegram не подтвердил действие. Проверь результат", 502)
    except Exception:
        logger.exception("NORA moderation result uncertain")
        await dispatch.finish(db, uid, op_id, "uncertain",
                              error="Действие могло примениться. Проверь журнал")
        return _error("Не удалось подтвердить результат. Не повторяй действие сразу", 500)
