from __future__ import annotations

import html
import re
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from community_bot.keyboards import STYLE_CLOSE, STYLE_FUN, STYLE_GO, ibtn

TEMPLATES: dict[str, dict[str, Any]] = {
    "announce": {
        "title": "📢 Объявление",
        "hint": "Официальный текст. Жирный, курсив и ссылки из сообщения Telegram сохранятся.",
        "wrap": "<b>📢 Объявление сообщества</b>\n<blockquote>{body}</blockquote>\n<i>Nora Community</i>",
    },
    "event": {
        "title": "🎟 Мероприятие",
        "hint": "Дата, место, цена. Форматирование Telegram сохраняется.",
        "wrap": (
            "<b>🎟 Мероприятие</b>\n"
            "<blockquote expandable>{body}</blockquote>\n"
            "🍪 Билеты — в магазине · напишите «магазин»"
        ),
    },
    "shop": {
        "title": "🛒 Витрина",
        "hint": "Акция или полка. Скидка золота и серебра в магазине действует сама.",
        "wrap": "<b>🛒 НОРА · Витрина</b>\n<blockquote>{body}</blockquote>\nОткрыть: /shop или «магазин»",
    },
    "alert": {
        "title": "⚠️ Важно",
        "hint": "Правила, предупреждение или срочное сообщение администрации.",
        "wrap": "<b>⚠️ Важно</b>\n<blockquote>{body}</blockquote>",
    },
    "update": {
        "title": "✨ Обновление",
        "hint": "Короткая новость для чата. Полный список новинок остаётся в админ-панели.",
        "wrap": "<b>✨ Обновление Норы</b>\n<blockquote>{body}</blockquote>",
    },
    "html": {
        "title": "🖋 Свой текст",
        "hint": "Текст как есть: жирный, курсив, ссылки, код. Без рамки шаблона.",
        "raw": True,
    },
}

_STYLE_ALIASES = {
    "green": STYLE_GO,
    "зелёный": STYLE_GO,
    "зеленый": STYLE_GO,
    "success": STYLE_GO,
    "blue": STYLE_FUN,
    "синий": STYLE_FUN,
    "primary": STYLE_FUN,
    "red": STYLE_CLOSE,
    "красный": STYLE_CLOSE,
    "danger": STYLE_CLOSE,
    "gray": None,
    "серый": None,
}


def render_post(template_id: str, body: str) -> str:
    template = TEMPLATES.get(template_id) or TEMPLATES["announce"]
    body = (body or "").strip()
    if template.get("raw"):
        return body
    if not body:
        return str(template["wrap"]).replace("<blockquote>{body}</blockquote>", "").replace(
            "<blockquote expandable>{body}</blockquote>",
            "",
        ).replace("{body}", "")
    return str(template["wrap"]).replace("{body}", body)


def parse_button_lines(raw: str) -> tuple[list[dict[str, str]], str | None]:
    buttons: list[dict[str, str]] = []
    for index, line in enumerate((raw or "").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 2:
            return [], f"Строка {index}: нужен формат «Текст | https://ссылка | green»."
        title, url, *rest = parts
        if not title or not url.startswith(("https://", "http://", "tg://")):
            return [], f"Строка {index}: укажите текст и ссылку http(s) или tg://."
        style_key = (rest[0] if rest else "").casefold()
        if rest and style_key not in _STYLE_ALIASES:
            return [], f"Строка {index}: цвет — green, blue, red или gray."
        style = _STYLE_ALIASES.get(style_key)
        buttons.append({"text": title[:64], "url": url, "style": style or ""})
        if len(buttons) >= 8:
            break
    if not buttons:
        return [], "Нужна хотя бы одна кнопка или напишите «нет»."
    return buttons, None


def parse_poll_options(raw: str) -> tuple[list[str], str | None]:
    options: list[str] = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        options.append(line[:100])
        if len(options) >= 10:
            break
    if len(options) < 2:
        return [], "Нужно от 2 до 10 вариантов, каждый с новой строки."
    return options, None


def buttons_markup(buttons: list[dict[str, str]] | None) -> InlineKeyboardMarkup | None:
    return compose_post_markup(buttons, None)


def compose_post_markup(
    buttons: list[dict[str, str]] | None,
    rsvp_id: str | None = None,
    pay: tuple[str, str] | None = None,
    *,
    rsvp_count: int = 0,
    preview: bool = False,
) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    for item in buttons or []:
        kwargs: dict[str, Any] = {"text": item["text"], "url": item["url"]}
        if item.get("style"):
            kwargs["style"] = item["style"]
        rows.append([InlineKeyboardButton(**kwargs)])
    if rsvp_id:
        action = "post:rsvp:preview" if preview else f"rsvp:{rsvp_id}"
        rows.append([ibtn(f"Я буду ({rsvp_count})", action, STYLE_GO)])
    if pay:
        rows.append([ibtn(pay[0][:64], f"evpay:{pay[1]}", STYLE_GO)])
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def templates_keyboard() -> InlineKeyboardMarkup:
    rows = [[ibtn(str(meta["title"]), f"post:tpl:{key}", STYLE_FUN)] for key, meta in TEMPLATES.items()]
    rows.append([ibtn("Отмена", "post:cancel", STYLE_CLOSE)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def skip_keyboard(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("Пропустить", f"post:skip:{action}", STYLE_FUN)],
            [ibtn("Отмена", "post:cancel", STYLE_CLOSE)],
        ]
    )


def poll_ask_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("📊 Да, голосование", "post:poll:yes", STYLE_GO),
                ibtn("Нет, только пост", "post:poll:no", STYLE_FUN),
            ],
            [ibtn("Отмена", "post:cancel", STYLE_CLOSE)],
        ]
    )


def poll_anonymous_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("🕶 Анонимное", "post:poll:anon:1", STYLE_FUN)],
            [ibtn("👁 Видно, кто голосует", "post:poll:anon:0", STYLE_GO)],
            [ibtn("Отмена", "post:cancel", STYLE_CLOSE)],
        ]
    )


def rsvp_ask_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("Я буду", "post:rsvp:yes", STYLE_GO),
                ibtn("Без RSVP", "post:rsvp:no", STYLE_FUN),
            ],
            [ibtn("Отмена", "post:cancel", STYLE_CLOSE)],
        ]
    )


def pay_ask_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("Да, кнопку оплаты", "post:pay:yes", STYLE_GO),
                ibtn("Нет, без кнопки", "post:pay:no", STYLE_FUN),
            ],
        ]
    )


def event_pay_keyboard(event_id: str, price: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn(f"Оплатить {price} 🍪", f"evpaygo:{event_id}", STYLE_GO)],
            [ibtn("✖️ Закрыть", "ui:close", STYLE_CLOSE)],
        ]
    )


def event_pay_confirm_keyboard(event_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("Да, оплатить", f"evpayyes:{event_id}", STYLE_GO)],
            [ibtn("Отмена", "ui:close", STYLE_CLOSE)],
        ]
    )


def preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("🚀 Опубликовать", "post:send", STYLE_GO)],
            [ibtn("Отмена", "post:cancel", STYLE_CLOSE)],
        ]
    )


def media_from_studio_message(message: Message) -> tuple[str | None, str | None]:
    if message.photo:
        return "photo", message.photo[-1].file_id
    if message.video:
        return "video", message.video.file_id
    if message.animation:
        return "animation", message.animation.file_id
    if message.document:
        return "document", message.document.file_id
    if message.audio:
        return "audio", message.audio.file_id
    if message.voice:
        return "voice", message.voice.file_id
    return None, None


def is_skip_text(text: str | None) -> bool:
    value = (text or "").strip().casefold()
    return value in {"нет", "пропуск", "пропустить", "-", "skip", "none"}


def poll_preview_block(poll: dict[str, Any] | None) -> str:
    if not poll:
        return ""
    options = "\n".join(f"• {html.escape(str(item))}" for item in poll.get("options") or [])
    anonymous = "анонимное" if poll.get("anonymous", True) else "видно, кто голосует"
    question = html.escape(str(poll.get("question") or ""))
    return f"\n\n📊 <b>Голосование</b> ({anonymous})\n<b>{question}</b>\n{options}"


def rsvp_preview_block(rsvp_id: str | None) -> str:
    if not rsvp_id:
        return ""
    return "\n\n🎟 Запись: «Я буду (0)». Список участников виден только администрации."


def post_title(body: str) -> str:
    plain = html.unescape(re.sub(r"<[^>]*>", "", body))
    return next((line.strip()[:100] for line in plain.splitlines() if line.strip()), "Мероприятие")


async def send_studio_post(
    bot: Any,
    chat_id: int,
    html_text: str,
    media_type: str | None,
    file_id: str | None,
    markup: InlineKeyboardMarkup | None,
) -> Any:
    kwargs: dict[str, Any] = {"parse_mode": "HTML", "reply_markup": markup}
    if media_type == "photo" and file_id:
        return await bot.send_photo(chat_id, file_id, caption=html_text[:1024], **kwargs)
    if media_type == "video" and file_id:
        return await bot.send_video(chat_id, file_id, caption=html_text[:1024], **kwargs)
    if media_type == "animation" and file_id:
        return await bot.send_animation(chat_id, file_id, caption=html_text[:1024], **kwargs)
    if media_type == "document" and file_id:
        return await bot.send_document(chat_id, file_id, caption=html_text[:1024], **kwargs)
    if media_type == "audio" and file_id:
        return await bot.send_audio(chat_id, file_id, caption=html_text[:1024], **kwargs)
    if media_type == "voice" and file_id:
        return await bot.send_voice(chat_id, file_id, caption=html_text[:1024], **kwargs)
    return await bot.send_message(chat_id, html_text, **kwargs)


async def send_studio_poll(bot: Any, chat_id: int, poll: dict[str, Any]) -> None:
    await bot.send_poll(
        chat_id,
        question=str(poll["question"])[:300],
        options=[str(item)[:100] for item in poll["options"]],
        is_anonymous=bool(poll.get("anonymous", True)),
    )
