from __future__ import annotations

import re

from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatMemberOwner, Message

from community_bot.config import Settings
from community_bot.domain import normalize_phrase

_OWNER = re.compile(
    r"кто (?:(?:тут |здесь )?главный(?: (?:в чате|в группе|в сообществе))?"
    r"|владелец (?:этого )?(?:чата|группы|сообщества)|управляет (?:чатом|группой|сообществом))"
)
_ABOUT = re.compile(
    r"(?:расскажи (?:мне )?(?:о|об|про) (?:нашем |наше |этом |это )?(?:сообществе|сообщество|чате|чат)"
    r"|что (?:это )?за (?:сообщество|чат|группа)|что такое (?:это )?сообщество)"
)
_SUMMARY = (
    "Мы закрытое петербургское сообщество с входом по анкете. "
    "В Норе есть профили, репутация, игры, питомцы и мини-приложение."
)


async def community_fact(prompt: str, message: Message, settings: Settings) -> str | None:
    """Resolve factual questions locally using Telegram metadata."""
    question = normalize_phrase(prompt).strip(" .!?")
    question = re.sub(r"^(?:(?:отлично|хорошо|ок|слушай),? |а |тогда )+", "", question)
    if question in {"кто я", "как меня зовут"} and message.from_user:
        return f"В Telegram твоё имя — {message.from_user.full_name}."

    chat_id = settings.community_chat_id
    if not chat_id:
        return None
    if _OWNER.fullmatch(question):
        try:
            admins = await message.bot.get_chat_administrators(chat_id, request_timeout=5)
        except TelegramAPIError:
            admins = []
        for admin in admins:
            if isinstance(admin, ChatMemberOwner):
                if admin.is_anonymous:
                    return "Владелец чата включил анонимность в Telegram."
                return f"Чатом владеет {admin.user.full_name}."
        return "Сейчас не могу подтвердить, кто владеет чатом."

    if _ABOUT.fullmatch(question):
        try:
            chat = await message.bot.get_chat(chat_id, request_timeout=5)
        except TelegramAPIError:
            return _SUMMARY
        description = (chat.description or "").strip()
        title = f"Это «{chat.title}». " if chat.title else ""
        return f"{title}{description or _SUMMARY}"
    return None
