from __future__ import annotations

from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup, Message

from community_bot.ephemeral import keep_in_chat
from community_bot.keyboards import STYLE_CLOSE, STYLE_FUN, STYLE_GO, back_btn, ibtn

DEFAULT_PRIZE = 50
MAX_PRIZE = 100_000
MAX_EXTRA = 1500
CAPTION_LIMIT = 1000

CONTEST_TEMPLATE = """🍪 <b>Конкурс на печеньки</b>

Разыгрываем <b>{prize}</b> 🍪.

Нажмите кнопку под постом — один человек, одна заявка.
Участники ничего не платят. Победителя выберет администрация."""


def contest_text(prize: int, extra: str = "") -> str:
    body = CONTEST_TEMPLATE.format(prize=max(1, int(prize)))
    extra = (extra or "").strip()
    if extra:
        return f"{body}\n\n{extra}"
    return body


def contest_join_keyboard(contest_id: int, count: int = 0) -> InlineKeyboardMarkup:
    label = "Участвовать" if count <= 0 else f"Участвуете ({count})"
    return InlineKeyboardMarkup(inline_keyboard=[[ibtn(label, f"contest:join:{contest_id}", STYLE_GO)]])


def contest_home_keyboard(*, has_open: bool) -> InlineKeyboardMarkup:
    rows = [[ibtn("📝 Новый конкурс", "admin:contest:new", STYLE_GO)]]
    if has_open:
        rows.append([ibtn("🏆 Подвести итог", "admin:contest:draw", STYLE_FUN)])
        rows.append([ibtn("👥 Участники", "admin:contest:list")])
        rows.append([ibtn("✖️ Снять конкурс", "admin:contest:cancel", STYLE_CLOSE)])
    rows.append([ibtn("Сезон 1 · Багровый Страж Норы", "admin:season:home")])
    rows.append([back_btn("admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def contest_skip_text_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("Без доп. текста", "admin:contest:text:skip")],
            [ibtn("Отмена", "admin:contest:home", STYLE_CLOSE)],
        ]
    )


def contest_skip_media_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("Без медиа", "admin:contest:media:skip")],
            [ibtn("Отмена", "admin:contest:home", STYLE_CLOSE)],
        ]
    )


def contest_prize_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn(f"Приз {DEFAULT_PRIZE} 🍪", "admin:contest:prize:default", STYLE_GO)],
            [ibtn("Отмена", "admin:contest:home", STYLE_CLOSE)],
        ]
    )


def contest_preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("📣 Опубликовать в чат", "admin:contest:publish", STYLE_GO)],
            [ibtn("Отмена", "admin:contest:home", STYLE_CLOSE)],
        ]
    )


def contest_home_text(open_contest: dict[str, Any] | None, count: int = 0) -> str:
    lines = [
        "🍪 <b>Конкурс на печеньки</b>",
        "",
        "Отдельный пост в сообщество с кнопкой «Участвовать».",
        "Это не розыгрыш-котёл: никто не платит взнос.",
        "",
        "<b>Как устроить</b>",
        "1. «Новый конкурс» — подставится базовый шаблон с призом.",
        "2. Допишите свой текст или нажмите «Без доп. текста».",
        "3. При желании пришлите фото, видео или кружок — либо «Без медиа».",
        "4. Укажите приз в печеньках (сколько получит победитель).",
        "5. Проверьте превью и опубликуйте в чат.",
        "6. В посте кнопка «Участвовать». После первого нажатия она станет «Участвуете (N)».",
        "7. Когда пора — «Подвести итог»: случайный участник получит приз.",
        "",
    ]
    if open_contest:
        lines.append(
            f"Сейчас открыт конкурс №{open_contest['id']}: "
            f"приз <b>{int(open_contest['prize'])}</b> 🍪 · участников <b>{count}</b>."
        )
    else:
        lines.append("Открытого конкурса нет. Можно запускать новый.")
    return "\n".join(lines)


def contest_preview_text(prize: int, extra: str, has_media: bool) -> str:
    media = "есть" if has_media else "нет"
    return (
        "👀 <b>Превью конкурса</b>\n"
        f"Приз: <b>{prize}</b> 🍪 · медиа: {media}\n\n"
        f"{contest_text(prize, extra)}\n\n"
        "В чате под этим текстом будет кнопка «Участвовать»."
    )


async def publish_contest_post(
    bot: Bot,
    chat_id: int,
    contest_id: int,
    text: str,
    media_type: str | None,
    media_file_id: str | None,
) -> Message | None:
    keyboard = contest_join_keyboard(contest_id, 0)
    with keep_in_chat():
        try:
            if media_type and media_file_id and len(text) <= CAPTION_LIMIT:
                return await _send_media(
                    bot,
                    chat_id,
                    media_type,
                    media_file_id,
                    caption=text,
                    reply_markup=keyboard,
                )
            if media_type and media_file_id:
                await _send_media(bot, chat_id, media_type, media_file_id, caption=None, reply_markup=None)
            return await bot.send_message(
                chat_id,
                text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            return None


async def _send_media(
    bot: Bot,
    chat_id: int,
    media_type: str,
    file_id: str,
    *,
    caption: str | None,
    reply_markup: InlineKeyboardMarkup | None,
) -> Message:
    kwargs: dict[str, Any] = {"reply_markup": reply_markup}
    if caption:
        kwargs["caption"] = caption
        kwargs["parse_mode"] = "HTML"
    if media_type == "photo":
        return await bot.send_photo(chat_id, file_id, **kwargs)
    if media_type == "video":
        return await bot.send_video(chat_id, file_id, **kwargs)
    if media_type == "animation":
        return await bot.send_animation(chat_id, file_id, **kwargs)
    if media_type == "document":
        return await bot.send_document(chat_id, file_id, **kwargs)
    if media_type == "audio":
        return await bot.send_audio(chat_id, file_id, **kwargs)
    if media_type == "voice":
        return await bot.send_voice(chat_id, file_id, **kwargs)
    return await bot.send_message(chat_id, caption or "🍪 Конкурс", parse_mode="HTML", reply_markup=reply_markup)
