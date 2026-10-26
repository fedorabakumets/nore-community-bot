from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from community_bot.config import Settings, load_settings
from community_bot.covers import cover_path_for
from community_bot.database import Database
from community_bot.ephemeral import GroupCallbackEphemeralMiddleware, GroupHousekeepingMiddleware, patch_bot_ephemeral
from community_bot.helpers import send_stored_message
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
from community_bot.telegraph import (
    publish_commands_guide,
    publish_member_update,
    publish_staff_guide,
    publish_staff_update,
)
from community_bot.ui_owner import UiOwnerMiddleware
from community_bot.updates import announcement_key, community_announcement, latest_update

logger = logging.getLogger(__name__)


async def configure_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="apply", description="Заполнить анкету"),
            BotCommand(command="question", description="Задать вопрос"),
            BotCommand(command="profile", description="Мой профиль"),
            BotCommand(command="balance", description="Кошелёк"),
            BotCommand(command="shop", description="Магазин"),
            BotCommand(command="pet", description="Мой тамагочи"),
            BotCommand(command="buycookies", description="Купить печеньки через СБП"),
            BotCommand(command="mail", description="Анонимное письмо в чат"),
            BotCommand(command="help", description="Помощь"),
            BotCommand(command="pogoda", description="Погода в Петербурге"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
        language_code="ru",
    )
    await bot.set_my_commands(
        [
            BotCommand(command="profile", description="Профиль (можно ответом)"),
            BotCommand(command="balance", description="Кошелёк"),
            BotCommand(command="commands", description="Команды бота"),
            BotCommand(command="reputation", description="Система репутации"),
            BotCommand(command="store", description="Магазин и оплата"),
            BotCommand(command="shop", description="Магазин"),
            BotCommand(command="pet", description="Открыть тамагочи"),
            BotCommand(command="games", description="Мини-игры: рулетка, блэкджек, кубик, рейс, капкан"),
            BotCommand(command="blackjack", description="Блэкджек: /blackjack 10"),
            BotCommand(command="dice", description="Кубик 1 на 1: /dice 10"),
            BotCommand(command="crash", description="Рейс на 🍪: /crash 10"),
            BotCommand(command="trap", description="Капкан на 🍪: /trap 10"),
            BotCommand(command="mafia", description="Мафия: роли в личку"),
            BotCommand(command="bunker", description="Бункер: досье в личку"),
            BotCommand(command="roulette", description="Рулетка на мут 30 мин"),
            BotCommand(command="gift", description="Подарить товар ответом"),
            BotCommand(command="report", description="Репорт ответом на сообщение"),
            BotCommand(command="board", description="Доска недели"),
            BotCommand(command="gamecancel", description="Отменить текущую игру"),
            BotCommand(command="pogoda", description="Погода в Петербурге"),
        ],
        scope=BotCommandScopeAllGroupChats(),
        language_code="ru",
    )


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
    item = latest_update()
    last = await db.get_bot_state("last_announced_update")
    if last == announcement_key(item):
        return
    if not settings.community_chat_id:
        return
    url = await publish_member_update(db, item)
    if url:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Что изменилось", url=url)]]
        )
    else:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Что изменилось", callback_data="updates:dm")]]
        )
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
    await _pin_announcement(bot, db, settings, sent.message_id)
    await db.set_bot_state("last_announcement_message_id", str(sent.message_id))
    await db.set_bot_state("last_announced_update", announcement_key(item))
    if _same_release(last, item.number):
        return
    staff_url = await publish_staff_update(db, item)
    await notify_staff_update(bot, db, item, staff_url)


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
        for user in restored:
            if int(user["reputation"]) >= settings.restricted_reputation_threshold:
                with contextlib.suppress(Exception):
                    from community_bot.routers.group import _full_permissions

                    await bot.restrict_chat_member(
                        settings.community_chat_id,
                        int(user["user_id"]),
                        permissions=_full_permissions(),
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


async def day_note_job(db: Database, settings: Settings, bot: Bot) -> None:
    from community_bot.day_note import day_note_text

    timezone = ZoneInfo(settings.timezone)
    while True:
        now = datetime.now(timezone)
        local = now.astimezone(timezone)
        stamp = local.date().isoformat()
        posted = await db.get_bot_state("day_note_day")
        morning_history = await db.get_bot_state("morning_history_day")
        in_window = 12 <= local.hour < 18
        if in_window and posted != stamp and morning_history != stamp and settings.community_chat_id:
            try:
                text = await day_note_text(local)
            except Exception:
                logger.exception("Ошибка поста «Этот день»")
                text = None
            if text:
                try:
                    await bot.send_message(settings.community_chat_id, text, parse_mode="HTML")
                    await db.set_bot_state("day_note_day", stamp)
                except Exception:
                    logger.exception("Не удалось отправить «Этот день»")
            await asyncio.sleep(600)
            continue
        nxt = local.replace(hour=12, minute=0, second=0, microsecond=0)
        if nxt <= local:
            nxt += timedelta(days=1)
        await asyncio.sleep(max(1, (nxt - local).total_seconds()))


async def morning_digest_job(db: Database, settings: Settings, bot: Bot) -> None:
    from community_bot.morning import due_morning, publish_missed_today, publish_morning_digest, seconds_until_morning

    timezone = ZoneInfo(settings.timezone)
    for _ in range(3):
        try:
            await publish_missed_today(bot, db, settings)
            break
        except Exception:
            logger.exception("Не удалось отправить сводку за сегодня")
            await asyncio.sleep(20)
    while True:
        now = datetime.now(timezone)
        try:
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
    while True:
        try:
            collected = await db.collect_due_loans()
            for loan in collected:
                user_id = int(loan["user_id"])
                due_amount = int(loan["due_amount"])
                debt = int(loan.get("debt_added") or 0)
                extra = f" Недостающие {debt} 🍪 ушли в долг кошелька." if debt else ""
                with contextlib.suppress(Exception):
                    await bot.send_message(
                        user_id,
                        f"💳 Срок кредита истёк: списано {due_amount} 🍪.{extra}",
                    )
                await asyncio.sleep(0.05)
        except Exception:
            logger.exception("Ошибка сбора кредитов кошелька")
        await asyncio.sleep(60)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings()
    db = Database(settings.database_path)
    await db.initialize()
    if await db.get_bot_state("emergency_disabled") == "1":
        logger.critical("Бот заблокирован аварийным выключателем")
        await asyncio.Event().wait()
        return
    for owner_id in settings.owner_ids:
        await db.ensure_user(owner_id, telegram_name="Владелец")
        await db.set_role(owner_id, "owner")
    for moderator_id in settings.moderator_ids:
        moderator = await db.ensure_user(moderator_id, telegram_name="Модератор")
        if moderator["role"] == "member":
            await db.set_role(moderator_id, "moderator")

    bot = Bot(settings.bot_token)
    bot.community_db = db  # type: ignore[attr-defined]
    patch_bot_ephemeral(bot)
    dispatcher = Dispatcher()
    dispatcher.message.outer_middleware(GroupHousekeepingMiddleware())
    dispatcher.callback_query.outer_middleware(UiOwnerMiddleware())
    dispatcher.callback_query.outer_middleware(GroupCallbackEphemeralMiddleware())
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
    dispatcher.include_router(contest_router)
    dispatcher.include_router(shop_admin_router)
    dispatcher.include_router(private_router)
    dispatcher.include_router(group_router)

    from community_bot.command_registry import load_registry

    await load_registry(db)
    await configure_commands(bot)
    await log_community_permissions(bot, settings)
    await announce_latest_update(bot, db, settings)
    await publish_staff_guide(db)
    await publish_commands_guide(db)
    await bot.delete_webhook(drop_pending_updates=False)
    emergency_stop = asyncio.Event()
    restart_stop = asyncio.Event()
    reputation_task = asyncio.create_task(daily_reputation_job(db, settings, bot))
    scheduled_task = asyncio.create_task(scheduled_messages_job(db, settings, bot))
    pet_task = asyncio.create_task(pet_notifications_job(db, bot, settings))
    digest_task = asyncio.create_task(notify_digest_job(db, bot, settings))
    loan_task = asyncio.create_task(cookie_loan_job(db, bot))
    board_task = asyncio.create_task(weekly_board_job(db, settings, bot))
    morning_task = asyncio.create_task(morning_digest_job(db, settings, bot))
    daily_chat_task = asyncio.create_task(daily_chat_job(db, settings, bot))
    day_note_task = asyncio.create_task(day_note_job(db, settings, bot))
    emergency_task = asyncio.create_task(emergency_stop_job(dispatcher, emergency_stop))
    restart_task = asyncio.create_task(restart_stop_job(dispatcher, restart_stop))
    try:
        await dispatcher.start_polling(
            bot,
            db=db,
            settings=settings,
            emergency_stop=emergency_stop,
            restart_stop=restart_stop,
        )
    finally:
        for task in (
            reputation_task,
            scheduled_task,
            pet_task,
            digest_task,
            loan_task,
            board_task,
            morning_task,
            daily_chat_task,
            day_note_task,
            emergency_task,
            restart_task,
        ):
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(
                reputation_task,
                scheduled_task,
                pet_task,
                digest_task,
                loan_task,
                board_task,
                morning_task,
                daily_chat_task,
                day_note_task,
                emergency_task,
                restart_task,
            )
        await bot.session.close()
    if restart_stop.is_set() and await db.get_bot_state("emergency_disabled") != "1":
        logger.info("owner restart: relaunching in-place, sqlite and settings preserved")
        relaunch()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
