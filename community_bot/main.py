from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from community_bot.community_scope import CommunityScopeMiddleware, FreshMessageMiddleware
from community_bot.config import Settings, load_settings
from community_bot.covers import cover_path_for
from community_bot.database import Database
from community_bot.ephemeral import GroupCallbackEphemeralMiddleware, GroupHousekeepingMiddleware, patch_bot_ephemeral
from community_bot.helpers import send_stored_message
from community_bot.navigation import CabinetNavigationMiddleware
from community_bot.openrouter_chat import OpenRouterChat
from community_bot.release_backup import verify_requested_release_backup, verify_widget_notification_backup
from community_bot.restart import relaunch
from community_bot.routers import (
    command_admin_router,
    contest_router,
    cookie_games_router,
    flows_router,
    games_router,
    group_router,
    life_router,
    nora_router,
    notices_router,
    pets_router,
    private_router,
    profile_router,
    shop_admin_router,
    social_games_router,
    wallet_router,
)
from community_bot.routers.nora import assistant_router
from community_bot.telegraph import (
    publish_staff_guide,
    repair_member_images,
)
from community_bot.ui_owner import UiOwnerMiddleware
from community_bot.updates import announcement_key, community_announcement, latest_update

logger = logging.getLogger(__name__)


async def configure_commands(bot: Bot, community_chat_id: int) -> None:
    private_commands = [BotCommand(command="start", description="Открыть НОРУ")]
    group_commands = [BotCommand(command="commands", description="Нора команды")]
    for language_code in (None, "ru"):
        await bot.delete_my_commands(scope=BotCommandScopeAllGroupChats(), language_code=language_code)
        await bot.set_my_commands(
            private_commands, scope=BotCommandScopeAllPrivateChats(), language_code=language_code,
        )
        if community_chat_id:
            await bot.set_my_commands(
                group_commands, scope=BotCommandScopeChat(chat_id=community_chat_id),
                language_code=language_code,
            )


async def retry_transient_telegram_setup(label: str, operation) -> object:
    """A temporary Bot API failure must never terminate the entire NORA process."""
    delay = 3
    while True:
        try:
            return await operation()
        except (TelegramNetworkError, TelegramServerError, TelegramRetryAfter) as error:
            logger.warning(
                "Telegram %s temporarily unavailable (%s); retrying in %s seconds",
                label, type(error).__name__, delay,
            )
            await asyncio.sleep(delay)
            delay = min(60, delay * 2)


def _same_release(last: str | None, number: int) -> bool:
    if not last:
        return False
    return str(last).split(":", 1)[0] == str(number)


async def _pin_announcement(bot: Bot, db: Database, settings: Settings, message_id: int) -> None:
    chat_id = settings.community_chat_id
    try:
        await bot.pin_chat_message(chat_id, message_id, disable_notification=True)
        old_pin = await db.get_bot_state("last_announcement_message_id")
        if old_pin and int(old_pin) != message_id:
            with contextlib.suppress(Exception):
                await bot.unpin_chat_message(chat_id, int(old_pin))
    except Exception:
        logger.warning("Не удалось закрепить анонс — сообщение осталось в чате как пост.")


async def announce_latest_update(bot: Bot, db: Database, settings: Settings) -> None:
    from community_bot.stickers import STICKER_PACK_URL, send_context_sticker

    item = latest_update()
    last = await db.get_bot_state("last_announced_update")
    if last == announcement_key(item):
        source = await db.get_bot_state("last_announcement_message_id")
        if source and settings.community_chat_id:
            await send_context_sticker(bot, db, settings.community_chat_id, "update", int(source))
        return
    if not settings.community_chat_id:
        return
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Что изменилось", callback_data="updates:dm")]]
    )
    if item.sticker_pack_url:
        markup.inline_keyboard.append([InlineKeyboardButton(text="😎 Забрать стикеры", url=STICKER_PACK_URL)])
    caption = community_announcement(item)
    cover = cover_path_for(item)
    try:
        if cover:
            sent = await bot.send_photo(
                settings.community_chat_id,
                FSInputFile(cover),
                caption=caption,
                parse_mode="HTML",
                reply_markup=markup,
            )
        else:
            sent = await bot.send_message(
                settings.community_chat_id,
                caption,
                parse_mode="HTML",
                reply_markup=markup,
            )
    except Exception:
        logger.exception("Не удалось объявить обновление в чате сообщества")
        return
    await send_context_sticker(bot, db, settings.community_chat_id, "update", sent.message_id)
    await _pin_announcement(bot, db, settings, sent.message_id)
    await db.set_bot_state("last_announcement_message_id", str(sent.message_id))
    await db.set_bot_state("last_announced_update", announcement_key(item))
    if _same_release(last, item.number):
        return
    await notify_staff_update(bot, db, item)


async def notify_staff_update(bot: Bot, db: Database, item, staff_url: str | None = None) -> None:
    from community_bot.updates import staff_announcement

    text = staff_announcement(item)
    if not text:
        return
    if staff_url:
        text = f"{text}\n\n<a href=\"{staff_url}\">Служебная страница</a>"
    for user_id in await db.list_panel_user_ids():
        with contextlib.suppress(Exception):
            await bot.send_message(user_id, text, parse_mode="HTML")
        await asyncio.sleep(0.05)


async def log_community_permissions(bot: Bot, settings: Settings) -> None:
    if not settings.community_chat_id:
        logger.warning("COMMUNITY_CHAT_ID не задан — бот не сможет стирать команды в чате")
        return
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(settings.community_chat_id, me.id)
        can_delete = bool(getattr(member, "can_delete_messages", False) or member.status == "creator")
        logger.info(
            "Права бота в чате сообщества: status=%s can_delete_messages=%s",
            member.status,
            can_delete,
        )
        if member.status not in {"administrator", "creator"} or not can_delete:
            logger.warning("Чтобы стирать команды, бот должен быть администратором с правом удалять сообщения.")
    except Exception:
        logger.exception("Не удалось проверить права бота в чате сообщества")


async def send_memory_notice_once(bot: Bot, db: Database, settings: Settings) -> None:
    from community_bot.chat_memory import MEMORY_NOTICE, MEMORY_NOTICE_KEY

    if not settings.community_chat_id:
        return
    if await db.get_bot_state(MEMORY_NOTICE_KEY) == "1":
        return
    try:
        await bot.send_message(settings.community_chat_id, MEMORY_NOTICE)
    except Exception:
        logger.warning("Не удалось отправить уведомление о памяти сообщества")
        return
    await db.set_bot_state(MEMORY_NOTICE_KEY, "1")


async def daily_reputation_job(db: Database, settings: Settings, bot: Bot) -> None:
    timezone = ZoneInfo(settings.timezone)
    while True:
        now = datetime.now(timezone)
        tomorrow = now.date() + timedelta(days=1)
        next_run = datetime.combine(tomorrow, datetime.min.time(), timezone)
        await asyncio.sleep(max(1, (next_run - now).total_seconds()))
        restored = await db.restore_daily_reputation(datetime.now(timezone).date())
        if not settings.community_chat_id:
            continue
        from community_bot.reputation_chat_access import sync_reputation_chat_access

        for user in restored:
            if int(user["reputation"]) >= settings.restricted_reputation_threshold:
                await sync_reputation_chat_access(
                    db, settings, bot, settings.community_chat_id,
                    int(user["user_id"]), int(user["reputation"]),
                    allow_legacy_recovery=True,
                )


async def scheduled_messages_job(db: Database, settings: Settings, bot: Bot) -> None:
    while True:
        try:
            due = await db.due_scheduled_messages(datetime.now(tz=ZoneInfo("UTC")))
            for schedule in due:
                schedule_id = int(schedule["id"])
                interval = int(schedule["interval_minutes"])
                await db.mark_scheduled_sent(schedule_id, interval)
                if schedule["target"] == "community":
                    if settings.community_chat_id:
                        await send_stored_message(
                            bot,
                            settings.community_chat_id,
                            schedule["text"],
                            schedule["media_type"],
                            schedule["media_file_id"],
                        )
                    continue
                for user in await db.list_all_users():
                    await send_stored_message(
                        bot,
                        int(user["user_id"]),
                        schedule["text"],
                        schedule["media_type"],
                        schedule["media_file_id"],
                    )
                    await asyncio.sleep(0.05)
        except Exception:
            logger.exception("Ошибка фоновой отправки автосообщений")
        await asyncio.sleep(30)


async def emergency_stop_job(dispatcher: Dispatcher, emergency_stop: asyncio.Event) -> None:
    await emergency_stop.wait()
    await dispatcher.stop_polling()


async def restart_stop_job(dispatcher: Dispatcher, restart_stop: asyncio.Event) -> None:
    await restart_stop.wait()
    await dispatcher.stop_polling()


async def pet_notifications_job(db: Database, bot: Bot, settings: Settings) -> None:
    from community_bot.expedition import ExpeditionLoot, announce_expedition_result, parse_loot

    while True:
        try:
            for stored in await db.list_due_expeditions():
                await db.settle_pet(int(stored["user_id"]))
            pending = await db.list_pending_expedition_notices()
            for pet in pending:
                loot = ExpeditionLoot.from_mapping(pet.get("expedition_loot")) or parse_loot(
                    str(pet.get("expedition_loot") or "")
                )
                if loot is None:
                    await db.claim_expedition_notice(int(pet["user_id"]))
                    continue
                await announce_expedition_result(bot, db, settings, int(pet["user_id"]), pet, loot)
                await asyncio.sleep(0.05)
        except Exception:
            logger.exception("Ошибка уведомлений тамагочи")
        await asyncio.sleep(60)


async def weekly_board_job(db: Database, settings: Settings, bot: Bot) -> None:
    timezone = ZoneInfo(settings.timezone)
    while True:
        now = datetime.now(timezone)
        days_ahead = (6 - now.weekday()) % 7
        target = datetime.combine(now.date() + timedelta(days=days_ahead), datetime.min.time(), timezone)
        target = target.replace(hour=20)
        if target <= now:
            target += timedelta(days=7)
        await asyncio.sleep(max(1, (target - now).total_seconds()))
        if not settings.community_chat_id:
            continue
        week_id = datetime.now(UTC).strftime("%G-W%V")
        last = await db.get_bot_state("last_weekly_board")
        if last == week_id:
            continue
        from community_bot.routers.life import _format_board

        board = await db.weekly_board(week_id)
        with contextlib.suppress(Exception):
            await bot.send_message(settings.community_chat_id, _format_board(week_id, board), parse_mode="HTML")
        plus = (board.get("plus") or [])
        if plus:
            top_id = int(plus[0]["user_id"])
            await db.set_weekly_star(top_id)
            from community_bot.life import unlock

            await unlock(db, top_id, "board")
        for row in (board.get("messages") or [])[:3] + (board.get("plus") or [])[:3]:
            from community_bot.life import unlock

            await unlock(db, int(row["user_id"]), "board")
        await db.set_bot_state("last_weekly_board", week_id)


async def notify_digest_job(db: Database, bot: Bot, settings: Settings) -> None:
    timezone = ZoneInfo(settings.timezone)
    while True:
        now = datetime.now(timezone)
        target = now.replace(hour=20, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep(max(1, (target - now).total_seconds()))
        day = datetime.now(timezone).date().isoformat()
        last = await db.get_bot_state("notify_digest_day")
        if last == day:
            continue
        from community_bot.notify import deliver_digests

        try:
            await deliver_digests(bot, db)
            await db.set_bot_state("notify_digest_day", day)
        except Exception:
            logger.exception("Ошибка дайджеста уведомлений")


async def daily_chat_job(db: Database, settings: Settings, bot: Bot) -> None:
    from community_bot.daily_chat import due_daily_chat, publish_daily_chat, seconds_until_midnight

    timezone = ZoneInfo(settings.timezone)
    while True:
        now = datetime.now(timezone)
        posted = await db.get_bot_state("daily_chat_marker")
        day = due_daily_chat(now, posted)
        if day is not None:
            try:
                await publish_daily_chat(bot, db, settings, day)
            except Exception:
                logger.exception("Ошибка сводки суток")
            if await db.get_bot_state(f"daily_chat:{day.isoformat()}"):
                await db.set_bot_state("daily_chat_marker", day.isoformat())
            await asyncio.sleep(600)
            continue
        await asyncio.sleep(seconds_until_midnight(now))


async def morning_digest_job(db: Database, settings: Settings, bot: Bot) -> None:
    from community_bot.maintenance import apply_requested_morning_rebuild
    from community_bot.morning import due_morning, publish_missed_today, publish_morning_digest, seconds_until_morning
    from community_bot.morning_tvrain_trial import apply_tvrain_trial

    timezone = ZoneInfo(settings.timezone)
    for _ in range(3):
        try:
            await publish_missed_today(bot, db, settings)
            break
        except Exception:
            logger.exception("Не удалось отправить сводку за сегодня")
            await asyncio.sleep(20)
    await apply_tvrain_trial(bot, settings)
    while True:
        now = datetime.now(timezone)
        try:
            if not await apply_requested_morning_rebuild(bot, db, settings):
                await asyncio.sleep(30)
                continue
            await publish_morning_digest(bot, db, settings)
        except Exception:
            logger.exception("Ошибка утреннего поста")
        now = datetime.now(timezone)
        posted = await db.get_bot_state("morning_digest_day")
        if due_morning(now, posted):
            await asyncio.sleep(600)
            continue
        await asyncio.sleep(seconds_until_morning(now))


async def cookie_loan_job(db: Database, bot: Bot) -> None:
    from community_bot.widget_notifications import Sender, send_service_notification

    while True:
        try:
            collected = await db.collect_due_loans()
            for loan in collected:
                user_id = int(loan["user_id"])
                due_amount = int(loan["due_amount"])
                debt = int(loan.get("debt_added") or 0)
                extra = f" Недостающие {debt} 🍪 ушли в долг кошелька." if debt else ""
                with contextlib.suppress(Exception):
                    await send_service_notification(
                        bot, db, user_id, Sender(), "Кошелёк",
                        f"💳 Срок стартер-пака истёк: списано {due_amount} 🍪.{extra}",
                        "history", event_key=f"loan-repaid:{loan['id']}",
                    )
                await asyncio.sleep(0.05)
        except Exception:
            logger.exception("Ошибка сбора кредитов кошелька")
        await asyncio.sleep(60)


async def memory_cleanup_job(db: Database) -> None:
    while True:
        try:
            await db.cleanup_community_messages()
        except Exception:
            logger.exception("Ошибка очистки памяти сообщества")
        await asyncio.sleep(3600)


def create_dispatcher() -> Dispatcher:
    from community_bot.access import PrivateAccessMiddleware, ProfileAccessMiddleware
    from community_bot.city_gate import CityGateMiddleware
    from community_bot.group_message_close import GroupCloseCallbackMiddleware, GroupMessageActorsMiddleware
    from community_bot.private_rich import PrivateRichContextMiddleware
    from community_bot.reply_rich import ReplyRichContextMiddleware

    dispatcher = Dispatcher()
    from community_bot.message_widgets import WidgetUpdateMiddleware

    dispatcher.update.outer_middleware(FreshMessageMiddleware())
    dispatcher.update.outer_middleware(CommunityScopeMiddleware())
    dispatcher.update.outer_middleware(GroupMessageActorsMiddleware())
    dispatcher.update.outer_middleware(WidgetUpdateMiddleware())
    from community_bot.staff_chat import StaffChatCaptureMiddleware
    dispatcher.update.outer_middleware(StaffChatCaptureMiddleware())
    from community_bot.memory_capture import CommunityMemoryMiddleware
    from community_bot.reaction_authors import ReactionAuthors

    reaction_authors = ReactionAuthors()
    dispatcher["reaction_authors"] = reaction_authors
    dispatcher.message.outer_middleware(reaction_authors)
    memory_middleware = CommunityMemoryMiddleware()
    dispatcher.edited_message.outer_middleware(memory_middleware)
    reply_context = ReplyRichContextMiddleware()
    dispatcher.message.outer_middleware(reply_context)
    dispatcher.callback_query.outer_middleware(reply_context)
    dispatcher.message.outer_middleware(PrivateRichContextMiddleware())
    dispatcher.callback_query.outer_middleware(PrivateRichContextMiddleware())
    dispatcher.message.outer_middleware(PrivateAccessMiddleware())
    dispatcher.callback_query.outer_middleware(PrivateAccessMiddleware())
    dispatcher.message.outer_middleware(CityGateMiddleware())
    dispatcher.callback_query.outer_middleware(CityGateMiddleware())
    from community_bot.nora_game_chat import GameChatMiddleware
    from community_bot.routers.group import CommunityModerationMiddleware, moderation_router

    dispatcher.message.outer_middleware(CommunityModerationMiddleware())
    dispatcher.message.outer_middleware(memory_middleware)
    game_chat_middleware = GameChatMiddleware()
    dispatcher.message.outer_middleware(game_chat_middleware)
    dispatcher.chat_member.outer_middleware(game_chat_middleware)
    dispatcher.message.outer_middleware(GroupHousekeepingMiddleware())
    dispatcher.message.outer_middleware(ProfileAccessMiddleware())
    dispatcher.callback_query.outer_middleware(GroupCloseCallbackMiddleware())
    dispatcher.callback_query.outer_middleware(ProfileAccessMiddleware())
    dispatcher.callback_query.outer_middleware(UiOwnerMiddleware())
    dispatcher.callback_query.outer_middleware(CabinetNavigationMiddleware())
    dispatcher.callback_query.outer_middleware(GroupCallbackEphemeralMiddleware())
    from community_bot.birthday import router as birthday_router
    from community_bot.commands_guide import router as commands_router
    from community_bot.event_access import router as event_router
    from community_bot.game_invitations import router as game_invitations_router
    from community_bot.mafia_notifications import router as mafia_notifications_router
    from community_bot.routers.member_stats import router as member_stats_router
    from community_bot.routers.song_requests import router as song_requests_router
    from community_bot.sea_notifications import router as sea_notifications_router

    dispatcher.include_router(game_invitations_router)
    dispatcher.include_router(mafia_notifications_router)
    dispatcher.include_router(sea_notifications_router)
    dispatcher.include_router(birthday_router)
    dispatcher.include_router(event_router)
    dispatcher.include_router(moderation_router)
    dispatcher.include_router(song_requests_router)
    dispatcher.include_router(nora_router)
    dispatcher.include_router(command_admin_router)
    dispatcher.include_router(flows_router)
    dispatcher.include_router(profile_router)
    dispatcher.include_router(notices_router)
    dispatcher.include_router(wallet_router)
    dispatcher.include_router(cookie_games_router)
    dispatcher.include_router(social_games_router)
    dispatcher.include_router(games_router)
    dispatcher.include_router(pets_router)
    dispatcher.include_router(life_router)
    from community_bot.referral_campaign import router as referral_campaign_router

    dispatcher.include_router(referral_campaign_router)
    from community_bot.december_house_vote import router as house_vote_router

    dispatcher.include_router(house_vote_router)
    dispatcher.include_router(contest_router)
    dispatcher.include_router(shop_admin_router)
    dispatcher.include_router(commands_router)
    dispatcher.include_router(private_router)
    dispatcher.include_router(member_stats_router)
    dispatcher.include_router(group_router)
    dispatcher.include_router(assistant_router)
    return dispatcher


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings()
    db = Database(settings.database_path)
    from community_bot import profile_access_rollout
    from community_bot.community_reset import apply_reset, prepare_reset, reset_settings
    from community_bot.profile_likes_grant import apply_profile_likes_grant
    from community_bot.wallet_reset import apply_wallet_reset_release

    await profile_access_rollout.prepare(db)
    await prepare_reset(db)
    await verify_requested_release_backup(db)
    await verify_widget_notification_backup(db)
    from community_bot.release_backup import verify_durak_backup, verify_pet_development_backup

    await verify_pet_development_backup(db)
    await verify_durak_backup(db)
    from community_bot.release_backup import verify_city_profile_backup

    await verify_city_profile_backup(db)
    await db.initialize()
    await apply_reset(db, settings)
    await apply_wallet_reset_release(db)
    settings = await reset_settings(db, settings)
    if await db.get_bot_state("emergency_disabled") == "1":
        logger.critical("Бот заблокирован аварийным выключателем")
        await asyncio.Event().wait()
        return
    await apply_profile_likes_grant(db, settings)
    settings = await profile_access_rollout.apply(db, settings)
    await profile_access_rollout.queue_notices(db)
    for owner_id in settings.owner_ids:
        if not await db.get_user(owner_id):
            await db.ensure_user(owner_id, telegram_name="Владелец")
        await db.set_role(owner_id, "owner")
    for moderator_id in settings.moderator_ids:
        moderator = await db.ensure_user(moderator_id, telegram_name="Модератор")
        if moderator["role"] == "member":
            await db.set_role(moderator_id, "moderator")

    from community_bot.message_widgets import WidgetSession

    bot = Bot(settings.bot_token, session=WidgetSession())
    bot.community_db = db  # type: ignore[attr-defined]
    bot.community_settings = settings  # type: ignore[attr-defined]
    from community_bot.profile_maintenance import run_requested_reset

    await run_requested_reset(db, settings, bot)
    from community_bot.dot_api import grant_owner_dot_cookies

    try:
        if await grant_owner_dot_cookies(db, settings.owner_id, settings.owner_id):
            logger.info("DOT: one-time owner grant of 4000 cookies applied")
    except Exception:
        logger.exception("DOT owner grant failed; shop request can retry")
    from community_bot.access import OnboardingKeyboardMiddleware, configure_private_menus
    from community_bot.group_message_close import GroupCloseSendMiddleware, normalize_current_pin
    from community_bot.private_rich import PrivateRichMiddleware
    from community_bot.reply_rich import ReplyRichMiddleware

    bot.session.middleware.register(OnboardingKeyboardMiddleware())
    bot.session.middleware.register(PrivateRichMiddleware())
    patch_bot_ephemeral(bot)
    bot.session.middleware.register(ReplyRichMiddleware())
    bot.session.middleware.register(GroupCloseSendMiddleware())
    from community_bot.staff_chat import StaffChatOutgoingMiddleware
    bot.session.middleware.register(StaffChatOutgoingMiddleware())
    dispatcher = create_dispatcher()
    if settings.openrouter_api_key or settings.deepseek_api_key:
        dispatcher["openrouter_chat"] = OpenRouterChat(db, settings)

    from community_bot.birthday import birthday_job
    from community_bot.command_registry import load_registry

    await load_registry(db)
    command_setup_task = asyncio.create_task(
        retry_transient_telegram_setup(
            "command registration", lambda: configure_commands(bot, settings.community_chat_id),
        ),
        name="nora-telegram-command-registration",
    )
    await log_community_permissions(bot, settings)
    await normalize_current_pin(bot, settings)
    await send_memory_notice_once(bot, db, settings)
    from community_bot.stickers import sticker_delivery_job, verify_sticker_pack

    await verify_sticker_pack(bot)
    await repair_member_images(db)
    await announce_latest_update(bot, db, settings)
    if await db.get_bot_state("event_shop_fix_staff_notice_v1") != "1":
        for staff_id in await db.list_panel_user_ids():
            await safe_staff_event_notice(bot, staff_id)
        await db.set_bot_state("event_shop_fix_staff_notice_v1", "1")
    await publish_staff_guide(db)
    emergency_stop = asyncio.Event()
    restart_stop = asyncio.Event()
    web_runner = None
    if os.getenv("MINIAPP_ENABLED") == "1":
        from community_bot.miniapp import start_server

        web_runner = await start_server(db, settings, bot, {"restart_stop": restart_stop})
        dispatcher["nora_game_chat"] = web_runner.app["nora_game_chat"]
        dispatcher["nora_cinema"] = web_runner.app["nora_cinema"]
        logger.info("Nora Mini App HTTP server started")
    # Serve Mini App even while the Telegram API is returning 502 during startup.
    # Removing an old webhook is required before long polling, so retry that call.
    await retry_transient_telegram_setup(
        "webhook removal", lambda: bot.delete_webhook(drop_pending_updates=False),
    )
    profile_access_task = asyncio.create_task(configure_private_menus(bot, db, settings))
    from community_bot.menu_recovery import recover_private_menus

    menu_recovery_task = asyncio.create_task(recover_private_menus(bot, db, settings, dispatcher.fsm))
    reputation_task = asyncio.create_task(daily_reputation_job(db, settings, bot))
    scheduled_task = asyncio.create_task(scheduled_messages_job(db, settings, bot))
    pet_task = asyncio.create_task(pet_notifications_job(db, bot, settings))
    digest_task = asyncio.create_task(notify_digest_job(db, bot, settings))
    loan_task = asyncio.create_task(cookie_loan_job(db, bot))
    board_task = asyncio.create_task(weekly_board_job(db, settings, bot))
    morning_task = asyncio.create_task(morning_digest_job(db, settings, bot))
    daily_chat_task = asyncio.create_task(daily_chat_job(db, settings, bot))
    birthday_task = asyncio.create_task(birthday_job(bot, db, settings))
    memory_task = asyncio.create_task(memory_cleanup_job(db))
    from community_bot.december_cabin import run as publish_december_meetup
    from community_bot.december_house_vote import run as publish_house_vote
    from community_bot.pet_video import PetVideoQueue
    from community_bot.rsvp import event_counters_job
    from community_bot.telegram_like_tags import LikeTagMembershipMiddleware, like_tags_job
    from community_bot.widget_notifications import widget_notification_job

    widget_notification_task = asyncio.create_task(widget_notification_job(bot, db))
    like_tags_checked: dict[int, tuple[int, float]] = {}
    dispatcher.update.outer_middleware(LikeTagMembershipMiddleware(settings.community_chat_id, like_tags_checked))
    like_tags_task = asyncio.create_task(like_tags_job(db, bot, settings.community_chat_id, like_tags_checked))
    event_counters_task = asyncio.create_task(event_counters_job(bot, db))
    december_meetup_task = asyncio.create_task(publish_december_meetup(db, settings, bot))
    house_vote_task = asyncio.create_task(publish_house_vote(db, settings, bot))
    sticker_delivery_task = asyncio.create_task(sticker_delivery_job(bot, db))
    from community_bot.onboarding_invites import run_entry_release

    entry_release_task = asyncio.create_task(run_entry_release(bot, db, settings))
    from community_bot.referral_campaign import reward_scheduler

    referral_reward_task = asyncio.create_task(reward_scheduler(bot, db))
    emergency_task = asyncio.create_task(emergency_stop_job(dispatcher, emergency_stop))
    restart_task = asyncio.create_task(restart_stop_job(dispatcher, restart_stop))
    pet_video_queue = PetVideoQueue(db)
    pet_video_queue.start()
    dispatcher["pet_video_queue"] = pet_video_queue
    try:
        await retry_transient_telegram_setup(
            "polling",
            lambda: dispatcher.start_polling(
                bot,
                allowed_updates=sorted({
                    *dispatcher.resolve_used_update_types(),
                    "my_chat_member", "chat_member", "widget_query", "message", "edited_message",
                }),
                db=db,
                settings=settings,
                emergency_stop=emergency_stop,
                restart_stop=restart_stop,
                close_bot_session=False,
            ),
        )
    finally:
        await pet_video_queue.close()
        for task in (
            command_setup_task,
            profile_access_task,
            menu_recovery_task,
            reputation_task,
            scheduled_task,
            pet_task,
            digest_task,
            loan_task,
            board_task,
            morning_task,
            daily_chat_task,
            birthday_task,
            memory_task,
            widget_notification_task,
            like_tags_task,
            event_counters_task,
            december_meetup_task,
            house_vote_task,
            sticker_delivery_task,
            entry_release_task,
            referral_reward_task,
            emergency_task,
            restart_task,
        ):
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(
                command_setup_task,
                profile_access_task,
                menu_recovery_task,
                reputation_task,
                scheduled_task,
                pet_task,
                digest_task,
                loan_task,
                board_task,
                morning_task,
                daily_chat_task,
                birthday_task,
                memory_task,
                widget_notification_task,
                like_tags_task,
                event_counters_task,
                december_meetup_task,
                house_vote_task,
                sticker_delivery_task,
                entry_release_task,
            referral_reward_task,
                emergency_task,
                restart_task,
            )
        if web_runner:
            await web_runner.cleanup()
        await bot.session.close()
    if restart_stop.is_set() and await db.get_bot_state("emergency_disabled") != "1":
        logger.info("owner restart: relaunching in-place, sqlite and settings preserved")
        relaunch()


def run() -> None:
    asyncio.run(main())


async def safe_staff_event_notice(bot, user_id):
    with contextlib.suppress(Exception):
        await bot.send_message(
            user_id,
            "🛠 Исправлены мероприятия в магазине: цена берётся из анонса, без цены — бесплатная запись. "
            "Команда «участники» и журнал оплат доступны по отдельному праву "
            "«Мероприятия: участники и журнал оплат» в настройках ролей.",
        )


if __name__ == "__main__":
    run()
