from pathlib import Path

from aiogram import Bot
from aiogram.types import (
    FSInputFile,
    InputMediaPhoto,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
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


async def send_member_welcome(bot: Bot, chat_id: int, member: User) -> None:
    me = await bot.me()
    if member.username:
        mention = RichTextMention(text=f"@{member.username}", username=member.username)
    else:
        mention = RichTextTextMention(text=member.full_name, user=member)
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
        InputRichBlockPhoto(photo=InputMediaPhoto(media=FSInputFile(WELCOME_ART))),
    ])
    with keep_in_chat():
        await bot.send_rich_message(chat_id, rich_message=rich_message)
