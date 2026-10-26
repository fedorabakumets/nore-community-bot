from __future__ import annotations

from pathlib import Path
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InputMediaPhoto, Message

COVERS = Path(__file__).resolve().parent.parent / "assets" / "covers"
CAPTION_LIMIT = 1024


def fits_caption(text: str) -> bool:
    # Conservative for HTML: count markup too, and never slice a finished tag/entity.
    return len(text.encode("utf-16-le")) // 2 <= CAPTION_LIMIT

BLOCK_FILES = {
    "commands": "commands.jpg",
    "shop": "shop.jpg",
    "profile": "profile.jpg",
    "events": "events.jpg",
    "cookies": "cookies.jpg",
    "wallet": "wallet.jpg",
    "games": "games.jpg",
    "roulette": "roulette.jpg",
    "blackjack": "blackjack.jpg",
    "dice": "dice.jpg",
    "crash": "crash.jpg",
    "admin": "admin.jpg",
    "reputation": "reputation.jpg",
    "pet": "pet.jpg",
    "mafia": "mafia.jpg",
    "mafia_night": "mafia_night.jpg",
    "mafia_day": "mafia_day.jpg",
    "mafia_court": "mafia_court.jpg",
    "role_mafia": "role_mafia.jpg",
    "role_civilian": "role_civilian.jpg",
    "role_doctor": "role_doctor.jpg",
    "role_sheriff": "role_sheriff.jpg",
    "bunker": "bunker.jpg",
    "bunker_weather": "bunker_weather.jpg",
    "bunker_external": "bunker_external.jpg",
    "bunker_meeting": "bunker_meeting.jpg",
    "bunker_card": "bunker_card.jpg",
    "cabinet": "cabinet.jpg",
    "ticket": "ticket.jpg",
    "verify": "verify.jpg",
    "notify": "notify.jpg",
}


def cover_path(block: str) -> Path | None:
    name = BLOCK_FILES.get(block)
    if not name:
        return None
    path = COVERS / name
    return path if path.is_file() else None


def cover_file(block: str) -> FSInputFile | None:
    path = cover_path(block)
    return FSInputFile(path) if path else None


async def answer_block(
    message: Message,
    block: str,
    text: str,
    *,
    cover_caption: str | None = None,
    **kwargs: Any,
) -> Message:
    path = cover_path(block)
    if path:
        try:
            split = cover_caption is not None or not fits_caption(text)
            if split:
                photo_kwargs = {key: value for key, value in kwargs.items() if key != "reply_markup"}
                caption = (cover_caption or text.split("\n", 1)[0])[:CAPTION_LIMIT]
                await message.answer_photo(FSInputFile(path), caption=caption, **photo_kwargs)
                return await message.answer(text, **kwargs)
            return await message.answer_photo(FSInputFile(path), caption=text, **kwargs)
        except (TelegramBadRequest, OSError):
            pass
    return await message.answer(text, **kwargs)


async def edit_block(message: Message, text: str, **kwargs: Any) -> Message | None:
    try:
        if message.photo or message.caption is not None:
            if not fits_caption(text):
                await message.edit_reply_markup(reply_markup=None)
                return await message.answer(text, **kwargs)
            return await message.edit_caption(caption=text, **kwargs)
    except TelegramBadRequest as error:
        if "message is not modified" in str(error).casefold():
            return None
    try:
        return await message.edit_text(text, **kwargs)
    except TelegramBadRequest as error:
        if "message is not modified" in str(error).casefold():
            return None
        return await message.answer(text, **kwargs)


async def replace_block(message: Message, block: str, text: str, **kwargs: Any) -> Message | None:
    path = cover_path(block)
    markup = kwargs.get("reply_markup")
    parse_mode = kwargs.get("parse_mode")
    if path and fits_caption(text):
        try:
            media = InputMediaPhoto(media=FSInputFile(path), caption=text, parse_mode=parse_mode)
            return await message.edit_media(media=media, reply_markup=markup)
        except TelegramBadRequest as error:
            if "message is not modified" in str(error).casefold():
                return None
        except OSError:
            pass
    return await edit_block(message, text, **kwargs)
