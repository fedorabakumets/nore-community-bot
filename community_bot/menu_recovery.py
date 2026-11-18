"""One-time redelivery of private menus after the November 18 start fix."""
from __future__ import annotations

import asyncio
import json
import logging
import os

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from community_bot.bot_identity import marked_bots
from community_bot.database import utcnow
from community_bot.private_rich import fresh_private_panel, private_turn_lock
from community_bot.routers.private import private_menu_content

logger = logging.getLogger(__name__)


async def _send_menu(bot, db, settings, fsm, uid):
    async with private_turn_lock(bot, uid):
        state = fsm.get_context(bot=bot, chat_id=uid, user_id=uid)
        if await state.get_state():
            username = (await bot.me()).username
            markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Открыть меню", url=f"https://t.me/{username}?start=menu"),
            ]])
            await bot.send_message(uid, "Меню Норы снова доступно.", reply_markup=markup)
            return
        text, markup = await private_menu_content(db, settings, uid)
        if not markup.inline_keyboard:
            await bot.send_message(uid, text)
            return
        with fresh_private_panel(uid):
            await bot.send_message(uid, text, parse_mode="HTML", reply_markup=markup)


async def recover_private_menus(bot, db, settings, fsm):
    if os.getenv("RAILWAY_ENVIRONMENT_NAME") != "production":
        return
    checkpoint = db.path.with_name("menu-recovery-2026-11-18.json")
    staged = checkpoint.with_suffix(".tmp")

    def save():
        staged.write_text(json.dumps(progress), encoding="utf-8")
        staged.replace(checkpoint)

    try:
        if checkpoint.exists():
            progress = json.loads(checkpoint.read_text(encoding="utf-8"))
        else:
            progress = dict(cutoff=utcnow(), last_id=0, sent=0, unreachable=0, uncertain=0, complete=False)
            save()
        if progress["complete"]:
            return
        bots = await marked_bots(db)
        recipients = await db.fetchall(
            "SELECT user_id FROM users WHERE user_id>? AND created_at<=? ORDER BY user_id",
            (progress["last_id"], progress["cutoff"]),
        )
        for row in recipients:
            uid = row["user_id"]
            if uid == bot.id or str(uid) in bots:
                continue
            # Reserve the attempt before contacting Telegram so a restart cannot send it twice.
            progress["last_id"] = uid
            progress["uncertain"] += 1
            save()
            try:
                try:
                    await _send_menu(bot, db, settings, fsm, uid)
                except TelegramRetryAfter as error:
                    await asyncio.sleep(error.retry_after + 0.1)
                    await _send_menu(bot, db, settings, fsm, uid)
            except (TelegramForbiddenError, TelegramBadRequest):
                progress["unreachable"] += 1
                progress["uncertain"] -= 1
            except TelegramAPIError as error:
                logger.warning("Private menu redelivery failed (%s)", type(error).__name__)
            else:
                progress["sent"] += 1
                progress["uncertain"] -= 1
            save()
            await asyncio.sleep(0.1)

        progress["complete"] = True
        save()
        report = (f"Рассылка меню завершена. Отправлено: {progress['sent']}. "
                  f"Недоступно: {progress['unreachable']}. Без подтверждения: {progress['uncertain']}.")
        logger.info(report)
        await bot.send_message(settings.owner_id, report)
    except (OSError, ValueError, TelegramAPIError):
        logger.warning("Не удалось завершить рассылку меню или отправить отчёт")
