"""Profile-1 Telegram widgets, with ordinary-message fallback on older Bot APIs.

Contract: TelegramMessenger/widget-sandbox docs/tgw-format.md (Bot API 10.4).
Widget methods and their updates use Telegram beta route for regular chats.
"""
from __future__ import annotations

import json
import logging
import re
import time
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from aiogram import BaseMiddleware
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramServerError,
    TelegramUnauthorizedError,
)
from aiogram.methods.base import TelegramMethod
from aiogram.types import InlineKeyboardMarkup, Message, Update

logger = logging.getLogger(__name__)

TEMPLATE = Path(__file__).with_name("widgets") / "number.html"
PICKERS = {"FlexiblePurchase:amount": (1, 1_000_000)}


class WidgetSession(AiohttpSession):
    """One poller, with regular API calls kept on the stable transport."""

    def __init__(self):
        super().__init__()
        self.widget_api = AiohttpSession(api=TelegramAPIServer.from_base("https://api.telegram.org/beta"))
        self.retry_poll_at = 0.0

    async def close(self):
        try:
            await self.widget_api.close()
        finally:
            await super().close()

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109
        name = method.__api_method__
        if name in {"sendWidget", "sendSharedWidget", "answerWidgetQuery", "editSharedWidgetData",
                    "editMessageWidgetData"}:
            return await self.widget_api.make_request(bot, method, timeout)
        if name == "getUpdates" and time.monotonic() >= self.retry_poll_at:
            try:
                return await self.widget_api.make_request(bot, method, timeout)
            except (TelegramNotFound, TelegramUnauthorizedError, TelegramForbiddenError,
                    TelegramServerError, TelegramNetworkError):
                self.retry_poll_at = time.monotonic() + 60
        return await super().make_request(bot, method, timeout)


class SendWidget(TelegramMethod[Message]):
    __returning__ = Message
    __api_method__ = "sendWidget"

    chat_id: int
    html: str
    caption: str
    width: int = 0
    height: int = 0
    allow_queries: bool = False
    is_shared: bool = False
    public_data: str | None = None
    reply_markup: InlineKeyboardMarkup | None = None


class SendNotificationWidget(SendWidget):
    width: int | None = None
    height: int | None = None
    chat_data: str
    disable_notification: bool = False
    parse_mode: str = "HTML"


class EditMessageWidgetData(TelegramMethod[bool]):
    __returning__ = bool
    __api_method__ = "editMessageWidgetData"

    chat_id: int
    message_id: int
    chat_data: str


class SendSharedWidget(TelegramMethod[Message]):
    """Publish an existing shared widget by ID, preserving its live state."""

    __returning__ = Message
    __api_method__ = "sendSharedWidget"

    chat_id: int
    widget_id: str


class AnswerWidgetQuery(TelegramMethod[bool]):
    __returning__ = bool
    __api_method__ = "answerWidgetQuery"

    widget_query_id: str
    data: str


class EditSharedWidgetData(TelegramMethod[bool]):
    __returning__ = bool
    __api_method__ = "editSharedWidgetData"

    widget_id: str
    public_data: str
    cache_time: int = 5


def document(config: dict[str, Any]) -> str:
    # JSON in a script must not be allowed to terminate its enclosing element.
    encoded = json.dumps(config, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    result = TEMPLATE.read_text(encoding="utf-8").replace("/*CONFIG*/{}", encoded)
    raw = result.encode("utf-8")
    if len(raw) > 32768 or len(zlib.compress(raw, 9)) > 4096:
        raise ValueError("Telegram widget exceeds the mini-HTML limits")
    return result


async def try_send(make_request, bot, request: SendWidget) -> Message | None:
    if time.monotonic() < getattr(bot, "_nora_widgets_retry_at", 0):
        return None
    try:
        return await make_request(bot, request)
    except (TelegramNotFound, TelegramUnauthorizedError) as error:
        logger.warning("Telegram widget API unavailable (%s); using chat controls", type(error).__name__)
        bot._nora_widgets_retry_at = time.monotonic() + 600
    except TelegramForbiddenError:
        logger.info("Telegram denied widget delivery for this request; using chat controls")
    except TelegramBadRequest as error:
        detail = str(error).casefold()
        if not any(reason in detail for reason in (
            "method not found", "unknown method", "method is not available", "not supported", "widget",
        )):
            raise
        logger.info("Telegram rejected widget delivery; using chat controls")
        if "widget" not in detail:
            bot._nora_widgets_retry_at = time.monotonic() + 600
    return None


async def picker(make_request, bot, uid, current, footer):
    if current not in PICKERS:
        return None
    low, high = PICKERS[current]
    token = uuid4().hex[:16]
    config = {"title": "Сумма оплаты", "unit": "печенек",
              "value": max(low, min(high, 100)), "min": low, "max": high,
              "step": 50, "presets": [100, 500, 1000],
              "token": token, "submit": "Продолжить",
              "note": "Списание — после отдельного подтверждения"}
    rows = [[{k: b[k] for k in ("text", "callback_data") if k in b}
             for b in block["buttons"] if isinstance(b.get("text"), str) and b.get("callback_data")]
            for block in footer]
    # The caption remains useful when an older client cannot render widgets.
    caption = config["title"] + f" · от {low} до {high}. Можно отправить число в чат."
    result = await try_send(make_request, bot, SendWidget(
        chat_id=uid, html=document(config), caption=caption, allow_queries=True,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[row for row in rows if row]),
    ))
    return (result, {"token": token, "min": low, "max": high}) if result else None


async def transfer_card(message, target, amount, percent, received, markup) -> bool:
    """Display only; the existing inline buttons retain atomic transfer authorization."""
    bot = message.bot
    if time.monotonic() < getattr(bot, "_nora_widgets_retry_at", 0):
        return False
    name = str(target.get("profile_name") or target.get("telegram_name") or target.get("username") or "Участник")
    config = {"title": "Перевод печенек", "unit": "печенек", "value": amount,
              "recipient": name[:64], "received": received, "percent": percent,
              "note": "Проверь сумму и подтверди перевод кнопкой ниже"}
    caption = (f"Перевести {name[:64]} {amount} 🍪? Комиссия {percent}%, "
               f"получателю — {received} 🍪. Подтверди кнопкой ниже.")
    return await try_send(lambda b, m: b(m), bot, SendWidget(
        chat_id=message.chat.id, html=document(config), caption=caption, reply_markup=markup,
    )) is not None


def submission(event, page, current):
    """Validate under the private-panel lock, before existing access/FSM handlers."""
    incoming = getattr(event, "nora_widget", None)
    if not incoming:
        return True
    saved = page.get("widget") or page.get("number_choice") or {}
    return bool(current in PICKERS and current == page.get("flow")
                and event.message_id == page.get("message_id") and event.from_user
                and event.from_user.id == event.chat.id and incoming == saved.get("token")
                and event.text and re.fullmatch(r"[0-9]{1,7}", event.text)
                and saved["min"] <= int(event.text) <= saved["max"])


class WidgetUpdateMiddleware(BaseMiddleware):
    """Bridge aiogram's extra update into the same authenticated message pipeline."""

    async def __call__(self, handler, event: Update, data):
        query = getattr(event, "widget_query", None)
        if hasattr(query, "model_dump"):
            query = query.model_dump(by_alias=True, exclude_none=True)
        if isinstance(query, dict) and data.get("db") is not None:
            from community_bot.widget_notifications import handle_widget_query

            if await handle_widget_query(data["bot"], data["db"], query):
                return
        callback = event.callback_query
        button = callback and (callback.data or "").startswith("nora:")
        if button and isinstance(callback.message, Message):
            query = {"id": callback.id, "from": callback.from_user.model_dump(by_alias=True),
                     "chat": callback.message.chat.model_dump(), "message_id": callback.message.message_id,
                     "data": callback.data}
        if not isinstance(query, dict):
            return await handler(event, data)
        bot = data["bot"]
        match = re.fullmatch(r"nora:([a-f0-9]{16}):([0-9]{1,7})", str(query.get("data", "")))
        chat, sender = query.get("chat") or {}, query.get("from") or {}
        valid = (match and chat.get("type") == "private" and chat.get("id") == sender.get("id")
                 and isinstance(query.get("message_id"), int) and not query.get("inline_message_id"))
        answer = {"ok": False, "message": "Открой актуальный выбор в боте"}
        if valid:
            message = Message.model_validate({
                "message_id": query["message_id"], "date": datetime.now(UTC), "chat": chat, "from": sender,
                "text": match[2], "nora_widget": match[1],
            }, context={"bot": bot})
            outcome = await data["dispatcher"].feed_update(
                bot, Update(update_id=event.update_id, message=message),
                **{k: data[k] for k in ("db", "settings") if k in data},
            )
            if outcome != "nora_widget_rejected":
                answer = {"ok": True, "message": "Готово"}
        if button:
            await callback.answer(answer["message"])
            return
        await bot(AnswerWidgetQuery(widget_query_id=str(query["id"]),
                                    data=json.dumps(answer, ensure_ascii=False)))
