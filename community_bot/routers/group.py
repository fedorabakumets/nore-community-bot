from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from random import choice
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    ChatJoinRequest,
    ChatMemberRestricted,
    ChatMemberUpdated,
    ChatPermissions,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichBlockButtons,
    InputRichBlockParagraph,
    InputRichMessage,
    LinkPreviewOptions,
    Message,
    MessageReactionUpdated,
    ReplyParameters,
    RichMessageButton,
    Update,
    User,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from community_bot import social_likes
from community_bot.access import needs_reapplication
from community_bot.aliases import command_or_alias, is_command_message, remainder_args, strip_command_address
from community_bot.audit import (
    SYSTEM_ACTOR_ID,
    duration_label,
    parse_punitive_args,
    parse_warn_args,
    person_label,
)
from community_bot.blocks import answer_block, edit_block
from community_bot.bot_identity import is_bot
from community_bot.config import COOKIE_PAYMENT_MESSAGE_QR, COOKIE_PAYMENT_URL, Settings
from community_bot.database import Database
from community_bot.domain import (
    NEGATIVE_REPUTATION_PHRASES,
    POSITIVE_REPUTATION_PHRASES,
    REPUTATION_DOWN_DELTA,
    REPUTATION_UP_DELTA,
    cookies_phrase,
    discounted_price,
    is_permanent_duration,
    reputation_delta,
    reputation_tier,
    transfer_amount,
    transfer_commission_percent,
)
from community_bot.ephemeral import delete_user_command, keep_in_chat
from community_bot.group_message_close import without_group_close
from community_bot.group_profile import LIKE_PREFIX, refresh_group_profile
from community_bot.helpers import (
    BOT_REPLY_TTL,
    can_manage_user,
    delete_later,
    display_name,
    effective_role,
    has_permission,
    is_like_phrase,
    like_interaction,
    rank_of_user,
    register_telegram_user,
    resolve_command_target,
    resolve_member_mention,
    resolve_reply_target,
    safe_send,
    targeted_phrase,
    user_link,
    user_permissions,
)
from community_bot.keyboards import (
    admin_panel_keyboard,
    cookie_packages_keyboard,
    flow_reply_keyboard,
    freebie_keyboard,
    pet_species_keyboard,
    profile_transfer_keyboard,
    public_profile_keyboard,
    sbp_payment_keyboard,
    shop_category_keyboard,
    shop_confirm_keyboard,
    shop_home_keyboard,
    transfer_keyboard,
)
from community_bot.permissions import (
    PERM_ADMIN_PANEL,
    PERM_BAN,
    PERM_KICK,
    PERM_MUTE,
    PERM_PAYMENTS,
    PERM_PURGE,
    PERM_ROLES_ASSIGN,
    PERM_USERS_COOKIES,
    PERM_USERS_EDIT,
    PERM_WARN,
)
from community_bot.profile_fields import normalize_tg_channel_url
from community_bot.reaction_authors import ReactionAuthors
from community_bot.reply_rich import bot_publication
from community_bot.reputation_chat_access import sync_reputation_chat_access
from community_bot.shop_catalog import (
    IMMUNITY_HOURS,
    PET_SUPPLIES,
    cookie_rate_line,
    cookie_shop_member_text,
    format_rub,
    item_discount,
    item_label,
    shop_header_lines,
    shop_prices_for,
)
from community_bot.states import CookiePurchase, FlexiblePurchase, ProfileEdit
from community_bot.texts import REPUTATION_HELP_TEXT, STORE_HELP_TEXT
from community_bot.ui_owner import bind_ui_owner

router = Router(name="community")
moderation_router = Router(name="community_moderation")
_bulk_unmute_lock = asyncio.Lock()
_like_limit_notices: dict[tuple[int, int], float] = {}
_LIKE_NOTICE_COOLDOWN = 300


@router.chat_join_request()
async def community_join_request(request: ChatJoinRequest, db: Database, settings: Settings) -> None:
    """Record referrals while Telegram admins review requests."""
    if request.chat.id != settings.community_chat_id:
        return
    from community_bot.referral_campaign import remember_request

    await remember_request(db, request)


@router.chat_member()
async def community_membership_changed(event: ChatMemberUpdated, db: Database, settings: Settings, bot: Bot) -> None:
    if event.chat.id != settings.community_chat_id:
        return
    member = event.new_chat_member
    uid = member.user.id
    if member.user.is_bot:
        return
    if not event.from_user.is_bot:
        if member.status == ChatMemberStatus.KICKED:
            until = member.until_date.timestamp()
            await db.reset_banned_user(uid, until or None)
            return
        if event.old_chat_member.status == ChatMemberStatus.KICKED:
            await db.release_ban_reset(uid)
    joined = member.status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR} or (
        member.status == ChatMemberStatus.RESTRICTED and member.is_member
    )
    if joined and await needs_reapplication(db, uid):
        if db.ban_is_active(await db.ban_reset_state(uid)):
            return
        with contextlib.suppress(TelegramBadRequest, TelegramForbiddenError):
            await bot.ban_chat_member(event.chat.id, uid, until_date=datetime.now(UTC) + timedelta(minutes=1))
            await bot.unban_chat_member(event.chat.id, uid, only_if_banned=True)
        return
    previous = event.old_chat_member
    was_outside = previous.status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED} or (
        previous.status == ChatMemberStatus.RESTRICTED and not previous.is_member
    )
    if joined and (was_outside or isinstance(member, ChatMemberRestricted) and not member.can_send_messages):
        await register_telegram_user(db, member.user)
    if joined and was_outside:
        from community_bot.referral_campaign import record_join

        try:
            await record_join(db, event)
        except Exception:
            logging.getLogger(__name__).exception("Could not attribute a competition invite")
        moscow_day = event.date.astimezone(ZoneInfo("Europe/Moscow")).date()
        await db.remember_community_join(event.chat.id, uid, moscow_day.isoformat())
        from community_bot.welcome import send_member_welcome

        await send_member_welcome(bot, event.chat.id, member.user)


async def text_moderation_reason(db, settings, flags, text, activity_count, *, allow_tgk_link=False):
    blocked_reason = None
    if flags.get("quiet_hours") and 0 <= datetime.now(ZoneInfo(settings.timezone)).hour < 7:
        blocked_reason = "Включён ночной режим: чат открыт с 07:00."
    if flags.get("raid_mode") and activity_count <= 2:
        blocked_reason = "Включён рейд-режим: первые сообщения новых участников проходят проверку."
    if (flags.get("link_filter") and not allow_tgk_link
            and any(marker in text.casefold() for marker in ("http://", "https://", "t.me/"))):
        blocked_reason = "Ссылки сейчас запрещены настройками чата."
    if flags.get("word_filter") and text:
        from community_bot.life import matches_stop_word

        words = [str(row["word"]) for row in await db.list_stop_words()]
        if matches_stop_word(text, words):
            blocked_reason = "Слово из стоп-листа."
    return blocked_reason


class CommunityModerationMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._messages: dict[tuple[int, int], deque[float]] = defaultdict(deque)
        self._admin_cache: dict[tuple[int, int], tuple[float, bool]] = {}
        self._restricted_notices: dict[int, float] = {}

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
        except (TelegramServerError, TelegramNetworkError, TelegramRetryAfter) as error:
            # Fail open on temporary Bot API outages: never mute a Telegram
            # administrator just because getChatMember returned 502.
            logging.getLogger(__name__).warning(
                "Telegram admin role unknown, skipping punitive moderation (%s)",
                type(error).__name__,
            )
            return cached[1] if cached else True
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
        if event.chat.type in {"group", "supergroup"} and isinstance(db, Database) and event.from_user:
            if (
                isinstance(settings, Settings)
                and event.chat.id == settings.community_chat_id
                and await needs_reapplication(db, event.from_user.id)
            ):
                with contextlib.suppress(TelegramAPIError):
                    await event.delete()
                return None
            user = await register_telegram_user(db, event.from_user)
            # A Telegram mute alone is not an access check: a manual unmute,
            # a missed reputation update or a reconnect can restore posting.
            # Enforce the reputation gate before activity rewards and handlers.
            if (
                isinstance(settings, Settings)
                and isinstance(bot, Bot)
                and settings.community_chat_id
                and event.chat.id == settings.community_chat_id
                and not event.sender_chat
                and not event.from_user.is_bot
                and int(user["reputation"]) < settings.restricted_reputation_threshold
                and not await self._is_telegram_admin(bot, event.chat.id, event.from_user.id)
            ):
                with contextlib.suppress(TelegramAPIError):
                    await event.delete()
                await sync_reputation_chat_access(
                    db, settings, bot, event.chat.id,
                    event.from_user.id, int(user["reputation"]),
                )
                now = time.monotonic()
                if now - self._restricted_notices.get(event.from_user.id, -float("inf")) >= 600:
                    if len(self._restricted_notices) > 2000:
                        self._restricted_notices.clear()
                    self._restricted_notices[event.from_user.id] = now
                    with contextlib.suppress(TelegramAPIError):
                        await bot.send_message(
                            event.from_user.id,
                            "🔞 Репутация ниже бронзы. Писать в чат Норы нельзя. "
                            "Восстанови репутацию через магазин в личном чате с Норой.",
                        )
                return None
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
                if activity_count >= 100:
                    from community_bot.life import unlock

                    await unlock(db, event.from_user.id, "messages_100")
                if rewarded and flags.get("activity_rewards", True):
                    pass
                chat_admin = await self._is_telegram_admin(bot, event.chat.id, event.from_user.id)
                member = (not chat_admin) and await rank_of_user(db, settings, event.from_user.id) < 40
                text = event.text or event.caption or ""
                allow_tgk_link = False
                if member and event.text and event.reply_to_message and any(
                    part in event.text.casefold() for part in ("t.me/", "telegram.me/")
                ):
                    prompt = await db.fetchone(
                        "SELECT user_id,expires_at FROM profile_tgk_prompts WHERE chat_id=? AND message_id=?",
                        (event.chat.id, event.reply_to_message.message_id),
                    )
                    if (prompt and int(prompt["user_id"]) == event.from_user.id
                            and str(prompt["expires_at"]) > datetime.now(UTC).isoformat()):
                        try:
                            normalize_tg_channel_url(event.text)
                        except ValueError:
                            pass
                        else:
                            allow_tgk_link = True
                blocked_reason = (
                    await text_moderation_reason(
                        db, settings, flags, text, activity_count, allow_tgk_link=allow_tgk_link,
                    ) if member else None
                )
                media_filter_on = bool(flags.get("media_filter"))
                sticker_filter_on = bool(flags.get("sticker_filter"))
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
                    # Telegram batches updates after deploys and API outages.
                    # Only recent author timestamps count; never count how
                    # rapidly the backlog was delivered to the bot.
                    sent_at = (
                        event.date.timestamp() if isinstance(event.date, datetime)
                        else float(event.date)
                    )
                    arrival_age = datetime.now(UTC).timestamp() - sent_at
                    if 0 <= arrival_age <= 30:
                        key = (event.chat.id, event.from_user.id)
                        bucket = self._messages[key]
                        if bucket and sent_at < bucket[-1]:
                            bucket.clear()
                        bucket.append(sent_at)
                        while bucket and sent_at - bucket[0] > 10:
                            bucket.popleft()
                        if len(bucket) > 6:
                            blocked_reason = "Антифлуд: не больше 6 сообщений за 10 секунд."
                            with contextlib.suppress(TelegramAPIError):
                                await bot.restrict_chat_member(
                                    event.chat.id,
                                    event.from_user.id,
                                    permissions=ChatPermissions(can_send_messages=False),
                                    until_date=datetime.now(UTC) + timedelta(minutes=5),
                                )
                if blocked_reason:
                    with contextlib.suppress(TelegramAPIError):
                        await event.delete()
                    with contextlib.suppress(TelegramAPIError):
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
                if settings.community_chat_id == event.chat.id and flags.get("tamagotchi"):
                    from community_bot.pet_progress import record_message

                    await record_message(db, event)
        return await handler(event, data)


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


def _reputation_ping(settings: Settings, target: dict[str, object], value: int, text: str, pet_line: str | None) -> str:
    tier = reputation_tier(value, settings.restricted_reputation_threshold)
    extra = f"\n{pet_line}" if pet_line else ""
    return f"{tier.emoji} {_target_display(target)}: {html.escape(text)}{extra}"


_SOCIAL_LINES = {
    "обнять": ("🫂 {actor} обнимает {target}.", "🤗 {actor} отправляет тёплые объятия {target}."),
    "пнуть": ("💢 {actor} пинает {target}.", "👟 {actor} отвешивает пинок {target}."),
    "ударить": ("💥 {actor} ударяет {target}.", "🥊 {actor} наносит удар участнику {target}."),
}


async def _give_like(
    db: Database, bot: Bot, actor, target, *, reaction_message: tuple[int, int] | None = None,
) -> str | None:
    if actor.is_bot or await is_bot(db, target, bot.id):
        return "Лайки доступны между участниками."
    return await social_likes.give(db, actor.id, int(target["user_id"]), reaction_message=reaction_message)


def _like_notice(actor: User, target) -> str:
    sender = user_link(actor.id, "@" + (actor.username or actor.full_name))
    recipient = user_link(int(target["user_id"]), "@" + (target.get("username") or display_name(target)))
    return f"❤️ {sender} лайкнул {recipient}"


async def _announce_like(message: Message, actor: User, target) -> None:
    with bot_publication(), keep_in_chat():
        await message.answer(_like_notice(actor, target), parse_mode="HTML")


def _claim_like_limit_notice(actor_id: int, target_id: int) -> float | None:
    now = time.monotonic()
    # Insertion order lets us discard expired pairs without scanning all active ones.
    while _like_limit_notices:
        oldest = next(iter(_like_limit_notices))
        if now - _like_limit_notices[oldest] < _LIKE_NOTICE_COOLDOWN:
            break
        del _like_limit_notices[oldest]
    pair = (actor_id, target_id)
    if pair in _like_limit_notices:
        return None
    _like_limit_notices[pair] = now
    return now


async def _send_like_limit_notice(
    bot: Bot, actor: User, target, chat_id: int, message_id: int, thread_id: int | None = None,
) -> None:
    pair = (actor.id, int(target["user_id"]))
    claimed = _claim_like_limit_notice(*pair)
    if claimed is None:
        return
    try:
        username = (await bot.me()).username
        text = "💔 Лайк этому участнику уже поставлен. Можно восстановить лимиты в магазине или сыграв в игры:"
        buttons = []
        if username:
            base = f"https://t.me/{username}?startapp=nora_to_"
            buttons = [
                RichMessageButton(text="🃏 Дурак", url=f"{base}durak", style="primary"),
                RichMessageButton(text="🪵 Баррикада", url=f"{base}barricade", style="success"),
            ]
        blocks = [InputRichBlockParagraph(text=text)]
        if buttons:
            blocks.append(InputRichBlockButtons(align="center", buttons=buttons))
        reply = ReplyParameters(message_id=message_id, allow_sending_without_reply=True)
        with bot_publication(), without_group_close():
            try:
                await bot.send_rich_message(
                    chat_id, rich_message=InputRichMessage(blocks=blocks, skip_entity_detection=True),
                    reply_parameters=reply, message_thread_id=thread_id,
                )
            except (TelegramBadRequest, TelegramNotFound):
                markup = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=b.text, url=b.url, style=b.style) for b in buttons
                ]]) if buttons else None
                await bot.send_message(
                    chat_id, text, reply_markup=markup, reply_parameters=reply, message_thread_id=thread_id,
                )
    except BaseException:
        if _like_limit_notices.get(pair) == claimed:
            _like_limit_notices.pop(pair, None)
        raise


async def _can_manage_target(
    actor_id: int,
    target: dict[str, object],
    db: Database,
    settings: Settings,
) -> bool:
    return await can_manage_user(db, settings, actor_id, int(target["user_id"]))


def _full_permissions() -> ChatPermissions:
    return ChatPermissions(**dict.fromkeys(ChatPermissions.model_fields, True))


async def _take_target(
    message: Message,
    db: Database,
    settings: Settings,
    hint: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    if not message.from_user:
        return None, []
    target, args, _ = await resolve_command_target(message, db)
    if not target:
        await _respond(message, hint)
        return None, args
    if int(target["user_id"]) == message.from_user.id:
        await _respond(message, "На себя эту команду закрыть нельзя.")
        return None, args
    if not await can_manage_user(db, settings, message.from_user.id, int(target["user_id"])):
        await _respond(message, "Ранг этого человека не ниже вашего — действие закрыто.")
        return None, args
    return target, args


async def restrict_mute(bot: Bot, chat_id: int, user_id: int, duration: timedelta) -> None:
    kwargs: dict[str, Any] = {"permissions": ChatPermissions(can_send_messages=False)}
    if not is_permanent_duration(duration):
        kwargs["until_date"] = datetime.now(UTC) + duration
    await bot.restrict_chat_member(chat_id, user_id, **kwargs)


async def _delete_message_ids(bot: Bot, chat_id: int, message_ids: list[int]) -> int:
    unique = [item for item in dict.fromkeys(message_ids) if item > 0]
    removed = 0
    for index in range(0, len(unique), 100):
        chunk = unique[index : index + 100]
        try:
            await bot.delete_messages(chat_id, chunk)
            removed += len(chunk)
        except (TelegramBadRequest, TelegramForbiddenError, AttributeError):
            for message_id in chunk:
                with contextlib.suppress(TelegramBadRequest, TelegramForbiddenError):
                    await bot.delete_message(chat_id, message_id)
                    removed += 1
    return removed


@router.message(command_or_alias("question"), F.chat.type.in_({"group", "supergroup"}))
async def question_in_group(message: Message) -> None:
    notice = await message.reply(
        "Тикет открывается в личке с ботом: напишите «вопрос» или нажмите «🎫 Тикет»."
    )
    asyncio.create_task(_delete_later(notice))


@router.message(command_or_alias("commands", "help"), F.chat.type.in_({"group", "supergroup"}))
@router.message(F.chat.type.in_({"group", "supergroup"}), F.text, Command("commands", magic=~F.args))
async def group_commands(message: Message, bot: Bot) -> None:
    from community_bot.commands_guide import send_commands_card

    if strip_command_address(message.text or message.caption or "") is None:
        from community_bot.command_registry import get_command

        view = get_command("commands")
        if view and (not view.enabled or not view.allows(message.chat.type)):
            return
        await delete_user_command(message, bot)
    await send_commands_card(message, bot)


@router.message(command_or_alias("cinema"), F.chat.type.in_({"group", "supergroup"}))
async def cinema_from_chat(message: Message, bot: Bot, settings: Settings, nora_cinema=None) -> None:
    if message.chat.id != settings.community_chat_id or not message.from_user or message.sender_chat:
        return
    if not nora_cinema:
        await _respond(message, "Кинотеатр пока недоступен.")
        return
    media = message.reply_to_message
    if not media:
        await _respond(message, "Ответь «Нора, в кино» на видео MP4 до 20 МБ.")
        return
    try:
        await nora_cinema.import_clip(bot, media)
    except ValueError as error:
        await _respond(message, str(error))
        return
    await _respond(message, "Ролик в кинотеатре. Открой список «Видео из Telegram» в зале.")


@router.message(command_or_alias("pogoda"), F.chat.type.in_({"group", "supergroup"}))
async def group_weather(message: Message, settings: Settings) -> None:
    from community_bot.morning import weather_reply

    now = datetime.now(ZoneInfo(settings.timezone))
    await message.answer(
        await weather_reply(now),
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@router.message(command_or_alias("reputation"), F.chat.type.in_({"group", "supergroup"}))
async def reputation_help(message: Message) -> None:
    await answer_block(message, "reputation", REPUTATION_HELP_TEXT, parse_mode="HTML")


@router.message(command_or_alias("store"), F.chat.type.in_({"group", "supergroup"}))
async def store_help(message: Message) -> None:
    await answer_block(message, "shop", STORE_HELP_TEXT, parse_mode="HTML")


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
    from community_bot.routers.private import _web_admin_markup

    web_markup = await _web_admin_markup(db, settings, message.from_user.id)
    try:
        await bot.send_message(
            message.from_user.id,
            text,
            parse_mode="HTML",
            reply_markup=web_markup or admin_panel_keyboard(
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
    target, args, _ = await resolve_command_target(message, db)
    if not target or args:
        await _respond(message, "Ответьте «Нора карточка» или напишите «Нора карточка @имя».")
        return
    pet = await db.get_pet(int(target["user_id"]), settle=False)
    note = str(target.get("moderator_note") or "").strip() or "нет"
    pet_line = str(pet["name"]) if pet else "нет"
    await _respond(
        message,
        f"👤 <b>{html.escape(person_label(target))}</b> · <code>{target['user_id']}</code>\n"
        f"Роль: {html.escape(str(target['role']))}\n"
        f"Репутация: <b>{target['reputation']}</b> · 🍪 {target['cookies']}\n"
        f"Варны: {target['warnings']} · щиты: {int(target.get('hate_shields') or 0)}\n"
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
    target, args = await _take_target(
        message, db, settings, "Ответьте «Нора мут 30m флуд» или напишите «Нора мут @имя 30m флуд».",
    )
    if not target:
        return
    duration, reason, error = parse_punitive_args(args, need_duration=True)
    if error or duration is None:
        await _respond(message, error or "Нужны время и причина. Пример: /mute 30m флуд")
        return
    label = duration_label(duration)
    try:
        await restrict_mute(bot, message.chat.id, int(target["user_id"]), duration)
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        await _respond(message, f"Telegram отказал в муте: {exc}")
        return
    await db.log_admin_action(
        message.from_user.id,
        "mute",
        str(target["user_id"]),
        label,
        reason=reason,
        actor_name=message.from_user.full_name,
        target_name=person_label(target),
        default_duration=False,
    )
    await _respond(
        message,
        f"🔇 {_target_display(target)} получает мут на {label} · {html.escape(reason)}.",
        parse_mode="HTML",
    )


@router.callback_query(
    F.data.regexp(rf"^{LIKE_PREFIX}[1-9][0-9]{{0,15}}$"), F.message.chat.type.in_({"group", "supergroup"}),
)
async def profile_like(callback: CallbackQuery, db: Database, settings: Settings, bot: Bot) -> None:
    message = callback.message
    if not isinstance(message, Message) or not callback.data:
        await callback.answer("Профиль больше недоступен.")
        return
    if settings.community_chat_id and message.chat.id != settings.community_chat_id:
        await callback.answer("Лайки доступны в основном чате Норы.", show_alert=True)
        return
    target_id = int(callback.data.removeprefix(LIKE_PREFIX))
    target = await db.get_user(target_id)
    if target is None:
        await callback.answer("Профиль больше недоступен.")
        return
    error = await _give_like(db, bot, callback.from_user, target)
    await callback.answer(error or "Лайк отправлен ❤️", show_alert=bool(error))
    if not error:
        await _announce_like(message, callback.from_user, target)
    await refresh_group_profile(message, db, settings, target_id)


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
    if action not in {"rep_up", "rep_down"}:
        return
    if await is_bot(db, target):
        await callback.answer("Репутация ботов не меняется.", show_alert=True)
        return
    delta = REPUTATION_UP_DELTA if action == "rep_up" else REPUTATION_DOWN_DELTA
    timezone = ZoneInfo(settings.timezone)
    local_date = datetime.now(timezone).date()
    from community_bot.reputation import change_community_reputation

    ok, text, new_value, pet_line = await change_community_reputation(
        db, settings, actor, target, delta, local_date
    )
    if not ok or new_value is None:
        await callback.answer(text, show_alert=True)
        return
    if callback.message.chat.id == settings.community_chat_id and not callback.from_user.is_bot:
        from community_bot.pet_progress import record_telegram_event

        await record_telegram_event(
            db, callback.from_user.id, "plus" if delta > 0 else "minus",
            (callback.message.chat.id, f"callback:{callback.id}", datetime.now(UTC)),
        )
    if delta > 0:
        from community_bot.life import unlock

        await unlock(db, callback.from_user.id, "first_plus")
    await callback.answer("Питомец вмешался!" if pet_line and "перехватил" in pet_line else text[:180])
    await callback.message.answer(
        _reputation_ping(settings, target, new_value, text, pet_line),
        parse_mode="HTML",
    )
    if pet_line and "перехватил" in pet_line:
        from community_bot.notify import emit

        await emit(bot, db, target_id, "pet", pet_line)
    if callback.message.chat.id == settings.community_chat_id:
        access = await sync_reputation_chat_access(
            db, settings, bot, callback.message.chat.id, target_id, new_value,
            allow_legacy_recovery=delta > 0,
        )
        if new_value < settings.restricted_reputation_threshold:
            await callback.message.answer("🔞 Репутация ниже 50: отправка сообщений в чат ограничена.")
        elif access == "restored":
            await callback.message.answer("✅ Репутация снова от 50: доступ к чату восстановлен.")
    if isinstance(callback.message, Message):
        await refresh_group_profile(callback.message, db, settings, target_id)


@router.callback_query(F.data.startswith("profile_transfer:"), F.message.chat.type.in_({"group", "supergroup"}))
async def profile_transfer(callback: CallbackQuery, db: Database, settings: Settings) -> None:
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
    percent = transfer_commission_percent(
        int(sender["reputation"]),
        settings.restricted_reputation_threshold,
    )
    received = amount * (100 - percent) // 100
    transfer_id = await db.create_transfer(callback.from_user.id, target_id, amount)
    await callback.message.edit_reply_markup(reply_markup=public_profile_keyboard(target_id))
    await callback.answer("Подтвердите перевод.")
    from community_bot.message_widgets import transfer_card

    if await transfer_card(callback.message, target, amount, percent, received, transfer_keyboard(transfer_id)):
        return
    await callback.message.answer(
        f"<b>Перевод · {amount} 🍪</b>\nПолучатель: {_target_display(target)}\n"
        f"Комиссия {percent}% (по уровню репутации), пользователь получит {received} 🍪.",
        parse_mode="HTML",
        reply_markup=transfer_keyboard(transfer_id),
    )


async def _lift_community_mutes(bot: Bot, db: Database, settings: Settings, actor_id: int) -> str:
    chat_id = settings.community_chat_id
    chat = await bot.get_chat(chat_id)
    bot_member = await bot.get_chat_member(chat_id, bot.id)
    if bot_member.status != ChatMemberStatus.CREATOR and not getattr(bot_member, "can_restrict_members", False):
        return "Норе нужно право «Блокировка участников» в Telegram."

    opened_text = chat.permissions is not None and not chat.permissions.can_send_messages
    if opened_text:
        permissions = chat.permissions.model_copy(update={"can_send_messages": True})
        await bot.set_chat_permissions(chat_id, permissions, use_independent_chat_permissions=True)

    lifted = skipped = errors = 0
    wait_seconds = 0
    if chat.type == "supergroup":
        for row in await db.list_all_users():
            uid = int(row["user_id"])
            if uid <= 0 or uid == bot.id:
                continue
            try:
                member = await bot.get_chat_member(chat_id, uid)
                if not isinstance(member, ChatMemberRestricted) or not member.is_member or member.can_send_messages:
                    continue
                if (
                    int(row["reputation"]) < settings.restricted_reputation_threshold
                    or not await can_manage_user(db, settings, actor_id, uid)
                    or await needs_reapplication(db, uid)
                ):
                    skipped += 1
                    continue
                await bot.restrict_chat_member(
                    chat_id, uid, permissions=_full_permissions(), use_independent_chat_permissions=True,
                )
                lifted += 1
            except TelegramRetryAfter as error:
                wait_seconds = error.retry_after
                break
            except TelegramAPIError:
                errors += 1

    text = (
        f"{'Отправка текста в чате открыта.' if opened_text else 'Общего запрета на текст не было.'}\n"
        f"Личных мутов снято: {lifted}."
    )
    if skipped:
        text += f"\nПропущено по рангу или статусу допуска: {skipped}."
    if errors:
        text += f"\nОшибок Telegram при проверке или снятии: {errors}."
    if wait_seconds:
        text += f"\nTelegram прервал проверку по лимиту. Повтори команду через {wait_seconds} сек."
    return text


@moderation_router.message(command_or_alias("unmute_all"), F.text)
async def unmute_all_members(
    message: Message, command: CommandObject, db: Database, settings: Settings, bot: Bot,
) -> None:
    chat_id = settings.community_chat_id
    if message.sender_chat or not message.from_user or message.from_user.is_bot:
        return
    if message.chat.type != "private" and message.chat.id != chat_id:
        return
    if not await _require_perm(message, db, settings, PERM_MUTE):
        return
    if command.args:
        await _respond(message, "Напиши «Нора размут всех» без дополнительных слов.")
        return
    if not chat_id:
        await _respond(message, "ID чата сообщества не настроен.")
        return
    if _bulk_unmute_lock.locked():
        await _respond(message, "Нора уже проверяет муты в чате.")
        return
    async with _bulk_unmute_lock:
        try:
            result = await _lift_community_mutes(bot, db, settings, message.from_user.id)
        except TelegramAPIError:
            result = "Telegram не дал проверить или изменить общие права чата."
        await db.log_admin_action(
            message.from_user.id, "unmute_all", str(chat_id), result, actor_name=message.from_user.full_name,
        )
    await _respond(message, result)


@router.message(command_or_alias("unmute"), F.chat.type.in_({"group", "supergroup"}))
async def unmute_member(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not await _require_perm(message, db, settings, PERM_MUTE) or not message.from_user:
        return
    target, args = await _take_target(message, db, settings, "Ответьте человеку или напишите «Нора размут @имя».")
    if not target:
        return
    if int(target["reputation"]) < settings.restricted_reputation_threshold:
        await _respond(message, "🔞 Репутация ниже бронзы: сначала нужно её восстановить.")
        return
    try:
        await bot.restrict_chat_member(message.chat.id, int(target["user_id"]), permissions=_full_permissions())
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        await _respond(message, f"Telegram отказал: {exc}")
        return
    await db.log_admin_action(
        message.from_user.id,
        "unmute",
        str(target["user_id"]),
        actor_name=message.from_user.full_name,
        target_name=person_label(target),
        reason=" ".join(args),
    )
    await _respond(message, f"🔊 Мут с {_target_display(target)} снят.", parse_mode="HTML")


@router.message(command_or_alias("kick"), F.chat.type.in_({"group", "supergroup"}))
async def kick_member(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not await _require_perm(message, db, settings, PERM_KICK) or not message.from_user:
        return
    target, args = await _take_target(
        message, db, settings, "Ответьте «Нора кик реклама» или напишите «Нора кик @имя реклама».",
    )
    if not target:
        return
    _, reason, error = parse_punitive_args(args, need_duration=False)
    if error:
        await _respond(message, error)
        return
    target_id = int(target["user_id"])
    try:
        await bot.ban_chat_member(message.chat.id, target_id)
        await bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        await _respond(message, f"Telegram отказал в кике: {exc}")
        return
    await db.log_admin_action(
        message.from_user.id,
        "kick",
        str(target_id),
        actor_name=message.from_user.full_name,
        target_name=person_label(target),
        reason=reason,
    )
    await _respond(
        message,
        f"👢 {_target_display(target)} исключён из чата · {html.escape(reason)}.",
        parse_mode="HTML",
    )


async def apply_chat_ban(
    bot: Bot, db: Database, settings: Settings, chat_id: int, target_id: int, duration: timedelta,
) -> bool:
    until = None if is_permanent_duration(duration) else datetime.now(UTC) + duration
    await bot.ban_chat_member(chat_id, target_id, **({"until_date": until} if until else {}))
    resets_account = chat_id == settings.community_chat_id or not settings.community_chat_id
    if resets_account:
        await db.reset_banned_user(target_id, until.timestamp() if until else None)
    return resets_account


async def lift_chat_ban(bot: Bot, db: Database, settings: Settings, chat_id: int, target_id: int) -> None:
    await bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
    if chat_id == settings.community_chat_id or not settings.community_chat_id:
        await db.release_ban_reset(target_id)


@router.message(command_or_alias("ban"), F.chat.type.in_({"group", "supergroup"}))
async def ban_member(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not await _require_perm(message, db, settings, PERM_BAN) or not message.from_user:
        return
    target, args = await _take_target(
        message, db, settings, "Ответьте «Нора бан 7d спам» или напишите «Нора бан @имя 7d спам».",
    )
    if not target:
        return
    duration, reason, error = parse_punitive_args(args, need_duration=True, allow_permanent=True)
    if error or duration is None:
        await _respond(message, error or "Нужны время и причина. Пример: /ban 7d скам или /ban навсегда скам")
        return
    label = duration_label(duration)
    target_id = int(target["user_id"])
    try:
        resets_account = await apply_chat_ban(bot, db, settings, message.chat.id, target_id, duration)
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        await _respond(message, f"Telegram отказал в бане: {exc}")
        return
    await db.log_admin_action(
        message.from_user.id,
        "ban",
        str(target["user_id"]),
        label,
        actor_name=message.from_user.full_name,
        target_name=person_label(target),
        reason=reason,
        default_duration=False,
    )
    await _respond(
        message,
        f"⛔ {_target_display(target)} заблокирован на {label} · {html.escape(reason)}."
        + (" Профиль и прогресс сброшены." if resets_account else ""),
        parse_mode="HTML",
    )


@router.message(command_or_alias("unban"), F.chat.type.in_({"group", "supergroup"}))
async def unban_member(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not await _require_perm(message, db, settings, PERM_BAN) or not message.from_user:
        return
    stored, args, explicit = await resolve_command_target(message, db)
    target_id: int | None = None
    if not explicit and args and args[0].lstrip("-").isdigit():
        target_id = int(args[0])
        stored = await db.get_user(target_id)
        args = args[1:]
    elif stored:
        target_id = int(stored["user_id"])
    if target_id is None:
        await _respond(message, "Ответьте «Нора разбан причина» или укажите @имя либо Telegram ID перед причиной.")
        return
    reason = " ".join(args)
    if len(reason) < 2:
        await _respond(message, "Нужна причина разбана — минимум два символа.")
        return
    if stored and not await can_manage_user(db, settings, message.from_user.id, target_id):
        await _respond(message, "Ранг этого человека не ниже вашего — действие закрыто.")
        return
    try:
        await lift_chat_ban(bot, db, settings, message.chat.id, target_id)
    except (TelegramBadRequest, TelegramForbiddenError) as exc:
        await _respond(message, f"Telegram отказал: {exc}")
        return
    await db.log_admin_action(
        message.from_user.id,
        "unban",
        str(target_id),
        actor_name=message.from_user.full_name,
        target_name=person_label(stored, str(target_id)),
        reason=reason,
    )
    await _respond(message, f"Пользователь разблокирован · {html.escape(reason)}.")


@router.message(command_or_alias("warn"), F.chat.type.in_({"group", "supergroup"}))
async def warn_member(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not await _require_perm(message, db, settings, PERM_WARN) or not message.from_user:
        return
    target, args = await _take_target(
        message, db, settings, "Ответьте «Нора варн спам» или напишите «Нора варн @имя спам».",
    )
    if not target:
        return
    duration, reason, error = parse_warn_args(args)
    if error:
        await _respond(message, error)
        return
    warnings = await db.add_warning(int(target["user_id"]))
    mute_note = ""
    if duration is not None:
        try:
            await restrict_mute(bot, message.chat.id, int(target["user_id"]), duration)
            mute_note = f" + мут {duration_label(duration)}"
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            mute_note = f" (мут не встал: {exc})"
    from community_bot.routers.life import apply_warn_ladder

    ladder = await apply_warn_ladder(bot, message, int(target["user_id"]), warnings)
    details = f"всего {warnings}{mute_note}"
    if message.reply_to_message and message.reply_to_message.from_user and (
        message.reply_to_message.from_user.id == target["user_id"]
    ):
        details = f"{details}|src:{message.chat.id}:{message.reply_to_message.message_id}"
    await db.log_admin_action(
        message.from_user.id,
        "warn",
        str(target["user_id"]),
        details,
        actor_name=message.from_user.full_name,
        target_name=person_label(target),
        reason=reason,
    )
    await _respond(
        message,
        f"⚠️ {_target_display(target)} получает предупреждение. Всего: {warnings}."
        f" · {html.escape(reason)}{html.escape(mute_note)}{ladder}",
        parse_mode="HTML",
    )


@router.message(command_or_alias("unwarn"), F.chat.type.in_({"group", "supergroup"}))
async def unwarn_member(message: Message, db: Database, settings: Settings) -> None:
    if not await _require_perm(message, db, settings, PERM_WARN) or not message.from_user:
        return
    target, args = await _take_target(message, db, settings, "Ответьте человеку или напишите «Нора разварн @имя».")
    if not target:
        return
    warnings = await db.remove_warning(int(target["user_id"]))
    await db.log_admin_action(
        message.from_user.id,
        "unwarn",
        str(target["user_id"]),
        f"осталось {warnings}",
        actor_name=message.from_user.full_name,
        target_name=person_label(target),
        reason=" ".join(args),
    )
    await _respond(
        message,
        f"✅ С {_target_display(target)} снято предупреждение. Осталось: {warnings}.",
        parse_mode="HTML",
    )


@router.message(command_or_alias("purge"), F.chat.type.in_({"group", "supergroup"}))
async def purge_chat(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not await _require_perm(message, db, settings, PERM_PURGE) or not message.from_user:
        return
    args = remainder_args(message.text or "")
    if not args or not args[0].isdigit():
        await _respond(message, "Нужны число 2–100 и причина. Пример: /purge 50 флуд")
        return
    count = int(args[0])
    if not 2 <= count <= 100:
        await _respond(message, "Число сообщений — от 2 до 100.")
        return
    reason = " ".join(args[1:]).strip()
    if len(reason) < 2:
        await _respond(message, "После числа напишите причину — минимум два символа.")
        return
    start = max(1, message.message_id - count + 1)
    ids = list(range(start, message.message_id + 1))
    removed = await _delete_message_ids(bot, message.chat.id, ids)
    await db.log_admin_action(
        message.from_user.id,
        "purge",
        str(message.chat.id),
        f"{removed} из {count}",
        actor_name=message.from_user.full_name,
        target_name=str(message.chat.id),
        reason=reason,
    )
    await _respond(message, f"🧹 Удалено сообщений: {removed} · {html.escape(reason)}")


@router.message(command_or_alias("botsweep"), F.chat.type.in_({"group", "supergroup"}))
async def sweep_bot_messages(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    if not await _require_perm(message, db, settings, PERM_PURGE) or not message.from_user:
        return
    args = remainder_args(message.text or "")
    if not args or not args[0].isdigit():
        await _respond(message, "Нужны число 1–100 и причина. Пример: /botsweep 30 уборка")
        return
    count = int(args[0])
    if not 1 <= count <= 100:
        await _respond(message, "Число сообщений бота — от 1 до 100.")
        return
    reason = " ".join(args[1:]).strip()
    if len(reason) < 2:
        await _respond(message, "После числа напишите причину — минимум два символа.")
        return
    ids = await db.recent_bot_message_ids(message.chat.id, count)
    removed = await _delete_message_ids(bot, message.chat.id, ids)
    await db.forget_bot_messages(message.chat.id, ids)
    await db.log_admin_action(
        message.from_user.id,
        "botsweep",
        str(message.chat.id),
        f"{removed} из {len(ids)}",
        actor_name=message.from_user.full_name,
        target_name=str(message.chat.id),
        reason=reason,
    )
    await _respond(message, f"🤖 Удалено сообщений бота: {removed} · {html.escape(reason)}")


@router.message(command_or_alias("role"), F.chat.type.in_({"group", "supergroup"}))
async def change_role(message: Message, db: Database, settings: Settings) -> None:
    if not await _require_perm(message, db, settings, PERM_ROLES_ASSIGN) or not message.from_user:
        return
    target, args, _ = await resolve_command_target(message, db, after_first=True)
    if not target or len(args) != 1:
        await _respond(message, "Ответьте «Нора роль код_роли» или напишите «Нора роль @имя код_роли».")
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


async def _shop_prices(db: Database, user: dict[str, object], settings: Settings) -> dict[str, int]:
    return shop_prices_for(user, settings.restricted_reputation_threshold, await db.priced_shop_map())


async def _shop_home_text(db: Database, user: dict[str, object], settings: Settings) -> str:
    tier = reputation_tier(int(user["reputation"]), settings.restricted_reputation_threshold)
    header = shop_header_lines(await db.shop_header())
    cookie_shop = await db.cookie_shop()
    rate = cookie_rate_line(int(cookie_shop["rate_rub"])) if cookie_shop.get("enabled") else ""
    rate_line = f"{rate}\n" if rate else ""
    return (
        f"{header}🛒 <b>Магазин NORA</b>\n"
        f"{rate_line}"
        f"Баланс: <b>{user['cookies']} 🍪</b>\n"
        f"Уровень: {tier.emoji} · скидка {tier.discount}%\n\n"
        "Откройте полку — у каждого товара цена в 🍪. Покупка только после подтверждения. "
        "Категории и покупки синхронизированы с миниапкой."
    )


async def _shop_home_markup(db: Database):
    from community_bot.life import vitrine_active

    key = await db.get_bot_state("shop_featured")
    label = await db.get_bot_state("shop_featured_label")
    stock = await db.get_bot_state("shop_featured_stock")
    until = await db.get_bot_state("shop_featured_until")
    if key and not vitrine_active(stock, until):
        await db.set_bot_state("shop_featured", "")
        await db.set_bot_state("shop_featured_label", "")
        key, label = "", None
    elif key and label:
        extra = []
        if stock and stock not in {"", "0"}:
            extra.append(f"ещё {stock}")
        if until:
            try:
                extra.append("до " + datetime.fromisoformat(until).strftime("%H:%M"))
            except ValueError:
                pass
        if extra:
            label = f"{label} · {' · '.join(extra)}"
    categories = await db.list_shop_categories(enabled_only=True)
    return shop_home_keyboard(
        categories,
        featured_key=key,
        featured_label=label if key else None,
        cookie_shop=await db.cookie_shop(),
    )


@router.message(command_or_alias("shop"))
@router.message(F.chat.type == "private", F.text == "🛒 Магазин")
async def show_shop(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    user = await register_telegram_user(db, message.from_user)
    sent = await answer_block(
        message,
        "shop",
        await _shop_home_text(db, user, settings),
        parse_mode="HTML",
        reply_markup=await _shop_home_markup(db),
    )
    await bind_ui_owner(db, sent, message.from_user.id, "shop")


@router.callback_query(F.data == "shop:home")
async def shop_home(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message:
        return
    user = await register_telegram_user(db, callback.from_user)
    await callback.answer()
    markup = await _shop_home_markup(db)
    await edit_block(
        callback.message,
        await _shop_home_text(db, user, settings),
        parse_mode="HTML",
        reply_markup=markup,
    )


@router.callback_query(F.data.startswith("shop:cat:"))
async def shop_category(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message:
        return
    category = callback.data.rsplit(":", 1)[1]
    user = await register_telegram_user(db, callback.from_user)
    prices = await _shop_prices(db, user, settings)
    header = shop_header_lines(await db.shop_header())
    if category == "extra":
        event_title = (await db.get_bot_state("event_title")) or "текущее мероприятие"
        title = "🎟 Мероприятия"
        intro = (
            f"Сейчас: <b>{html.escape(event_title)}</b>. "
            "Скидка репутации на мероприятия не действует — цена как указано."
        )
        items: list[dict[str, object]] = []
    else:
        cat = await db.get_shop_category(category)
        if not cat or not int(cat.get("enabled") or 0):
            await callback.answer("Нет такой полки.", show_alert=True)
            return
        title = str(cat["title"])
        intro = str(cat.get("description") or "")
        items = await db.list_shop_items(category, enabled_only=True, priced_only=True)
    text = f"{header}{title}\nБаланс: <b>{user['cookies']} 🍪</b>\n\n{intro}"
    await callback.answer()
    await edit_block(
        callback.message,
        text,
        parse_mode="HTML",
        reply_markup=shop_category_keyboard(category, prices, items=items),
    )


@router.callback_query(F.data == "shop:buy_cookies")
async def choose_cookie_pack(callback: CallbackQuery, db: Database) -> None:
    shop = await db.cookie_shop()
    if not shop.get("enabled"):
        await callback.answer("Покупка печенек временно закрыта.", show_alert=True)
        return
    await callback.answer()
    if not callback.message:
        return
    header = shop_header_lines(await db.shop_header())
    await edit_block(
        callback.message,
        cookie_shop_member_text(shop, header),
        parse_mode="HTML",
        reply_markup=cookie_packages_keyboard(shop),
    )


@router.message(command_or_alias("buycookies"))
async def buycookies_command(message: Message, db: Database) -> None:
    shop = await db.cookie_shop()
    if not shop.get("enabled"):
        await message.answer("Покупка печенек временно закрыта.")
        return
    header = shop_header_lines(await db.shop_header())
    await message.answer(
        cookie_shop_member_text(shop, header),
        parse_mode="HTML",
        reply_markup=cookie_packages_keyboard(shop),
    )


@router.callback_query(F.data.startswith("cookies:sbp:"))
async def begin_sbp_purchase(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    shop = await db.cookie_shop()
    if not shop.get("enabled"):
        await callback.answer("Покупка печенек временно закрыта.", show_alert=True)
        return
    amount = int(callback.data.rsplit(":", 1)[1])
    packs = {int(item) for item in shop["packs"]}
    if amount not in packs:
        await callback.answer("Некорректный пакет.", show_alert=True)
        return
    rubles = amount * int(shop["rate_rub"])
    await state.set_state(CookiePurchase.receipt)
    await state.set_data({"amount": amount, "rubles": rubles})
    await callback.answer()
    await callback.message.answer_photo(
        photo=FSInputFile(COOKIE_PAYMENT_MESSAGE_QR),
        caption=(
            f"Вы выбрали <b>{cookies_phrase(amount, case='acc')}</b> ({amount} 🍪). "
            f"К оплате: <b>{format_rub(rubles)}</b>.\n\n"
            "Откройте СБП кнопкой или отсканируйте QR-код. Укажите точную сумму и выберите свой банк. "
            "После перевода отправьте чек следующим сообщением."
        ),
        parse_mode="HTML",
        reply_markup=sbp_payment_keyboard(COOKIE_PAYMENT_URL),
    )
    if callback.message.chat.type == "private":
        await callback.message.answer(
            "Чтобы отменить оплату, напишите /close или откройте меню.",
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
    from community_bot.shop_api import notify_cookie_order

    await notify_cookie_order(bot, db, settings, order_id)


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
    from community_bot.widget_notifications import Sender, send_service_notification

    if approved:
        details = f"Оплата заказа №{order_id} подтверждена. На баланс начислено {order['amount']} 🍪."
    else:
        details = f"Оплата заказа №{order_id} не подтверждена. Напишите боту «вопрос» или нажмите «Тикет»."
    await send_service_notification(
        bot, db, int(order["user_id"]), Sender(), "Статус оплаты", details, "history",
        event_key=f"payment:{order_id}",
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
        or callback.data.startswith("shop:g:")
    ):
        return
    if callback.data.startswith("shop:eq:") or callback.data.startswith("shop:look:"):
        await callback.answer("Этот товар больше не продаётся.", show_alert=True)
        return
    raw = callback.data
    if raw.startswith("shop:ok:"):
        await callback.answer("Старая кнопка покупки. Откройте товар заново — списания не было.", show_alert=True)
        return
    confirmed = raw.startswith("shop:pay:")
    token = raw.removeprefix("shop:pay:") if confirmed else None
    intent = await db.get_wallet_intent(callback.from_user.id, token) if token else None
    if confirmed and not intent:
        await callback.answer("Подтверждение устарело или уже выполнено. Откройте товар заново.", show_alert=True)
        return
    item = str(intent["item"]) if intent else raw.split(":", 1)[1]
    user = await register_telegram_user(db, callback.from_user)
    prices = await _shop_prices(db, user, settings)
    if item == "event_pass":
        from community_bot.event_access import open_event_purchase

        await state.clear()
        await open_event_purchase(callback, db)
        return
    if item in {"event_pass", "support"} and not confirmed:
        tier = reputation_tier(int(user["reputation"]), settings.restricted_reputation_threshold)
        discount = item_discount(item, tier.discount)
        await state.set_state(FlexiblePurchase.amount)
        await state.set_data({"flex_item": item, "flex_discount": discount})
        label = "оплаты мероприятия" if item == "event_pass" else "поддержки развития"
        extra = (
            "Скидка репутации на мероприятия не действует."
            if item == "event_pass"
            else f"Ваша скидка уровня — {discount}%; итог бот покажет перед списанием."
        )
        await callback.answer()
        await callback.message.answer(
            f"Введите желаемую сумму для {label} в печеньках. {extra}",
            reply_markup=flow_reply_keyboard() if callback.message.chat.type == "private" else None,
        )
        return
    catalog_item = await db.get_shop_item(item)
    if catalog_item and not int(catalog_item.get("enabled") or 0):
        await callback.answer("Товар выключен.", show_alert=True)
        return
    flexible = item in {"event_pass", "support"}
    if item not in prices and not flexible:
        await callback.answer("Товар временно недоступен.", show_alert=True)
        return
    price = int(intent["price"]) if intent else prices[item]
    if confirmed and not flexible and price != prices[item]:
        await callback.answer("Цена изменилась. Откройте товар и подтвердите новую цену.", show_alert=True)
        return
    if confirmed and intent["payload"].get("gift"):
        from community_bot.routers.life import _deliver_shop

        ok, error = await _deliver_shop(
            db, settings, bot, callback.from_user.id, int(intent["target_id"]), item, price, intent_id=token,
        )
        if not ok:
            await callback.answer(error, show_alert=True)
            return
        await callback.answer("Подарок доставлен.")
        await edit_block(
            callback.message,
            f"🎁 Подарок «{html.escape(item_label(item))}» доставлен.\nСписано <b>{price} 🍪</b>.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛒 В магазин", callback_data="shop:home")],
            ]),
        )
        return
    if not confirmed:
        token = await db.create_wallet_intent(callback.from_user.id, item, price)
        label = item_label(item, str((catalog_item or {}).get("title") or ""))
        description = str((catalog_item or {}).get("description") or "").strip()
        header = shop_header_lines(await db.shop_header())
        extra = f"\n{html.escape(description)}\n" if description else ""
        await callback.answer()
        await edit_block(
            callback.message,
            f"{header}🛒 <b>Подтверждение покупки</b>\n"
            f"{html.escape(label)}\n"
            f"{extra}"
            f"Цена: <b>{price} 🍪</b>\n"
            f"Баланс: <b>{int(user['cookies'])} 🍪</b>\n\n"
            "Нажмите «Подтвердить», чтобы списать печеньки.",
            parse_mode="HTML",
            reply_markup=shop_confirm_keyboard(token, price),
        )
        return
    if item == "video_avatar":
        if not await db.feature_enabled("profile_video"):
            await callback.answer("Видео-профили временно выключены.", show_alert=True)
            return
        if int(user["cookies"]) < price:
            await callback.answer("Недостаточно печенек.", show_alert=True)
            return
        await state.set_state(ProfileEdit.video_avatar)
        await state.set_data({"shop_price": price, "purchase_intent": token})
        await callback.answer()
        await callback.message.answer(
            "Отправьте короткое видео для карточки профиля. После сохранения спишется стоимость товара.",
            reply_markup=flow_reply_keyboard() if callback.message.chat.type == "private" else None,
        )
        return
    if item == "tamagotchi":
        if not await db.feature_enabled("tamagotchi"):
            await callback.answer("Питомцы временно выключены.", show_alert=True)
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
            reply_markup=pet_species_keyboard(token),
        )
        return
    pet_items = PET_SUPPLIES
    if item in pet_items:
        kind, gain, label = pet_items[item]
        ok, error, _ = await db.purchase_pet_supply(
            callback.from_user.id, kind, gain, price, item, intent_id=token,
        )
        if not ok:
            await callback.answer(error, show_alert=True)
            return
        await callback.answer("Питомец доволен!")
        from community_bot.notify import vitrine_consumed

        await vitrine_consumed(bot, db, item)
        from community_bot.life import unlock

        await unlock(db, callback.from_user.id, "shop_first")
        fresh = await db.get_user(callback.from_user.id) or user
        await edit_block(
            callback.message,
            await _shop_home_text(db, fresh, settings),
            parse_mode="HTML",
            reply_markup=await _shop_home_markup(db),
        )
        return
    if item in IMMUNITY_HOURS:
        ok, error = await db.buy_item(callback.from_user.id, item, price, intent_id=token)
        if not ok:
            await callback.answer(error, show_alert=True)
            return
        hours = IMMUNITY_HOURS[item]
        from community_bot.notify import vitrine_consumed

        await vitrine_consumed(bot, db, item)
        from community_bot.life import unlock

        await unlock(db, callback.from_user.id, "shop_first")
        await callback.answer(f"Иммунитет продлён на {hours} ч.")
        fresh = await db.get_user(callback.from_user.id) or user
        await edit_block(
            callback.message,
            await _shop_home_text(db, fresh, settings),
            parse_mode="HTML",
            reply_markup=await _shop_home_markup(db),
        )
        return
    if item == "private_profile" and user.get("profile_private"):
        await callback.answer("Профиль уже скрыт.", show_alert=True)
        return
    if item == "ornate_profile" and user.get("profile_ornate"):
        await callback.answer("Кастомный профиль уже куплен.", show_alert=True)
        return
    ok, error = await db.buy_item(callback.from_user.id, item, price, intent_id=token)
    if not ok:
        await callback.answer(error, show_alert=True)
        return
    if item in {"forgive", "restore_rep"} and settings.community_chat_id:
        fresh_rep = await db.get_user(callback.from_user.id)
        value = int(fresh_rep["reputation"]) if fresh_rep else 0
        if item == "forgive" and value >= settings.restricted_reputation_threshold:
            try:
                await bot.restrict_chat_member(
                    settings.community_chat_id, callback.from_user.id, permissions=_full_permissions()
                )
            except TelegramBadRequest:
                pass
        else:
            await sync_reputation_chat_access(
                db, settings, bot, settings.community_chat_id, callback.from_user.id, value,
                allow_legacy_recovery=item == "restore_rep",
            )
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
        "restore_rep": "Репутация поднята в пределах доступного максимума.",
        "rep_shield": "Щит поглощает один −реп и действует до первого удара без срока.",
        "event_pass": "Заявка на проходку передана владельцу.",
        "reset_limits": "Сегодняшние лимиты лайков, репутации и скачиваний видео или музыки сброшены.",
        "forgive": "Предупреждения очищены, мут снят.",
        "support": "Спасибо за поддержку проекта!",
        "private_profile": "Профиль скрыт от чужих. Открыть снова можно кнопкой на своей карточке.",
        "ornate_profile": "Кастомное оформление профиля включено.",
        "season_pack": "Сезонный набор: одноразовый щит без срока и обед питомцу.",
    }
    from community_bot.notify import vitrine_consumed

    await vitrine_consumed(bot, db, item)
    from community_bot.life import unlock

    await unlock(db, callback.from_user.id, "shop_first")
    await callback.answer(labels.get(item, "Покупка выполнена."))
    fresh = await db.get_user(callback.from_user.id) or user
    await edit_block(
        callback.message,
        await _shop_home_text(db, fresh, settings),
        parse_mode="HTML",
        reply_markup=await _shop_home_markup(db),
    )


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
    item = str(data.get("flex_item") or "")
    if item not in {"event_pass", "support"}:
        await message.answer("Откройте оплату заново — списания не было.")
        return
    discount = int(data["flex_discount"])
    price = discounted_price(base_amount, discount)
    token = await db.create_wallet_intent(
        message.from_user.id, item, price, payload={"base_amount": base_amount, "discount": discount},
    )
    label = "Оплата мероприятия" if item == "event_pass" else "Поддержка развития"
    await state.clear()
    await message.answer(
        f"<b>{label}</b>\nВыбрано: {base_amount} 🍪 · скидка {discount}%\n"
        f"Спишется: <b>{price} 🍪</b>. Подтвердите оплату кнопкой.",
        parse_mode="HTML", reply_markup=shop_confirm_keyboard(token, price),
    )


@router.message(ProfileEdit.video_avatar)
async def save_video_avatar(message: Message, state: FSMContext, db: Database) -> None:
    if not message.from_user or not message.video:
        await message.answer("Нужно отправить видеофайл как видео, не как документ.")
        return
    data = await state.get_data()
    if not data.get("purchase_intent"):
        await message.answer("Покупка устарела. Откройте товар заново.")
        return
    price = int(data["shop_price"])
    ok, error = await db.buy_item(
        message.from_user.id, "video_avatar", price,
        intent_id=str(data["purchase_intent"]), profile_value=message.video.file_id,
    )
    if not ok:
        await state.clear()
        await message.answer(error)
        return
    await state.clear()
    await message.answer(f"✅ Видео-профиль установлен. Списано {price} 🍪.")


@router.message(command_or_alias("givecookies"), F.chat.type.in_({"group", "supergroup"}))
async def admin_give_cookies(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    actor_role = await _require_perm(message, db, settings, PERM_USERS_COOKIES)
    if not actor_role or not message.from_user:
        return
    target, args, _ = await resolve_command_target(message, db)
    if not target or not args or not args[0].isdigit():
        await _respond(message, "Ответьте человеку или напишите «Нора выдать печеньки @имя 100 причина».")
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
    audit_id = await db.log_admin_action(
        message.from_user.id,
        "give_cookies",
        str(target["user_id"]),
        f"+{amount} 🍪",
        actor_name=message.from_user.full_name,
        target_name=person_label(target),
        reason=reason,
    )
    await _respond(message, f"Начислено {amount} 🍪 пользователю {_target_display(target)}.", parse_mode="HTML")
    from community_bot.widget_notifications import Sender, send_service_notification

    await send_service_notification(
        bot, db, int(target["user_id"]), Sender(), "Начисление печенек",
        f"Вам начислено {amount} 🍪.", "history", event_key=f"admin:{audit_id}", context=reason,
    )


@router.message(command_or_alias("setcookies"), F.chat.type.in_({"group", "supergroup"}))
async def admin_set_cookies(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    actor_role = await _require_perm(message, db, settings, PERM_USERS_COOKIES)
    if not actor_role or not message.from_user:
        return
    target, args, _ = await resolve_command_target(message, db)
    if not target or not args or not args[0].isdigit():
        await _respond(message, "Ответьте человеку или напишите «Нора сетпеченьки @имя 100 причина».")
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
    audit_id = await db.log_admin_action(
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
    if difference:
        from community_bot.widget_notifications import Sender, send_service_notification

        await send_service_notification(
            bot, db, int(target["user_id"]), Sender(), "Изменение баланса",
            f"Баланс установлен: {amount} 🍪 ({sign}{difference}).", "history",
            event_key=f"admin:{audit_id}", context=reason,
        )


@router.message(command_or_alias("freebie"), F.chat.type.in_({"group", "supergroup"}))
async def freebie_offer(message: Message, settings: Settings) -> None:
    if not settings.freebie_channel_id or not settings.freebie_channel_url:
        await _respond(message, "Бонус за подписку ещё не настроен владельцем.")
        return
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
    channel_id = settings.freebie_channel_id
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
async def transfer_command(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    target, args, _ = await resolve_command_target(message, db, after_first=True)
    if not target or not args or not args[0].isdigit():
        await _respond(message, "Ответьте «Нора перевести 100» или напишите «Нора перевести @имя 100».")
        return
    await _prepare_transfer(message, db, settings, target, int(args[0]))


async def _prepare_transfer(
    message: Message,
    db: Database,
    settings: Settings,
    target: dict[str, object],
    amount: int,
) -> None:
    assert message.from_user
    sender = await register_telegram_user(db, message.from_user)
    if int(target["user_id"]) == message.from_user.id:
        await _respond(message, "Нельзя перевести печеньки самому себе.")
        return
    if amount <= 0 or amount > int(sender["cookies"]):
        await _respond(message, f"Недостаточно печенек. Ваш баланс: {sender['cookies']} 🍪.")
        return
    percent = transfer_commission_percent(
        int(sender["reputation"]),
        settings.restricted_reputation_threshold,
    )
    received = amount * (100 - percent) // 100
    if received <= 0:
        await _respond(message, "После комиссии получателю ничего не останется. Увеличьте сумму.")
        return
    transfer_id = await db.create_transfer(message.from_user.id, int(target["user_id"]), amount)
    with keep_in_chat():
        from community_bot.message_widgets import transfer_card

        if await transfer_card(message, target, amount, percent, received, transfer_keyboard(transfer_id)):
            return
        await _respond(
            message,
            f"<b>Перевод · {amount} 🍪</b>\nПолучатель: {_target_display(target)}\n"
            f"Комиссия {percent}% (по уровню репутации), пользователь получит {received} 🍪.",
            parse_mode="HTML",
            reply_markup=transfer_keyboard(transfer_id),
        )


@router.callback_query(F.data.startswith("transfer:"))
async def confirm_transfer(callback: CallbackQuery, db: Database, settings: Settings, bot: Bot) -> None:
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
    ok, error, received = await db.complete_transfer(
        transfer_id,
        callback.from_user.id,
        settings.restricted_reputation_threshold,
    )
    if not ok:
        await callback.answer(error, show_alert=True)
        return
    await callback.answer("Перевод выполнен.")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"✅ Перевод выполнен. Получателю зачислено {received} 🍪.")
    if transfer:
        from community_bot.widget_notifications import Sender, send_service_notification

        await send_service_notification(
            bot, db, int(transfer["receiver_id"]), Sender(), "Перевод печенек",
            f"Вам перевели {received} 🍪 после комиссии.", "history", event_key=f"transfer:{transfer_id}",
        )


@router.message(
    F.text, F.reply_to_message | F.text.contains("@") | F.entities | F.text.func(is_like_phrase),
    F.chat.type.in_({"group", "supergroup"}),
)
async def group_reply_actions(message: Message, db: Database, settings: Settings, bot: Bot) -> None:
    addressed = strip_command_address(message.text or "")
    amount = transfer_amount(addressed) if addressed is not None and message.reply_to_message else None
    like = like_interaction(message)
    interaction = like or targeted_phrase(message, POSITIVE_REPUTATION_PHRASES | NEGATIVE_REPUTATION_PHRASES)
    if not interaction and message.reply_to_message and reputation_delta(message.text or "") is not None:
        interaction = (message.text or "", None)
    if amount is None and interaction is None:
        if is_like_phrase(message.text or ""):
            await message.answer("Напиши «Лайк» ответом на сообщение участника или отправь «Нора, лайк @имя».")
            return
        raise SkipHandler
    if not message.from_user or message.from_user.is_bot or message.sender_chat:
        return
    if amount is not None:
        target = await resolve_reply_target(message, db)
        if target:
            await _prepare_transfer(message, db, settings, target, amount)
        return
    assert interaction is not None
    phrase, mention = interaction
    target = (
        await resolve_member_mention(db, mention) if mention is not None else await resolve_reply_target(message, db)
    )
    if not target:
        if mention is not None:
            await message.reply("Не нашла участника по @имени. Попробуйте ответить на его сообщение.")
        return
    if like:
        if settings.community_chat_id and message.chat.id != settings.community_chat_id:
            return
        error = await _give_like(db, bot, message.from_user, target)
        if error == social_likes.ALREADY_PROFILE_LIKED:
            await _send_like_limit_notice(
                bot, message.from_user, target, message.chat.id, message.message_id,
                message.message_thread_id if message.is_topic_message else None,
            )
        elif error:
            await message.reply(error)
        else:
            await _announce_like(message, message.from_user, target)
        return
    delta = reputation_delta(phrase)
    assert delta is not None
    await _apply_chat_reputation(db, bot, settings, message.chat.id, message.from_user, target, delta, message.reply,
                                 phrase=phrase)


async def _apply_chat_reputation(db, bot, settings, chat_id, user, target, delta, send, *, phrase=None) -> bool:
    if await is_bot(db, target, getattr(bot, "id", None)):
        if phrase:
            await send("Репутация ботов не меняется.")
        return False
    actor = await register_telegram_user(db, user)
    timezone = ZoneInfo(settings.timezone)
    local_date = datetime.now(timezone).date()
    from community_bot.reputation import change_community_reputation

    ok, text, new_value, pet_line = await change_community_reputation(
        db, settings, actor, target, delta, local_date
    )
    if not ok or new_value is None:
        if phrase:
            await send(text)
        return False
    if delta > 0:
        from community_bot.life import unlock

        await unlock(db, user.id, "first_plus")
    response = _reputation_ping(settings, target, new_value, text, pet_line)
    if phrase and (lines := _SOCIAL_LINES.get(phrase.split()[0])):
        response = choice(lines).format(
            actor=user_link(user.id, user.full_name), target=_target_display(target),
        ) + "\n" + response
    await send(response, parse_mode="HTML")
    if pet_line and "перехватил" in pet_line:
        from community_bot.notify import emit

        await emit(bot, db, int(target["user_id"]), "pet", pet_line)
    if chat_id == getattr(settings, "community_chat_id", None):
        access = await sync_reputation_chat_access(
            db, settings, bot, chat_id, int(target["user_id"]), new_value,
            allow_legacy_recovery=delta > 0,
        )
        if new_value < settings.restricted_reputation_threshold:
            await send("🔞 Репутация ниже 50: отправка сообщений в чат ограничена.")
        elif access == "restored":
            await send("✅ Репутация снова от 50: доступ к чату восстановлен.")
    return True


@router.message_reaction(F.chat.type.in_({"group", "supergroup"}))
async def group_reaction(
    event: MessageReactionUpdated, event_update: Update, db: Database, settings: Settings, bot: Bot,
    reaction_authors: ReactionAuthors,
) -> None:
    user, chat_id = event.user, event.chat.id
    if not user or user.is_bot or chat_id != settings.community_chat_id or not event.new_reaction:
        return
    if not reaction_authors.claim_update(event_update.update_id):
        return
    added = await reaction_authors.added(event, bot)
    if not added:
        return
    target, thread = await reaction_authors.target(db, chat_id, event.message_id)
    if not target or target["user_id"] == user.id or await needs_reapplication(db, user.id):
        return
    async def send(text, **kwargs):
        return await bot.send_message(
            chat_id, text, message_thread_id=thread,
            reply_parameters=ReplyParameters(message_id=event.message_id, allow_sending_without_reply=True), **kwargs,
        )

    reaction_message = (chat_id, event.message_id)
    if "like" in added:
        error = await _give_like(db, bot, user, target, reaction_message=reaction_message)
        if error is None:
            await send(_like_notice(user, target), parse_mode="HTML")
        elif error == social_likes.ALREADY_PROFILE_LIKED:
            await _send_like_limit_notice(bot, user, target, chat_id, event.message_id, thread)
    votes = added & {"plus", "minus"}
    if len(votes) == 1:
        vote = votes.pop()
        if await _apply_chat_reputation(
            db, bot, settings, chat_id, user, target,
            REPUTATION_UP_DELTA if vote == "plus" else REPUTATION_DOWN_DELTA, send,
        ):
            from community_bot.pet_progress import record_telegram_event

            await record_telegram_event(db, user.id, vote, (chat_id, f"reaction:{event_update.update_id}", event.date))
