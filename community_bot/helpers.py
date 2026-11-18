from __future__ import annotations

import asyncio
import html
import logging
import secrets
from datetime import UTC, date, datetime
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message, User

from community_bot.aliases import message_trigger, parse_trigger, split_target_argument
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.domain import (
    NEGATIVE_REPUTATION_PHRASES,
    POSITIVE_REPUTATION_PHRASES,
    ROLE_LABELS,
    ROLE_LEVELS,
    reputation_delta,
    reputation_tier,
)
from community_bot.permissions import (
    PERM_SEE_PRIVATE,
    parse_permissions,
    role_has_permission,
)
from community_bot.profile_fields import profile_age
from community_bot.profile_fill import profile_fill_percent

BOT_REPLY_TTL = 30.0
logger = logging.getLogger(__name__)


async def register_telegram_user(db: Database, user: User) -> dict[str, Any]:
    row = await db.ensure_user(user.id, user.username, user.full_name)
    if user.is_bot:
        await db.set_bot_state(f"telegram_is_bot:{user.id}", "1")
    return row


def lobby_count_ok(count: int, minimum: int, maximum: int, staff: bool) -> bool:
    if count < 1 or count > maximum:
        return False
    if staff:
        return True
    return minimum <= count <= maximum


def telegram_message_link(chat_id: int, message_id: int) -> str:
    raw = str(chat_id)
    if raw.startswith("-100"):
        return f"https://t.me/c/{raw[4:]}/{message_id}"
    return f"https://t.me/c/{abs(chat_id)}/{message_id}"


def parse_warn_source(details: str) -> tuple[int, int] | None:
    for part in str(details or "").split("|"):
        part = part.strip()
        if part.startswith("src:"):
            bits = part.split(":")
            if len(bits) == 3 and bits[1].lstrip("-").isdigit() and bits[2].isdigit():
                return int(bits[1]), int(bits[2])
    return None


def format_warn_entry(row: dict[str, Any], index: int) -> str:
    when = str(row.get("created_at") or "")[:16].replace("T", " ")
    reason = html.escape(str(row.get("reason") or "без причины"))
    actor = html.escape(str(row.get("actor_name") or row.get("actor_display") or "неизвестно"))
    if int(row.get("actor_id") or 0) == 0:
        actor = "Система"
    lines = [
        f"<b>#{index}</b> · {html.escape(when)}",
        f"Причина: {reason}",
        f"Выдал: {actor}",
    ]
    source = parse_warn_source(str(row.get("details") or ""))
    if source:
        link = telegram_message_link(source[0], source[1])
        lines.append(f'<a href="{link}">Сообщение</a>')
    return "\n".join(lines)


def user_link(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'


def display_name(user: dict[str, Any] | None, fallback: str = "неизвестный") -> str:
    from community_bot.audit import person_label

    return person_label(user, fallback)


async def delete_later(message: Message, delay: float = BOT_REPLY_TTL) -> None:
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError) as error:
        logger.warning(
            "Не удалось удалить сообщение бота %s в чате %s: %s",
            message.message_id,
            message.chat.id,
            error,
        )


async def answer_group_ephemeral(
    message: Message,
    text: str,
    *,
    ttl: float | None = BOT_REPLY_TTL,
    **kwargs: Any,
) -> Message:
    sent = await message.answer(text, **kwargs)
    if ttl and message.chat.type in {"group", "supergroup"}:
        asyncio.create_task(delete_later(sent, ttl))
    return sent


def message_media(message: Message, *kinds: str):
    for kind in kinds:
        if media := getattr(message, kind, None):
            return kind, media
    if rich := getattr(message, "rich_message", None):
        for block in rich.blocks:
            kind = "voice" if block.type == "voice_note" else block.type
            if kind in kinds:
                return kind, getattr(block, block.type)
    return None, None


def media_from_message(message: Message) -> tuple[str | None, str | None]:
    kind, media = message_media(message, "photo", "document", "video", "audio", "voice", "animation")
    return kind, ((media[-1] if kind == "photo" else media).file_id if media else None)


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


async def application_block_reason(db: Database, user_id: int) -> str | None:
    if db.ban_is_active(await db.ban_reset_state(user_id)):
        return "Анкету можно заполнить после разбана."
    if await db.has_approved_application(user_id):
        return "Ты уже проходил анкету — повторно заполнять её нельзя."
    if await db.has_pending_application(user_id):
        return "Анкета уже на проверке. Решение придёт в этот чат."
    return None


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
    age = profile_age(user) or "не указан"
    reputation = int(user["reputation"])
    filled = round(max(0, min(100, reputation)) / 10)
    progress = "█" * filled + "░" * (10 - filled)
    lines = [
        "✦ <b>NORA COMMUNITY</b> ✦",
        "",
        f"👤 <b>{user_link(int(user['user_id']), str(name))}</b>",
        f"{role_icons.get(role, '💠')} <b>{html.escape(str(label))}</b>",
    ]
    bio = str(user.get("profile_bio") or "").strip()
    if bio:
        lines.append(f"📝 {html.escape(bio)}")
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
            f"🪪 <b>Верификация:</b> {profile_fill_percent(user)}%",
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
    age = profile_age(user) or "—"
    reputation = int(user["reputation"])
    filled = round(max(0, min(100, reputation)) / 10)
    progress = "◆" * filled + "◇" * (10 - filled)
    jewels = {"owner": "👑", "admin": "🛡", "moderator": "⚔️", "member": "🌙"}
    jewel = jewels.get(role, "💠")
    lock = "  🔒 скрыт от чужих глаз\n" if user.get("profile_private") else ""
    bio = str(user.get("profile_bio") or "").strip()
    bio_line = f"  📝  {html.escape(bio)}\n" if bio else ""
    return (
        "✧･ﾟ: *✧･ﾟ:*  <b>Ｎ Ｏ Ｒ Ａ</b>  *:･ﾟ✧*:･ﾟ✧\n"
        "\n"
        "╭─━━━━━━━━━━━━━━━━━─╮\n"
        f"   {jewel}  {user_link(int(user['user_id']), name)}\n"
        f"   ✦ {html.escape(str(label))} ✦\n"
        "╰─━━━━━━━━━━━━━━━━━─╯\n"
        f"{lock}"
        f"{bio_line}"
        f"  𓆩 {html.escape(username)} 𓆪\n"
        "\n"
        f"  🎂  {age}     🍪  {user['cookies']}\n"
        f"  🎯  {hobbies}\n"
        "\n"
        f"  {tier.emoji}  репутация  <b>{reputation}</b>/100\n"
        f"  <code>{progress}</code>\n"
        f"  ❖ {tier.label} · скидка {tier.discount}%\n"
        f"  ⚠️  предупреждения: {user['warnings']}\n"
        f"  🪪  верификация {profile_fill_percent(user)}%\n"
        "\n"
        "· · · ☽ ✦ ❋ ✦ ☾ · · ·"
    )


def compact_profile_text(user: dict[str, Any], settings: Settings, role_name: str) -> str:
    name = str(user.get("profile_name") or user.get("telegram_name") or f"ID {user['user_id']}")
    tier = reputation_tier(int(user["reputation"]), settings.restricted_reputation_threshold)
    identity = f" · @{html.escape(str(user['username']))}" if user.get("username") else ""
    lines = [
        f"<b>{user_link(int(user['user_id']), name)}</b>{identity}",
        f"{html.escape(role_display_name(str(user['role']), role_name))} · Возраст: {profile_age(user) or '—'}",
    ]
    if user.get("profile_private"):
        lines.append("🔒 Закрытый профиль")
    if user.get("profile_bio"):
        lines.append(html.escape(str(user["profile_bio"])))
    if user.get("hobbies"):
        lines.append(f"Увлечения: {html.escape(str(user['hobbies']))}")
    lines.extend([
        f"Репутация: {int(user['reputation'])}/100 · {tier.label} · скидка {tier.discount}%",
        f"🍪 {user['cookies']} · Профиль: {profile_fill_percent(user)}% · Варны: {user['warnings']}",
    ])
    return "\n".join(lines)


async def render_profile(db: Database, settings: Settings, user: dict[str, Any], *, compact: bool = False) -> str:
    from community_bot.life import achievement_lines

    title = await role_title(db, str(user["role"]))
    text = compact_profile_text(user, settings, title) if compact else profile_text(user, settings, title)
    extra = achievement_lines(await db.list_achievements(int(user["user_id"])))
    if extra:
        return f"{text}\n{extra}"
    return text


async def can_view_profile(db: Database, settings: Settings, actor_id: int, target: dict[str, Any]) -> bool:
    if actor_id == int(target["user_id"]):
        return True
    if not target.get("profile_private"):
        return True
    return await has_permission(db, settings, actor_id, PERM_SEE_PRIVATE)


async def pet_guard_reputation(
    db: Database,
    target_id: int,
    delta: int,
    action_date: date | None = None,
) -> tuple[int, str | None]:
    if delta >= 0:
        return delta, None
    pet = await db.get_pet(target_id)
    if not pet or int(pet.get("sleeping") or 0) or int(pet.get("hunger") or 0) < 70:
        return delta, None
    used_on = str(pet.get("guard_used_on") or "")
    today = (action_date or datetime.now(UTC).date()).isoformat()
    if used_on == today:
        return delta, None
    chance = 5 + max(0, min(100, int(pet.get("mood") or 0))) * 25 // 100
    if secrets.randbelow(100) >= chance:
        return delta, None
    await db.mark_pet_guard(target_id, today)
    name = html.escape(str(pet["name"]))
    return 0, f"🐾 Сытый <b>{name}</b> перехватил −реп и спрятал его в норке."


async def resolve_reply_target(message: Message, db: Database) -> dict[str, Any] | None:
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return None
    target = message.reply_to_message.from_user
    return await register_telegram_user(db, target)


async def resolve_member_mention(db: Database, mention: str | User) -> dict[str, Any] | None:
    if isinstance(mention, User):
        return await register_telegram_user(db, mention)
    matches = await db.fetchall("SELECT * FROM users WHERE username = ? COLLATE NOCASE LIMIT 2", (mention,))
    return matches[0] if len(matches) == 1 else None


async def resolve_command_target(
    message: Message, db: Database, *, after_first: bool = False,
) -> tuple[dict[str, Any] | None, list[str], bool]:
    source = getattr(message, "text", None) or getattr(message, "caption", None) or ""
    parsed = message_trigger(message) or parse_trigger(source)
    args = parsed[1] if parsed else ""
    mention, rest = split_target_argument(message, args)
    if mention is None and after_first:
        parts = args.split(maxsplit=1)
        if len(parts) == 2:
            candidate, remaining = split_target_argument(message, parts[1])
            if candidate is not None and not remaining:
                mention, rest = candidate, parts[0]
    if mention is not None:
        return await resolve_member_mention(db, mention), rest.split(), True
    return await resolve_reply_target(message, db), args.split(), False


def reputation_interaction(message: Message) -> tuple[int, str | User | None] | None:
    text = (message.text or "").strip()
    delta = reputation_delta(text)
    if delta is not None and message.reply_to_message:
        return delta, None
    for phrase in POSITIVE_REPUTATION_PHRASES | NEGATIVE_REPUTATION_PHRASES:
        if not text.casefold().startswith(phrase + " "):
            continue
        mention, rest = split_target_argument(message, text[len(phrase):].strip())
        if mention is not None and not rest:
            return (5 if phrase in POSITIVE_REPUTATION_PHRASES else -5), mention
    return None
