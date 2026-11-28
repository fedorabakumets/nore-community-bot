"""Separate NORA updates feed; never routes activity into the main community."""
from __future__ import annotations

import asyncio
import logging
import os

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InputRichMessage, BufferedInputFile, InputMediaPhoto, InputRichBlockPhoto, InputRichBlockButtons, RichMessageButton, InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import io
import re

from community_bot.ephemeral import keep_in_chat
from community_bot.group_message_close import without_group_close, HOME_SCREEN_PARAM

logger = logging.getLogger(__name__)
_lock = asyncio.Lock()

# Only the repository-controlled release list can publish. Keep IDs immutable.
POSTS = (
    {
        "id": "nora-intro-final-20261128",
        "revision": "1",
        "pin": True,
        "intro": True,
        "blocks": [
            {"type": "heading", "text": "Что это?", "size": 1},
            {"type": "paragraph", "text": [{"type": "bold", "text": "Нора"}, " — твоё ", {"type": "bold", "text": "цифровое пространство внутри Telegram"}, ". Здесь можно общаться, знакомиться, играть, слушать музыку, находить случайных собеседников в анонимном чате и участвовать в событиях сообщества"]},
        ],
    },
    {
        "id": "delivery-test-20261128",
        "revision": "1",
        "pin": False,
        "blocks": [{"type": "paragraph", "text": "🔴 НОРА: тестовая публикация. Проверка связи с каналом обновлений."}],
    },
    {
        "id": "welcome-20261128",
        "revision": "1",
        "pin": False,
        "blocks": [
            {"type": "heading", "text": "НОРА / ОБНОВЛЕНИЯ", "size": 1},
            {"type": "paragraph", "text": "У Норы теперь есть отдельное место для новостей."},
            {"type": "blockquote", "blocks": [
                {"type": "paragraph", "text": "Здесь будут обновления, новые идеи и планы развития Норы."},
            ]},
            {"type": "paragraph", "text": "Добро пожаловать ❤️"},
        ],
    },
)


def target():
    value = os.getenv("UPDATES_CHAT_ID", "@noranoranoranoranora").strip()
    if value.startswith("@") and value[1:].isascii() and value[1:].replace("_", "").isalnum():
        return value
    if value.startswith("-100") and value[1:].isdigit():
        return int(value)
    return None


def is_updates_chat(chat):
    destination = target()
    if chat.type not in {"supergroup", "channel"} or destination is None:
        return False
    if isinstance(destination, int):
        return chat.id == destination
    return ("@" + (getattr(chat, "username", None) or "")).casefold() == destination.casefold()


def is_production():
    return (
        os.getenv("RAILWAY_SERVICE_ID") == "dae67cd6-25ee-4710-b11a-7c8f6801e35b"
        and os.getenv("RAILWAY_ENVIRONMENT_ID") == "136c278e-4a0f-4b54-986c-8b64f9d69ad6"
    )


def intro_cover():
    root = Path(__file__).resolve().parent.parent / "assets"
    return (root / "branding" / "nora-logo-ru.jpg").read_bytes()


async def publish_post(db, bot, chat_id, post):
    key = f"updates_feed:{chat_id}:{post['id']}"
    message_id = await db.get_bot_state(key)
    revision_key = key + ":revision"
    if post.get("intro") and message_id and await db.get_bot_state(revision_key) == post["revision"]:
        if post.get("pin") and await db.get_bot_state(key + ":pinned") != "1":
            await bot.pin_chat_message(chat_id, int(message_id), disable_notification=True)
            await db.set_bot_state(key + ":pinned", "1")
        return
    blocks = list(post["blocks"])
    kwargs = {}
    if post.get("intro"):
        url = "https://t.me/nora_community_bot?startapp"
        blocks.insert(0, InputRichBlockPhoto(photo=InputMediaPhoto(media=BufferedInputFile(intro_cover(), filename="nora.jpg"))))
        blocks.append(InputRichBlockButtons(buttons=[RichMessageButton(text="Открыть Нору", url=url, style="primary")]))
        blocks.append(InputRichBlockButtons(buttons=[RichMessageButton(text="Добавить Нору на экран", url=url+"="+HOME_SCREEN_PARAM, style="success")]))
        kwargs["reply_markup"] = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="НОРА", url=url, style="danger")]])
    if post.get("incognito_cover"):
        cover_path = Path(__file__).resolve().parent.parent / "assets" / "branding" / "incognito-search-original.jpg"
        blocks.insert(1, InputRichBlockPhoto(photo=InputMediaPhoto(media=BufferedInputFile(cover_path.read_bytes(), filename="incognito.jpg"))))
    rich = InputRichMessage(blocks=blocks, skip_entity_detection=True)
    if not message_id:
        if await db.get_bot_state(key + ":sending"):
            logger.warning("Updates feed delivery uncertain; duplicate suppressed: %s", post["id"])
            return
        await db.set_bot_state(key + ":sending", "1")
        try:
            with keep_in_chat(), without_group_close():
                sent = await bot.send_rich_message(chat_id, rich_message=rich, **kwargs)
        except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter):
            await db.execute("DELETE FROM bot_state WHERE key=?", (key + ":sending",))
            raise
        message_id = str(sent.message_id)
        await db.set_bot_state(key, message_id)
        await db.set_bot_state(revision_key, post["revision"])
    elif await db.get_bot_state(revision_key) != post["revision"]:
        try:
            with keep_in_chat(), without_group_close():
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=int(message_id), rich_message=rich, parse_mode=None, **kwargs,
                )
        except TelegramBadRequest as error:
            if "not modified" not in error.message.casefold():
                raise
        await db.set_bot_state(revision_key, post["revision"])
    if post.get("pin") and await db.get_bot_state(key + ":pinned") != "1":
        await bot.pin_chat_message(chat_id, int(message_id), disable_notification=True)
        await db.set_bot_state(key + ":pinned", "1")


async def run(db, settings, bot):
    """Publish configured releases only in the separate, verified production channel or group."""
    destination = target()
    if not is_production() or not destination or not settings.community_chat_id:
        return
    async with _lock:
        try:
            chat = await bot.get_chat(destination)
            if not is_updates_chat(chat) or chat.id == settings.community_chat_id:
                logger.warning("Updates feed target is not a separate configured channel or supergroup")
                return
            for post in POSTS:
                try:
                    await publish_post(db, bot, chat.id, post)
                except Exception:
                    logger.exception("Updates feed post not confirmed: %s", post["id"])
        except Exception:
            logger.exception("Updates feed chat unavailable")


# A single release, independently delivered and pinned in each destination.
INCOGNITO_POST = {
    "id": "incognito-launch-photo-20261128",
    "revision": "2",
    "pin": True,
    "incognito_cover": True,
    "blocks": [
        {"type": "heading", "text": "ИНКОГНИТО", "size": 1},
        {"type": "blockquote", "blocks": [
            {"type": "paragraph", "text": "Ни имён. Ни профилей. Только вы и разговор."},
        ]},
        {"type": "paragraph", "text": [
            {"type": "bold", "text": "Инкогнито"},
            " — новый анонимный чат Норы. Знакомься со случайными собеседниками один на один, не раскрывая свой профиль.",
        ]},
        {"type": "heading", "text": "Как начать?", "size": 2},
        {"type": "paragraph", "text": "1. Открой Коммьюнити кнопкой ниже и выбери «Инкогнито»."},
        {"type": "paragraph", "text": "2. Нажми «Найти собеседника» и дождись подключения."},
        {"type": "paragraph", "text": "3. Общайся. Нажми «Следующий», чтобы найти другого человека, или «Завершить», чтобы выйти."},
        {"type": "paragraph", "text": "🔒 Только текст, 18+. Не делись личными данными. В меню диалога можно заблокировать собеседника или пожаловаться. После завершения жалоба доступна ещё 15 минут."},
        {"type": "buttons", "buttons": [
            {"text": "🎭 Открыть Коммьюнити", "url": "https://t.me/nora_community_bot?startapp=nora_to_community", "style": "primary"},
        ]},
        {"type": "buttons", "buttons": [
            {"text": "НОРА", "url": "https://t.me/nora_community_bot?startapp", "style": "danger"},
        ]},
    ],
}


async def _publish_incognito_photo(db, bot, chat_id):
    await publish_post(db, bot, chat_id, INCOGNITO_POST)
    key = f"updates_feed:{chat_id}:{INCOGNITO_POST['id']}"
    if await db.get_bot_state(key + ":pinned") != "1":
        return
    logger.info("Incognito photo announcement published and pinned in %s", chat_id)
    old_key = f"updates_feed:{chat_id}:incognito-launch-20261128"
    old_id = await db.get_bot_state(old_key)
    if old_id and await db.get_bot_state(key + ":old_unpinned") != "1":
        try:
            await bot.unpin_chat_message(chat_id, int(old_id))
        except TelegramBadRequest:
            # An old message may already have been deleted or unpinned.
            pass
        except Exception:
            logger.warning("Could not unpin previous Incognito announcement in %s", chat_id)
            return
        await db.set_bot_state(key + ":old_unpinned", "1")


async def publish_incognito_announcement(db, settings, bot):
    """Publish in the community and the verified updates channel independently."""
    if not is_production() or not settings.community_chat_id:
        return
    async with _lock:
        try:
            await _publish_incognito_photo(db, bot, settings.community_chat_id)
        except Exception:
            logger.exception("Incognito community announcement not confirmed")
        destination = target()
        if not destination:
            return
        try:
            chat = await bot.get_chat(destination)
            if not is_updates_chat(chat) or chat.id == settings.community_chat_id:
                logger.warning("Incognito updates destination is not a separate configured chat")
                return
            await _publish_incognito_photo(db, bot, chat.id)
        except Exception:
            logger.exception("Incognito channel announcement not confirmed")
