from __future__ import annotations

import asyncio
import contextlib
import html
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    ChatPermissions,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from community_bot.aliases import command_or_alias, is_command_message, remainder_args
from community_bot.audit import SYSTEM_ACTOR_ID, parse_moderation_args, person_label
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.domain import (
    discounted_price,
    reputation_delta,
    reputation_tier,
    transfer_amount,
    transfer_commission_percent,
)
from community_bot.ephemeral import keep_in_chat
from community_bot.game_notify import notify_game_event, send_game_finale
from community_bot.helpers import (
    BOT_REPLY_TTL,
    can_manage_user,
    delete_later,
    display_name,
    effective_role,
    has_permission,
    rank_of_user,
    register_telegram_user,
    resolve_reply_target,
    safe_send,
    user_link,
    user_permissions,
)
from community_bot.keyboards import (
    admin_panel_keyboard,
    cookie_order_review_keyboard,
    cookie_packages_keyboard,
    flow_reply_keyboard,
    freebie_keyboard,
    pet_species_keyboard,
    profile_transfer_keyboard,
    public_profile_keyboard,
    roulette_invite_keyboard,
    sbp_payment_keyboard,
    shop_category_keyboard,
    shop_home_keyboard,
    transfer_keyboard,
)
from community_bot.permissions import (
    PERM_ADMIN_PANEL,
    PERM_BAN,
    PERM_KICK,
    PERM_MUTE,
    PERM_PAYMENTS,
    PERM_ROLES_ASSIGN,
    PERM_USERS_COOKIES,
    PERM_USERS_EDIT,
    PERM_WARN,
)
from community_bot.shop_catalog import IMMUNITY_HOURS, PET_SUPPLIES, SHOP_CATEGORIES, TITLE_ITEMS, shop_prices_for
from community_bot.states import CookiePurchase, FlexiblePurchase, ProfileEdit
from community_bot.texts import GROUP_COMMANDS_TEXT, REPUTATION_HELP_TEXT, STORE_HELP_TEXT

router = Router(name="community")


@router.my_chat_member()
async def remember_managed_channel(event: ChatMemberUpdated, db: Database) -> None:
    if event.chat.type == "channel" and event.new_chat_member.status in {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
    }:
        await db.set_bot_state("freebie_channel_id", str(event.chat.id))


class DeleteGroupCommandMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._messages: dict[tuple[int, int], deque[float]] = defaultdict(deque)
        self._admin_cache: dict[tuple[int, int], tuple[float, bool]] = {}

    async def _is_telegram_admin(self, bot: Bot, chat_id: int, user_id: int) -> bool:
        key = (chat_id, user_id)
        now_monotonic = time.monotonic()
        cached = self._admin_cache.get(key)
        if cached and now_monotonic - cached[0] < 60:
            return cached[1]
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            is_admin = member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
        except (TelegramBadRequest, TelegramForbiddenError):
            is_admin = False
        self._admin_cache[key] = (now_monotonic, is_admin)
        return is_admin

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        db = data.get("db")
        settings = data.get("settings")
        bot = data.get("bot")
        if isinstance(db, Database) and event.from_user:
            await register_telegram_user(db, event.from_user)
            if (
                isinstance(settings, Settings)
                and isinstance(bot, Bot)
                and event.chat.type in {"group", "supergroup"}
                and (not settings.community_chat_id or event.chat.id == settings.community_chat_id)
            ):
                flags = {str(row["key"]): bool(int(row["enabled"])) for row in await db.list_feature_flags()}
                activity_count, rewarded = await db.record_activity(
                    event.from_user.id,
                    event.chat.id,
                    flags.get("activity_rewards", True),
                )
                if rewarded and flags.get("activity_rewards", True):
                    pass
                chat_admin = await self._is_telegram_admin(bot, event.chat.id, event.from_user.id)
                member = (not chat_admin) and await rank_of_user(db, settings, event.from_user.id) < 40
                blocked_reason: str | None = None
                text = event.text or event.caption or ""
                media_filter_on = bool(flags.get("media_filter"))
                sticker_filter_on = bool(flags.get("sticker_filter"))
                if member and flags.get("quiet_hours"):
                    local_hour = datetime.now(ZoneInfo(settings.timezone)).hour
                    if 0 <= local_hour < 7:
                        blocked_reason = "Включён ночной режим: чат открыт с 07:00."
                if member and flags.get("raid_mode") and activity_count <= 2:
                    blocked_reason = "Включён рейд-режим: первые сообщения новых участников проходят проверку."
                contains_link = any(marker in text.casefold() for marker in ("http://", "https://", "t.me/"))
                if member and flags.get("link_filter") and contains_link:
                    blocked_reason = "Ссылки сейчас запрещены настройками чата."
                has_media = bool(
                    event.photo
                    or event.video
                    or event.document
                    or event.audio
                    or event.voice
                    or event.animation
                    or event.video_note
                )
                if member and media_filter_on and has_media:
                    blocked_reason = "Медиа сейчас запрещены настройками чата."
                if member and sticker_filter_on and event.sticker:
                    blocked_reason = "Стикеры сейчас запрещены настройками чата."
                if member and flags.get("anti_flood"):
                    key = (event.chat.id, event.from_user.id)
                    now_monotonic = time.monotonic()
                    bucket = self._messages[key]
                    bucket.append(now_monotonic)
                    while bucket and now_monotonic - bucket[0] > 10:
                        bucket.popleft()
                    if len(bucket) > 6:
                        blocked_reason = "Антифлуд: не больше 6 сообщений за 10 секунд."
                        with contextlib.suppress(TelegramBadRequest):
                            await bot.restrict_chat_member(
                                event.chat.id,
                                event.from_user.id,
                                permissions=ChatPermissions(can_send_messages=False),
                                until_date=datetime.now(UTC) + timedelta(minutes=5),
                            )
                if blocked_reason:
                    with contextlib.suppress(TelegramBadRequest):
                        await event.delete()
                    with contextlib.suppress(TelegramBadRequest, TelegramForbiddenError):
                        await bot.send_message(event.from_user.id, f"🛡 {blocked_reason}")
                    await db.log_admin_action(
                        SYSTEM_ACTOR_ID,
                        "delete_message",
                        str(event.from_user.id),
                        blocked_reason,
                        reason=blocked_reason,
                        actor_name="Система",
                        target_name=event.from_user.full_name,
                    )
                    return None
        result = await handler(event, data)
        return result


router.message.outer_middleware(DeleteGroupCommandMiddleware())


def _group_chat(message: Message) -> bool:
    return message.chat.type in {"group", "supergroup"}


async def _respond(
    message: Message,
    text: str,
    *,
    ephemeral: bool = True,
    ttl: float = BOT_REPLY_TTL,
    **kwargs: Any,
) -> Message:
    del ephemeral, ttl
    if is_command_message(message.text or message.caption or ""):
        return await message.answer(text, **kwargs)
    return await message.reply(text, **kwargs)


async def _delete_later(message: Message, delay: float = BOT_REPLY_TTL) -> None:
    await delete_later(message, delay)


async def _private_chat_notice(message: Message, bot: Bot) -> None:
    me = await bot.get_me()
    builder = InlineKeyboardBuilder()
    builder.button(text="Открыть бота", url=f"https://t.me/{me.username}?start=private")
    notice = await message.answer(
        "Чтобы получить личный ответ, сначала откройте бота и нажмите Start.",
        reply_markup=builder.as_markup(),
    )
    asyncio.create_task(_delete_later(notice))


async def _require_role(message: Message, db: Database, settings: Settings, minimum: str = "moderator") -> str | None:
    if not message.from_user:
        return None
    await register_telegram_user(db, message.from_user)
    role = await effective_role(db, settings, message.from_user.id)
    from community_bot.helpers import rank_of_role

    if await rank_of_user(db, settings, message.from_user.id) < await rank_of_role(db, minimum):
        await _respond(message, "Недостаточно прав для этой команды.")
        return None
    return role


async def _require_perm(message: Message, db: Database, settings: Settings, permission: str) -> str | None:
    if not message.from_user:
        return None
    await register_telegram_user(db, message.from_user)
    if not await has_permission(db, settings, message.from_user.id, permission):
        await _respond(message, "Недостаточно прав для этой команды.")
        return None
    return await effective_role(db, settings, message.from_user.id)


def _target_display(target: dict[str, object]) -> str:
    return user_link(int(target["user_id"]), display_name(target))


async def _can_manage_target(
    actor_id: int,
    target: dict[str, object],
    db: Database,
    settings: Settings,
) -> bool:
    return await can_manage_user(db, settings, actor_id, int(target["user_id"]))


def _full_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_invite_users=True,
    )


@router.message(command_or_alias("commands", "help"), F.chat.type.in_({"group", "supergroup"}))
async def group_commands(message: Message) -> None:
    await _respond(message, GROUP_COMMANDS_TEXT, parse_mode="HTML")


@router.message(command_or_alias("reputation"), F.chat.type.in_({"group", "supergroup"}))
async def reputation_help(message: Message) -> None:
    await _respond(message, REPUTATION_HELP_TEXT, parse_mode="HTML")


@router.message(command_or_alias("store"), F.chat.type.in_({"group", "supergroup"}))
async def store_help(message: Message) -> None:
    await _respond(message, STORE_HELP_TEXT, parse_mode="HTML")


@router.message(command_or_alias("updates"), F.chat.type.in_({"group", "supergroup"}))
async def group_updates(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    if not await has_permission(db, settings, message.from_user.id, PERM_ADMIN_PANEL):
        return
    from community_bot.updates import updates_text

    await _respond(message, updates_text(), parse_mode="HTML")


@router.message(command_or_alias("admin"), F.chat.type.in_({"group", "supergroup"}))
async def open_admin_from_group(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not message.from_user:
        return
    if not await has_permission(db, settings, message.from_user.id, PERM_ADMIN_PANEL):
        await _respond(message, "Недостаточно прав для админ-панели.")
        return
    pending = len(await db.pending_applications(limit=100))
    orders = await db.fetchone("SELECT COUNT(*) AS count FROM cookie_orders WHERE status = 'pending'")
    text = (
        "🛡 <b>Админ-панель</b>\n\n"
        f"Анкет на проверке: <b>{pending}</b>\n"
        f"Платежей на проверке: <b>{int(orders['count']) if orders else 0}</b>"
    )
    try:
        await bot.send_message(
            message.from_user.id,
            text,
            parse_mode="HTML",
            reply_markup=admin_panel_keyboard(
                await user_permissions(db, settings, message.from_user.id),
                await db.dashboard_stats(),
            ),
        )
    except (TelegramForbiddenError, TelegramBadRequest):
        await _private_chat_notice(message, bot)


@router.message(command_or_alias("card"), F.chat.type.in_({"group", "supergroup"}))
async def staff_user_card(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    if not (
        await has_permission(db, settings, message.from_user.id, PERM_USERS_EDIT)
        or await has_permission(db, settings, message.from_user.id, PERM_USERS_COOKIES)
        or await has_permission(db, settings, message.from_user.id, PERM_ADMIN_PANEL)
    ):
        return
    target = await resolve_reply_target(message, db)
    if not target:
        await _respond(message, "Ответьте «карточка» на сообщение человека.")
        return
    pet = await db.get_pet(int(target["user_id"]), settle=False)
    note = str(target.get("moderator_note") or "").strip() or "нет"
    pet_line = str(pet["name"]) if pet else "нет"
    with keep_in_chat():
        await _respond(
            message,
            f"👤 <b>{html.escape(person_label(target))}</b> · <code>{target['user_id']}</code>\n"
            f"Роль: {html.escape(str(target['role']))}\n"
            f"Репутация: <b>{target['reputation']}</b> · 🍪 {target['cookies']}\n"
            f"Варны: {target['warnings']} · щиты: {int(target.get('hate_shields') or 0)}\n"
            f"Титул: {html.escape(str(target.get('profile_title') or 'нет'))}\n"
            f"Питомец: {html.escape(str(pet_line))}\n"
            f"Заметка: {html.escape(note)}",
            parse_mode="HTML",
        )


@router.message(command_or_alias("id"))
async def show_identifiers(message: Message, bot: Bot) -> None:
    user_id = message.from_user.id if message.from_user else "—"
    text = f"Ваш Telegram ID: <code>{user_id}</code>\nID этого чата: <code>{message.chat.id}</code>"
    if _group_chat(message) and message.from_user:
        try:
            await bot.send_message(message.from_user.id, text, parse_mode="HTML")
        except (TelegramForbiddenError, TelegramBadRequest):
            await _private_chat_notice(message, bot)
        return
    await message.answer(text, parse_mode="HTML")


@router.message(command_or_alias("mute"), F.chat.type.in_({"group", "supergroup"}))
async def mute_member(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not await _require_perm(message, db, settings, PERM_MUTE) or not message.from_user:
        return
    target = await resolve_reply_target(message, db)
    if not target:
        await _respond(message, "Ответьте командой на сообщение пользователя: /mute 30m причина")
        return
    duration, reason, explicit = parse_moderation_args(message.text or "")
    until = datetime.now(UTC) + duration
    minutes = max(1, int(duration.total_seconds() // 60))
    label = f"{minutes} мин" if minutes < 120 else f"{minutes // 60} ч"
    await bot.restrict_chat_member(
        message.chat.id,
        int(target["user_id"]),
        permissions=ChatPermissions(can_send_messages=False),
        until_date=until,
    )
    await db.log_admin_action(
        message.from_user.id,
        "mute",
        str(target["user_id"]),
        label,
        reason=reason,
        actor_name=message.from_user.full_name,
        target_name=person_label(target),
        default_duration=not explicit,
    )
    note = f" · {reason}" if reason else " · без причины"
    await _respond(
        message,
        f"🔇 {_target_display(target)} получает мут на {label}{note}.",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("profile_action:"), F.message.chat.type.in_({"group", "supergroup"}))
async def profile_action(callback: CallbackQuery, db: Database, settings: Settings, bot: Bot) -> None:
    if not callback.data or not callback.message:
        return
    _, action, raw_target_id = callback.data.split(":")
    target_id = int(raw_target_id)
    target = await db.get_user(target_id)
    if not target:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    if action == "transfer":
        if callback.from_user.id == target_id:
            await callback.answer("Нельзя перевести печеньки самому себе.", show_alert=True)
            return
        await callback.message.edit_reply_markup(reply_markup=profile_transfer_keyboard(target_id))
        await callback.answer("Выберите сумму перевода.")
        return
    if action == "back":
        await callback.message.edit_reply_markup(reply_markup=public_profile_keyboard(target_id))
        await callback.answer()
        return
    actor = await register_telegram_user(db, callback.from_user)
    if callback.from_user.id == target_id:
        await callback.answer("С собой это действие выполнить нельзя.", show_alert=True)
        return
    if action == "hug":
        tier = reputation_tier(int(actor["reputation"]), settings.restricted_reputation_threshold)
        if tier.daily_actions == 0:
            await callback.answer(
                "Ваш уровень репутации не позволяет взаимодействовать с участниками.",
                show_alert=True,
            )
            return
        await callback.answer("Объятия отправлены 💌")
        await callback.message.answer(
            f"💌 {user_link(callback.from_user.id, callback.from_user.full_name)} обнимает "
            f"{_target_display(target)} 🤗",
            parse_mode="HTML",
        )
        return
    delta = 5 if action == "rep_up" else -5
    timezone = ZoneInfo(settings.timezone)
    local_date = datetime.now(timezone).date()
    from community_bot.reputation import change_community_reputation

    ok, text, new_value, pet_line = await change_community_reputation(
        db, settings, actor, target, delta, local_date
    )
    if not ok or new_value is None:
        await callback.answer(text, show_alert=True)
        return
    target_tier = reputation_tier(new_value, settings.restricted_reputation_threshold)
    await callback.answer("Питомец вмешался!" if pet_line and "перехватил" in pet_line else text[:180])
    extra = f"\n{pet_line}" if pet_line else ""
    await callback.message.answer(
        f"{target_tier.emoji} {_target_display(target)}: {html.escape(text)}{extra}",
        parse_mode="HTML",
    )
    if new_value < settings.restricted_reputation_threshold:
        try:
            await bot.restrict_chat_member(
                callback.message.chat.id,
                target_id,
                permissions=ChatPermissions(can_send_messages=False),
            )
            await callback.message.answer("🔞 Пользователь ограничен: доступен только магазин в личном чате с ботом.")
        except TelegramBadRequest:
            pass


@router.callback_query(F.data.startswith("profile_transfer:"), F.message.chat.type.in_({"group", "supergroup"}))
async def profile_transfer(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    _, raw_target_id, raw_amount = callback.data.split(":")
    target_id = int(raw_target_id)
    amount = int(raw_amount)
    if callback.from_user.id == target_id:
        await callback.answer("Нельзя перевести печеньки самому себе.", show_alert=True)
        return
    sender = await register_telegram_user(db, callback.from_user)
    target = await db.get_user(target_id)
    if not target:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    if amount > int(sender["cookies"]):
        await callback.answer(f"Недостаточно печенек. Ваш баланс: {sender['cookies']} 🍪.", show_alert=True)
        return
    percent = transfer_commission_percent(int(sender["reputation"]))
    received = amount * (100 - percent) // 100
    transfer_id = await db.create_transfer(callback.from_user.id, target_id, amount)
    await callback.message.edit_reply_markup(reply_markup=public_profile_keyboard(target_id))
    await callback.answer("Подтвердите перевод.")
    await callback.message.answer(
        f"Перевести {_target_display(target)} {amount} 🍪?\n"
        f"Комиссия {percent}% (по уровню репутации), пользователь получит {received} 🍪.",
        parse_mode="HTML",
        reply_markup=transfer_keyboard(transfer_id),
    )


@router.message(command_or_alias("unmute"), F.chat.type.in_({"group", "supergroup"}))
async def unmute_member(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not await _require_perm(message, db, settings, PERM_MUTE) or not message.from_user:
        return
    target = await resolve_reply_target(message, db)
    if not target:
        await _respond(message, "Ответьте командой на сообщение пользователя: /unmute")
        return
    await bot.restrict_chat_member(message.chat.id, int(target["user_id"]), permissions=_full_permissions())
    await db.log_admin_action(
        message.from_user.id,
        "unmute",
        str(target["user_id"]),
        actor_name=message.from_user.full_name,
        target_name=person_label(target),
        reason=" ".join(remainder_args(message.text or "")),
    )
    await _respond(message, f"🔊 Мут с {_target_display(target)} снят.", parse_mode="HTML")


@router.message(command_or_alias("kick"), F.chat.type.in_({"group", "supergroup"}))
async def kick_member(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not await _require_perm(message, db, settings, PERM_KICK) or not message.from_user:
        return
    target = await resolve_reply_target(message, db)
    if not target:
        await _respond(message, "Ответьте командой на сообщение пользователя: /kick причина")
        return
    reason = " ".join(remainder_args(message.text or ""))
    target_id = int(target["user_id"])
    await bot.ban_chat_member(message.chat.id, target_id)
    await bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
    await db.log_admin_action(
        message.from_user.id,
        "kick",
        str(target_id),
        actor_name=message.from_user.full_name,
        target_name=person_label(target),
        reason=reason,
    )
    note = f" · {reason}" if reason else " · без причины"
    await _respond(message, f"👢 {_target_display(target)} исключён из чата{note}.", parse_mode="HTML")


@router.message(command_or_alias("ban"), F.chat.type.in_({"group", "supergroup"}))
async def ban_member(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not await _require_perm(message, db, settings, PERM_BAN) or not message.from_user:
        return
    target = await resolve_reply_target(message, db)
    if not target:
        await _respond(message, "Ответьте командой на сообщение пользователя: /ban причина")
        return
    reason = " ".join(remainder_args(message.text or ""))
    await bot.ban_chat_member(message.chat.id, int(target["user_id"]))
    await db.log_admin_action(
        message.from_user.id,
        "ban",
        str(target["user_id"]),
        actor_name=message.from_user.full_name,
        target_name=person_label(target),
        reason=reason,
    )
    note = f" · {reason}" if reason else " · без причины"
    await _respond(message, f"⛔ {_target_display(target)} заблокирован{note}.", parse_mode="HTML")


@router.message(command_or_alias("unban"), F.chat.type.in_({"group", "supergroup"}))
async def unban_member(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not await _require_perm(message, db, settings, PERM_BAN) or not message.from_user:
        return
    args = remainder_args(message.text or "")
    if not args or not args[0].lstrip("-").isdigit():
        await _respond(message, "Использование: /unban TELEGRAM_ID")
        return
    target_id = int(args[0])
    reason = " ".join(args[1:])
    stored = await db.get_user(target_id)
    await bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
    await db.log_admin_action(
        message.from_user.id,
        "unban",
        str(target_id),
        actor_name=message.from_user.full_name,
        target_name=person_label(stored, str(target_id)),
        reason=reason,
    )
    await _respond(message, "Пользователь разблокирован.")


@router.message(command_or_alias("warn"), F.chat.type.in_({"group", "supergroup"}))
async def warn_member(message: Message, db: Database, settings: Settings) -> None:
    if not await _require_perm(message, db, settings, PERM_WARN) or not message.from_user:
        return
    target = await resolve_reply_target(message, db)
    if not target:
        await _respond(message, "Ответьте командой на сообщение пользователя: /warn причина")
        return
    reason = " ".join(remainder_args(message.text or ""))
    warnings = await db.add_warning(int(target["user_id"]))
    await db.log_admin_action(
        message.from_user.id,
        "warn",
        str(target["user_id"]),
        f"всего {warnings}",
        actor_name=message.from_user.full_name,
        target_name=person_label(target),
        reason=reason,
    )
    note = f" · {reason}" if reason else " · без причины"
    await _respond(
        message,
        f"⚠️ {_target_display(target)} получает предупреждение. Всего: {warnings}.{note}",
        parse_mode="HTML",
    )


@router.message(command_or_alias("unwarn"), F.chat.type.in_({"group", "supergroup"}))
async def unwarn_member(message: Message, db: Database, settings: Settings) -> None:
    if not await _require_perm(message, db, settings, PERM_WARN) or not message.from_user:
        return
    target = await resolve_reply_target(message, db)
    if not target:
        await _respond(message, "Ответьте командой на сообщение пользователя: /unwarn")
        return
    warnings = await db.remove_warning(int(target["user_id"]))
    await db.log_admin_action(
        message.from_user.id,
        "unwarn",
        str(target["user_id"]),
        f"осталось {warnings}",
        actor_name=message.from_user.full_name,
        target_name=person_label(target),
        reason=" ".join(remainder_args(message.text or "")),
    )
    await _respond(
        message,
        f"✅ С {_target_display(target)} снято предупреждение. Осталось: {warnings}.",
        parse_mode="HTML",
    )


@router.message(command_or_alias("role"), F.chat.type.in_({"group", "supergroup"}))
async def change_role(message: Message, db: Database, settings: Settings) -> None:
    if not await _require_perm(message, db, settings, PERM_ROLES_ASSIGN) or not message.from_user:
        return
    target = await resolve_reply_target(message, db)
    args = remainder_args(message.text or "")
    if not target or len(args) != 1:
        await _respond(message, "Ответьте на сообщение: /role код_роли")
        return
    new_role = args[0].casefold()
    role = await db.get_staff_role(new_role)
    if not role or new_role == "owner":
        names = ", ".join(item["slug"] for item in await db.list_staff_roles() if item["slug"] != "owner")
        await _respond(message, f"Неизвестная роль. Доступны: {names}")
        return
    if settings.is_owner(int(target["user_id"])) or int(target["user_id"]) == message.from_user.id:
        await _respond(message, "Эту роль нельзя изменить командой.")
        return
    if not await can_manage_user(db, settings, message.from_user.id, int(target["user_id"])):
        await _respond(message, "Нельзя менять роль равного или выше.")
        return
    actor_rank = await rank_of_user(db, settings, message.from_user.id)
    if not settings.is_owner(message.from_user.id) and int(role["rank"]) >= actor_rank:
        await _respond(message, "Нельзя выдать роль не ниже своей.")
        return
    await db.set_role(int(target["user_id"]), new_role)
    await db.log_admin_action(
        message.from_user.id,
        "role",
        str(target["user_id"]),
        str(role["name"]),
        actor_name=message.from_user.full_name,
        target_name=person_label(target),
        reason=str(role["name"]),
    )
    await _respond(
        message,
        f"Роль {_target_display(target)}: {html.escape(str(role['name']))}.",
        parse_mode="HTML",
    )


@router.message(command_or_alias("setstatus"), F.chat.type.in_({"group", "supergroup"}))
async def admin_set_status(message: Message, db: Database, settings: Settings) -> None:
    if not await _require_perm(message, db, settings, PERM_USERS_EDIT) or not message.from_user:
        return
    target = await resolve_reply_target(message, db)
    status = " ".join(remainder_args(message.text or "")).strip()[:50]
    if not target or not status:
        await _respond(message, "Ответьте на сообщение: /setstatus Новый статус")
        return
    await db.update_profile(int(target["user_id"]), "custom_status", status)
    await db.log_admin_action(
        message.from_user.id,
        "set_status",
        str(target["user_id"]),
        status,
        actor_name=message.from_user.full_name,
        target_name=person_label(target),
        reason=status,
    )
    await _respond(message, "Кастомный статус установлен.")


async def _shop_prices(user: dict[str, object], settings: Settings) -> dict[str, int]:
    return shop_prices_for(user, settings.restricted_reputation_threshold)


def _shop_home_text(user: dict[str, object], settings: Settings) -> str:
    tier = reputation_tier(int(user["reputation"]), settings.restricted_reputation_threshold)
    return (
        f"🛒 <b>Магазин NORA</b>\n"
        f"Баланс: <b>{user['cookies']} 🍪</b>\n"
        f"Уровень: {tier.emoji} · скидка {tier.discount}%\n\n"
        "Откройте полку и нажмите товар — покупка списывается сразу. "
        "В чате этот экран не исчезает через 30 секунд."
    )


async def _shop_home_markup(db: Database):
    key = await db.get_bot_state("shop_featured")
    label = await db.get_bot_state("shop_featured_label")
    return shop_home_keyboard(featured_key=key, featured_label=label if key else None)


@router.message(command_or_alias("shop"))
@router.message(F.text == "🛒 Магазин")
async def show_shop(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    user = await register_telegram_user(db, message.from_user)
    await message.answer(
        _shop_home_text(user, settings),
        parse_mode="HTML",
        reply_markup=await _shop_home_markup(db),
    )


@router.callback_query(F.data == "shop:home")
async def shop_home(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message:
        return
    user = await register_telegram_user(db, callback.from_user)
    await callback.answer()
    markup = await _shop_home_markup(db)
    try:
        await callback.message.edit_text(
            _shop_home_text(user, settings),
            parse_mode="HTML",
            reply_markup=markup,
        )
    except TelegramBadRequest:
        await callback.message.answer(
            _shop_home_text(user, settings),
            parse_mode="HTML",
            reply_markup=markup,
        )


@router.callback_query(F.data.startswith("shop:cat:"))
async def shop_category(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message:
        return
    category = callback.data.rsplit(":", 1)[1]
    user = await register_telegram_user(db, callback.from_user)
    prices = await _shop_prices(user, settings)
    if category == "extra":
        event_title = (await db.get_bot_state("event_title")) or "текущее мероприятие"
        title = "🎟 Мероприятия"
        intro = f"Сейчас: <b>{html.escape(event_title)}</b>. Введите сумму в печеньках — скидка уровня применится сама."
    elif category in SHOP_CATEGORIES:
        title = str(SHOP_CATEGORIES[category]["title"])
        intro = str(SHOP_CATEGORIES[category]["intro"])
    else:
        await callback.answer("Нет такой полки.", show_alert=True)
        return
    text = f"{title}\nБаланс: <b>{user['cookies']} 🍪</b>\n\n{intro}"
    await callback.answer()
    try:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=shop_category_keyboard(category, prices),
        )
    except TelegramBadRequest:
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=shop_category_keyboard(category, prices),
        )


@router.callback_query(F.data == "shop:buy_cookies")
async def choose_cookie_pack(callback: CallbackQuery, settings: Settings) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"Выберите пакет. 1 🍪 = {settings.cookie_price_rub} ₽, оплата проводится вручную через СБП:",
            reply_markup=cookie_packages_keyboard(),
        )


@router.message(command_or_alias("buycookies"))
async def buycookies_command(message: Message, settings: Settings) -> None:
    prompt = f"Выберите пакет. 1 🍪 = {settings.cookie_price_rub} ₽:"
    await message.answer(prompt, reply_markup=cookie_packages_keyboard())


@router.callback_query(F.data.startswith("cookies:sbp:"))
async def begin_sbp_purchase(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    if not callback.data or not callback.message:
        return
    amount = int(callback.data.rsplit(":", 1)[1])
    if amount not in {10, 50, 100}:
        await callback.answer("Некорректный пакет.", show_alert=True)
        return
    if not settings.sbp_payment_url:
        await callback.answer("Оплата СБП ещё не настроена владельцем.", show_alert=True)
        return
    rubles = amount * settings.cookie_price_rub
    await state.set_state(CookiePurchase.receipt)
    await state.set_data({"amount": amount, "rubles": rubles})
    await callback.answer()
    await callback.message.answer(
        f"Вы выбрали <b>{amount} 🍪</b>. К оплате: <b>{rubles} ₽</b>.\n\n"
        "Переведите точную сумму по ссылке СБП, затем следующим сообщением отправьте скриншот оплаты.",
        parse_mode="HTML",
        reply_markup=sbp_payment_keyboard(settings.sbp_payment_url),
    )
    if callback.message.chat.type == "private":
        await callback.message.answer(
            "Чтобы выйти — зелёный «Профиль» или синее «Меню» снизу.",
            reply_markup=flow_reply_keyboard(),
        )


@router.message(CookiePurchase.receipt)
async def receive_sbp_receipt(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    if not message.from_user:
        return
    media_type: str | None = None
    file_id: str | None = None
    if message.photo:
        media_type, file_id = "photo", message.photo[-1].file_id
    elif message.document:
        media_type, file_id = "document", message.document.file_id
    if not media_type or not file_id:
        await message.answer("Пришлите скриншот фотографией или файлом.")
        return
    data = await state.get_data()
    amount = int(data["amount"])
    rubles = int(data["rubles"])
    order_id = await db.create_cookie_order(
        message.from_user.id,
        amount,
        rubles,
        media_type,
        file_id,
    )
    await state.clear()
    await message.answer(
        f"✅ Скриншот по заказу №{order_id} получен. Платёж взят в обработку.\n"
        "После проверки администратором бот сообщит результат."
    )
    candidates = set(settings.reviewers)
    for user in await db.list_all_users():
        if str(user["role"]) in {"owner", "admin"}:
            candidates.add(int(user["user_id"]))
    recipients = {user_id for user_id in candidates if await has_permission(db, settings, user_id, PERM_PAYMENTS)}
    caption = (
        f"💳 <b>Заказ печенек №{order_id}</b>\n"
        f"Пользователь: {user_link(message.from_user.id, message.from_user.full_name)}\n"
        f"Пакет: <b>{amount} 🍪</b> · сумма <b>{rubles} ₽</b>"
    )
    for recipient_id in recipients:
        try:
            if media_type == "photo":
                await bot.send_photo(
                    recipient_id,
                    file_id,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=cookie_order_review_keyboard(order_id),
                )
            else:
                await bot.send_document(
                    recipient_id,
                    file_id,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=cookie_order_review_keyboard(order_id),
                )
        except (TelegramForbiddenError, TelegramBadRequest):
            continue


@router.callback_query(F.data.startswith("cookie_order:"))
async def review_cookie_order(callback: CallbackQuery, db: Database, settings: Settings, bot: Bot) -> None:
    if not callback.data or not callback.message:
        return
    if not await has_permission(db, settings, callback.from_user.id, PERM_PAYMENTS):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return
    _, decision, raw_order_id = callback.data.split(":")
    order_id = int(raw_order_id)
    approved = decision == "approve"
    order = await db.review_cookie_order(order_id, callback.from_user.id, approved)
    if not order:
        await callback.answer("Заказ уже обработан.", show_alert=True)
        return
    await callback.answer("Оплата подтверждена." if approved else "Оплата отклонена.")
    await callback.message.edit_reply_markup(reply_markup=None)
    await db.log_admin_action(
        callback.from_user.id,
        "payment_approved" if approved else "payment_rejected",
        str(order["user_id"]),
        f"заказ №{order_id} · {order['amount']} 🍪",
        actor_name=callback.from_user.full_name,
        reason="проверка СБП",
    )
    if approved:
        await safe_send(
            bot,
            int(order["user_id"]),
            f"✅ Оплата заказа №{order_id} подтверждена. На баланс начислено {order['amount']} 🍪.",
        )
    else:
        await safe_send(
            bot,
            int(order["user_id"]),
            f"❌ Оплата заказа №{order_id} не подтверждена. Обратитесь к администрации через «Задать вопрос».",
        )


@router.callback_query(F.data.startswith("shop:"))
async def buy_shop_item(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    if (
        not callback.data
        or not callback.message
        or callback.data in {"shop:buy_cookies", "shop:home", "shop:close"}
        or callback.data.startswith("shop:cat:")
    ):
        return
    item = callback.data.split(":", 1)[1]
    user = await register_telegram_user(db, callback.from_user)
    prices = await _shop_prices(user, settings)
    if item in {"event_pass", "support"}:
        tier = reputation_tier(int(user["reputation"]), settings.restricted_reputation_threshold)
        await state.set_state(FlexiblePurchase.amount)
        await state.set_data({"flex_item": item, "flex_discount": tier.discount})
        label = "оплаты мероприятия" if item == "event_pass" else "поддержки развития"
        await callback.answer()
        await callback.message.answer(
            f"Введите желаемую сумму для {label} в печеньках. "
            f"Ваша скидка уровня — {tier.discount}%; итог бот покажет перед списанием.",
            reply_markup=flow_reply_keyboard() if callback.message.chat.type == "private" else None,
        )
        return
    if item not in prices:
        await callback.answer("Товар временно недоступен.", show_alert=True)
        return
    price = prices[item]
    if item == "video_avatar":
        if not await db.feature_enabled("profile_video"):
            await callback.answer("Видео-профили временно выключены.", show_alert=True)
            return
        if int(user["cookies"]) < price:
            await callback.answer("Недостаточно печенек.", show_alert=True)
            return
        await state.set_state(ProfileEdit.video_avatar)
        await state.set_data({"shop_price": price})
        await callback.answer()
        await callback.message.answer(
            "Отправьте короткое видео для карточки профиля. После сохранения спишется стоимость товара.",
            reply_markup=flow_reply_keyboard() if callback.message.chat.type == "private" else None,
        )
        return
    if item == "tamagotchi":
        if not await db.feature_enabled("tamagotchi"):
            await callback.answer("Тамагочи временно выключены.", show_alert=True)
            return
        if await db.get_pet(callback.from_user.id, settle=False):
            await callback.answer("У вас уже есть питомец.", show_alert=True)
            return
        if int(user["cookies"]) < price:
            await callback.answer("Недостаточно печенек.", show_alert=True)
            return
        await callback.answer()
        await callback.message.answer(
            f"Выберите питомца. Цена с вашей скидкой: {price} 🍪.",
            reply_markup=pet_species_keyboard(price),
        )
        return
    pet_items = PET_SUPPLIES
    if item in pet_items:
        kind, gain, label = pet_items[item]
        ok, error, _ = await db.purchase_pet_supply(callback.from_user.id, kind, gain, price, item)
        if not ok:
            await callback.answer(error, show_alert=True)
            return
        await callback.answer("Питомец доволен!")
        await callback.message.answer(f"✅ {label}: +{gain} к шкале. Списано {price} 🍪.")
        return
    if item == "custom_status":
        if int(user["cookies"]) < price:
            await callback.answer("Недостаточно печенек.", show_alert=True)
            return
        await state.set_state(ProfileEdit.custom_status)
        await state.set_data({"shop_price": price})
        await callback.answer()
        await callback.message.answer(
            "Введите новый кастомный статус (до 50 символов).",
            reply_markup=flow_reply_keyboard() if callback.message.chat.type == "private" else None,
        )
        return
    if item in IMMUNITY_HOURS:
        ok, error = await db.buy_item(callback.from_user.id, item, price)
        if not ok:
            await callback.answer(error, show_alert=True)
            return
        hours = IMMUNITY_HOURS[item]
        await db.set_immunity(callback.from_user.id, datetime.now(UTC) + timedelta(hours=hours))
        await callback.answer("Покупка выполнена.")
        await callback.message.answer(f"✅ Иммунитет от −репа включён на {hours} ч. Списано {price} 🍪.")
        return
    if item in TITLE_ITEMS:
        ok, error = await db.buy_item(callback.from_user.id, item, price)
        if not ok:
            await callback.answer(error, show_alert=True)
            return
        await db.update_profile(callback.from_user.id, "profile_title", TITLE_ITEMS[item])
        await callback.answer("Титул надет.")
        await callback.message.answer(f"✅ Титул «{html.escape(TITLE_ITEMS[item])}». Списано {price} 🍪.")
        return
    if item == "private_profile" and user.get("profile_private"):
        await callback.answer("Профиль уже скрыт.", show_alert=True)
        return
    if item == "ornate_profile" and user.get("profile_ornate"):
        await callback.answer("Кастомный профиль уже куплен.", show_alert=True)
        return
    ok, error = await db.buy_item(callback.from_user.id, item, price)
    if not ok:
        await callback.answer(error, show_alert=True)
        return
    if item == "forgive" and settings.community_chat_id:
        try:
            await bot.restrict_chat_member(
                settings.community_chat_id, callback.from_user.id, permissions=_full_permissions()
            )
        except TelegramBadRequest:
            pass
    elif item in {"event_pass", "support"}:
        for owner_id in settings.owner_ids:
            await safe_send(
                bot,
                owner_id,
                f"🛒 Пользователь {user_link(callback.from_user.id, callback.from_user.full_name)} "
                f"купил: <b>{html.escape(item)}</b> за {price} 🍪.",
                parse_mode="HTML",
            )
    labels = {
        "restore_rep": "Репутация поднята на +10 (не выше 100).",
        "immunity": "Иммунитет от отрицательной репутации включён на 24 часа.",
        "immunity_24h": "Плащ иммунитета на 24 часа.",
        "rep_shield": "Щит на один −реп добавлен.",
        "event_pass": "Заявка на проходку передана владельцу.",
        "reset_limits": "Лимит действий репутации сброшен.",
        "forgive": "Предупреждения очищены, мут снят.",
        "support": "Спасибо за поддержку проекта!",
        "private_profile": "Профиль скрыт от чужих. Открыть снова можно кнопкой на своей карточке.",
        "ornate_profile": "Кастомное оформление профиля включено.",
    }
    await callback.answer("Покупка выполнена.")
    await callback.message.answer(f"✅ {labels[item]} Списано {price} 🍪.")


@router.message(FlexiblePurchase.amount)
async def finish_flexible_purchase(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    if not message.from_user or not message.text or not message.text.isdigit():
        await message.answer("Введите сумму целым числом печенек.")
        return
    base_amount = int(message.text)
    if not 1 <= base_amount <= 1_000_000:
        await message.answer("Сумма должна быть от 1 до 1 000 000 🍪.")
        return
    data = await state.get_data()
    item = str(data["flex_item"])
    discount = int(data["flex_discount"])
    price = discounted_price(base_amount, discount)
    ok, error = await db.buy_item(message.from_user.id, item, price)
    if not ok:
        await state.clear()
        await message.answer(error)
        return
    label = "Оплата мероприятия" if item == "event_pass" else "Поддержка развития"
    await state.clear()
    await message.answer(
        f"✅ {label}: выбрано {base_amount} 🍪, скидка {discount}%, списано <b>{price} 🍪</b>.",
        parse_mode="HTML",
    )
    for owner_id in settings.owner_ids:
        await safe_send(
            bot,
            owner_id,
            f"💚 {user_link(message.from_user.id, message.from_user.full_name)} — {label.lower()}: "
            f"{base_amount} 🍪, списано {price} 🍪 со скидкой {discount}%.",
            parse_mode="HTML",
        )


@router.message(ProfileEdit.video_avatar)
async def save_video_avatar(message: Message, state: FSMContext, db: Database) -> None:
    if not message.from_user or not message.video:
        await message.answer("Нужно отправить видеофайл как видео, не как документ.")
        return
    data = await state.get_data()
    price = int(data["shop_price"])
    ok, error = await db.buy_item(message.from_user.id, "video_avatar", price)
    if not ok:
        await state.clear()
        await message.answer(error)
        return
    await db.update_profile(message.from_user.id, "avatar_file_id", message.video.file_id)
    await db.update_profile(message.from_user.id, "avatar_media_type", "video")
    await state.clear()
    await message.answer(f"✅ Видео-профиль установлен. Списано {price} 🍪.")


@router.message(ProfileEdit.custom_status)
async def save_purchased_status(message: Message, state: FSMContext, db: Database) -> None:
    if not message.from_user or not message.text:
        await message.answer("Введите статус текстом.")
        return
    status = message.text.strip()
    if not 1 <= len(status) <= 50:
        await message.answer("Статус должен содержать от 1 до 50 символов.")
        return
    data = await state.get_data()
    price = int(data["shop_price"])
    ok, error = await db.buy_item(message.from_user.id, "custom_status", price)
    if not ok:
        await state.clear()
        await message.answer(error)
        return
    await db.update_profile(message.from_user.id, "custom_status", status)
    await state.clear()
    await message.answer(f"✅ Статус установлен. Списано {price} 🍪.")


@router.message(command_or_alias("givecookies"), F.chat.type.in_({"group", "supergroup"}))
async def admin_give_cookies(message: Message, db: Database, settings: Settings) -> None:
    actor_role = await _require_perm(message, db, settings, PERM_USERS_COOKIES)
    if not actor_role or not message.from_user:
        return
    target = await resolve_reply_target(message, db)
    args = remainder_args(message.text or "")
    if not target or not args or not args[0].isdigit():
        await _respond(message, "Ответьте на сообщение: /givecookies 100 причина")
        return
    if not await _can_manage_target(message.from_user.id, target, db, settings):
        await _respond(message, "Нельзя изменять баланс пользователя с равной или более высокой ролью.")
        return
    amount = int(args[0])
    reason = " ".join(args[1:])
    if amount <= 0 or amount > 1_000_000:
        await _respond(message, "Количество должно быть от 1 до 1 000 000 🍪.")
        return
    await db.add_cookies(int(target["user_id"]), amount, "admin", f"by:{message.from_user.id}")
    await db.log_admin_action(
        message.from_user.id,
        "give_cookies",
        str(target["user_id"]),
        f"+{amount} 🍪",
        actor_name=message.from_user.full_name,
        target_name=person_label(target),
        reason=reason,
    )
    await _respond(message, f"Начислено {amount} 🍪 пользователю {_target_display(target)}.", parse_mode="HTML")


@router.message(command_or_alias("setcookies"), F.chat.type.in_({"group", "supergroup"}))
async def admin_set_cookies(message: Message, db: Database, settings: Settings) -> None:
    actor_role = await _require_perm(message, db, settings, PERM_USERS_COOKIES)
    if not actor_role or not message.from_user:
        return
    target = await resolve_reply_target(message, db)
    args = remainder_args(message.text or "")
    if not target or not args or not args[0].isdigit():
        await _respond(message, "Ответьте на сообщение: /setcookies 100 причина")
        return
    if not await _can_manage_target(message.from_user.id, target, db, settings):
        await _respond(message, "Нельзя изменять баланс пользователя с равной или более высокой ролью.")
        return
    amount = int(args[0])
    reason = " ".join(args[1:])
    if amount > 1_000_000:
        await _respond(message, "Баланс не может превышать 1 000 000 🍪.")
        return
    ok, difference = await db.set_cookies(int(target["user_id"]), amount, message.from_user.id)
    if not ok:
        await _respond(message, "Не удалось изменить баланс.")
        return
    sign = "+" if difference >= 0 else ""
    await db.log_admin_action(
        message.from_user.id,
        "set_cookies",
        str(target["user_id"]),
        f"{amount} 🍪 ({sign}{difference})",
        actor_name=message.from_user.full_name,
        target_name=person_label(target),
        reason=reason,
    )
    await _respond(
        message,
        f"Баланс {_target_display(target)} установлен: {amount} 🍪 ({sign}{difference}).",
        parse_mode="HTML",
    )


@router.message(command_or_alias("roulette"), F.chat.type.in_({"group", "supergroup"}))
async def roulette_invite(message: Message, db: Database, bot: Bot) -> None:
    if not message.from_user:
        return
    target = await resolve_reply_target(message, db)
    if not target or not message.reply_to_message or not message.reply_to_message.from_user:
        await _respond(message, "Ответьте командой /roulette на сообщение игрока. Можно указать ставку: /roulette 25")
        return
    if message.reply_to_message.from_user.is_bot:
        await _respond(message, "С ботами играть нельзя.")
        return
    if int(target["user_id"]) == message.from_user.id:
        await _respond(message, "Нельзя сыграть с самим собой.")
        return
    args = remainder_args(message.text or "")
    try:
        stake = int(args[0]) if args else 10
    except ValueError:
        stake = 0
    if not 1 <= stake <= 500:
        await _respond(message, "Ставка рулетки — от 1 до 500 🍪. Пример: /roulette 25 или «рулетка 50»")
        return
    challenger = await register_telegram_user(db, message.from_user)
    if int(challenger["cookies"]) < stake or int(target["cookies"]) < stake:
        await _respond(message, f"Для игры у обоих участников должно быть минимум {stake} 🍪.")
        return
    game_id = await db.create_roulette(message.chat.id, message.from_user.id, int(target["user_id"]), stake)
    with keep_in_chat():
        await _respond(
            message,
            f"🎯 {_target_display(target)}, вас вызывает на русскую рулетку "
            f"{user_link(message.from_user.id, message.from_user.full_name)}!\n"
            f"Ставка — {stake} 🍪. Победитель определяется автоматически.",
            parse_mode="HTML",
            reply_markup=roulette_invite_keyboard(game_id),
        )
    await notify_game_event(
        bot,
        message.chat.id,
        [challenger, target],
        f"🎯 Рулетка №{game_id}: ставка {stake} 🍪.",
        f"🎯 Вас вызвали / вы вызвали на рулетку. Ставка {stake} 🍪.",
    )


@router.callback_query(F.data.startswith("roulette:"), F.message.chat.type.in_({"group", "supergroup"}))
async def roulette_decision(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    if not callback.data or not callback.message:
        return
    _, decision, raw_game_id = callback.data.split(":")
    game_id = int(raw_game_id)
    game = await db.get_roulette(game_id)
    if not game or game["status"] != "pending":
        await callback.answer("Эта игра уже завершена.", show_alert=True)
        return
    if callback.from_user.id != int(game["opponent_id"]):
        await callback.answer("Ответить на приглашение может только вызванный игрок.", show_alert=True)
        return
    if decision == "decline":
        challenger = await db.get_user(int(game["challenger_id"]))
        opponent = await db.get_user(int(game["opponent_id"]))
        await db.cancel_roulette(game_id, callback.from_user.id)
        await callback.answer("Вы отказались от игры.")
        await callback.message.edit_reply_markup(reply_markup=None)
        await send_game_finale(callback.message, "Русская рулетка отменена: соперник отказался.")
        players = [item for item in (challenger, opponent) if item]
        await notify_game_event(
            bot,
            callback.message.chat.id,
            players,
            f"❌ Рулетка №{game_id} отменена.",
            f"❌ Рулетка №{game_id} отменена: соперник отказался.",
        )
        return
    stake = int(game["stake"])
    winner_id = secrets.choice([int(game["challenger_id"]), int(game["opponent_id"])])
    ok, error, result = await db.settle_roulette(game_id, callback.from_user.id, winner_id)
    if not ok or not result:
        await callback.answer(error, show_alert=True)
        return
    winner = await db.get_user(int(result["winner_id"]))
    loser = await db.get_user(int(result["loser_id"]))
    if not winner or not loser:
        await callback.answer("Ошибка профиля игрока.", show_alert=True)
        return
    await callback.answer("Выстрел! Результат определён.")
    await callback.message.edit_reply_markup(reply_markup=None)
    commission = "" if int(result["payout"]) == stake else " (после комиссии)"
    await send_game_finale(
        callback.message,
        "🔫 Барабан прокручен… выстрел!\n\n"
        f"🏆 Победил {_target_display(winner)} и получил {result['payout']} 🍪{commission}.\n"
        f"💀 {_target_display(loser)} потерял {stake} 🍪.",
    )
    await notify_game_event(
        bot,
        callback.message.chat.id,
        [winner, loser],
        f"🔫 Рулетка №{game_id}: победил {_target_display(winner)}.",
        f"🔫 Рулетка №{game_id} сыграна. Победитель получил {result['payout']} 🍪.",
    )


@router.message(command_or_alias("freebie"), F.chat.type.in_({"group", "supergroup"}))
async def freebie_offer(message: Message, settings: Settings) -> None:
    if not settings.freebie_channel_url:
        await _respond(message, "Бонус за подписку ещё не настроен владельцем.")
        return
    with keep_in_chat():
        await _respond(
            message,
            "🎁 <b>Бесплатные печеньки</b>\n\n"
            "Подпишитесь на канал и нажмите «Проверить подписку». "
            "Золотой уровень получит 10 🍪, остальные — 8 🍪. Награда выдаётся один раз.",
            parse_mode="HTML",
            reply_markup=freebie_keyboard(settings.freebie_channel_url),
        )


@router.callback_query(F.data == "freebie:check", F.message.chat.type.in_({"group", "supergroup"}))
async def freebie_check(callback: CallbackQuery, db: Database, settings: Settings, bot: Bot) -> None:
    stored_channel_id = await db.get_bot_state("freebie_channel_id")
    channel_id = settings.freebie_channel_id or (int(stored_channel_id) if stored_channel_id else 0)
    if not channel_id:
        await callback.answer("Проверка подписки ещё не настроена владельцем.", show_alert=True)
        return
    try:
        member = await bot.get_chat_member(channel_id, callback.from_user.id)
    except TelegramBadRequest:
        await callback.answer("Бот пока не может проверить канал. Добавьте его администратором.", show_alert=True)
        return
    if member.status not in {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
    }:
        await callback.answer("Подписка не найдена. Подпишитесь и попробуйте снова.", show_alert=True)
        return
    user = await register_telegram_user(db, callback.from_user)
    amount = 10 if int(user["reputation"]) >= 90 else 8
    if not await db.claim_freebie(callback.from_user.id, amount):
        await callback.answer("Вы уже получали награду за подписку.", show_alert=True)
        return
    await callback.answer(f"Начислено {amount} 🍪!", show_alert=True)
    if callback.message:
        await callback.message.answer(
            f"🎁 {user_link(callback.from_user.id, callback.from_user.full_name)} получил {amount} 🍪 за подписку.",
            parse_mode="HTML",
        )


@router.message(command_or_alias("transfer"), F.chat.type.in_({"group", "supergroup"}))
async def transfer_command(message: Message, db: Database) -> None:
    if not message.from_user:
        return
    target = await resolve_reply_target(message, db)
    args = remainder_args(message.text or "")
    if not target or not args or not args[0].isdigit():
        await _respond(message, "Ответьте на сообщение пользователя: /transfer 100")
        return
    await _prepare_transfer(message, db, target, int(args[0]))


async def _prepare_transfer(message: Message, db: Database, target: dict[str, object], amount: int) -> None:
    assert message.from_user
    sender = await register_telegram_user(db, message.from_user)
    if int(target["user_id"]) == message.from_user.id:
        await _respond(message, "Нельзя перевести печеньки самому себе.")
        return
    if amount <= 0 or amount > int(sender["cookies"]):
        await _respond(message, f"Недостаточно печенек. Ваш баланс: {sender['cookies']} 🍪.")
        return
    percent = transfer_commission_percent(int(sender["reputation"]))
    received = amount * (100 - percent) // 100
    if received <= 0:
        await _respond(message, "После комиссии получателю ничего не останется. Увеличьте сумму.")
        return
    transfer_id = await db.create_transfer(message.from_user.id, int(target["user_id"]), amount)
    with keep_in_chat():
        await _respond(
            message,
            f"Перевести {_target_display(target)} {amount} 🍪?\n"
            f"Комиссия {percent}% (по уровню репутации), пользователь получит {received} 🍪.",
            parse_mode="HTML",
            reply_markup=transfer_keyboard(transfer_id),
        )


@router.callback_query(F.data.startswith("transfer:"))
async def confirm_transfer(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    if not callback.data or not callback.message:
        return
    _, decision, raw_id = callback.data.split(":")
    transfer_id = int(raw_id)
    if decision == "no":
        await db.cancel_transfer(transfer_id, callback.from_user.id)
        await callback.answer("Перевод отменён.")
        await callback.message.edit_reply_markup(reply_markup=None)
        return
    transfer = await db.fetchone("SELECT * FROM pending_transfers WHERE id = ?", (transfer_id,))
    ok, error, received = await db.complete_transfer(transfer_id, callback.from_user.id)
    if not ok:
        await callback.answer(error, show_alert=True)
        return
    await callback.answer("Перевод выполнен.")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"✅ Перевод выполнен. Получателю зачислено {received} 🍪.")
    if transfer:
        await safe_send(
            bot,
            int(transfer["receiver_id"]),
            f"Вам перевели {received} 🍪 после комиссии.",
        )


@router.message(F.reply_to_message, F.text, F.chat.type.in_({"group", "supergroup"}))
async def group_reply_actions(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not message.from_user or not message.reply_to_message or not message.reply_to_message.from_user:
        return
    target = await resolve_reply_target(message, db)
    if not target:
        return
    amount = transfer_amount(message.text or "")
    if amount is not None:
        await _prepare_transfer(message, db, target, amount)
        return
    delta = reputation_delta(message.text or "")
    if delta is None:
        return
    actor = await register_telegram_user(db, message.from_user)
    if message.reply_to_message.from_user.is_bot:
        await message.reply("Репутация ботов не меняется.")
        return
    timezone = ZoneInfo(settings.timezone)
    local_date = datetime.now(timezone).date()
    from community_bot.reputation import change_community_reputation

    ok, text, new_value, pet_line = await change_community_reputation(
        db, settings, actor, target, delta, local_date
    )
    if not ok or new_value is None:
        await message.reply(text)
        return
    target_tier = reputation_tier(new_value, settings.restricted_reputation_threshold)
    extra = f"\n{pet_line}" if pet_line else ""
    await message.reply(
        f"{target_tier.emoji} {_target_display(target)}: {html.escape(text)}{extra}",
        parse_mode="HTML",
    )
    if new_value < settings.restricted_reputation_threshold:
        try:
            await bot.restrict_chat_member(
                message.chat.id,
                int(target["user_id"]),
                permissions=ChatPermissions(can_send_messages=False),
            )
            await message.answer("🔞 Пользователь ограничен: доступен только магазин в личном чате с ботом.")
        except TelegramBadRequest:
            pass


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def remember_group_member(message: Message) -> None:
    return None
