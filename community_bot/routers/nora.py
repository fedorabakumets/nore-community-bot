from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import Filter
from aiogram.types import LinkPreviewOptions, Message

from community_bot.aliases import parse_trigger
from community_bot.command_registry import get_command
from community_bot.config import Settings
from community_bot.ephemeral import reply_ttl
from community_bot.nora import reply_for, reply_ttl_seconds, strip_address

router = Router(name="nora")

_NORA = re.compile(r"(?i)^\s*нора\b")


@router.message(F.text.regexp(_NORA), F.chat.type.in_({"private", "group", "supergroup"}))
async def nora_address(message: Message, settings: Settings) -> None:
    if not message.from_user or message.from_user.is_bot:
        return
    text = message.text or ""
    if strip_address(text) is None:
        return
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo(settings.timezone))
    answer = await reply_for(text, settings, now)
    if not answer:
        return
    with reply_ttl(reply_ttl_seconds(text)):
        await message.answer(
            answer,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )


class CustomCommand(Filter):
    async def __call__(self, message: Message) -> bool:
        parsed = parse_trigger(message.text or message.caption or "")
        if not parsed:
            return False
        view = get_command(parsed[0])
        if view is None or view.kind != "custom" or not view.enabled or not view.reply_text:
            return False
        return view.allows(message.chat.type)


@router.message(CustomCommand(), F.chat.type.in_({"private", "group", "supergroup"}))
async def custom_command(message: Message) -> None:
    parsed = parse_trigger(message.text or message.caption or "")
    if not parsed:
        return
    view = get_command(parsed[0])
    if view is None or not view.reply_text:
        return
    await message.answer(view.reply_text, parse_mode="HTML")
