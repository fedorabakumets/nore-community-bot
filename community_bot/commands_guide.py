from __future__ import annotations

import asyncio
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InputMediaPhoto,
    InputRichBlockButtons,
    InputRichBlockPhoto,
    InputRichMessage,
    Message,
    RichMessageButton,
)

from community_bot.config import Settings
from community_bot.database import Database
from community_bot.domain import ROLE_LEVELS
from community_bot.ephemeral import reply_ttl
from community_bot.helpers import delete_later, rank_of_user

router = Router(name="commands_guide")

CLOSE_COMMANDS_CARD = "commands:close"
COMMANDS_ART = Path(__file__).resolve().parent.parent / "assets" / "commands" / "guide.jpg"
COMMANDS_CARD_TTL = 60
_pending_cards: dict[tuple[int, int], tuple[int, asyncio.Task[None]]] = {}


async def _expire_card(message: Message, key: tuple[int, int]) -> None:
    try:
        await delete_later(message, COMMANDS_CARD_TTL)
    finally:
        _pending_cards.pop(key, None)


async def send_commands_card(message: Message, bot: Bot) -> None:
    if message.from_user is None:
        return
    from community_bot.private_rich import standalone_rich_message

    rich_message = InputRichMessage(blocks=[
        InputRichBlockPhoto(photo=InputMediaPhoto(media=FSInputFile(COMMANDS_ART))),
        InputRichBlockButtons(buttons=[
            RichMessageButton(text="Закрыть", style="danger", callback_data=CLOSE_COMMANDS_CARD),
        ], align="center"),
    ])
    with reply_ttl(None), standalone_rich_message():
        sent = await bot.send_rich_message(
            message.chat.id,
            rich_message=rich_message,
            message_thread_id=message.message_thread_id if message.is_topic_message else None,
        )
    key = (sent.chat.id, sent.message_id)
    _pending_cards[key] = (message.from_user.id, asyncio.create_task(_expire_card(sent, key)))


async def _can_close(
    message: Message, actor_id: int, requester_id: int, bot: Bot, db: Database, settings: Settings,
) -> bool:
    if actor_id == requester_id:
        return True
    if message.chat.type not in {"group", "supergroup"}:
        return False
    if await rank_of_user(db, settings, actor_id) >= ROLE_LEVELS["moderator"]:
        return True
    try:
        member = await bot.get_chat_member(message.chat.id, actor_id)
    except TelegramAPIError:
        return False
    return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}


@router.callback_query(F.data == CLOSE_COMMANDS_CARD)
async def close_commands_card(callback: CallbackQuery, bot: Bot, db: Database, settings: Settings) -> None:
    message = callback.message
    if not isinstance(message, Message):
        await callback.answer()
        return
    key = (message.chat.id, message.message_id)
    card = _pending_cards.get(key)
    if card is None:
        await callback.answer("Карточка уже недоступна.")
        return
    requester_id, timer = card
    if not await _can_close(message, callback.from_user.id, requester_id, bot, db, settings):
        await callback.answer("Закрыть карточку может автор запроса или модератор.", show_alert=True)
        return
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError):
        await callback.answer("Не удалось закрыть карточку.")
        return
    _pending_cards.pop(key, None)
    timer.cancel()
    await callback.answer()
