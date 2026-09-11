from __future__ import annotations

from pathlib import Path
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, Message

COVERS = Path(__file__).resolve().parent.parent / "assets" / "covers"
CAPTION_LIMIT = 1024

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
            split = cover_caption is not None or len(text) > CAPTION_LIMIT
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
    caption = text[:CAPTION_LIMIT]
    try:
        if message.photo or message.caption is not None:
            return await message.edit_caption(caption=caption, **kwargs)
    except TelegramBadRequest:
        pass
    try:
        return await message.edit_text(text, **kwargs)
    except TelegramBadRequest:
        return await message.answer(text, **kwargs)
