from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Filter, StateFilter
from aiogram.types import LinkPreviewOptions, Message

from community_bot.aliases import message_trigger, parse_trigger
from community_bot.chat_memory import retention_notice
from community_bot.command_registry import get_command, nora_enabled
from community_bot.community_facts import community_fact
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.ephemeral import delete_user_command, reply_ttl
from community_bot.nora import reply_for, reply_ttl_seconds, rule_intent, strip_address
from community_bot.nora_knowledge import is_nora_topic
from community_bot.openrouter_chat import OpenRouterChat, archive_question
from community_bot.pet_progress import level
from community_bot.pet_video import PetVideoQueue, video_command

router = Router(name="nora")
assistant_router = Router(name="nora_assistant")

_NORA = re.compile(r"(?i)^\s*нора\b")


async def has_assistant_access(user_id: int, settings: Settings, db: Database | None) -> bool:
    if user_id in settings.owner_ids | settings.moderator_ids:
        return True
    return bool(db and await level(db, user_id) >= 2 and await db.feature_enabled("tamagotchi"))


async def assistant_access_error(
    user_id: int, settings: Settings, db: Database | None, *, in_community: bool = False,
) -> str | None:
    if not in_community and not await has_assistant_access(user_id, settings, db):
        if db and not await db.feature_enabled("tamagotchi"):
            return "Нора ИИ сейчас недоступна: питомцы временно отключены."
        if db and not await db.get_pet(user_id, settle=False):
            return "Чтобы общаться с Норой ИИ, сначала заведите питомца и достигните 2 уровня."
        return "Нора ИИ открывается на 2 уровне питомца."
    if db:
        pet = await db.get_pet(user_id)
        if pet and pet.get("expedition_until"):
            return "Пока питомец в походе, Нора ИИ недоступна. Верните питомца через «Питомец» или /pet."
    return None


def _noted_answer(prompt: str, answer: str, settings: Settings) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    note = retention_notice(prompt, datetime.now(ZoneInfo(settings.timezone))) if archive_question(prompt) else None
    return f"{note}\n\n{answer}" if note else answer


async def _respond_to_prompt(
    message: Message,
    settings: Settings,
    chat: OpenRouterChat,
    prompt: str,
    history: list[dict[str, str]] | None = None,
    conversation_id: str | None = None,
) -> None:
    assert message.from_user is not None
    reply_options = LinkPreviewOptions(is_disabled=True)
    fact = await community_fact(prompt, message, settings)
    if fact is not None:
        await message.reply(fact, parse_mode=None, allow_sending_without_reply=True, link_preview_options=reply_options)
        return
    if history is None:
        answer = await chat.answer(prompt, message.from_user.id, message=message)
    else:
        answer = await chat.answer_with_history(history, prompt, message.from_user.id, message=message)
    if not answer:
        return
    sent = await message.reply(
        _noted_answer(prompt, answer, settings),
        parse_mode=None,
        allow_sending_without_reply=True,
        link_preview_options=reply_options,
    )
    sent_id = getattr(sent, "message_id", None)
    if isinstance(sent_id, int):
        chat.remember_dialogue(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            prompt=prompt,
            answer=answer,
            message_id=sent_id,
            conversation_id=conversation_id,
        )


@assistant_router.message(
    F.text.regexp(_NORA), F.chat.type.in_({"private", "group", "supergroup"}), StateFilter(None),
)
async def nora_address(
    message: Message, settings: Settings, openrouter_chat: OpenRouterChat | None = None,
    db: Database | None = None,
) -> None:
    if not message.from_user or message.from_user.is_bot:
        return
    text = message.text or ""
    if video_command(text):
        return
    if message_trigger(message) or parse_trigger(text):
        raise SkipHandler
    body = strip_address(text)
    if body is None:
        return
    if openrouter_chat is not None and (rule_intent(body) is None or archive_question(body) or is_nora_topic(body)):
        if not nora_enabled():
            return
        prompt = openrouter_chat.prompt_for(message)
        if not prompt:
            return
        error = await assistant_access_error(
            message.from_user.id, settings, db, in_community=openrouter_chat.can_read_archive(message),
        )
        if error:
            await message.reply(error, parse_mode=None)
            return
        if message.reply_to_message is not None:
            found = openrouter_chat.continuation_for(message)
            if found is not None:
                await _respond_to_prompt(message, settings, openrouter_chat, *found)
                return
        await _respond_to_prompt(message, settings, openrouter_chat, prompt)
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


@assistant_router.message(
    F.reply_to_message,
    F.text,
    F.chat.type.in_({"private", "group", "supergroup"}),
    StateFilter(None),
)
async def nora_reply_continuation(
    message: Message, settings: Settings, openrouter_chat: OpenRouterChat | None = None,
    db: Database | None = None,
) -> None:
    if openrouter_chat is None or not message.from_user or message.from_user.is_bot:
        return
    if not nora_enabled():
        return
    if parse_trigger(message.text or ""):
        raise SkipHandler
    found = openrouter_chat.continuation_for(message)
    if found is None and openrouter_chat.continuation_for(message, allow_other_user=True) is None:
        return
    in_community = openrouter_chat.can_read_archive(message)
    error = await assistant_access_error(message.from_user.id, settings, db, in_community=in_community)
    if error:
        await message.reply(error, parse_mode=None)
    elif found is not None:
        await _respond_to_prompt(message, settings, openrouter_chat, *found)
    elif in_community:
        await _respond_to_prompt(message, settings, openrouter_chat, message.text or "")


@router.message(
    F.text.func(video_command), F.chat.type.in_({"private", "group", "supergroup"}), StateFilter(None),
)
async def nora_video(message: Message, settings: Settings, pet_video_queue: PetVideoQueue | None = None) -> None:
    user = message.from_user
    if (not user or user.is_bot or message.sender_chat or message.forward_origin or message.via_bot
            or (message.chat.type != "private" and message.chat.id != settings.community_chat_id)):
        return
    if pet_video_queue is not None:
        await pet_video_queue.enqueue(message, video_command(message.text))


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
