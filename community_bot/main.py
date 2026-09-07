from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats

from community_bot.config import Settings, load_settings
from community_bot.database import Database
from community_bot.helpers import send_stored_message
from community_bot.pets_talk import idle_ping
from community_bot.routers import flows_router, games_router, group_router, pets_router, private_router

logger = logging.getLogger(__name__)


async def configure_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="apply", description="Заполнить анкету"),
            BotCommand(command="question", description="Задать вопрос"),
            BotCommand(command="profile", description="Мой профиль"),
            BotCommand(command="shop", description="Магазин"),
            BotCommand(command="pet", description="Мой тамагочи"),
            BotCommand(command="buycookies", description="Купить печеньки через СБП"),
            BotCommand(command="admin", description="Админ-панель"),
            BotCommand(command="help", description="Помощь"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
        language_code="ru",
    )
    await bot.set_my_commands(
        [
            BotCommand(command="profile", description="Профиль (можно ответом)"),
            BotCommand(command="commands", description="Все команды бота"),
            BotCommand(command="reputation", description="Система репутации"),
            BotCommand(command="store", description="Магазин и оплата"),
            BotCommand(command="shop", description="Магазин"),
            BotCommand(command="transfer", description="Перевести печеньки ответом"),
            BotCommand(command="roulette", description="Русская рулетка ответом"),
            BotCommand(command="games", description="Мини-игры и правила"),
            BotCommand(command="pet", description="Открыть тамагочи в личке"),
            BotCommand(command="gamecancel", description="Отменить текущую игру"),
            BotCommand(command="mute", description="Мут ответом: /mute 30m"),
            BotCommand(command="unmute", description="Снять мут ответом"),
            BotCommand(command="warn", description="Предупреждение ответом"),
            BotCommand(command="unwarn", description="Снять предупреждение ответом"),
            BotCommand(command="kick", description="Исключить ответом"),
            BotCommand(command="ban", description="Заблокировать ответом"),
            BotCommand(command="unban", description="Разблокировать по ID"),
        ],
        scope=BotCommandScopeAllGroupChats(),
        language_code="ru",
    )


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


async def pet_notifications_job(db: Database, bot: Bot) -> None:
    while True:
        try:
            for stored_pet in await db.list_pets():
                user_id = int(stored_pet["user_id"])
                pet = await db.settle_pet(user_id)
                if not pet:
                    continue
                payout = int(pet.get("payout", 0))
                sleeping = bool(int(pet["sleeping"]))
                now = datetime.now(tz=ZoneInfo("UTC"))
                last_notice_raw = pet.get("last_notice_at")
                last_notice = datetime.fromisoformat(str(last_notice_raw)) if last_notice_raw else None
                hungry_notice_due = sleeping and (not last_notice or now - last_notice >= timedelta(hours=12))
                cute_ping_due = (
                    not sleeping
                    and not payout
                    and (not last_notice or now - last_notice >= timedelta(hours=8))
                )
                if not payout and not hungry_notice_due and not cute_ping_due:
                    continue
                if payout:
                    text = f"🍪✨ {pet['name']} притащил тебе {payout} 🍪 и смотрит глазами-сердечками 💕"
                elif hungry_notice_due:
                    text = (
                        f"💤🥺 {pet['name']} свернулся калачиком: сытость или вода на нуле. "
                        "Загляни в /pet, пожалуйста 🫶🌸"
                    )
                else:
                    text = idle_ping(pet)
                if await send_stored_message(bot, user_id, text, None, None):
                    await db.execute(
                        "UPDATE pets SET last_notice_at = ?, updated_at = ? WHERE user_id = ?",
                        (now.isoformat(), now.isoformat(), user_id),
                    )
                await asyncio.sleep(0.05)
        except Exception:
            logger.exception("Ошибка уведомлений тамагочи")
        await asyncio.sleep(1800)


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
    dispatcher = Dispatcher()
    dispatcher.include_router(flows_router)
    dispatcher.include_router(games_router)
    dispatcher.include_router(pets_router)
    dispatcher.include_router(private_router)
    dispatcher.include_router(group_router)

    await configure_commands(bot)
    await bot.delete_webhook(drop_pending_updates=False)
    emergency_stop = asyncio.Event()
    reputation_task = asyncio.create_task(daily_reputation_job(db, settings, bot))
    scheduled_task = asyncio.create_task(scheduled_messages_job(db, settings, bot))
    pet_task = asyncio.create_task(pet_notifications_job(db, bot))
    emergency_task = asyncio.create_task(emergency_stop_job(dispatcher, emergency_stop))
    try:
        await dispatcher.start_polling(bot, db=db, settings=settings, emergency_stop=emergency_stop)
    finally:
        for task in (reputation_task, scheduled_task, pet_task, emergency_task):
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(reputation_task, scheduled_task, pet_task, emergency_task)
        await bot.session.close()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
