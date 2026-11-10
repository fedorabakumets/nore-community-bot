from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Filter, StateFilter
from aiogram.types import LinkPreviewOptions, Message

from community_bot.aliases import message_trigger, parse_trigger
from community_bot.command_registry import get_command, nora_enabled
from community_bot.config import Settings
from community_bot.ephemeral import delete_user_command, reply_ttl
from community_bot.nora import reply_for, reply_ttl_seconds, rule_intent, strip_address
from community_bot.openrouter_chat import OpenRouterChat

router = Router(name="nora")
assistant_router = Router(name="nora_assistant")

_NORA = re.compile(r"(?i)^\s*нора\b")


@assistant_router.message(
    F.text.regexp(_NORA), F.chat.type.in_({"private", "group", "supergroup"}), StateFilter(None),
)
async def nora_address(
    message: Message, settings: Settings, openrouter_chat: OpenRouterChat | None = None,
) -> None:
    if not message.from_user or message.from_user.is_bot:
        return
    text = message.text or ""
    if parse_trigger(text):
        raise SkipHandler
    body = strip_address(text)
    if body is None:
        return
    if openrouter_chat is not None and rule_intent(body) is None:
        if message.from_user.id not in (
            settings.owner_ids | settings.moderator_ids
        ):
            return
        prompt = openrouter_chat.prompt_for(message)
        if prompt and nora_enabled():
            answer = await openrouter_chat.answer(prompt, message.from_user.id)
            if answer:
                await message.reply(
                    answer,
                    parse_mode=None,
                    allow_sending_without_reply=True,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
        return
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo(settings.timezone))
    answer = await reply_for(text, settings, now)
    if answer:
        with reply_ttl(reply_ttl_seconds(text)):
            await message.answer(
                answer,
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
    if message.chat.type in {"group", "supergroup"}:
        await delete_user_command(message, message.bot)


class CustomCommand(Filter):
    async def __call__(self, message: Message) -> bool:
        parsed = message_trigger(message)
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
