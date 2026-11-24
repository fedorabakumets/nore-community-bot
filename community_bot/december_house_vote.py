"""One-off Rich house-choice poll, independent of the December event RSVP."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputRichBlockButtons,
    InputRichBlockDetails,
    InputRichBlockDivider,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichBlockSectionHeading,
    InputRichMessage,
    RichMessageButton,
)

from community_bot.ephemeral import keep_in_chat
from community_bot.group_message_close import without_group_close

router = Router(name="december_house_vote")
logger = logging.getLogger(__name__)
KEY = "december-house-vote-2026"
PREFIX = "dec_house:"
END = datetime(2026, 12, 2, 11, tzinfo=UTC)
ROOT = Path(__file__).resolve().parent.parent / "assets" / "events" / "house-vote"
LOCK = asyncio.Lock()
BASE = "https://www.avito.ru/sankt-peterburg_krasnoye_selo/doma_dachi_kottedzhi/"
HOUSES = (
    (
        "Дом 1 · 100 м²", "5,0 · 57 отзывов", "4 комнаты · горячая купель",
        "➕ Горячая купель, заезд с 14:00, двуспальный диван.",
        "➖ Горячая купель 5 000 ₽/сут., холодная 2 000 ₽/сут., сауна 2 000 ₽/сут. Бильярд не заявлен.",
        "Заезд 14:00 · выезд 12:00", "4-k._dom_100_m_2828106085",
    ),
    (
        "Дом 2 · 110 м²", "5,0 · 194 отзыва", "4 комнаты · бильярд",
        "➕ Самый большой дом, бильярд, просторный двор, 5 парковочных мест.",
        "➖ Заезд с 16:00, диваны не раскладываются, сауна 2 000 ₽/сут. Бассейн только летний.",
        "Заезд 16:00 · выезд 14:00", "4-k._dom_110_m_2028014059",
    ),
    (
        "Дом 3 · 100 м²", "4,9 · 61 отзыв", "4 комнаты · бильярд",
        "➕ Бильярд, караоке, заезд с 14:00, двуспальный диван.",
        "➖ Небольшой двор, сауна 2 000 ₽/сут. Купель не заявлена.",
        "Заезд 14:00 · выезд 12:00", "dom_100_m_2732145087",
    ),
)


def paragraph(text):
    return InputRichBlockParagraph(text=text)


def build_rich(media, votes, *, closed=False):
    blocks = [
        InputRichBlockSectionHeading(text="🏡 Выбираем дом на 2 декабря", size=1),
        paragraph("2–3 декабря 2026 · Красное Село, Лагерная ул., 470"),
        paragraph("Цена аренды и наличие свободных дат уточняются. Выбираем предпочтительный вариант."),
        InputRichBlockDetails(summary="Общие условия", blocks=[
            paragraph("8 спальных мест, до 12 человек за столом, мангал, караоке, Wi-Fi, два санузла."),
            paragraph("Шуметь можно только в доме с закрытыми окнами и дверьми. Банных полотенец нет."),
            paragraph("Бронь с 23 лет; для гостей 18–23 лет — до 8 человек и залог 10 000 ₽. "
                      "Для домов 1 и 3 цена рассчитана на 8 гостей, далее доплата."),
        ]),
    ]
    for photo, (name, rating, features, pros, cons, hours, slug) in zip(media, HOUSES, strict=True):
        blocks.extend([
            InputRichBlockDivider(),
            InputRichBlockPhoto(photo=InputMediaPhoto(media=photo)),
            InputRichBlockSectionHeading(text=name, size=2),
            paragraph(f"⭐ {rating} · {features}"),
            InputRichBlockDetails(summary="Подробнее", blocks=[
                paragraph(pros), paragraph(cons), paragraph(hours),
            ]),
            InputRichBlockButtons(buttons=[RichMessageButton(text="Авито ↗", url=BASE + slug, style="primary")]),
        ])
    total = len(votes)
    blocks.extend([InputRichBlockDivider(), InputRichBlockSectionHeading(text="🗳 Голосование", size=2)])
    status = "Голосование завершено." if closed else "Один человек — один голос. Выбор можно изменить."
    blocks.append(paragraph(f"Проголосовало: {total}. {status}"))
    for i in range(1, 4):
        count = sum(v == i for v in votes.values())
        pct = round(count * 100 / total) if total else 0
        line = f"Дом {i} · {pct}% ({count})"
        if closed:
            blocks.append(paragraph(line))
        else:
            blocks.append(InputRichBlockButtons(buttons=[
                RichMessageButton(text=line, callback_data=PREFIX + str(i), style="primary"),
            ]))
    return InputRichMessage(blocks=blocks, skip_entity_detection=True)


async def load(db):
    raw = await db.get_bot_state(KEY)
    return json.loads(raw) if raw else {}


async def save(db, state):
    await db.set_bot_state(KEY, json.dumps(state, ensure_ascii=False))


def markup(username):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="НОРА", url=f"https://t.me/{username}?startapp")],
    ])


async def refresh(db, settings, bot, state, *, closed=False):
    if len(state.get("media", [])) != 3:
        return False
    try:
        with keep_in_chat(), without_group_close():
            await bot.edit_message_text(
                chat_id=settings.community_chat_id,
                message_id=state["message_id"],
                rich_message=build_rich(state["media"], state.get("votes", {}), closed=closed),
                reply_markup=markup(state["username"]),
                parse_mode=None,
            )
    except TelegramBadRequest as error:
        if "not modified" not in error.message.casefold():
            logger.exception("House vote counter edit failed")
            return False
    except TelegramAPIError:
        logger.exception("House vote counter edit failed")
        return False
    state["dirty"] = False
    state["closed"] = closed
    await save(db, state)
    return True


async def publish(db, settings, bot):
    state = await load(db)
    if state.get("message_id") or state.get("sending") or datetime.now(UTC) >= END:
        return
    paths = [ROOT / f"house-{i}.jpg" for i in range(1, 4)]
    if not all(p.is_file() for p in paths):
        logger.error("House vote not sent: missing images")
        return
    username = (await bot.me()).username
    if not username:
        return
    rich = build_rich([FSInputFile(p) for p in paths], {})
    await save(db, {"sending": True})
    try:
        with keep_in_chat(), without_group_close():
            sent = await bot.send_rich_message(
                chat_id=settings.community_chat_id, rich_message=rich, reply_markup=markup(username),
            )
    except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter):
        await save(db, {})
        logger.exception("House vote rejected by Telegram")
        return
    except Exception:
        logger.exception("House vote delivery uncertain; refusing automatic duplicate")
        return
    state = {"message_id": sent.message_id, "media": [], "votes": {}, "username": username}
    await save(db, state)
    if sent.rich_message:
        state["media"] = [b.photo[-1].file_id for b in sent.rich_message.blocks if b.type == "photo"]
        await save(db, state)
    logger.info("House vote posted: %s", sent.message_id)


async def run(db, settings, bot: Bot):
    if (
        os.getenv("RAILWAY_SERVICE_ID") != "dae67cd6-25ee-4710-b11a-7c8f6801e35b"
        or os.getenv("RAILWAY_ENVIRONMENT_ID") != "136c278e-4a0f-4b54-986c-8b64f9d69ad6"
        or not settings.community_chat_id
    ):
        return
    try:
        async with LOCK:
            await publish(db, settings, bot)
    except Exception:
        logger.exception("House vote publication interrupted")
        return
    while True:
        async with LOCK:
            state = await load(db)
            if not state.get("message_id") or len(state.get("media", [])) != 3:
                return
            closed = datetime.now(UTC) >= END
            if state.get("closed"):
                return
            if closed or state.get("dirty"):
                if await refresh(db, settings, bot, state, closed=closed) and closed:
                    return
        await asyncio.sleep(30)


@router.callback_query(F.data.in_({PREFIX + str(i) for i in range(1, 4)}))
async def vote(callback: CallbackQuery, bot: Bot, db, settings):
    if callback.message is None or callback.message.chat.id != settings.community_chat_id:
        await callback.answer("Это голосование доступно в чате Норы.", show_alert=True)
        return
    async with LOCK:
        state = await load(db)
        if callback.message.message_id != state.get("message_id") or len(state.get("media", [])) != 3:
            await callback.answer("Голосование недоступно.", show_alert=True)
            return
        if datetime.now(UTC) >= END:
            await callback.answer("Голосование завершено.", show_alert=True)
            return
        votes = state.setdefault("votes", {})
        uid = str(callback.from_user.id)
        choice = int(callback.data.removeprefix(PREFIX))
        votes[uid] = choice
        state["dirty"] = True
        await save(db, state)
        await callback.answer(f"Голос за дом {choice} сохранён.")
        await refresh(db, settings, bot, state)
