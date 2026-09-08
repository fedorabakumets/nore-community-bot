from __future__ import annotations

import html
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from community_bot.keyboards import STYLE_CLOSE, STYLE_FUN, STYLE_GO, ibtn

TEMPLATES: dict[str, dict[str, Any]] = {
    "announce": {
        "title": "📢 Объявление",
        "hint": "Короткий официальный текст. Заголовок и рамка добавятся сами.",
        "wrap": ("╔══════════════╗\n   📢 <b>ОБЪЯВЛЕНИЕ</b>\n╚══════════════╝\n\n{body}\n\n— <i>Nora Community</i>"),
    },
    "event": {
        "title": "🎟 Мероприятие",
        "hint": "Дата, место, цена. Можно потом добавить кнопки «Билет» и «Магазин».",
        "wrap": ("✦･ﾟ: *✧･ﾟ:*  <b>МЕРОПРИЯТИЕ</b>  *:･ﾟ✧*:･ﾟ✦\n\n{body}\n\n🍪 Билеты — в магазине · напишите «магазин»"),
    },
    "shop": {
        "title": "🛒 Витрина",
        "hint": "Акция, полка, цена в 🍪. Скидка золота/серебра действует автоматически.",
        "wrap": (
            "━━━━━━━━━━━━━━━━\n🛒 <b>НОРА · ВИТРИНА</b>\n━━━━━━━━━━━━━━━━\n\n{body}\n\nОткрыть: /shop или «магазин»"
        ),
    },
    "alert": {
        "title": "⚠️ Важно",
        "hint": "Правила, предупреждение, срочное сообщение администрации.",
        "wrap": ("⚠️ <b>ВАЖНО</b>\n────────────────\n{body}\n────────────────"),
    },
    "update": {
        "title": "✨ Обновление",
        "hint": "Краткая новость для чата. Полный список новинок остаётся в админ-панели.",
        "wrap": ("✨ <b>Обновление Норы</b>\n\n{body}"),
    },
    "html": {
        "title": "🖋 Свой HTML",
        "hint": "Свой текст: &lt;b&gt;, &lt;i&gt;, &lt;u&gt;, &lt;code&gt;, &lt;a href=&quot;...&quot;&gt;.",
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
    return str(template["wrap"]).format(body=html.escape(body))


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


def buttons_markup(buttons: list[dict[str, str]] | None) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    for item in buttons:
        kwargs: dict[str, Any] = {"text": item["text"], "url": item["url"]}
        if item.get("style"):
            kwargs["style"] = item["style"]
        rows.append([InlineKeyboardButton(**kwargs)])
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


async def send_studio_post(
    bot: Any,
    chat_id: int,
    html_text: str,
    media_type: str | None,
    file_id: str | None,
    markup: InlineKeyboardMarkup | None,
) -> None:
    kwargs: dict[str, Any] = {"parse_mode": "HTML", "reply_markup": markup}
    if media_type == "photo" and file_id:
        await bot.send_photo(chat_id, file_id, caption=html_text[:1024], **kwargs)
    elif media_type == "video" and file_id:
        await bot.send_video(chat_id, file_id, caption=html_text[:1024], **kwargs)
    elif media_type == "animation" and file_id:
        await bot.send_animation(chat_id, file_id, caption=html_text[:1024], **kwargs)
    elif media_type == "document" and file_id:
        await bot.send_document(chat_id, file_id, caption=html_text[:1024], **kwargs)
    elif media_type == "audio" and file_id:
        await bot.send_audio(chat_id, file_id, caption=html_text[:1024], **kwargs)
    elif media_type == "voice" and file_id:
        await bot.send_voice(chat_id, file_id, caption=html_text[:1024], **kwargs)
    else:
        await bot.send_message(chat_id, html_text, **kwargs)
