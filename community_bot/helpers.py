from __future__ import annotations

import html
import secrets
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message, User

from community_bot.config import Settings
from community_bot.database import Database
from community_bot.domain import ROLE_LABELS, ROLE_LEVELS, reputation_tier
from community_bot.permissions import (
    PERM_SEE_PRIVATE,
    parse_permissions,
    role_has_permission,
)


async def register_telegram_user(db: Database, user: User) -> dict[str, Any]:
    return await db.ensure_user(user.id, user.username, user.full_name)


def user_link(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'


def media_from_message(message: Message) -> tuple[str | None, str | None]:
    if message.photo:
        return "photo", message.photo[-1].file_id
    if message.document:
        return "document", message.document.file_id
    if message.video:
        return "video", message.video.file_id
    if message.audio:
        return "audio", message.audio.file_id
    if message.voice:
        return "voice", message.voice.file_id
    if message.animation:
        return "animation", message.animation.file_id
    return None, None


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs: Any) -> bool:
    try:
        await bot.send_message(chat_id, text, **kwargs)
        return True
    except (TelegramForbiddenError, TelegramBadRequest):
        return False


async def send_stored_message(
    bot: Bot,
    chat_id: int,
    text: str | None,
    media_type: str | None,
    media_file_id: str | None,
) -> bool:
    try:
        if not media_type or not media_file_id:
            await bot.send_message(chat_id, text or "")
        elif media_type == "photo":
            await bot.send_photo(chat_id, media_file_id, caption=text)
        elif media_type == "document":
            await bot.send_document(chat_id, media_file_id, caption=text)
        elif media_type == "video":
            await bot.send_video(chat_id, media_file_id, caption=text)
        elif media_type == "audio":
            await bot.send_audio(chat_id, media_file_id, caption=text)
        elif media_type == "voice":
            await bot.send_voice(chat_id, media_file_id, caption=text)
        elif media_type == "animation":
            await bot.send_animation(chat_id, media_file_id, caption=text)
        else:
            return False
        return True
    except (TelegramForbiddenError, TelegramBadRequest):
        return False


async def effective_role(db: Database, settings: Settings, user_id: int) -> str:
    if settings.is_owner(user_id):
        return "owner"
    user = await db.get_user(user_id)
    stored = str(user["role"]) if user else "member"
    if stored == "owner" or await db.get_staff_role(stored):
        if user_id in settings.moderator_ids and stored == "member":
            return "moderator"
        return stored
    if user_id in settings.moderator_ids:
        return "moderator"
    return stored


async def rank_of_role(db: Database, slug: str) -> int:
    role = await db.get_staff_role(slug)
    if role:
        return int(role["rank"])
    return int(ROLE_LEVELS.get(slug, 0))


async def rank_of_user(db: Database, settings: Settings, user_id: int) -> int:
    if settings.is_owner(user_id):
        return 1000
    return await rank_of_role(db, await effective_role(db, settings, user_id))


async def role_title(db: Database, slug: str) -> str:
    role = await db.get_staff_role(slug)
    if role:
        return str(role["name"])
    return ROLE_LABELS.get(slug, slug)


async def user_permissions(db: Database, settings: Settings, user_id: int) -> list[str]:
    if settings.is_owner(user_id):
        return ["*"]
    slug = await effective_role(db, settings, user_id)
    role = await db.get_staff_role(slug)
    if not role:
        return ["*"] if slug == "owner" else []
    if role["permissions"]:
        return list(role["permissions"])
    return parse_permissions(str(role.get("permissions_json") or "[]"))


async def has_permission(db: Database, settings: Settings, user_id: int, permission: str) -> bool:
    return role_has_permission(await user_permissions(db, settings, user_id), permission)


async def can_manage_user(db: Database, settings: Settings, actor_id: int, target_id: int) -> bool:
    if settings.is_owner(actor_id):
        return True
    if settings.is_owner(target_id):
        return False
    return await rank_of_user(db, settings, actor_id) > await rank_of_user(db, settings, target_id)


def is_immunity_active(value: str | None) -> bool:
    if not value:
        return False
    try:
        return datetime.fromisoformat(value).astimezone(UTC) > datetime.now(UTC)
    except ValueError:
        return False


def role_display_name(slug: str, role_name: str | None = None) -> str:
    if role_name:
        return role_name
    pretty = {
        "owner": "Владелец",
        "admin": "Администратор",
        "moderator": "Модератор",
        "member": "Участник",
    }
    return pretty.get(slug, ROLE_LABELS.get(slug, slug))


def profile_text(user: dict[str, Any], settings: Settings, role_name: str | None = None) -> str:
    if user.get("profile_ornate"):
        return ornate_profile_text(user, settings, role_name)
    tier = reputation_tier(int(user["reputation"]), settings.restricted_reputation_threshold)
    name = user["profile_name"] or user["telegram_name"] or f"ID {user['user_id']}"
    username = f"@{user['username']}" if user["username"] else "не указан"
    role = str(user["role"])
    role_icons = {"owner": "👑", "admin": "🛡", "moderator": "🔨", "member": "👤"}
    label = role_display_name(role, role_name)
    hobbies = user["hobbies"] or "не указаны"
    age = user["age"] or "не указан"
    reputation = int(user["reputation"])
    filled = round(max(0, min(100, reputation)) / 10)
    progress = "█" * filled + "░" * (10 - filled)
    lines = [
        "✦ <b>NORA COMMUNITY</b> ✦",
        "",
        f"👤 <b>{user_link(int(user['user_id']), str(name))}</b>",
        f"{role_icons.get(role, '💠')} <b>{html.escape(str(label))}</b>",
    ]
    if user["custom_status"]:
        lines.append(f"💬 <i>«{html.escape(str(user['custom_status']))}»</i>")
    if user.get("profile_private"):
        lines.append("🔒 <i>Профиль скрыт от посторонних</i>")
    lines.extend(
        [
            f"🔗 {html.escape(username)}",
            "",
            f"🎂 <b>Возраст:</b> {age}",
            f"🎯 <b>Увлечения:</b> {html.escape(str(hobbies))}",
            "",
            "━━━━━━━━━━━━━━",
            f"{tier.emoji} <b>Репутация:</b> {reputation}/100 · {tier.label}",
            f"🏷 <b>Уровень:</b> {tier.emoji} {tier.label} · скидка {tier.discount}%",
            f"<code>{progress}</code>",
            f"🍪 <b>Печеньки:</b> {user['cookies']}",
            f"⚠️ <b>Предупреждения:</b> {user['warnings']}",
        ]
    )
    return "\n".join(lines)


def ornate_profile_text(user: dict[str, Any], settings: Settings, role_name: str | None = None) -> str:
    tier = reputation_tier(int(user["reputation"]), settings.restricted_reputation_threshold)
    name = str(user["profile_name"] or user["telegram_name"] or f"ID {user['user_id']}")
    username = f"@{user['username']}" if user["username"] else "без юзернейма"
    role = str(user["role"])
    label = role_display_name(role, role_name)
    hobbies = html.escape(str(user["hobbies"] or "пока тайна"))
    age = user["age"] or "—"
    reputation = int(user["reputation"])
    filled = round(max(0, min(100, reputation)) / 10)
    progress = "◆" * filled + "◇" * (10 - filled)
    jewels = {"owner": "👑", "admin": "🛡", "moderator": "⚔️", "member": "🌙"}
    jewel = jewels.get(role, "💠")
    status = (
        f"\n     <i>❝ {html.escape(str(user['custom_status']))} ❞</i>\n" if user.get("custom_status") else "\n"
    )
    lock = "  🔒 скрыт от чужих глаз\n" if user.get("profile_private") else ""
    return (
        "✧･ﾟ: *✧･ﾟ:*  <b>Ｎ Ｏ Ｒ Ａ</b>  *:･ﾟ✧*:･ﾟ✧\n"
        "\n"
        "╭─━━━━━━━━━━━━━━━━━─╮\n"
        f"   {jewel}  {user_link(int(user['user_id']), name)}\n"
        f"   ✦ {html.escape(str(label))} ✦\n"
        f"{status}"
        "╰─━━━━━━━━━━━━━━━━━─╯\n"
        f"{lock}"
        f"  𓆩 {html.escape(username)} 𓆪\n"
        "\n"
        f"  🎂  {age}     🍪  {user['cookies']}\n"
        f"  🎯  {hobbies}\n"
        "\n"
        f"  {tier.emoji}  репутация  <b>{reputation}</b>/100\n"
        f"  <code>{progress}</code>\n"
        f"  ❖ {tier.label} · скидка {tier.discount}%\n"
        f"  ⚠️  предупреждения: {user['warnings']}\n"
        "\n"
        "· · · ☽ ✦ ❋ ✦ ☾ · · ·"
    )


async def render_profile(db: Database, settings: Settings, user: dict[str, Any]) -> str:
    title = await role_title(db, str(user["role"]))
    return profile_text(user, settings, title)


async def can_view_profile(db: Database, settings: Settings, actor_id: int, target: dict[str, Any]) -> bool:
    if actor_id == int(target["user_id"]):
        return True
    if not target.get("profile_private"):
        return True
    return await has_permission(db, settings, actor_id, PERM_SEE_PRIVATE)


async def pet_guard_reputation(db: Database, target_id: int, delta: int) -> tuple[int, str | None]:
    if delta == 0:
        return delta, None
    pet = await db.get_pet(target_id)
    if not pet or int(pet.get("sleeping") or 0) or int(pet.get("hunger") or 0) < 70:
        return delta, None
    name = html.escape(str(pet["name"]))
    if delta < 0 and secrets.randbelow(100) < 40:
        return 0, f"🐾 Сытый <b>{name}</b> перехватил −реп и спрятал его в норке."
    if delta > 0 and secrets.randbelow(100) < 35:
        doubled = delta * 2
        return doubled, f"🐾 Сытый <b>{name}</b> так обрадовался, что +реп удвоился: +{doubled}!"
    return delta, None


async def resolve_reply_target(message: Message, db: Database) -> dict[str, Any] | None:
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return None
    target = message.reply_to_message.from_user
    return await register_telegram_user(db, target)
