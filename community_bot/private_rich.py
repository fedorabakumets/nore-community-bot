"""A persistent RichMessage surface for all private bot screens.

The request middleware also covers answer/reply shortcuts and background notices.
Handlers keep their authorization and FSM logic; only presentation is centralized.
"""
from __future__ import annotations

import asyncio
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from uuid import uuid4
from weakref import WeakValueDictionary

from aiogram import BaseMiddleware
from aiogram.client.default import Default
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import CopyMessage, DeleteMessage, EditMessageText, SendRichMessage
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardMarkup,
    InputFile,
    InputMediaVoiceNote,
    InputRichBlockButtons,
    InputRichMessage,
    Message,
    MessageId,
    RichMessageButton,
)
from aiogram.utils.text_decorations import html_decoration

from community_bot.commands_guide import CLOSE_COMMANDS_CARD
from community_bot.inline_style import button_style

_MEDIA = {
    "photo": "photo", "video": "video", "animation": "animation", "audio": "audio",
    "document": "document", "voice": "voice_note",
}
_SEND = {"sendMessage", "sendRichMessage", "sendSticker", "sendPoll", *(
    "send" + kind.title() for kind in _MEDIA
)}
_EDIT = {"editMessageText", "editMessageCaption", "editMessageMedia", "editMessageReplyMarkup"}
_MISSING = ("message to edit not found", "message_id_invalid")
_LOCKS: WeakValueDictionary[tuple[int, int], asyncio.Lock] = WeakValueDictionary()
_EVENT_LOCKS: WeakValueDictionary[tuple[int, int], asyncio.Lock] = WeakValueDictionary()


def _lock(locks, bot, uid):
    key = (bot.id, uid)
    lock = locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        locks[key] = lock
    return lock


@dataclass
class Turn:
    source: Message
    state: object = None
    sent: set[int] = field(default_factory=set)
    screen: str = field(default_factory=lambda: uuid4().hex)
    task: object = field(default_factory=asyncio.current_task)
    active: bool = True
    reopen: bool = False
    action: str = ""

    @property
    def is_handler(self):
        return self.active and self.task is asyncio.current_task()


_TURN: ContextVar[Turn | None] = ContextVar("private_rich_turn", default=None)
_STANDALONE: ContextVar[bool] = ContextVar("standalone_rich_message", default=False)


@contextmanager
def standalone_rich_message():
    """Send a Rich message separately from the persistent private panel."""
    token = _STANDALONE.set(True)
    try:
        yield
    finally:
        _STANDALONE.reset(token)


def reopen_private_panel():
    """Explicit /start must restore visibility even after a local chat deletion."""
    turn = _TURN.get()
    if turn and turn.is_handler:
        turn.reopen = True


class RichHTML(HTMLParser):
    """Convert existing Telegram HTML to RichText, preserving escaped user input."""

    TYPES = {"b": "bold", "strong": "bold", "i": "italic", "em": "italic", "u": "underline",
             "ins": "underline", "s": "strikethrough", "strike": "strikethrough", "del": "strikethrough",
             "code": "code", "tg-spoiler": "spoiler", "mark": "marked", "sub": "subscript", "sup": "superscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = [("root", {}, [])]

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.handle_data("\n")
        else:
            self.stack.append((tag, dict(attrs), []))

    def handle_endtag(self, tag):
        if len(self.stack) == 1:
            return
        name, attrs, parts = self.stack.pop()
        text = parts[0] if len(parts) == 1 else parts
        kind = self.TYPES.get(name)
        if name == "span" and "tg-spoiler" in (attrs.get("class") or ""):
            kind = "spoiler"
        if kind:
            value = {"type": kind, "text": text}
        elif name == "a":
            value = {"type": "url", "text": text, "url": attrs.get("href", "")}
        elif name == "tg-emoji":
            value = {"type": "custom_emoji", "alternative_text": "".join(str(part) for part in parts),
                     "custom_emoji_id": attrs.get("emoji-id", "")}
        elif name == "tg-time":
            value = {"type": "date_time", "unix_time": int(attrs["unix"]),
                     "date_time_format": attrs.get("format", "wDT"),
                     "text": text}
        elif name in {"blockquote", "pre"}:
            # These become separate blocks in blocks(), including expandable quotations.
            value = {"_block": "expandable_blockquote" if "expandable" in attrs else name, "text": text}
        else:
            value = text
        self.stack[-1][2].append(value)

    def handle_data(self, data):
        self.stack[-1][2].append(data)

    def blocks(self):
        while len(self.stack) > 1:
            self.handle_endtag(self.stack[-1][0])
        result, paragraph = [], []

        def flush():
            if paragraph:
                result.append({"type": "paragraph", "text": paragraph.copy()})
                paragraph.clear()

        for part in self.stack[0][2]:
            if isinstance(part, dict) and "_block" in part:
                flush()
                kind = part["_block"]
                if kind in {"pre", "expandable_blockquote"}:
                    result.append({"type": kind, "text": part["text"]})
                else:
                    result.append({"type": kind, "blocks": [{"type": "paragraph", "text": part["text"]}]})
            else:
                paragraph.append(part)
        flush()
        return result


def text_blocks(text, parse_mode=None, entities=None):
    if not text:
        return []
    if entities:
        text, parse_mode = html_decoration.unparse(text, entities), "HTML"
    if not re.search(r"<(pre|code)\b", text, re.I):
        text = re.sub(r"(?m)^[ \t]*[━─═✦✧·•\-_=]{3,}[ \t]*\n?", "", text)
        text = re.sub(r"\n[ \t]*\n+", "\n", text).strip()
    if str(parse_mode).upper() == "HTML":
        parser = RichHTML()
        parser.feed(text)
        return parser.blocks()
    return [{"type": "paragraph", "text": text}]


def button_rows(markup):
    if not isinstance(markup, InlineKeyboardMarkup):
        return []
    result = []
    for row in markup.inline_keyboard:
        buttons = []
        for button in row:
            fields = button.model_dump(exclude_none=True, include=set(RichMessageButton.model_fields))
            style = button_style(button) if button.callback_data else button.style
            fields["style"] = ((style if style in {"success", "danger"} else "link")
                               if button.callback_data else (style or "primary"))
            if button.callback_data and (button.text.startswith(("↩", "←")) or "назад" in button.text.casefold()):
                fields.update(text="← Назад", style="link")
            if button.icon_custom_emoji_id:
                fields["text"] = [{"type": "custom_emoji", "alternative_text": "▫️",
                                   "custom_emoji_id": button.icon_custom_emoji_id}, " " + button.text]
            buttons.append(RichMessageButton(**fields))
        for offset in range(0, len(buttons), 8):
            result.append(InputRichBlockButtons(buttons=buttons[offset:offset + 8]).model_dump(exclude_none=True))
    return result


def _plain_buttons(buttons):
    return {button.get("callback_data") for block in buttons if block.get("type") == "buttons"
            for button in block["buttons"]}


async def navigation(bot, uid, body, current, previous_back=None):
    from community_bot.access import private_allowed

    db, settings = bot.community_db, bot.community_settings
    turn = _TURN.get()
    route = turn.action if turn and turn.is_handler else ""
    actions = _plain_buttons(body)
    home = {"menu:profile", "menu:wallet", "menu:pet"} <= actions
    seen, backs = set(), []
    for block in body:
        if block.get("type") != "buttons":
            continue
        kept = []
        for button in block["buttons"]:
            action, text = button.get("callback_data"), button.get("text", "")
            identity = json.dumps({k: v for k, v in button.items() if k not in {"text", "style"}}, sort_keys=True)
            if identity in seen or action in {"ui:close", "shop:close"}:
                continue
            seen.add(identity)
            if action == route and action and (action.startswith("menu:") or action in {"wallet:home", "shop:home"}):
                continue
            if action == "menu:home" or (isinstance(text, str)
                                         and (text.startswith(("↩", "←")) or "назад" in text.casefold())):
                backs.append(button)
            elif action == "flow:cancel":
                backs.append(button)
            else:
                kept.append(button)
        block["buttons"] = kept
    body[:] = [block for block in body if block.get("type") != "buttons" or block["buttons"]]
    packed = []
    for block in body:
        if (block.get("type") == "buttons" and packed and packed[-1].get("type") == "buttons"
                and all(b.get("style") == "link" and isinstance(b.get("text"), str)
                        and len(b["text"]) <= 24 for b in packed[-1]["buttons"] + block["buttons"])
                and len(packed[-1]["buttons"]) + len(block["buttons"]) <= 3):
            packed[-1]["buttons"].extend(block["buttons"])
        else:
            packed.append(block)
    body[:] = packed
    actions = _plain_buttons(body)
    rows = []
    if current:
        row = []
        if current.startswith("ApplicationForm:") and "flow:restart" not in actions:
            row.append(RichMessageButton(text="Начать заново", callback_data="flow:restart", style="link"))
        parents = {"ProfileEdit": "menu:profile", "PetFlow": "menu:pet", "GiftFlow": "menu:shop",
                   "FlexiblePurchase": "menu:shop", "CookiePurchase": "menu:shop",
                   "ShopAdminFlow": "menu:admin", "AdminFlow": "menu:admin"}
        parent = parents.get(current.split(":", 1)[0], "flow:cancel")
        row.append(RichMessageButton(text="← Назад", callback_data=parent, style="link"))
        if row:
            rows.append(row)
        return [InputRichBlockButtons(buttons=row).model_dump(exclude_none=True) for row in rows]
    if await private_allowed(db, settings, uid):
        if home:
            return []
        back = next((b for b in backs if b.get("callback_data") != "menu:home"), None)
        back = back or (backs[0] if backs else {"callback_data": previous_back or "menu:home"})
        rows.append([RichMessageButton(text="← Назад", callback_data=back["callback_data"], style="link")])
        choices = []
    else:
        choices = [[("🎫 Помощь", "menu:question")]]
        if not await db.has_pending_application(uid) and not current:
            choices.insert(0, [("📝 Заполнить анкету", "start:apply")])
    for row in choices:
        buttons = [RichMessageButton(text=text, callback_data=action,
                                     style="success" if action == "start:apply" else "link")
                   for text, action in row if action not in actions]
        if buttons:
            rows.append(buttons)
    return [InputRichBlockButtons(buttons=row).model_dump(exclude_none=True) for row in rows]


def _mode(method, bot):
    mode = getattr(method, "parse_mode", None)
    return bot.default.parse_mode if isinstance(mode, Default) else mode


def _content(method, bot):
    rich = getattr(method, "rich_message", None)
    if rich:
        if rich.blocks is not None:
            return [block.model_dump(exclude_none=True, warnings=False) for block in rich.blocks]
        # Existing application Rich messages use blocks; preserve HTML when supplied by future callers.
        if rich.html is not None:
            return text_blocks(rich.html, "HTML")
        return text_blocks(rich.markdown)
    media = getattr(method, "media", None)
    source = media if media is not None else method
    blocks = []
    for key, kind in _MEDIA.items():
        file = getattr(method, key, None) if media is None else (media.media if media.type == kind else None)
        if file is not None:
            fields = {"type": key if key != "voice" else "voice_note", "media": file}
            for prop in ("duration", "width", "height", "performer", "title", "has_spoiler"):
                value = getattr(source, prop, None)
                if value is not None:
                    fields[prop] = value
            # Bot API accepts attach:// for voice notes, while aiogram types this field as str only.
            payload = (InputMediaVoiceNote.model_construct(**fields)
                       if kind == "voice_note" and isinstance(file, InputFile) else fields)
            blocks.append({"type": kind, kind: payload})
            break
    text = getattr(source, "text", None) or getattr(source, "caption", None)
    entities = getattr(source, "entities", None) or getattr(source, "caption_entities", None)
    blocks.extend(text_blocks(text, _mode(source, bot), entities))
    if method.__api_method__ == "sendSticker":
        blocks.append({"type": "paragraph", "text": "✨ Стикеры Норы"})
        blocks.extend(button_rows(InlineKeyboardMarkup(inline_keyboard=[[{
            "text": "Открыть стикеры", "url": "https://t.me/addstickers/vstickere",
        }]])))
    if method.__api_method__ == "sendPoll":
        blocks.append({"type": "paragraph", "text": method.question})
        blocks.extend({"type": "paragraph", "text": "○ " + option.text} for option in method.options)
    return blocks


def _reusable(blocks):
    """Convert returned RichBlock media into reusable InputRichBlock file IDs."""
    result = []
    for original in blocks:
        block = dict(original)
        kind = block.get("type")
        if kind in _MEDIA.values():
            output = block.get(kind)
            if isinstance(output, list):
                output = output[-1]
            if isinstance(output, dict) and "file_id" in output:
                block[kind] = {"type": kind, "media": output["file_id"]}
        if "blocks" in block:
            block["blocks"] = _reusable(block["blocks"])
        result.append(block)
    return result


def _message(bot, uid, message_id):
    return Message(message_id=message_id, date=datetime.now(UTC), chat=Chat(id=uid, type="private")).as_(bot)


def _uploaded_media(result, method):
    """Keep upload consumers compatible with Message.photo/video/etc. without a second send."""
    rich = getattr(result, "rich_message", None)
    if not rich:
        return result
    for key, kind in _MEDIA.items():
        if getattr(method, key, None) is None:
            continue
        block = next((block for block in reversed(rich.blocks) if block.type == kind), None)
        if block:
            return result.model_copy(update={key: getattr(block, kind),
                                              "caption": getattr(method, "caption", None),
                                              "caption_entities": getattr(method, "caption_entities", None)})
    return result


class PrivateRichContextMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        source = event.message if isinstance(event, CallbackQuery) else event
        if not isinstance(source, Message) or source.chat.type != "private":
            return await handler(event, data)
        bot, uid = data["bot"], source.chat.id
        async with _lock(_EVENT_LOCKS, bot, uid):
            if isinstance(event, Message) and getattr(event, "nora_widget", None):
                from community_bot.message_widgets import submission

                raw = await data["db"].get_bot_state(f"private_rich_panel:{uid}")
                current = await data["state"].get_state()
                if not submission(event, json.loads(raw) if raw else {}, current):
                    return "nora_widget_rejected"
            if isinstance(event, CallbackQuery) and event.data != CLOSE_COMMANDS_CARD and source.message_id > 0:
                saved = await data["db"].get_bot_state(f"private_rich_panel:{uid}")
                if saved and json.loads(saved)["message_id"] != source.message_id:
                    await event.answer(
                        "Это старое меню. Открой актуальное сообщение или отправь /start.", show_alert=True,
                    )
                    return
            action = (event.data or "") if isinstance(event, CallbackQuery) else ""
            context = Turn(source, data.get("state"), action=action)
            token = _TURN.set(context)
            try:
                return await handler(event, data)
            finally:
                context.active = False
                _TURN.reset(token)


class PrivateRichMiddleware(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        uid, name = getattr(method, "chat_id", None), method.__api_method__
        if not isinstance(uid, int) or uid <= 0 or not getattr(bot, "community_db", None):
            return await make_request(bot, method)
        if name == "sendRichMessage" and _STANDALONE.get():
            return await make_request(bot, method)
        if name not in _SEND | _EDIT | {"copyMessage", "deleteMessage"}:
            return await make_request(bot, method)
        async with _lock(_LOCKS, bot, uid):
            return await self.render(make_request, bot, method, uid, name)

    async def render(self, make_request, bot, method, uid, name):
        db, turn = bot.community_db, _TURN.get()
        key = f"private_rich_panel:{uid}"
        raw = await db.get_bot_state(key)
        page = json.loads(raw) if raw else {}
        message_id = page.get("message_id")
        personal_turn = turn and turn.is_handler and turn.source.chat.id == uid
        current = (await turn.state.get_state()
                   if personal_turn and turn.state and turn.source.message_id > 0 else page.get("flow"))
        if name == "deleteMessage":
            if method.message_id == message_id:
                return True  # Private close actions must keep the navigation surface.
            return await make_request(bot, method)
        if (page.get("widget") or page.get("number_choice")) and not personal_turn:
            # A background notice must leave the active number picker usable.
            if name in _EDIT:
                return _message(bot, uid, message_id)
            return await make_request(bot, method)
        if name in _EDIT and message_id and method.message_id != message_id:
            # Delayed game updates must not replace a newer personal screen.
            return _message(bot, uid, message_id)
        if name in _EDIT and turn and not turn.is_handler and page.get("screen") != turn.screen:
            return _message(bot, uid, message_id)
        if name == "editMessageReplyMarkup" and turn and uid in turn.sent and method.reply_markup is None:
            # Invitation handlers clean up the old buttons after sending their next screen.
            return _message(bot, uid, message_id)
        original = method
        if name == "copyMessage":
            source = turn.source if turn else None
            if not source or (method.from_chat_id, method.message_id) != (source.chat.id, source.message_id):
                raise TelegramBadRequest(method=method, message="Source message is unavailable for Rich rendering")
            from community_bot.helpers import media_from_message

            kind, file_id = media_from_message(source)
            blocks = text_blocks(method.caption if method.caption is not None else source.text or source.caption,
                                 _mode(method, bot) if method.caption is not None else None,
                                 method.caption_entities if method.caption is not None else
                                 source.entities or source.caption_entities)
            if kind:
                rich_kind = _MEDIA[kind]
                blocks.insert(0, {"type": rich_kind, rich_kind: {"type": rich_kind, "media": file_id}})
        else:
            blocks = _content(method, bot)
        markup = getattr(method, "reply_markup", None)
        buttons = button_rows(markup)
        if name == "editMessageReplyMarkup":
            blocks = [block for block in page.get("body", []) if block["type"] != "buttons"]
        elif name == "editMessageCaption":
            blocks = [block for block in page.get("body", []) if block["type"] in _MEDIA.values()] + blocks
        append = bool(turn and turn.is_handler and uid in turn.sent)
        # Background notices must not hide the question the user is currently answering.
        append |= bool(current and not personal_turn)
        if name in _SEND | {"copyMessage"} and append:
            # A handler may send a cover, its long body and a keyboard separately.
            # Keep them together, including ticket headers and their copied attachments.
            blocks = page.get("body", []) + blocks
        body = blocks + buttons
        footer = await navigation(bot, uid, body, current, page.get("back") if append or not personal_turn else None)
        widget = None
        from community_bot.message_widgets import PICKERS, picker

        if personal_turn and name in _SEND | _EDIT:
            widget = await picker(make_request, bot, uid, current, footer)
        # Telegram cannot edit a text/Rich message into a widget or vice versa.
        # Send the replacement first so a failed send keeps the old screen usable.
        if widget:
            result, widget_meta = widget
            screen = turn.screen if turn else uuid4().hex
            await db.set_bot_state(key, json.dumps({
                "version": 2, "message_id": result.message_id, "body": body,
                "flow": current, "screen": screen, "widget": widget_meta,
            }, ensure_ascii=False))
            turn.sent.add(uid)
            if message_id:
                await self.remove_old(make_request, bot, uid, message_id)
            return result
        number_choice = None
        if personal_turn and current in PICKERS and name in _SEND | _EDIT:
            low, high = PICKERS[current]
            token = turn.screen[:16]
            number_choice = {"token": token, "min": low, "max": high}
            presets = (16, 18, 21, 25) if current.endswith(":age") else (100, 500, 1000)
            body.append({"type": "buttons", "buttons": [
                {"text": str(value), "callback_data": f"nora:{token}:{value}", "style": "link"}
                for value in presets
            ]})
        rich = InputRichMessage(blocks=body + footer)
        old_widget_id = message_id if page.get("widget") else None
        if old_widget_id:
            message_id = None
        if personal_turn and turn.reopen and uid not in turn.sent:
            if message_id:
                try:
                    await make_request(bot, DeleteMessage(chat_id=uid, message_id=message_id))
                except TelegramBadRequest as error:
                    detail = str(error).casefold()
                    if not any(reason in detail for reason in (
                        "message to delete not found", "message can't be deleted", "message_id_invalid",
                    )):
                        raise
            # Telegram may accept edits after the user deleted the chat only locally.
            # A fresh send is the only reliable way to make /start visible again.
            message_id = None
        if message_id:
            request = EditMessageText(chat_id=uid, message_id=message_id, rich_message=rich,
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
        else:
            request = SendRichMessage(chat_id=uid, rich_message=rich,
                                      message_thread_id=getattr(original, "message_thread_id", None),
                                      disable_notification=getattr(original, "disable_notification", None),
                                      protect_content=getattr(original, "protect_content", None))
        try:
            result = await make_request(bot, request)
        except TelegramBadRequest as error:
            detail = str(error).casefold()
            if message_id and "message is not modified" in detail:
                if turn and turn.is_handler:
                    turn.sent.add(uid)
                result = _message(bot, uid, message_id)
                return MessageId(message_id=message_id) if isinstance(original, CopyMessage) else result
            elif message_id and (any(reason in detail for reason in _MISSING)
                                 or "message can't be edited" in detail and page.get("version") != 2):
                if "message can't be edited" in detail:
                    # Repair the old ReplyKeyboardRemove panel once. Delete it first:
                    # if deletion fails, do not leave another message in the dialog.
                    await make_request(bot, DeleteMessage(chat_id=uid, message_id=message_id))
                result = await make_request(bot, SendRichMessage(
                    chat_id=uid, rich_message=rich,
                    message_thread_id=getattr(original, "message_thread_id", None),
                ))
            else:
                raise  # Never turn transient/API/format errors into duplicate messages.
        # Telegram returns uploaded media as file IDs; persist those rather than local files.
        returned = getattr(result, "rich_message", None)
        if returned:
            reusable = _reusable(returned.model_dump(exclude_none=True)["blocks"])
            body = reusable[:-len(footer)] if footer else reusable
        screen = turn.screen if turn else uuid4().hex
        await db.set_bot_state(key, json.dumps({"version": 2, "message_id": result.message_id, "body": body,
                                              "back": next((b.get("callback_data") for block in footer
                                                            for b in block["buttons"]
                                                            if b.get("text") == "← Назад"), None),
                                              "screen": screen, "flow": current, "number_choice": number_choice},
                                              ensure_ascii=False))
        if turn and turn.is_handler:
            turn.sent.add(uid)
        if old_widget_id:
            await self.remove_old(make_request, bot, uid, old_widget_id)
        return (MessageId(message_id=result.message_id) if isinstance(original, CopyMessage)
                else _uploaded_media(result, original))

    @staticmethod
    async def remove_old(make_request, bot, uid, message_id):
        try:
            await make_request(bot, DeleteMessage(chat_id=uid, message_id=message_id))
        except TelegramBadRequest as error:
            if not any(reason in str(error).casefold() for reason in (
                "message to delete not found", "message can't be deleted", "message_id_invalid",
            )):
                raise
