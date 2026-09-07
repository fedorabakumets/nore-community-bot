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
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    ChatPermissions,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from community_bot.config import Settings
from community_bot.database import Database
from community_bot.domain import (
    discounted_price,
    parse_duration,
    reputation_delta,
    reputation_tier,
    transfer_amount,
)
from community_bot.helpers import (
    can_manage_user,
    effective_role,
    has_permission,
    is_immunity_active,
    pet_guard_reputation,
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
from community_bot.shop_catalog import IMMUNITY_HOURS, PET_SUPPLIES, SHOP_CATEGORIES, shop_prices_for
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
                    with contextlib.suppress(TelegramBadRequest, TelegramForbiddenError):
                        await bot.send_message(
                            event.from_user.id,
                            f"🎁 За активность в чате ({activity_count} сообщений) "
                            "ваш тамагочи получил 1 еду и 1 воду.",
                        )
                member = await rank_of_user(db, settings, event.from_user.id) < 40
                blocked_reason: str | None = None
                text = event.text or event.caption or ""
                if member and flags.get("quiet_hours"):
                    local_hour = datetime.now(ZoneInfo(settings.timezone)).hour
                    if 0 <= local_hour < 7:
                        blocked_reason = "Включён ночной режим: чат открыт с 07:00."
                if member and flags.get("raid_mode") and activity_count <= 2:
                    blocked_reason = "Включён рейд-режим: первые сообщения новых участников проходят проверку."
                contains_link = any(
                    marker in text.casefold() for marker in ("http://", "https://", "t.me/")
                )
                if member and flags.get("link_filter") and contains_link:
                    blocked_reason = "Ссылки сейчас запрещены настройками чата."
                has_media = bool(
                    event.photo
                    or event.video
                    or event.document
                    or event.audio
                    or event.voice
                    or event.animation
                    or event.sticker
                )
                if member and flags.get("media_filter") and has_media:
                    blocked_reason = "Медиа сейчас запрещены настройками чата."
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
                    return None
        result = await handler(event, data)
        text = (event.text or "").lstrip()
        if event.chat.type in {"group", "supergroup"} and text.startswith("/"):
            try:
                await event.delete()
            except TelegramBadRequest:
                pass
        return result


router.message.outer_middleware(DeleteGroupCommandMiddleware())


def _group_chat(message: Message) -> bool:
    return message.chat.type in {"group", "supergroup"}


async def _respond(message: Message, text: str, **kwargs: Any) -> Message:
    if (message.text or "").lstrip().startswith("/"):
        return await message.answer(text, **kwargs)
    return await message.reply(text, **kwargs)


async def _delete_later(message: Message, delay: float = 12) -> None:
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


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
    name = str(target["profile_name"] or target["telegram_name"] or target["user_id"])
    return user_link(int(target["user_id"]), name)


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


@router.message(Command("commands", "help"), F.chat.type.in_({"group", "supergroup"}))
async def group_commands(message: Message) -> None:
    await message.answer(GROUP_COMMANDS_TEXT, parse_mode="HTML")


@router.message(Command("reputation"), F.chat.type.in_({"group", "supergroup"}))
async def reputation_help(message: Message) -> None:
    await message.answer(REPUTATION_HELP_TEXT, parse_mode="HTML")


@router.message(Command("store"), F.chat.type.in_({"group", "supergroup"}))
async def store_help(message: Message) -> None:
    await message.answer(STORE_HELP_TEXT, parse_mode="HTML")


@router.message(Command("admin"), F.chat.type.in_({"group", "supergroup"}))
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
            reply_markup=admin_panel_keyboard(await user_permissions(db, settings, message.from_user.id)),
        )
    except (TelegramForbiddenError, TelegramBadRequest):
        await _private_chat_notice(message, bot)


@router.message(Command("id"))
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


@router.message(Command("profile"), F.chat.type.in_({"group", "supergroup"}))
async def group_profile_legacy(message: Message) -> None:
    del message
    return


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
    tier = reputation_tier(int(actor["reputation"]), settings.restricted_reputation_threshold)
    if tier.daily_actions == 0:
        await callback.answer("Ваш уровень репутации не позволяет влиять на других участников.", show_alert=True)
        return
    timezone = ZoneInfo(settings.timezone)
    local_date = datetime.now(timezone).date()
    used = await db.reputation_actions_today(callback.from_user.id, local_date)
    if used >= tier.daily_actions:
        await callback.answer(f"Дневной лимит исчерпан: {tier.daily_actions} действий.", show_alert=True)
        return
    if delta < 0 and is_immunity_active(target.get("hate_immunity_until")):
        await callback.answer("У пользователя действует иммунитет от понижения репутации.", show_alert=True)
        return
    delta, pet_line = await pet_guard_reputation(db, target_id, delta)
    new_value = await db.apply_reputation(callback.from_user.id, target_id, delta, local_date)
    target_tier = reputation_tier(new_value, settings.restricted_reputation_threshold)
    sign = "+" if delta > 0 else ""
    await callback.answer("Питомец вмешался!" if pet_line else f"Репутация изменена на {sign}{delta}.")
    extra = f"\n{pet_line}" if pet_line else ""
    await callback.message.answer(
        f"{target_tier.emoji} Репутация {_target_display(target)}: "
        f"{sign}{delta}, теперь {new_value}.{extra}",
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
    received = amount * 80 // 100
    transfer_id = await db.create_transfer(callback.from_user.id, target_id, amount)
    await callback.message.edit_reply_markup(reply_markup=public_profile_keyboard(target_id))
    await callback.answer("Подтвердите перевод.")
    await callback.message.answer(
        f"Перевести {_target_display(target)} {amount} 🍪?\n"
        f"Комиссия 20%, пользователь получит {received} 🍪.",
        parse_mode="HTML",
        reply_markup=transfer_keyboard(transfer_id),
    )


@router.message(Command("mute"), F.chat.type.in_({"group", "supergroup"}))
async def mute_member(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not await _require_perm(message, db, settings, PERM_MUTE):
        return
    target = await resolve_reply_target(message, db)
    if not target:
        await _respond(message, "Ответьте командой на сообщение пользователя: /mute 30m")
        return
    parts = (message.text or "").split()
    duration = parse_duration(parts[1]) if len(parts) > 1 else timedelta(hours=1)
    if not duration:
        await _respond(message, "Формат времени: 30m, 2h, 3d или 1w (также м/ч/д/н).")
        return
    until = datetime.now(UTC) + duration
    await bot.restrict_chat_member(
        message.chat.id,
        int(target["user_id"]),
        permissions=ChatPermissions(can_send_messages=False),
        until_date=until,
    )
    await _respond(
        message,
        f"🔇 {_target_display(target)} получает мут на {parts[1] if len(parts) > 1 else '1h'}.",
        parse_mode="HTML",
    )


@router.message(Command("unmute"), F.chat.type.in_({"group", "supergroup"}))
async def unmute_member(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not await _require_perm(message, db, settings, PERM_MUTE):
        return
    target = await resolve_reply_target(message, db)
    if not target:
        await _respond(message, "Ответьте командой на сообщение пользователя: /unmute")
        return
    await bot.restrict_chat_member(message.chat.id, int(target["user_id"]), permissions=_full_permissions())
    await _respond(message, f"🔊 Мут с {_target_display(target)} снят.", parse_mode="HTML")


@router.message(Command("kick"), F.chat.type.in_({"group", "supergroup"}))
async def kick_member(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not await _require_perm(message, db, settings, PERM_KICK):
        return
    target = await resolve_reply_target(message, db)
    if not target:
        await _respond(message, "Ответьте командой на сообщение пользователя: /kick")
        return
    target_id = int(target["user_id"])
    await bot.ban_chat_member(message.chat.id, target_id)
    await bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
    await _respond(message, f"👢 {_target_display(target)} исключён из чата.", parse_mode="HTML")


@router.message(Command("ban"), F.chat.type.in_({"group", "supergroup"}))
async def ban_member(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not await _require_perm(message, db, settings, PERM_BAN):
        return
    target = await resolve_reply_target(message, db)
    if not target:
        await _respond(message, "Ответьте командой на сообщение пользователя: /ban")
        return
    await bot.ban_chat_member(message.chat.id, int(target["user_id"]))
    await _respond(message, f"⛔ {_target_display(target)} заблокирован.", parse_mode="HTML")


@router.message(Command("unban"), F.chat.type.in_({"group", "supergroup"}))
async def unban_member(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not await _require_perm(message, db, settings, PERM_BAN):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await _respond(message, "Использование: /unban TELEGRAM_ID")
        return
    await bot.unban_chat_member(message.chat.id, int(parts[1]), only_if_banned=True)
    await _respond(message, "Пользователь разблокирован.")


@router.message(Command("warn"), F.chat.type.in_({"group", "supergroup"}))
async def warn_member(message: Message, db: Database, settings: Settings) -> None:
    if not await _require_perm(message, db, settings, PERM_WARN):
        return
    target = await resolve_reply_target(message, db)
    if not target:
        await _respond(message, "Ответьте командой на сообщение пользователя: /warn")
        return
    warnings = await db.add_warning(int(target["user_id"]))
    await _respond(
        message,
        f"⚠️ {_target_display(target)} получает предупреждение. Всего: {warnings}.",
        parse_mode="HTML",
    )


@router.message(Command("unwarn"), F.chat.type.in_({"group", "supergroup"}))
async def unwarn_member(message: Message, db: Database, settings: Settings) -> None:
    if not await _require_perm(message, db, settings, PERM_WARN):
        return
    target = await resolve_reply_target(message, db)
    if not target:
        await _respond(message, "Ответьте командой на сообщение пользователя: /unwarn")
        return
    warnings = await db.remove_warning(int(target["user_id"]))
    await _respond(
        message,
        f"✅ С {_target_display(target)} снято предупреждение. Осталось: {warnings}.",
        parse_mode="HTML",
    )


@router.message(Command("role"), F.chat.type.in_({"group", "supergroup"}))
async def change_role(message: Message, db: Database, settings: Settings) -> None:
    if not await _require_perm(message, db, settings, PERM_ROLES_ASSIGN) or not message.from_user:
        return
    target = await resolve_reply_target(message, db)
    parts = (message.text or "").split()
    if not target or len(parts) != 2:
        await _respond(message, "Ответьте на сообщение: /role код_роли")
        return
    new_role = parts[1].casefold()
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
    await _respond(
        message,
        f"Роль {_target_display(target)}: {html.escape(str(role['name']))}.",
        parse_mode="HTML",
    )


@router.message(Command("setstatus"), F.chat.type.in_({"group", "supergroup"}))
async def admin_set_status(message: Message, db: Database, settings: Settings) -> None:
    if not await _require_perm(message, db, settings, PERM_USERS_EDIT):
        return
    target = await resolve_reply_target(message, db)
    parts = (message.text or "").split(maxsplit=1)
    if not target or len(parts) != 2:
        await _respond(message, "Ответьте на сообщение: /setstatus Новый статус")
        return
    status = parts[1].strip()[:50]
    await db.update_profile(int(target["user_id"]), "custom_status", status)
    await _respond(message, "Кастомный статус установлен.")


async def _shop_prices(user: dict[str, object], settings: Settings) -> dict[str, int]:
    return shop_prices_for(user, settings.restricted_reputation_threshold)


def _shop_home_text(user: dict[str, object], settings: Settings) -> str:
    tier = reputation_tier(int(user["reputation"]), settings.restricted_reputation_threshold)
    return (
        f"🛒 <b>Магазин NORA</b>\n"
        f"Баланс: <b>{user['cookies']} 🍪</b>\n"
        f"Уровень: {tier.emoji} · скидка {tier.discount}%\n\n"
        "Полки: тамагочи, репутация, профиль и мероприятия. "
        "Покупка применяется сразу после кнопки."
    )


@router.message(Command("shop"))
@router.message(F.text == "🛒 Магазин")
async def show_shop(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    user = await register_telegram_user(db, message.from_user)
    await message.answer(
        _shop_home_text(user, settings),
        parse_mode="HTML",
        reply_markup=shop_home_keyboard(),
    )


@router.callback_query(F.data == "shop:home")
async def shop_home(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message:
        return
    user = await register_telegram_user(db, callback.from_user)
    await callback.answer()
    try:
        await callback.message.edit_text(
            _shop_home_text(user, settings),
            parse_mode="HTML",
            reply_markup=shop_home_keyboard(),
        )
    except TelegramBadRequest:
        await callback.message.answer(
            _shop_home_text(user, settings),
            parse_mode="HTML",
            reply_markup=shop_home_keyboard(),
        )


@router.callback_query(F.data.startswith("shop:cat:"))
async def shop_category(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message:
        return
    category = callback.data.rsplit(":", 1)[1]
    user = await register_telegram_user(db, callback.from_user)
    prices = await _shop_prices(user, settings)
    if category == "extra":
        title = "🎟 Мероприятия"
        intro = "Гибкая сумма в печеньках. Скидка уровня применится автоматически."
    elif category in SHOP_CATEGORIES:
        title = str(SHOP_CATEGORIES[category]["title"])
        intro = str(SHOP_CATEGORIES[category]["intro"])
    else:
        await callback.answer("Нет такой полки.", show_alert=True)
        return
    text = (
        f"{title}\nБаланс: <b>{user['cookies']} 🍪</b>\n\n{intro}"
    )
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
            f"Выберите пакет. 1 🍪 = {settings.cookie_price_rub} ₽, "
            "оплата проводится вручную через СБП:",
            reply_markup=cookie_packages_keyboard(),
        )


@router.message(Command("buycookies"))
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
    recipients = {
        user_id
        for user_id in candidates
        if await has_permission(db, settings, user_id, PERM_PAYMENTS)
    }
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
        await callback.message.answer("Введите новый кастомный статус (до 50 символов).",
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
        await callback.message.answer(
            f"✅ Иммунитет от −репа включён на {hours} ч. Списано {price} 🍪."
        )
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
        "restore_rep": "Репутация восстановлена до 100.",
        "immunity": "Иммунитет от отрицательной репутации включён на 24 часа.",
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


@router.message(Command("givecookies"), F.chat.type.in_({"group", "supergroup"}))
async def admin_give_cookies(message: Message, db: Database, settings: Settings) -> None:
    actor_role = await _require_perm(message, db, settings, PERM_USERS_COOKIES)
    if not actor_role:
        return
    target = await resolve_reply_target(message, db)
    parts = (message.text or "").split()
    if not target or len(parts) != 2 or not parts[1].isdigit():
        await _respond(message, "Ответьте на сообщение: /givecookies 100")
        return
    if not await _can_manage_target(message.from_user.id, target, db, settings):
        await _respond(message, "Нельзя изменять баланс пользователя с равной или более высокой ролью.")
        return
    amount = int(parts[1])
    if amount <= 0 or amount > 1_000_000:
        await _respond(message, "Количество должно быть от 1 до 1 000 000 🍪.")
        return
    await db.add_cookies(int(target["user_id"]), amount, "admin", f"by:{message.from_user.id}")
    await _respond(message, f"Начислено {amount} 🍪 пользователю {_target_display(target)}.", parse_mode="HTML")


@router.message(Command("setcookies"), F.chat.type.in_({"group", "supergroup"}))
async def admin_set_cookies(message: Message, db: Database, settings: Settings) -> None:
    actor_role = await _require_perm(message, db, settings, PERM_USERS_COOKIES)
    if not actor_role or not message.from_user:
        return
    target = await resolve_reply_target(message, db)
    parts = (message.text or "").split()
    if not target or len(parts) != 2 or not parts[1].isdigit():
        await _respond(message, "Ответьте на сообщение: /setcookies 100")
        return
    if not await _can_manage_target(message.from_user.id, target, db, settings):
        await _respond(message, "Нельзя изменять баланс пользователя с равной или более высокой ролью.")
        return
    amount = int(parts[1])
    if amount > 1_000_000:
        await _respond(message, "Баланс не может превышать 1 000 000 🍪.")
        return
    ok, difference = await db.set_cookies(int(target["user_id"]), amount, message.from_user.id)
    if not ok:
        await _respond(message, "Не удалось изменить баланс.")
        return
    sign = "+" if difference >= 0 else ""
    await _respond(
        message,
        f"Баланс {_target_display(target)} установлен: {amount} 🍪 ({sign}{difference}).",
        parse_mode="HTML",
    )


@router.message(Command("roulette"), F.chat.type.in_({"group", "supergroup"}))
async def roulette_invite(message: Message, db: Database) -> None:
    if not message.from_user:
        return
    target = await resolve_reply_target(message, db)
    if not target or not message.reply_to_message or not message.reply_to_message.from_user:
        await _respond(message, "Ответьте командой /roulette на сообщение игрока.")
        return
    if message.reply_to_message.from_user.is_bot:
        await _respond(message, "С ботами играть нельзя.")
        return
    if int(target["user_id"]) == message.from_user.id:
        await _respond(message, "Нельзя сыграть с самим собой.")
        return
    challenger = await register_telegram_user(db, message.from_user)
    if int(challenger["cookies"]) < 10 or int(target["cookies"]) < 10:
        await _respond(message, "Для игры у обоих участников должно быть минимум 10 🍪.")
        return
    game_id = await db.create_roulette(message.chat.id, message.from_user.id, int(target["user_id"]))
    await _respond(
        message,
        f"🎯 {_target_display(target)}, вас вызывает на русскую рулетку "
        f"{user_link(message.from_user.id, message.from_user.full_name)}!\n"
        "Ставка — 10 🍪. Победитель определяется автоматически.",
        parse_mode="HTML",
        reply_markup=roulette_invite_keyboard(game_id),
    )


@router.callback_query(F.data.startswith("roulette:"), F.message.chat.type.in_({"group", "supergroup"}))
async def roulette_decision(callback: CallbackQuery, db: Database) -> None:
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
        await db.cancel_roulette(game_id, callback.from_user.id)
        await callback.answer("Вы отказались от игры.")
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer("Русская рулетка отменена: соперник отказался.")
        return
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
    commission = "" if int(result["payout"]) == 10 else " (после комиссии)"
    await callback.message.answer(
        "🔫 Барабан прокручен… выстрел!\n\n"
        f"🏆 Победил {_target_display(winner)} и получил {result['payout']} 🍪{commission}.\n"
        f"💀 {_target_display(loser)} потерял 10 🍪.",
        parse_mode="HTML",
    )


def _is_freebie_request(message: Message) -> bool:
    return bool(message.text and message.text.strip().casefold() == "халява")


@router.message(_is_freebie_request, F.chat.type.in_({"group", "supergroup"}))
async def freebie_offer(message: Message, settings: Settings) -> None:
    if not settings.freebie_channel_url:
        offer = await message.answer("Бонус за подписку ещё не настроен владельцем.")
        asyncio.create_task(_delete_later(offer, 25))
        return
    offer = await message.answer(
        "🎁 <b>Бесплатные печеньки</b>\n\n"
        "Подпишитесь на канал и нажмите «Проверить подписку». "
        "Золотой уровень получит 10 🍪, остальные — 8 🍪. Награда выдаётся один раз.",
        parse_mode="HTML",
        reply_markup=freebie_keyboard(settings.freebie_channel_url),
    )
    asyncio.create_task(_delete_later(offer, 60))


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


@router.message(Command("transfer"), F.chat.type.in_({"group", "supergroup"}))
async def transfer_command(message: Message, db: Database) -> None:
    if not message.from_user:
        return
    target = await resolve_reply_target(message, db)
    parts = (message.text or "").split()
    if not target or len(parts) != 2 or not parts[1].isdigit():
        await _respond(message, "Ответьте на сообщение пользователя: /transfer 100")
        return
    await _prepare_transfer(message, db, target, int(parts[1]))


async def _prepare_transfer(message: Message, db: Database, target: dict[str, object], amount: int) -> None:
    assert message.from_user
    sender = await register_telegram_user(db, message.from_user)
    if int(target["user_id"]) == message.from_user.id:
        await _respond(message, "Нельзя перевести печеньки самому себе.")
        return
    if amount <= 0 or amount > int(sender["cookies"]):
        await _respond(message, f"Недостаточно печенек. Ваш баланс: {sender['cookies']} 🍪.")
        return
    received = amount * 80 // 100
    if received <= 0:
        await _respond(message, "После комиссии получателю ничего не останется. Минимум — 2 🍪.")
        return
    transfer_id = await db.create_transfer(message.from_user.id, int(target["user_id"]), amount)
    await _respond(
        message,
        f"Перевести {_target_display(target)} {amount} 🍪?\nКомиссия 20%, пользователь получит {received} 🍪.",
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
    if int(target["user_id"]) == message.from_user.id:
        await message.reply("Нельзя менять репутацию самому себе.")
        return
    if message.reply_to_message.from_user.is_bot:
        await message.reply("Репутация ботов не меняется.")
        return
    tier = reputation_tier(int(actor["reputation"]), settings.restricted_reputation_threshold)
    if tier.daily_actions == 0:
        await message.reply("Ваш уровень репутации не позволяет влиять на других участников.")
        return
    timezone = ZoneInfo(settings.timezone)
    local_date = datetime.now(timezone).date()
    used = await db.reputation_actions_today(message.from_user.id, local_date)
    if used >= tier.daily_actions:
        await message.reply(f"Дневной лимит исчерпан: {tier.daily_actions} действий.")
        return
    if delta < 0 and is_immunity_active(target.get("hate_immunity_until")):
        await message.reply("🛡 У пользователя действует иммунитет от понижения репутации.")
        return
    delta, pet_line = await pet_guard_reputation(db, int(target["user_id"]), delta)
    new_value = await db.apply_reputation(message.from_user.id, int(target["user_id"]), delta, local_date)
    target_tier = reputation_tier(new_value, settings.restricted_reputation_threshold)
    sign = "+" if delta > 0 else ""
    extra = f"\n{pet_line}" if pet_line else ""
    await message.reply(
        f"{target_tier.emoji} Репутация {_target_display(target)}: {sign}{delta}, теперь {new_value}.{extra}",
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
