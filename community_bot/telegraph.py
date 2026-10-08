from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import aiohttp

from community_bot.database import Database
from community_bot.updates import BotUpdate, member_details_nodes, member_details_text

logger = logging.getLogger(__name__)

_API = "https://api.telegra.ph"
_UPLOAD = "https://telegra.ph/upload"
_ASSETS = Path(__file__).resolve().parent.parent / "assets" / "updates"
_COVERS = Path(__file__).resolve().parent.parent / "assets" / "covers"


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


async def upload_image(path: Path) -> str | None:
    exists = await asyncio.to_thread(path.is_file)
    if not exists:
        return None
    payload = await asyncio.to_thread(path.read_bytes)
    content_type = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    try:
        form = aiohttp.FormData()
        form.add_field("file", payload, filename=path.name, content_type=content_type)
        async with aiohttp.ClientSession() as session:
            timeout = aiohttp.ClientTimeout(total=20)
            async with session.post(_UPLOAD, data=form, timeout=timeout) as resp:
                data = await resp.json(content_type=None)
    except Exception:
        logger.exception("Telegraph upload не ответил")
        return None
    if not isinstance(data, list) or not data:
        logger.warning("Telegraph upload: %s", data)
        return None
    src = str((data[0] or {}).get("src") or "").strip()
    if src.startswith("http"):
        return src
    if src.startswith("/"):
        return f"https://telegra.ph{src}"
    return None


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


async def _section_images(item: BotUpdate) -> dict[str, str]:
    urls: dict[str, str] = {}
    seen: set[str] = set()
    for section in item.sections:
        name = section.image
        if not name or name in seen:
            continue
        seen.add(name)
        path = _ASSETS / name
        if not path.is_file():
            path = _COVERS / name
        url = await upload_image(path)
        if url:
            urls[name] = url
    return urls


async def publish_member_update(db: Database, item: BotUpdate) -> str | None:
    token = await ensure_token(db)
    if not token:
        return None
    path_key = f"telegraph_path_{item.number}"
    path = await db.get_bot_state(path_key)
    image_urls = await _section_images(item)
    payload: dict[str, Any] = {
        "access_token": token,
        "title": item.telegraph_title or f"НОРА · Обновление №{item.number}",
        "author_name": "НОРА",
        "content": member_details_nodes(item, image_urls),
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
        await db.set_bot_state(path_key, new_path)
    if url:
        await db.set_bot_state("telegraph_url", url)
    return url or None


async def publish_staff_update(db: Database, item: BotUpdate) -> str | None:
    if not item.staff_details:
        return None
    token = await ensure_token(db)
    if not token:
        return None
    path_key = f"staff_telegraph_path_{item.number}"
    path = await db.get_bot_state(path_key)
    nodes: list[dict[str, Any]] = [
        {"tag": "h3", "children": [f"Служебное обновление №{item.number}"]},
        {"tag": "h4", "children": [item.title]},
    ]
    nodes.extend({"tag": "p", "children": [line]} for line in item.staff_details)
    payload: dict[str, Any] = {
        "access_token": token,
        "title": f"{item.title} · служебное",
        "author_name": "НОРА",
        "content": nodes,
        "return_content": False,
    }
    if path:
        payload["path"] = path
        result = await _call("editPage", payload)
        if not result:
            result = await _call("createPage", {k: v for k, v in payload.items() if k != "path"})
    else:
        result = await _call("createPage", payload)
    if not result:
        return None
    url = str(result.get("url") or "").strip()
    new_path = str(result.get("path") or "").strip()
    if new_path:
        await db.set_bot_state(path_key, new_path)
    if url:
        await db.set_bot_state(f"staff_telegraph_url_{item.number}", url)
    return url or None


async def publish_commands_guide(db: Database) -> str | None:
    from community_bot.commands_guide import COMMANDS_PAGE_VERSION, commands_guide_nodes

    token = await ensure_token(db)
    if not token:
        return None
    version = await db.get_bot_state("commands_guide_version")
    stored_url = await db.get_bot_state("commands_guide_url")
    path = await db.get_bot_state("commands_guide_path")
    if stored_url and version == COMMANDS_PAGE_VERSION:
        return stored_url
    payload: dict[str, Any] = {
        "access_token": token,
        "title": "Команды НОРЫ",
        "author_name": "НОРА",
        "content": commands_guide_nodes(),
        "return_content": False,
    }
    if path:
        payload["path"] = path
        result = await _call("editPage", payload)
        if not result:
            result = await _call("createPage", {k: v for k, v in payload.items() if k != "path"})
    else:
        result = await _call("createPage", payload)
    if not result:
        return stored_url or None
    url = str(result.get("url") or "").strip()
    new_path = str(result.get("path") or "").strip()
    if new_path:
        await db.set_bot_state("commands_guide_path", new_path)
    if url:
        await db.set_bot_state("commands_guide_url", url)
        await db.set_bot_state("commands_guide_version", COMMANDS_PAGE_VERSION)
    return url or stored_url or None


async def publish_staff_guide(db: Database) -> str | None:
    from community_bot.staff_guide import STAFF_GUIDE_VERSION, staff_guide_nodes

    token = await ensure_token(db)
    if not token:
        return None
    version = await db.get_bot_state("staff_guide_version")
    stored_url = await db.get_bot_state("staff_guide_url")
    path = await db.get_bot_state("staff_guide_path")
    if stored_url and version == STAFF_GUIDE_VERSION:
        return stored_url
    payload: dict[str, Any] = {
        "access_token": token,
        "title": "НОРА · Справка админки",
        "author_name": "НОРА",
        "content": staff_guide_nodes(),
        "return_content": False,
    }
    if path:
        payload["path"] = path
        result = await _call("editPage", payload)
        if not result:
            result = await _call("createPage", {k: v for k, v in payload.items() if k != "path"})
    else:
        result = await _call("createPage", payload)
    if not result:
        return stored_url or None
    url = str(result.get("url") or "").strip()
    new_path = str(result.get("path") or "").strip()
    if new_path:
        await db.set_bot_state("staff_guide_path", new_path)
    if url:
        await db.set_bot_state("staff_guide_url", url)
        await db.set_bot_state("staff_guide_version", STAFF_GUIDE_VERSION)
    return url or stored_url or None


def member_dm_text(item: BotUpdate) -> str:
    return member_details_text(item)
