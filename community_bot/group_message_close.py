"""Dismiss NORA's group messages with the same permissions in every feature."""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from aiogram import BaseMiddleware
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramNotFound
from aiogram.methods import EditMessageReplyMarkup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichBlockButtons,
    Message,
    MessageId,
    RichBlockButtons,
)

from community_bot.domain import ROLE_LEVELS
from community_bot.helpers import rank_of_user

PREFIX = "nora:close:"
RECORD = "group-close:"
LEGACY = {"ui:close", "g:hide", "shop:close", "commands:close", "nora_speech:close"}
LEGACY_INVITE = "game-invite:close:"
EDITS = {"editMessageText", "editMessageCaption", "editMessageMedia", "editMessageReplyMarkup",
         "editMessageLiveLocation", "stopMessageLiveLocation", "stopPoll"}
COPIES = {"copyMessage", "copyMessages", "forwardMessage", "forwardMessages"}
# A separate context is used by Mini App requests and tasks publishing to the chat for a named recipient.
_ACTORS: ContextVar[tuple[int, ...]] = ContextVar("group_close_actors", default=())
logger = logging.getLogger(__name__)


@contextmanager
def group_message_actors(*actors: int) -> Iterator[None]:
    ids = tuple(dict.fromkeys(uid for uid in actors if type(uid) is int and uid > 0))
    token = _ACTORS.set(ids)
    try:
        yield
    finally:
        _ACTORS.reset(token)


class GroupMessageActorsMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        with group_message_actors(user.id if user and not user.is_bot else 0):
            return await handler(event, data)


def _close_action(value):
    return isinstance(value, str) and (value in LEGACY or value.startswith((PREFIX, LEGACY_INVITE)))


def _owner_ids(button_data):
    if not isinstance(button_data, str):
        return ()
    match = re.fullmatch(r"nora:close:(\d{1,16})(?::(\d{1,16}))?", button_data)
    return tuple(int(uid) for uid in match.groups() if uid and int(uid)) if match else ()


def _callback_data(owners):
    return PREFIX + (":".join(str(uid) for uid in owners[:2]) or "0")


def _key(chat_id, message_id):
    return f"{RECORD}{chat_id}:{message_id}"


def _native(markup, data):
    original = markup.inline_keyboard if isinstance(markup, InlineKeyboardMarkup) else []
    rows = [[b for b in row if not _close_action(b.callback_data)] for row in original]
    return InlineKeyboardMarkup(inline_keyboard=[
        *[row for row in rows if row],
        [InlineKeyboardButton(text="✕ Закрыть", style="danger", callback_data=data)],
    ])


def _strip_rich_buttons(rich):
    blocks = []
    for block in rich.blocks:
        if isinstance(block, InputRichBlockButtons):
            buttons = [button for button in block.buttons if not _close_action(button.callback_data)]
            if not buttons:
                continue
            block = block.model_copy(update={"buttons": buttons})
        blocks.append(block)
    return rich.model_copy(update={"blocks": blocks})


async def _remember(db, key, data, sent):
    try:
        await db.set_bot_state(key, f"{int(sent)} {data}")
    except Exception:
        logger.exception("Could not remember group message ownership")


async def _edit_data(db, chat_id, message_id):
    stored = await db.get_bot_state(_key(chat_id, message_id))
    if stored:
        return stored.split(" ", 1)[-1]
    owner = await db.get_ui_owner(chat_id, message_id)
    return _callback_data((owner,) if owner else ())


class GroupCloseSendMiddleware(BaseRequestMiddleware):
    """All Bot API sends and message edits in the configured community."""

    async def __call__(self, make_request, bot, method):
        settings = getattr(bot, "community_settings", None)
        name = method.__api_method__
        chat_id = getattr(method, "chat_id", None)
        if not settings or not settings.community_chat_id or chat_id != settings.community_chat_id:
            return await make_request(bot, method)
        db = bot.community_db
        is_edit = name in EDITS
        if not (is_edit or (name.startswith("send") and name != "sendChatAction") or name in COPIES):
            return await make_request(bot, method)

        actor = getattr(getattr(method, "ephemeral_message_parameters", None), "receiver_user_id", None)
        owners = (*_ACTORS.get(), actor) if type(actor) is int and actor not in _ACTORS.get() else _ACTORS.get()
        data = await _edit_data(db, chat_id, method.message_id) if is_edit else _callback_data(owners)
        markup = getattr(method, "reply_markup", None)
        can_embed = "reply_markup" in type(method).model_fields and (
            markup is None or isinstance(markup, InlineKeyboardMarkup)
        )
        if can_embed:
            changes = {"reply_markup": _native(markup, data)}
            rich = getattr(method, "rich_message", None)
            if rich is not None:
                changes["rich_message"] = _strip_rich_buttons(rich)
            method = method.model_copy(update=changes)

        result = await make_request(bot, method)
        if is_edit:
            return result
        for message in result if isinstance(result, list) else [result]:
            if not isinstance(message, (Message, MessageId)) or message.message_id <= 0:
                continue
            if not can_embed:
                try:
                    await make_request(bot, EditMessageReplyMarkup(
                        chat_id=chat_id, message_id=message.message_id,
                        reply_markup=_native(getattr(message, "reply_markup", None), data),
                    ))
                except TelegramAPIError as error:
                    logger.warning("Telegram declined a close button on %s (%s)", name, type(error).__name__)
            if owners:
                # Use the original sending time even if the message is edited later.
                sent = message.date.timestamp() if isinstance(message, Message) else time.time()
                await _remember(db, _key(chat_id, message.message_id), data, sent)
        return result


def _has_button(message, data):
    markup = message.reply_markup
    if markup and any(button.callback_data == data for row in markup.inline_keyboard for button in row):
        return True
    rich = message.rich_message
    return bool(rich and any(
        button.callback_data == data
        for block in rich.blocks if isinstance(block, RichBlockButtons) for button in block.buttons
    ))


async def _is_admin(bot, db, settings, chat_id, uid):
    if await rank_of_user(db, settings, uid) >= ROLE_LEVELS["admin"]:
        return True
    try:
        member = await bot.get_chat_member(chat_id, uid)
    except TelegramAPIError:
        return False
    return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}


class GroupCloseCallbackMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not isinstance(event, CallbackQuery) or not _close_action(event.data):
            return await handler(event, data)
        message = event.message
        settings, bot, db = data["settings"], data["bot"], data["db"]
        if not message or message.chat.id != settings.community_chat_id:
            return await handler(event, data)
        if (not isinstance(message, Message) or not message.from_user or message.from_user.id != bot.id
                or not _has_button(message, event.data)):
            await event.answer("Сообщение уже недоступно.", show_alert=True)
            return
        uid = event.from_user.id
        owners = _owner_ids(event.data)
        if not event.data.startswith(PREFIX):
            saved = await _edit_data(db, message.chat.id, message.message_id)
            owners = _owner_ids(saved)
            if event.data.startswith(LEGACY_INVITE):
                invitee = event.data.removeprefix(LEGACY_INVITE).split(":", 1)[0]
                if invitee.isdecimal():
                    owners = (*owners, int(invitee))
            if message.reply_to_message and message.reply_to_message.from_user:
                owners = (*owners, message.reply_to_message.from_user.id)
        if uid not in owners and not await _is_admin(bot, db, settings, message.chat.id, uid):
            await event.answer("Закрыть может автор запроса, адресат или администратор.", show_alert=True)
            return
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except (TelegramBadRequest, TelegramNotFound) as error:
            if "not found" not in str(error).lower():
                await event.answer("Telegram не разрешил удалить это сообщение через бота.", show_alert=True)
                return
        except TelegramAPIError:
            await event.answer("Telegram не смог удалить сообщение.", show_alert=True)
            return
        await event.answer()


async def purge_ownership(db, now):
    await db.execute("DELETE FROM bot_state WHERE key BETWEEN 'group-close:' AND 'group-close;' AND "
                     "CAST(substr(value,1,instr(value,' ')-1) AS INTEGER) < ?", (int(now) - 48 * 3600,))
