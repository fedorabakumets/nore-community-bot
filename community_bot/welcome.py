import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    FSInputFile,
    InputMediaPhoto,
    InputMediaVideo,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichBlockVideo,
    InputRichMessage,
    RichMessageButton,
    RichTextButton,
    RichTextMention,
    RichTextTextMention,
    User,
)

from community_bot.commands_guide import OPEN_COMMANDS_CARD
from community_bot.ephemeral import keep_in_chat

logger = logging.getLogger(__name__)
ASSETS = Path(__file__).resolve().parent.parent / "assets"
WELCOME_ART = ASSETS / "welcome" / "new-member.jpg"
WELCOME_VIDEO = ASSETS / "branding" / "nora-update-20261120.mp4"


async def send_member_welcome(bot: Bot, chat_id: int, member: User) -> None:
    me = await bot.me()
    if member.username:
        mention = RichTextMention(text=f"@{member.username}", username=member.username)
    else:
        mention = RichTextTextMention(text=member.full_name, user=member)
    blocks = [
        InputRichBlockParagraph(text=["Привет, ", mention, "!"]),
        InputRichBlockParagraph(text=(
            "Помни! Мы с уважением относимся каждому. Перед общением, не забудь прочитать правила ❤️"
        )),
        InputRichBlockParagraph(text=[
            RichTextButton(button=RichMessageButton(text="команды", style="link", callback_data=OPEN_COMMANDS_CARD)),
            " · ",
            RichTextButton(button=RichMessageButton(text="Нора", style="link", url=f"https://t.me/{me.username}?startapp")),
        ]),
    ]
    video = InputRichBlockVideo(video=InputMediaVideo(
        media=FSInputFile(WELCOME_VIDEO), width=720, height=1280, duration=14, supports_streaming=True,
    ))
    with keep_in_chat():
        try:
            await bot.send_rich_message(chat_id, rich_message=InputRichMessage(blocks=[*blocks, video]))
        except (TelegramBadRequest, OSError):
            logger.warning("Could not send the welcome video, using the welcome image", exc_info=True)
            photo = InputRichBlockPhoto(photo=InputMediaPhoto(media=FSInputFile(WELCOME_ART)))
            await bot.send_rich_message(chat_id, rich_message=InputRichMessage(blocks=[*blocks, photo]))
