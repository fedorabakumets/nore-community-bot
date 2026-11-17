"""Render replies as Rich Messages while preserving their Telegram actions."""
from __future__ import annotations

import logging
from asyncio import Lock
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from weakref import WeakValueDictionary

from aiogram import BaseMiddleware
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramBadRequest, TelegramNotFound
from aiogram.methods import EditMessageText, SendRichMessage
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InputRichMessage, Message, ReplyParameters

from community_bot.aliases import message_trigger
from community_bot.nora_links import nora_link_block, profile_reply
from community_bot.private_rich import _content, _mode, _reusable, _uploaded_media, button_rows

logger = logging.getLogger(__name__)
_SEND = {"sendMessage", "sendPhoto", "sendVideo", "sendAnimation", "sendAudio", "sendDocument", "sendVoice"}
_EDIT = {"editMessageText", "editMessageCaption", "editMessageMedia", "editMessageReplyMarkup"}
_MEDIA_BLOCKS = {"photo", "video", "animation", "audio", "document", "voice_note"}
_CACHE_LIMIT = 256


@dataclass
class ReplyContext:
    message: Message
    action: str
    callback: bool
    private_recipient: int | None = None
    active: bool = True


_CONTEXT: ContextVar[ReplyContext | None] = ContextVar("rich_reply_context", default=None)
_PUBLICATION: ContextVar[bool] = ContextVar("rich_reply_publication", default=False)


@contextmanager
def bot_publication():
    """Leave posts and their pinning/refresh flows in their authored format."""
    token = _PUBLICATION.set(True)
    try:
        yield
    finally:
        _PUBLICATION.reset(token)


class ReplyRichContextMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        callback = isinstance(event, CallbackQuery)
        source = event.message if callback else event
        if not isinstance(source, Message) or source.chat.type == "channel" or source.pinned_message:
            return await handler(event, data)
        if callback:
            action = event.data or ""
        else:
            trigger = message_trigger(source)
            action = trigger[0] if trigger else ""
        recipient = source.from_user.id if source.from_user and not callback and action in {"id", "admin"} else None
        context = ReplyContext(source, action, callback, recipient)
        token = _CONTEXT.set(context)
        try:
            return await handler(event, data)
        finally:
            context.active = False
            _CONTEXT.reset(token)


def split_buttons(markup):
    if not isinstance(markup, InlineKeyboardMarkup):
        return [], markup, set()
    supported, native = [], []
    for row in markup.inline_keyboard:
        rich_row, native_row = [], []
        for button in row:
            legacy_only = (button.pay or button.callback_game is not None
                           or getattr(button.login_url, "bot_username", None))
            (native_row if legacy_only else rich_row).append(button)
        if rich_row:
            supported.append(rich_row)
        if native_row:
            native.append(native_row)
    rich = InlineKeyboardMarkup(inline_keyboard=supported)
    remaining = InlineKeyboardMarkup(inline_keyboard=native) if native else None
    actions = {button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data}
    return button_rows(rich, private=False), remaining, actions


def _method_fields(method, target):
    return {name: getattr(method, name) for name in target.model_fields if hasattr(method, name)}


def _reply_parameters(method):
    if method.reply_parameters is not None or not getattr(method, "reply_to_message_id", None):
        return method.reply_parameters
    return ReplyParameters(message_id=method.reply_to_message_id,
                           allow_sending_without_reply=method.allow_sending_without_reply)


@dataclass
class ReplyPage:
    blocks: list[dict]
    action: str


class ReplyRichMiddleware(BaseRequestMiddleware):
    def __init__(self):
        self.pages: OrderedDict[tuple[int, int], ReplyPage] = OrderedDict()
        self.edit_locks: WeakValueDictionary[tuple[int, int], Lock] = WeakValueDictionary()

    async def __call__(self, make_request, bot, method):
        name = method.__api_method__
        chat_id = getattr(method, "chat_id", None)
        if _PUBLICATION.get() or not isinstance(chat_id, int) or not chat_id:
            return await make_request(bot, method)
        context = _CONTEXT.get()
        if context and (not context.active or chat_id not in (context.message.chat.id, context.private_recipient)):
            context = None
        action = context.action if context else ""
        markup = getattr(method, "reply_markup", None)
        if name in _SEND and (context or _reply_parameters(method)):
            return await self.send(make_request, bot, method, action, markup)
        if name in _EDIT and getattr(method, "rich_message", None) is None:
            key = (chat_id, method.message_id)
            source = context.message if context and context.callback and context.message.message_id == key[1] else None
            incoming = (source.rich_message
                        if source and chat_id < 0 and not action.startswith(("rsvp:", "evpay:")) else None)
            if key in self.pages or incoming:
                lock = self.edit_locks.get(key)
                if lock is None:
                    lock = Lock()
                    self.edit_locks[key] = lock
                async with lock:
                    page = self.pages.get(key)
                    if page is None and incoming:
                        page = ReplyPage(_reusable(incoming.model_dump(exclude_none=True)["blocks"]), action)
                    if page:
                        return await self.edit(make_request, bot, method, page, action, markup)
        result = await make_request(bot, method)
        if name == "deleteMessage":
            self.pages.pop((chat_id, method.message_id), None)
        return result

    async def send(self, make_request, bot, method, action, markup):
        if (getattr(method, "callback_query_id", None) or getattr(method, "receiver_user_id", None)
                or (not getattr(method, "entities", None) and not getattr(method, "caption_entities", None)
                    and str(_mode(method, bot)).upper().startswith("MARKDOWN"))):
            return await make_request(bot, method)
        buttons, native, actions = split_buttons(markup)
        if profile_reply(action, actions) or any(cb.startswith(("rsvp:", "evpay:")) for cb in actions):
            return await make_request(bot, method)
        blocks = _content(method, bot, compact=False)
        rich = await _build(bot, blocks, action, buttons, actions, method)
        fields = _method_fields(method, SendRichMessage)
        fields.update(rich_message=rich, reply_markup=native, reply_parameters=_reply_parameters(method))
        try:
            result = await make_request(bot, SendRichMessage(**fields))
        except (TelegramBadRequest, TelegramNotFound):
            # These are definitive API rejections. Transport failures may have delivered the message.
            logger.warning("Telegram отклонил Rich-ответ (%s), отправляем в исходном формате", method.__api_method__)
            return await make_request(bot, method)
        self.remember(result, action)
        return _uploaded_media(result, method)

    async def edit(self, make_request, bot, method, page, action, markup):
        name = method.__api_method__
        # Keep intent through timer updates and keyboard removal, where no new destination was requested.
        action = page.action if not action or name == "editMessageReplyMarkup" else action
        buttons, native, actions = split_buttons(markup)
        if name == "editMessageReplyMarkup":
            blocks = [block for block in page.blocks if block["type"] != "buttons"]
        else:
            blocks = _content(method, bot, compact=False)
            if name == "editMessageCaption":
                blocks = [block for block in page.blocks if block["type"] in _MEDIA_BLOCKS] + blocks
        rich = await _build(bot, blocks, action, buttons, actions, method)
        fields = _method_fields(method, EditMessageText)
        fields.update(text=None, parse_mode=None, entities=None, link_preview_options=None,
                      disable_web_page_preview=None, rich_message=rich,
                      reply_markup=native or InlineKeyboardMarkup(inline_keyboard=[]))
        result = await make_request(bot, EditMessageText(**fields))
        self.remember(result, action)
        return result

    def remember(self, message, action):
        if not isinstance(message, Message) or not message.rich_message:
            return
        key = (message.chat.id, message.message_id)
        self.pages[key] = ReplyPage(_reusable(message.rich_message.model_dump(exclude_none=True)["blocks"]), action)
        self.pages.move_to_end(key)
        if len(self.pages) > _CACHE_LIMIT:
            self.pages.popitem(last=False)


async def _build(bot, blocks, action, buttons, actions, method):
    media = getattr(method, "media", None)
    text = getattr(method, "text", None) or getattr(media or method, "caption", None) or ""
    has_app = any(button.get("web_app") for row in buttons for button in row["buttons"])
    link = None if has_app or profile_reply(action, actions) else await nora_link_block(bot, action, actions, text)
    return InputRichMessage(blocks=[*blocks, *buttons, *([link] if link else [])])
