from __future__ import annotations

import html
import secrets
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, ChatPermissions, InlineKeyboardMarkup, Message

from community_bot.aliases import command_or_alias
from community_bot.audit import person_label
from community_bot.blocks import answer_block
from community_bot.database import Database
from community_bot.ephemeral import expire_game_result, keep_in_chat
from community_bot.game_notify import send_game_finale
from community_bot.helpers import register_telegram_user, resolve_reply_target, user_link
from community_bot.keyboards import close_btn, games_menu_keyboard, roulette_invite_keyboard
from community_bot.texts import GAMES_HELP_TEXT
from community_bot.ui_owner import bind_ui_owner

router = Router(name="games")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))
router.callback_query.filter(F.message.chat.type.in_({"group", "supergroup"}))

ROULETTE_MUTE_MINUTES = 30


def _player_name(player: dict[str, object]) -> str:
    return str(player.get("profile_name") or player.get("telegram_name") or player.get("username") or player["user_id"])


@router.message(command_or_alias("games"))
async def games_hub(message: Message, db: Database) -> None:
    if not await db.feature_enabled("games"):
        await message.answer("Мини-игры временно выключены администрацией.")
        return
    with keep_in_chat():
        sent = await answer_block(
            message,
            "games",
            GAMES_HELP_TEXT,
            parse_mode="HTML",
            reply_markup=games_menu_keyboard(),
        )
        if message.from_user:
            await bind_ui_owner(db, sent, message.from_user.id, "games")


@router.callback_query(F.data == "game:rules:all")
async def game_rules(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await answer_block(
            callback.message,
            "games",
            GAMES_HELP_TEXT,
            parse_mode="HTML",
            reply_markup=games_menu_keyboard(),
        )


@router.callback_query(F.data == "game:pick:roulette")
async def game_pick_roulette(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await answer_block(
            callback.message,
            "roulette",
            "🔫 <b>Рулетка</b>\nОтветьте «рулетка» на человека. Бесплатно, 50/50, проигравший в муте 30 минут.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[close_btn("ui:close")]]),
        )


@router.message(command_or_alias("roulette"))
async def roulette_invite(message: Message, db: Database) -> None:
    if not message.from_user:
        return
    if not await db.feature_enabled("games"):
        await message.answer("Мини-игры временно выключены администрацией.")
        return
    target = await resolve_reply_target(message, db)
    if not target or not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("Ответьте «рулетка» на сообщение человека. Вход бесплатный, на кону мут 30 минут.")
        return
    if message.reply_to_message.from_user.is_bot:
        await message.answer("С ботами играть нельзя.")
        return
    if int(target["user_id"]) == message.from_user.id:
        await message.answer("Нельзя сыграть с самим собой.")
        return
    await register_telegram_user(db, message.from_user)
    game_id = await db.create_roulette(message.chat.id, message.from_user.id, int(target["user_id"]), 0)
    with keep_in_chat():
        await answer_block(
            message,
            "roulette",
            f"🔫 {user_link(int(target['user_id']), person_label(target))} — вызов на рулетку от "
            f"{user_link(message.from_user.id, message.from_user.full_name)}.\n"
            f"Бесплатно. 50/50. Проигравший молчит {ROULETTE_MUTE_MINUTES} минут.",
            parse_mode="HTML",
            reply_markup=roulette_invite_keyboard(game_id),
        )


@router.callback_query(F.data.startswith("roulette:"))
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
        await callback.answer("Ответить может только вызванный.", show_alert=True)
        return
    if decision == "decline":
        await db.cancel_roulette(game_id, callback.from_user.id)
        await callback.answer("Отказ.")
        await callback.message.edit_reply_markup(reply_markup=None)
        await send_game_finale(callback.message, "🔫 Рулетка отменена: соперник отказался.")
        expire_game_result(callback.message)
        return
    winner_id = secrets.choice([int(game["challenger_id"]), int(game["opponent_id"])])
    ok, error, result = await db.settle_roulette(game_id, callback.from_user.id, winner_id)
    if not ok or not result:
        await callback.answer(error, show_alert=True)
        return
    winner = await db.get_user(int(result["winner_id"]))
    loser = await db.get_user(int(result["loser_id"]))
    if not winner or not loser:
        await callback.answer("Ошибка профиля.", show_alert=True)
        return
    until = datetime.now(UTC) + timedelta(minutes=ROULETTE_MUTE_MINUTES)
    with suppress(TelegramBadRequest, TelegramForbiddenError):
        await bot.restrict_chat_member(
            callback.message.chat.id,
            int(loser["user_id"]),
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
    await callback.answer("Выстрел.")
    await callback.message.edit_reply_markup(reply_markup=None)
    winner_name = html.escape(_player_name(winner))
    loser_name = html.escape(_player_name(loser))
    await send_game_finale(
        callback.message,
        f"🔫 <b>Рулетка</b>\n"
        f"Уцелел: {user_link(int(winner['user_id']), winner_name)}\n"
        f"Отлетел: {user_link(int(loser['user_id']), loser_name)} — мут {ROULETTE_MUTE_MINUTES} мин.",
    )
    expire_game_result(callback.message)


@router.callback_query(F.data.regexp(r"^game:(join|start|cancel|vote):"))
async def stale_game_buttons(callback: CallbackQuery) -> None:
    await callback.answer("Эта партия уже неактуальна. Откройте игры заново командой «игры».", show_alert=True)
