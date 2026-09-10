from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from community_bot.database import Database
from community_bot.updates import BotUpdate, member_details_nodes, member_details_text

logger = logging.getLogger(__name__)

_API = "https://api.telegra.ph"


async def _call(method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    form: dict[str, str] = {}
    for key, value in payload.items():
        if key == "content":
            form[key] = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            form[key] = "true" if value else "false"
        else:
            form[key] = str(value)
    try:
        async with aiohttp.ClientSession() as session:
            timeout = aiohttp.ClientTimeout(total=12)
            async with session.post(f"{_API}/{method}", data=form, timeout=timeout) as resp:
                data = await resp.json(content_type=None)
    except Exception:
        logger.exception("Telegraph %s не ответил", method)
        return None
    if not isinstance(data, dict) or not data.get("ok"):
        logger.warning("Telegraph %s: %s", method, data)
        return None
    result = data.get("result")
    return result if isinstance(result, dict) else None


async def ensure_token(db: Database) -> str | None:
    stored = await db.get_bot_state("telegraph_token")
    if stored:
        return stored
    account = await _call("createAccount", {"short_name": "NORA", "author_name": "НОРА"})
    token = str((account or {}).get("access_token") or "").strip()
    if not token:
        return None
    await db.set_bot_state("telegraph_token", token)
    return token


async def publish_member_update(db: Database, item: BotUpdate) -> str | None:
    token = await ensure_token(db)
    if not token:
        return None
    path = await db.get_bot_state("telegraph_path")
    payload: dict[str, Any] = {
        "access_token": token,
        "title": f"НОРА · {item.title}",
        "author_name": "НОРА",
        "content": member_details_nodes(item),
        "return_content": False,
    }
    if path:
        payload["path"] = path
        result = await _call("editPage", payload)
    else:
        result = await _call("createPage", payload)
    if not result:
        if path:
            result = await _call("createPage", {k: v for k, v in payload.items() if k != "path"})
        else:
            return None
    url = str((result or {}).get("url") or "").strip()
    new_path = str((result or {}).get("path") or "").strip()
    if new_path:
        await db.set_bot_state("telegraph_path", new_path)
    if url:
        await db.set_bot_state("telegraph_url", url)
    return url or None


def member_dm_text(item: BotUpdate) -> str:
    return member_details_text(item)
