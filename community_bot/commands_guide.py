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
    InputRichBlockDetails,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichMessage,
    Message,
    ReplyParameters,
    RichMessageButton,
)

from community_bot.config import Settings
from community_bot.database import Database
from community_bot.domain import ROLE_LEVELS
from community_bot.ephemeral import reply_ttl
from community_bot.helpers import delete_later, rank_of_user
from community_bot.nora_links import nora_link_block

router = Router(name="commands_guide")

CLOSE_COMMANDS_CARD = "commands:close"
OPEN_COMMANDS_CARD = "commands:open"
COMMANDS_ART = Path(__file__).resolve().parent.parent / "assets" / "commands" / "guide.jpg"
COMMANDS_CARD_TTL = 60
_pending_cards: dict[tuple[int, int], tuple[int, asyncio.Task[None]]] = {}


async def _expire_card(message: Message, key: tuple[int, int]) -> None:
    try:
        await delete_later(message, COMMANDS_CARD_TTL)
    finally:
        _pending_cards.pop(key, None)


async def send_commands_card(message: Message, bot: Bot, *, requester_id: int | None = None) -> None:
    reply = None
    if requester_id is None:
        if message.from_user is None:
            return
        requester_id = message.from_user.id
    else:
        reply = ReplyParameters(message_id=message.message_id, allow_sending_without_reply=True)
    from community_bot.private_rich import standalone_rich_message

    app = await nora_link_block(bot, "commands_guide", set(), "")
    rich_message = InputRichMessage(blocks=[
        InputRichBlockPhoto(photo=InputMediaPhoto(media=FSInputFile(COMMANDS_ART))),
        InputRichBlockDetails(summary="Как пользоваться Норой ИИ, читать записи и скачивать видео", blocks=[
            InputRichBlockParagraph(
                text="Нора ИИ · Со 2-го уровня начни вопрос с «Нора» в основном чате или в личке. "
                     "Ответь на её сообщение, чтобы продолжить разговор.",
            ),
            InputRichBlockParagraph(
                text="Голосовое · Ответь на запись фразой «Нора, расшифруй». Под ней раскрой «Текст голосового».",
            ),
            InputRichBlockParagraph(
                text="Кружок · Ответь на видеокружок фразой «Нора, расшифруй». Под ним раскрой «Текст кружка». "
                     "Карточки записей закрываются по ❌ и исчезают через две минуты.",
            ),
            InputRichBlockParagraph(
                text="Видео · С 3-го уровня отправь «Нора» и публичную ссылку на TikTok, Reels или Shorts. "
                     "Нора пришлёт MP4, который можно сохранить из Telegram.",
            ),
        ]),
        *([app] if app else []),
        InputRichBlockButtons(buttons=[
            RichMessageButton(text="Закрыть", style="danger", callback_data=CLOSE_COMMANDS_CARD),
        ], align="center"),
    ])
    with reply_ttl(None), standalone_rich_message():
        sent = await bot.send_rich_message(
            message.chat.id,
            rich_message=rich_message,
            message_thread_id=message.message_thread_id if message.is_topic_message else None,
            reply_parameters=reply,
        )
    key = (sent.chat.id, sent.message_id)
    _pending_cards[key] = (requester_id, asyncio.create_task(_expire_card(sent, key)))


@router.callback_query(F.data == OPEN_COMMANDS_CARD)
async def open_commands_card(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await send_commands_card(callback.message, bot, requester_id=callback.from_user.id)


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
