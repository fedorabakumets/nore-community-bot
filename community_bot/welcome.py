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

WELCOME_ART = Path(__file__).resolve().parent.parent / "assets" / "welcome" / "new-member.jpg"
WELCOME_VIDEO = WELCOME_ART.with_suffix(".mp4")


async def send_member_welcome(bot: Bot, chat_id: int, member: User) -> None:
    me = await bot.me()
    if member.username:
        mention = RichTextMention(text=f"@{member.username}", username=member.username)
    else:
        mention = RichTextTextMention(text=member.full_name, user=member)
    use_video = WELCOME_VIDEO.is_file()
    media = (InputRichBlockVideo(video=InputMediaVideo(media=FSInputFile(WELCOME_VIDEO), supports_streaming=True))
             if use_video else InputRichBlockPhoto(photo=InputMediaPhoto(media=FSInputFile(WELCOME_ART))))
    rich_message = InputRichMessage(blocks=[
        InputRichBlockParagraph(text=["Привет, ", mention, "!"]),
        InputRichBlockParagraph(text=(
            "Помни! Мы с уважением относимся каждому. Перед общением, не забудь прочитать правила ❤️"
        )),
        InputRichBlockParagraph(text=[
            RichTextButton(button=RichMessageButton(text="команды", style="link", callback_data=OPEN_COMMANDS_CARD)),
            " · ",
            RichTextButton(button=RichMessageButton(text="Нора", style="link", url=f"https://t.me/{me.username}?startapp")),
        ]),
        media,
    ])
    with keep_in_chat():
        try:
            await bot.send_rich_message(chat_id, rich_message=rich_message)
        except TelegramBadRequest:
            if not use_video:
                raise
            # Older Telegram clients or API restrictions may reject video in a Rich Message.
            # Keep the welcome visible instead of preventing the join handler from finishing.
            rich_message.blocks[-1] = InputRichBlockPhoto(photo=InputMediaPhoto(media=FSInputFile(WELCOME_ART)))
            await bot.send_rich_message(chat_id, rich_message=rich_message)
