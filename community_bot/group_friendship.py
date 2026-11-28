"""Friendship requests and confirmations sent from group profile cards."""

from __future__ import annotations

import logging
import re
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramNotFound
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InputRichBlockButtons,
    InputRichBlockParagraph,
    InputRichMessage,
    Message,
    ReplyParameters,
    RichMessageButton,
    RichTextTextMention,
    User,
)

from community_bot import friends_api
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.ephemeral import keep_in_chat
from community_bot.group_profile import FRIEND_PREFIX, refresh_group_profile
from community_bot.helpers import display_name, user_link
from community_bot.keyboards import ibtn
from community_bot.reply_rich import bot_publication

logger = logging.getLogger(__name__)
DECISION_PREFIX = "gf:"
_DECISION = re.compile(r"gf:([adrn]):([1-9][0-9]{0,15}):([1-9][0-9]{0,15}):([A-Za-z0-9_-]{24})")
_ACTIONS = {"a": "accept", "d": "decline", "r": "remove"}


def _mention(user, *, handle=False):
    name = display_name(user, "Участник")
    label = f"@{user['username']}" if handle and user.get("username") else name
    return RichTextTextMention(
        text=label,
        user=User(id=user["user_id"], first_name=name, is_bot=False),
    )


async def _send_prompt(message, bot, parts, buttons):
    params = {
        "reply_parameters": ReplyParameters(message_id=message.message_id, allow_sending_without_reply=True),
        "message_thread_id": message.message_thread_id if message.is_topic_message else None,
    }
    rich = InputRichMessage(
        blocks=[InputRichBlockParagraph(text=parts), InputRichBlockButtons(buttons=buttons, align="center")],
        skip_entity_detection=True,
    )
    try:
        await bot.send_rich_message(message.chat.id, rich_message=rich, **params)
    except (TelegramBadRequest, TelegramNotFound):
        text = "".join(escape(part) if isinstance(part, str) else user_link(part.user.id, part.text) for part in parts)
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            ibtn(btn.text, btn.callback_data, btn.style if btn.style != "link" else None) for btn in buttons
        ]])
        with bot_publication():
            await bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup, **params)


async def _close_prompt(message: Message, result: str):
    try:
        await message.delete()
    except TelegramAPIError:
        # Telegram can reject deletion of an old prompt. Retire its buttons in place.
        with bot_publication(), keep_in_chat():
            try:
                if message.rich_message:
                    await message.edit_text(rich_message=InputRichMessage(
                        blocks=[InputRichBlockParagraph(text=result)],
                    ), parse_mode=None)
                else:
                    await message.edit_text(result, parse_mode=None)
            except TelegramAPIError:
                pass


async def group_profile_friend(callback: CallbackQuery, db: Database, settings: Settings, bot: Bot) -> None:
    recipient = (callback.data or "").removeprefix(FRIEND_PREFIX)
    message = callback.message
    if not isinstance(message, Message) or not re.fullmatch(r"[1-9][0-9]{0,15}", recipient):
        await callback.answer("Открой профиль заново.", show_alert=True)
        return
    uid, other = callback.from_user.id, int(recipient)
    target = await db.get_user(other)
    if not target:
        await callback.answer("Участник не найден.", show_alert=True)
        return

    relation = await friends_api.current_relationship(db, uid, other)
    if relation and relation["status"] == "accepted":
        token = relation["token"]
        await callback.answer()
        await _send_prompt(message, bot, ["❗️Вы действительно хотите удалить из друзей ",
                                         _mention(target, handle=True), "?"], [
            RichMessageButton(text="ДА", style="danger", callback_data=f"gf:r:{uid}:{other}:{token}"),
            RichMessageButton(text="Нет", style="link", callback_data=f"gf:n:{uid}:{other}:{token}"),
        ])
        await refresh_group_profile(message, db, settings, other)
        return

    try:
        result, notices = await friends_api.mutate(db, settings, uid, {"action": "request", "recipient": recipient})
    except ValueError as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer(result, show_alert=True)
    if not notices:
        return
    try:
        relation = await friends_api.current_relationship(db, uid, other)
        if relation and relation["status"] == "pending" and relation["requester_id"] == uid:
            token = relation["token"]
            requester = await db.get_user(uid)
            with keep_in_chat():
                await _send_prompt(message, bot, [_mention(target, handle=True), ", ", _mention(requester),
                                                  " хочет добавить тебя в друзья."], [
                    RichMessageButton(text="Принять", style="success", callback_data=f"gf:a:{other}:{uid}:{token}"),
                    RichMessageButton(text="Отказаться", style="danger", callback_data=f"gf:d:{other}:{uid}:{token}"),
                ])
    except TelegramAPIError as error:
        logger.warning("Friendship request kept in Nora inbox after Telegram error: %s", type(error).__name__)
    finally:
        for inbox_id, target_id, text in notices:
            await friends_api.deliver_notice(bot, db, inbox_id, target_id, text)


async def group_friend_decision(callback: CallbackQuery, db: Database, settings: Settings, bot: Bot) -> None:
    match = _DECISION.fullmatch(callback.data or "")
    message = callback.message
    if not match or not isinstance(message, Message):
        await callback.answer("Кнопки устарели.", show_alert=True)
        return
    choice, recipient, other, token = match[1], int(match[2]), int(match[3]), match[4]
    if callback.from_user.id != recipient:
        await callback.answer("Эти кнопки предназначены другому участнику.", show_alert=True)
        return
    if choice == "n":
        await callback.answer("Отменено")
        await _close_prompt(message, "Отменено.")
        return

    relation = await friends_api.current_relationship(db, recipient, other)
    expected = "accepted" if choice == "r" else "pending"
    if not relation or relation["token"] != token or relation["status"] != expected:
        await callback.answer("Этот запрос уже закрыт.", show_alert=True)
        await _close_prompt(message, "Запрос закрыт.")
        return
    try:
        result, notices = await friends_api.mutate(
            db, settings, recipient, {"action": _ACTIONS[choice], "target_id": other, "token": token},
        )
    except ValueError as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer(result, show_alert=True)
    await _close_prompt(message, result)
    for inbox_id, uid, text in notices:
        await friends_api.deliver_notice(bot, db, inbox_id, uid, text)
    if message.reply_to_message and choice in {"a", "r"}:
        await refresh_group_profile(message.reply_to_message, db, settings, recipient if choice == "a" else other)
