"""One-time DOT launch announcement in the production community chat."""
from __future__ import annotations

import contextlib
import io
import logging
import os
import re
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (
    BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaPhoto, InputRichBlockButtons, InputRichBlockParagraph, InputRichBlockPhoto,
    InputRichBlockSectionHeading, InputRichMessage, RichMessageButton,
)
from PIL import Image, ImageDraw, ImageFont

from community_bot.ephemeral import keep_in_chat
from community_bot.group_message_close import HOME_SCREEN_LABEL, HOME_SCREEN_PARAM, without_group_close

logger = logging.getLogger(__name__)
KEY = "dot_announcement_message_id"
REVISION = "layout-v2"
ROOT = Path(__file__).resolve().parent.parent / "assets"


def cover() -> bytes:
    """Compose a minimal cover with the exact original NORA O silhouette."""
    image = Image.new("RGB", (1200, 720), "#101014")
    draw = ImageDraw.Draw(image)
    font = ROOT / "fonts" / "Inter-Bold.ttf"
    big = ImageFont.truetype(str(font), 174)
    small = ImageFont.truetype(str(font), 28)
    # Sparse arcade corridors and a red moving dot.
    for x, top, bottom in [(90, 150, 410), (1040, 270, 530)]:
        draw.rounded_rectangle((x, 0, x + 64, top), radius=12, fill="#22232c")
        draw.rounded_rectangle((x, bottom, x + 64, 720), radius=12, fill="#22232c")
    draw.line([(174, 490), (246, 453), (316, 471)], fill="#6b2039", width=5)
    draw.ellipse((303, 458, 329, 484), fill="#fa164b")
    draw.text((437, 324), "D", font=big, anchor="mm", fill="#f6f4f7")
    draw.text((762, 324), "T", font=big, anchor="mm", fill="#f6f4f7")
    svg = (ROOT / "branding" / "nora-home-icon.svg").read_text(encoding="utf-8")
    path = re.search(r'<path[^>]*\bd="([^"]+)"', svg)
    if not path:
        raise ValueError("Original NORA mark not found")
    coords = re.findall(r"[ML](\d+),(\d+)", path.group(1))
    if len(coords) < 20:
        raise ValueError("Unexpected NORA mark geometry")
    draw.polygon([(514 + int(x)*.335, 238 + int(y)*.335) for x, y in coords], fill="#fa164b")
    draw.text((600, 467), "БЕЙ РЕКОРД. ЗАБИРАЙ ПЕЧЕНЬКИ.", font=small, anchor="mm", fill="#a2a1ab")
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def rich_post(username, photo=None):
    base = f"https://t.me/{username}?startapp"
    if photo is None:
        photo = BufferedInputFile(cover(), filename="dot.png")
    return InputRichMessage(blocks=[
        InputRichBlockSectionHeading(text="DOT", size=1),
        InputRichBlockPhoto(photo=InputMediaPhoto(media=photo)),
        InputRichBlockParagraph(text="Маленькая капля в безграничном космосе. Тактильные вибрации, красивые эффекты и разнообразная механика."),
        {"type": "blockquote", "blocks": [{"type": "paragraph", "text":
            "🍪 Побей мировой рекорд — забери все печеньки, собранные за полёт, на основной баланс!"}]},
        InputRichBlockButtons(buttons=[
            RichMessageButton(text=HOME_SCREEN_LABEL, url=f"{base}={HOME_SCREEN_PARAM}", style="primary"),
        ]),
        InputRichBlockButtons(buttons=[
            RichMessageButton(text="НОРА", url=base, style="primary"),
        ]),
    ], skip_entity_detection=True)


def dot_markup(username):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="DOT", url=f"https://t.me/{username}?startapp=nora_to_dot"),
    ]])


async def refresh_existing(db, settings, bot, mid, username):
    if await db.get_bot_state(KEY + ":revision") == REVISION:
        return
    # Reuse the original cover file ID when the post is still the current pin.
    chat = await bot.get_chat(settings.community_chat_id)
    post = getattr(chat, "pinned_message", None)
    photo = None
    if post and str(post.message_id) == mid and post.rich_message:
        photo = next((block.photo[-1].file_id for block in post.rich_message.blocks
                      if block.type == "photo" and block.photo), None)
    try:
        with keep_in_chat(), without_group_close():
            await bot.edit_message_text(
                chat_id=settings.community_chat_id, message_id=int(mid),
                rich_message=rich_post(username, photo), reply_markup=dot_markup(username),
                parse_mode=None,
            )
    except TelegramBadRequest as error:
        if "not modified" not in error.message.casefold():
            raise
    await db.set_bot_state(KEY + ":revision", REVISION)


async def run(db, settings, bot):
    if (os.getenv("RAILWAY_SERVICE_ID") != "dae67cd6-25ee-4710-b11a-7c8f6801e35b"
            or os.getenv("RAILWAY_ENVIRONMENT_ID") != "136c278e-4a0f-4b54-986c-8b64f9d69ad6"
            or not settings.community_chat_id):
        return
    try:
        mid = await db.get_bot_state(KEY)
        username = (await bot.me()).username
        if not username:
            return
        if not mid:
            if await db.get_bot_state(KEY + ":sending"):
                logger.warning("DOT announcement delivery uncertain; duplicate suppressed")
                return
            rich = rich_post(username)
            markup = dot_markup(username)
            await db.set_bot_state(KEY + ":sending", "1")
            try:
                with keep_in_chat(), without_group_close():
                    sent = await bot.send_rich_message(settings.community_chat_id, rich_message=rich, reply_markup=markup)
            except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter):
                await db.execute("DELETE FROM bot_state WHERE key=?", (KEY + ":sending",))
                raise
            mid = str(sent.message_id)
            await db.set_bot_state(KEY, mid)
            await db.set_bot_state(KEY + ":revision", REVISION)
        else:
            await refresh_existing(db, settings, bot, mid, username)
        if await db.get_bot_state(KEY + ":pinned") == "1":
            return
        old = await db.get_bot_state("last_announcement_message_id")
        await bot.pin_chat_message(settings.community_chat_id, int(mid), disable_notification=True)
        if old and old != mid:
            with contextlib.suppress(Exception):
                await bot.unpin_chat_message(settings.community_chat_id, int(old))
        await db.set_bot_state("last_announcement_message_id", mid)
        await db.set_bot_state(KEY + ":pinned", "1")
        logger.info("DOT announcement published and pinned")
    except Exception:
        logger.exception("DOT announcement not confirmed")
