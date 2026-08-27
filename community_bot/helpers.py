from __future__ import annotations

import html
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message, User

from community_bot.config import Settings
from community_bot.database import Database
from community_bot.domain import ROLE_LABELS, reputation_tier


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
    if user_id == settings.owner_id:
        return "owner"
    if user_id in settings.moderator_ids:
        user = await db.get_user(user_id)
        if user and user["role"] in {"admin", "owner"}:
            return str(user["role"])
        return "moderator"
    user = await db.get_user(user_id)
    return str(user["role"]) if user else "member"


def is_immunity_active(value: str | None) -> bool:
    if not value:
        return False
    try:
        return datetime.fromisoformat(value).astimezone(UTC) > datetime.now(UTC)
    except ValueError:
        return False


def profile_text(user: dict[str, Any], settings: Settings) -> str:
    tier = reputation_tier(int(user["reputation"]), settings.restricted_reputation_threshold)
    name = user["profile_name"] or user["telegram_name"] or f"ID {user['user_id']}"
    username = f"@{user['username']}" if user["username"] else "не указан"
    role = str(user["role"])
    role_icons = {"owner": "👑", "admin": "🛡", "moderator": "🔨", "member": "👤"}
    role_labels = {
        "owner": "Владелец",
        "admin": "Администратор",
        "moderator": "Модератор",
        "member": "Участник",
    }
    hobbies = user["hobbies"] or "не указаны"
    age = user["age"] or "не указан"
    reputation = int(user["reputation"])
    filled = round(max(0, min(100, reputation)) / 10)
    progress = "█" * filled + "░" * (10 - filled)
    lines = [
        "✦ <b>NORA COMMUNITY</b> ✦",
        "",
        f"👤 <b>{user_link(int(user['user_id']), str(name))}</b>",
        f"{role_icons.get(role, '👤')} <b>{role_labels.get(role, ROLE_LABELS.get(role, 'Участник'))}</b>",
    ]
    if user["custom_status"]:
        lines.append(f"💬 <i>«{html.escape(str(user['custom_status']))}»</i>")
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


async def resolve_reply_target(message: Message, db: Database) -> dict[str, Any] | None:
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return None
    target = message.reply_to_message.from_user
    return await register_telegram_user(db, target)
