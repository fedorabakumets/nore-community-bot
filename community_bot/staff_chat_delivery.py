"""Durable staff-chat send receipts.

Telegram Bot API has no idempotency key for sendMessage / sendMediaGroup.
A committed claim stops duplicate requests; an uncertain response is never
automatically retried as a new send.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from aiohttp import web

KEY_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$")
STATES = {"sending", "sent", "uncertain", "failed"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS staff_chat_dispatches (
    user_id INTEGER NOT NULL,
    operation_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('sending','sent','uncertain','failed')),
    message_ids_json TEXT NOT NULL DEFAULT '[]',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, operation_id)
);
CREATE INDEX IF NOT EXISTS idx_staff_chat_dispatches_recent
    ON staff_chat_dispatches(user_id, created_at DESC);
"""


def validate_key(value: Any) -> str | None:
    if value is None or value == "":
        return None  # Older cached Mini Apps remain compatible.
    if not isinstance(value, str) or not KEY_RE.fullmatch(value):
        raise ValueError("Некорректный идентификатор отправки")
    return value


def payload_hash(chat: int, text: str, reply_to: int | None, kind: str,
                 files: list[tuple[str, bytes]]) -> str:
    parts = {
        "chat": chat, "text": text, "reply_to": reply_to, "kind": kind,
        "files": [
            [name, hashlib.sha256(content).hexdigest()] for name, content in files
        ],
    }
    return hashlib.sha256(
        json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def read(db, uid: int, operation_id: str) -> dict | None:
    return await db.fetchone(
        """SELECT operation_id,payload_hash,status,message_ids_json,error,created_at,updated_at
           FROM staff_chat_dispatches WHERE user_id=? AND operation_id=?""",
        (uid, operation_id),
    )


def response_data(row: dict) -> dict:
    state = row["status"]
    if state == "sending":
        try:
            when = datetime.fromisoformat(row["created_at"] + "+00:00")
            if (datetime.now(UTC) - when).total_seconds() > 75:
                state = "uncertain"
        except (ValueError, TypeError):
            state = "uncertain"
    ids = json.loads(row["message_ids_json"] or "[]")
    return {
        "ok": state == "sent", "state": state,
        "operation_id": row["operation_id"],
        "message_id": ids[0] if ids else None,
        "message_ids": ids,
        "error": row["error"] or "",
    }


async def claim(db, uid: int, operation_id: str, digest: str) -> tuple[str, dict]:
    """Atomic across requests, processes and restarts, not just an asyncio lock."""
    async with db.connect() as connection:
        await connection.execute("BEGIN IMMEDIATE")
        cursor = await connection.execute(
            """SELECT operation_id,payload_hash,status,message_ids_json,error,created_at,updated_at
               FROM staff_chat_dispatches WHERE user_id=? AND operation_id=?""",
            (uid, operation_id),
        )
        found = await cursor.fetchone()
        if found is not None:
            row = dict(found)
            await connection.commit()
            return "conflict" if row["payload_hash"] != digest else "existing", row
        await connection.execute(
            """INSERT INTO staff_chat_dispatches(user_id,operation_id,payload_hash,status)
               VALUES(?,?,?,'sending')""",
            (uid, operation_id, digest),
        )
        await connection.commit()
    return "new", {
        "operation_id": operation_id, "payload_hash": digest,
        "status": "sending", "message_ids_json": "[]", "error": "",
        "created_at": datetime.now(UTC).isoformat(),
    }


async def finish(db, uid: int, operation_id: str, state: str,
                 ids: list[int] | None = None, error: str = "") -> None:
    if state not in STATES - {"sending"}:
        raise ValueError("Invalid dispatch state")
    # Only the original sender can settle a claim.
    await db.execute(
        """UPDATE staff_chat_dispatches
           SET status=?,message_ids_json=?,error=?,updated_at=CURRENT_TIMESTAMP
           WHERE user_id=? AND operation_id=? AND status='sending'""",
        (state, json.dumps(ids or []), error[:250], uid, operation_id),
    )


async def status(request: web.Request) -> web.Response:
    from community_bot.staff_chat import staff_allowed

    db, settings = request.app["db"], request.app["settings"]
    uid = request["actor"]["id"]
    if not await staff_allowed(db, settings, uid):
        return web.json_response({"error": "Нет доступа к чату"}, status=403)
    try:
        operation_id = validate_key(request.match_info["operation_id"])
    except ValueError:
        return web.json_response({"error": "Некорректная отправка"}, status=400)
    if not operation_id:
        return web.json_response({"error": "Некорректная отправка"}, status=400)
    row = await read(db, uid, operation_id)
    if row is None:
        return web.json_response({"error": "Отправка не найдена", "state": "unknown"}, status=404,
                                 headers={"Cache-Control": "no-store"})
    return web.json_response(response_data(row), headers={"Cache-Control": "no-store"})
