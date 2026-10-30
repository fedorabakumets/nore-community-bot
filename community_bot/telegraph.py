from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp

from community_bot.database import Database
from community_bot.updates import BotUpdate, member_details_nodes, member_details_text

logger = logging.getLogger(__name__)

_API = "https://api.telegra.ph"
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


_PUBLIC_REPOSITORY = "fedorabakumets/nore-community-bot"
_PUBLIC_REF = "refs/heads/cursor/nora-2-update-d133"
_IMAGE_OVERRIDES = {"profile.jpg": "18-profile.jpg", "wallet.jpg": "18-wallet.jpg"}


def public_image_url(path: Path) -> str | None:
    """Publish only known artwork directories; never expose local files or credentials."""
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"} or not path.is_file():
        return None
    relative = None
    for directory, prefix in ((_ASSETS, "updates"), (_COVERS, "covers")):
        try:
            tail = path.resolve().relative_to(directory.resolve())
        except ValueError:
            continue
        relative = f"assets/{prefix}/{tail.as_posix()}"
        break
    if relative is None:
        return None
    revision = os.getenv("RAILWAY_GIT_COMMIT_SHA", "")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
        revision = _PUBLIC_REF
    return f"https://raw.githubusercontent.com/{_PUBLIC_REPOSITORY}/{revision}/{quote(relative, safe='/')}"


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
    for section in item.sections:
        name = section.image
        if not name or name in urls:
            continue
        # Rendered menu cache is not committed and cannot be used as a public article URL.
        filename = _IMAGE_OVERRIDES.get(name, name)
        path = _ASSETS / filename
        url = public_image_url(path) or public_image_url(_COVERS / filename)
        if url:
            urls[name] = url
        else:
            logger.warning("Telegraph illustration missing from public artwork: %s", name)
    return urls


def _image_sources(nodes: list[dict[str, Any]]) -> set[str]:
    sources: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("tag") == "img":
            sources.add(str(node.get("attrs", {}).get("src", "")))
        children = node.get("children")
        if isinstance(children, list):
            sources.update(_image_sources(children))
    return sources


async def publish_member_update(
    db: Database, item: BotUpdate, *, update_current_url: bool = True, existing_only: bool = False,
) -> str | None:
    token = await ensure_token(db)
    if not token:
        return None
    path_key = f"telegraph_path_{item.number}"
    path = await db.get_bot_state(path_key)
    if existing_only and not path:
        return None
    image_urls = await _section_images(item)
    if not {section.image for section in item.sections if section.image}.issubset(image_urls):
        logger.warning("Member article postponed: release %s artwork is incomplete", item.number)
        return None
    payload: dict[str, Any] = {
        "access_token": token,
        "title": item.telegraph_title or f"НОРА · Обновление №{item.number}",
        "author_name": "НОРА",
        "content": member_details_nodes(item, image_urls),
        "return_content": True,
    }
    if path:
        payload["path"] = path
        result = await _call("editPage", payload)
    else:
        result = await _call("createPage", payload)
    if not result:
        if path and not existing_only:
            result = await _call("createPage", {k: v for k, v in payload.items() if k != "path"})
        else:
            return None
    if image_urls and not set(image_urls.values()).issubset(_image_sources((result or {}).get("content") or [])):
        logger.warning("Telegraph did not retain all requested illustrations for release %s", item.number)
        return None
    url = str((result or {}).get("url") or "").strip()
    new_path = str((result or {}).get("path") or "").strip()
    if new_path:
        await db.set_bot_state(path_key, new_path)
    if url:
        if update_current_url:
            await db.set_bot_state("telegraph_url", url)
        logger.info("Member article published: release=%s illustrations=%s url=%s", item.number, len(image_urls), url)
    return url or None


async def repair_member_images(db: Database) -> None:
    """Refresh the existing release-18 article once, without creating or announcing a new post."""
    from community_bot.updates import UPDATES

    marker = "telegraph_images_repaired_v1"
    if await db.get_bot_state(marker) == "1":
        return
    item = next((entry for entry in UPDATES if entry.number == 18), None)
    if item is None or not await db.get_bot_state("telegraph_path_18"):
        return
    expected = {section.image for section in item.sections if section.image}
    if not expected.issubset(await _section_images(item)):
        return
    if await publish_member_update(db, item, update_current_url=False, existing_only=True):
        await db.set_bot_state(marker, "1")


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
