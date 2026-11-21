"""Dismiss NORA's group messages with the same permissions in every feature."""
from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from aiogram import BaseMiddleware
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramNotFound
from aiogram.methods import EditMessageReplyMarkup, EditMessageText, SendRichMessage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichBlockButtons,
    InputRichBlockParagraph,
    InputRichMessage,
    Message,
    MessageId,
    ReplyParameters,
    RichBlockButtons,
    RichMessageButton,
)

from community_bot.domain import ROLE_LEVELS
from community_bot.ephemeral import current_reply_ttl, schedule_group_reply
from community_bot.helpers import rank_of_user
from community_bot.private_rich import _content, _reusable, _uploaded_media, text_blocks
from community_bot.reply_rich import _SEND, _method_fields, _reply_parameters, split_buttons

PREFIX = "nora:close:"
RECORD = "group-close:"
PIN = "group-pin-button:"
LEGACY = {"ui:close", "g:hide", "shop:close", "commands:close", "nora_speech:close"}
LEGACY_INVITE = "game-invite:close:"
EDITS = {"editMessageText", "editMessageCaption", "editMessageMedia", "editMessageReplyMarkup",
         "editMessageLiveLocation", "stopMessageLiveLocation", "stopPoll"}
COPIES = {"copyMessage", "copyMessages", "forwardMessage", "forwardMessages"}
# A separate context is used by Mini App requests and tasks publishing to the chat for a named recipient.
_ACTORS: ContextVar[tuple[int, ...]] = ContextVar("group_close_actors", default=())
_SOURCE: ContextVar[Message | None] = ContextVar("group_close_source", default=None)
_SKIP_GROUP_CLOSE: ContextVar[bool] = ContextVar("skip_group_close", default=False)
logger = logging.getLogger(__name__)


@contextmanager
def group_message_actors(*actors: int) -> Iterator[None]:
    ids = tuple(dict.fromkeys(uid for uid in actors if type(uid) is int and uid > 0))
    token = _ACTORS.set(ids)
    try:
        yield
    finally:
        _ACTORS.reset(token)


@contextmanager
def without_group_close() -> Iterator[None]:
    token = _SKIP_GROUP_CLOSE.set(True)
    try:
        yield
    finally:
        _SKIP_GROUP_CLOSE.reset(token)


class GroupMessageActorsMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        callback = getattr(event, "callback_query", None)
        token = _SOURCE.set(callback.message if callback and isinstance(callback.message, Message) else None)
        try:
            with group_message_actors(user.id if user and not user.is_bot else 0):
                return await handler(event, data)
        finally:
            _SOURCE.reset(token)


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


def _pin_key(chat_id, message_id):
    return f"{PIN}{chat_id}:{message_id}"


def _pin_markup(url):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="НОРА", url=url)]]) if url else None


async def _set_pin_button(make_request, bot, chat_id, message_id, *, pinned):
    db = bot.community_db
    key = _pin_key(chat_id, message_id)
    if not pinned and not await db.get_bot_state(key):
        return
    try:
        async with asyncio.timeout(5):
            username = (await bot.me()).username if pinned else None
            url = f"https://t.me/{username}?startapp" if username else ""
            with without_group_close():
                await make_request(bot, EditMessageReplyMarkup(
                    chat_id=chat_id, message_id=message_id, reply_markup=_pin_markup(url),
                ))
    except TelegramBadRequest as error:
        if "not modified" not in str(error).lower():
            logger.warning("Telegram declined a pin menu change (%s)", type(error).__name__)
            return
    except (TelegramAPIError, TimeoutError, OSError) as error:
        logger.warning("Could not update the pinned NORA link (%s)", type(error).__name__)
        return
    if url:
        await db.set_bot_state(key, url)
    else:
        await db.execute("DELETE FROM bot_state WHERE key=?", (key,))


async def normalize_current_pin(bot, settings):
    if not settings.community_chat_id:
        return
    try:
        async with asyncio.timeout(5):
            chat = await bot.get_chat(settings.community_chat_id)
        post = chat.pinned_message
        if isinstance(post, Message) and post.from_user and post.from_user.id == bot.id:
            await _migrate_current_pin(bot, post)
            await _set_pin_button(lambda client, method: client(method), bot, chat.id, post.message_id, pinned=True)
    except (TelegramAPIError, TimeoutError, OSError) as error:
        logger.warning("Could not check the existing community pin (%s)", type(error).__name__)


@dataclass(frozen=True)
class CloseRecord:
    data: str
    target: int = 0
    rich: bool = False


async def _read(db, chat_id, message_id):
    stored = await db.get_bot_state(_key(chat_id, message_id))
    if not stored:
        return None
    parts = stored.split()
    if len(parts) not in (2, 4):
        return None
    target = int(parts[2]) if len(parts) == 4 and parts[2].isdecimal() else 0
    return CloseRecord(parts[1], target, len(parts) == 4 and parts[3] == "rich")


async def _remember(db, chat_id, message_id, record, sent):
    try:
        mode = "rich" if record.rich else "plain"
        await db.set_bot_state(_key(chat_id, message_id), f"{int(sent)} {record.data} {record.target} {mode}")
    except Exception:
        logger.exception("Could not remember group message ownership")


async def _edit_record(db, chat_id, message_id):
    record = await _read(db, chat_id, message_id)
    if record:
        return record
    owner = await db.get_ui_owner(chat_id, message_id)
    return CloseRecord(_callback_data((owner,) if owner else ()))


def _rich(blocks, markup, data, original=None):
    rows, _, _ = split_buttons(markup)
    merged = []
    seen = set()
    for block in [*blocks, *rows]:
        if not isinstance(block, InputRichBlockButtons):
            if not isinstance(block, dict) or block.get("type") != "buttons":
                merged.append(block)
                continue
            block = InputRichBlockButtons.model_validate(block)
        buttons = []
        for button in block.buttons:
            identity = button.model_dump_json(exclude_none=True)
            if _close_action(button.callback_data) or identity in seen:
                continue
            seen.add(identity)
            buttons.append(button)
        if buttons:
            merged.append(block.model_copy(update={"buttons": buttons}))
    close = RichMessageButton(text="❌", style="danger", callback_data=data)
    last_row = next((i for i in range(len(merged) - 1, -1, -1) if isinstance(merged[i], InputRichBlockButtons)), None)
    if last_row is not None and len(merged[last_row].buttons) < 8:
        row = merged[last_row]
        merged[last_row] = row.model_copy(update={"buttons": [*row.buttons, close]})
    else:
        merged.append(InputRichBlockButtons(align="center", buttons=[close]))
    extra = original.model_dump(exclude={"html", "markdown", "blocks"}, exclude_none=True) if original else {}
    return InputRichMessage(blocks=merged, **extra)


def _body(result):
    rich = getattr(result, "rich_message", None)
    return _reusable(rich.model_dump(exclude_none=True)["blocks"]) if rich else None


async def _migrate_current_pin(bot, message):
    db = bot.community_db
    chat_id, mid = message.chat.id, message.message_id
    if await db.get_bot_state(_pin_key(chat_id, mid)) and _body(message):
        return
    blocks = _body(message) or text_blocks(message.text, entities=message.entities, compact=False)
    if not blocks:
        return  # A native photo or poll can keep its pin, but cannot be edited into Rich text.
    record = await _edit_record(db, chat_id, mid)
    markup = _without_pin_link(message.reply_markup)
    try:
        with without_group_close():
            async with asyncio.timeout(5):
                await bot(EditMessageText(
                    chat_id=chat_id, message_id=mid, rich_message=_rich(blocks, markup, record.data),
                ))
        await _remember(db, chat_id, mid, CloseRecord(record.data, rich=True), message.date.timestamp())
    except TelegramBadRequest as error:
        if "not modified" not in str(error).lower():
            logger.warning("Telegram declined Rich migration of the current pin")
    except (TelegramAPIError, TimeoutError, OSError):
        logger.warning("Could not migrate the current pin to Rich")


def _without_pin_link(markup):
    if not isinstance(markup, InlineKeyboardMarkup):
        return markup
    rows = [[b for b in row if not (b.text == "НОРА" and b.url and b.url.endswith("?startapp"))]
            for row in markup.inline_keyboard]
    return InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row])


class GroupCloseSendMiddleware(BaseRequestMiddleware):
    """Keep all community controls in Rich blocks except the link on a pinned post."""

    def __init__(self):
        self.pages = OrderedDict()

    def cache(self, chat_id, mid, result):
        if blocks := _body(result):
            key = (chat_id, mid)
            self.pages[key] = blocks
            self.pages.move_to_end(key)
            if len(self.pages) > 256:
                self.pages.popitem(last=False)

    async def __call__(self, make_request, bot, method):
        settings = getattr(bot, "community_settings", None)
        name = method.__api_method__
        chat_id = getattr(method, "chat_id", None)
        if (_SKIP_GROUP_CLOSE.get() or not chat_id or not settings
                or chat_id != getattr(settings, "community_chat_id", 0)):
            return await make_request(bot, method)
        db = bot.community_db
        if name in {"pinChatMessage", "unpinChatMessage", "unpinAllChatMessages"}:
            result = await make_request(bot, method)
            mid = getattr(method, "message_id", None)
            if result and mid:
                await _set_pin_button(make_request, bot, chat_id, mid, pinned=name == "pinChatMessage")
            elif result and name == "unpinAllChatMessages":
                prefix = f"{PIN}{chat_id}:"
                for row in await db.fetchall("SELECT key FROM bot_state WHERE key GLOB ?", (prefix + "*",)):
                    await _set_pin_button(make_request, bot, chat_id, int(row["key"][len(prefix):]), pinned=False)
            return result
        if name in EDITS:
            return await self.edit(make_request, bot, method, chat_id)
        if (name.startswith("send") and name not in {"sendChatAction", "sendMessageDraft", "sendRichMessageDraft"}
                or name in COPIES):
            return await self.send(make_request, bot, method, chat_id)
        return await make_request(bot, method)

    async def send(self, make_request, bot, method, chat_id):
        owner_data = _callback_data(_ACTORS.get())
        markup = getattr(method, "reply_markup", None)
        original = getattr(method, "rich_message", None)
        if original or method.__api_method__ in _SEND:
            blocks = _content(method, bot, compact=False)
            rich = _rich(blocks, _without_pin_link(markup), owner_data, original)
            fields = _method_fields(method, SendRichMessage)
            fields.update(rich_message=rich, reply_markup=None, reply_parameters=_reply_parameters(method))
            try:
                result = await make_request(bot, SendRichMessage(**fields))
            except (TelegramBadRequest, TelegramNotFound):
                if original:
                    raise  # Keep authored Rich fallbacks in their feature handlers.
            else:
                await self.register(bot, chat_id, result, CloseRecord(owner_data, rich=True))
                return _uploaded_media(result, method)

        clean = method.model_copy(update={"reply_markup": None}) if isinstance(markup, InlineKeyboardMarkup) else method
        result = await make_request(bot, clean)
        for message in result if isinstance(result, list) else [result]:
            if not isinstance(message, (Message, MessageId)) or message.message_id <= 0:
                continue
            await self.companion(make_request, bot, chat_id, message, markup, owner_data)
        return result

    async def edit(self, make_request, bot, method, chat_id):
        mid = method.message_id
        db = bot.community_db
        record = await _edit_record(db, chat_id, mid)
        url = await db.get_bot_state(_pin_key(chat_id, mid))
        markup = getattr(method, "reply_markup", None)
        original = getattr(method, "rich_message", None)
        source = _SOURCE.get()
        cached = self.pages.get((chat_id, mid))
        if not cached and source and source.chat.id == chat_id and source.message_id == mid:
            cached = _body(source) or text_blocks(source.text, entities=source.entities, compact=False)
        name = method.__api_method__
        if original or name == "editMessageText" or cached and name in {
                "editMessageReplyMarkup", "editMessageCaption", "editMessageMedia",
        }:
            if name == "editMessageReplyMarkup":
                blocks = [block for block in cached if block["type"] != "buttons"]
            else:
                blocks = _content(method, bot, compact=False)
                if name == "editMessageCaption":
                    blocks = [block for block in cached if block["type"] in {
                        "photo", "video", "animation", "audio", "document", "voice_note",
                    }] + blocks
            fields = _method_fields(method, EditMessageText)
            fields.update(text=None, parse_mode=None, entities=None, link_preview_options=None,
                          disable_web_page_preview=None, reply_markup=_pin_markup(url),
                          rich_message=_rich(blocks, markup, record.data, original))
            try:
                result = await make_request(bot, EditMessageText(**fields))
            except (TelegramBadRequest, TelegramNotFound):
                if original or record.rich:
                    raise
            else:
                if not record.rich:
                    await self.register(bot, chat_id, result, CloseRecord(record.data, rich=True))
                else:
                    self.cache(chat_id, mid, result)
                return result
        if "reply_markup" in type(method).model_fields:
            method = method.model_copy(update={"reply_markup": _pin_markup(url)})
        return await make_request(bot, method)

    async def register(self, bot, chat_id, result, record):
        if isinstance(result, Message) and result.message_id > 0:
            self.cache(chat_id, result.message_id, result)
            await _remember(bot.community_db, chat_id, result.message_id, record, result.date.timestamp())

    async def companion(self, make_request, bot, chat_id, parent, markup, data):
        # Polls, stickers, and media albums have no corresponding interactive Rich block.
        try:
            result = await make_request(bot, SendRichMessage(
                chat_id=chat_id, disable_notification=True,
                reply_parameters=ReplyParameters(message_id=parent.message_id, allow_sending_without_reply=False),
                rich_message=_rich([InputRichBlockParagraph(text="Действия с сообщением")], markup, data),
            ))
        except TelegramAPIError as error:
            logger.warning("Could not add Rich controls to a native message (%s)", type(error).__name__)
            return
        await self.register(bot, chat_id, result, CloseRecord(data, target=parent.message_id, rich=True))
        if ttl := current_reply_ttl():
            schedule_group_reply(result, ttl)


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
        saved = await _read(db, message.chat.id, message.message_id)
        # Telegram can omit the sender or markup of the originating Rich message.
        known = saved and saved.data == event.data
        visible = (isinstance(message, Message) and message.from_user and message.from_user.id == bot.id
                   and _has_button(message, event.data))
        legacy_public = event.data == _callback_data(()) and not saved and not visible and await db.fetchone(
            "SELECT 1 FROM bot_chat_messages WHERE chat_id=? AND message_id=?",
            (message.chat.id, message.message_id),
        )
        if not known and not visible and not legacy_public:
            await event.answer("Сообщение уже недоступно.", show_alert=True)
            return
        uid = event.from_user.id
        owners = _owner_ids(event.data)
        if not event.data.startswith(PREFIX):
            owners = _owner_ids((saved or await _edit_record(db, message.chat.id, message.message_id)).data)
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
            if known and saved.target:
                try:
                    await bot.delete_message(message.chat.id, saved.target)
                except (TelegramBadRequest, TelegramNotFound) as error:
                    if "not found" not in str(error).lower():
                        raise
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
