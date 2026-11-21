"""NORA native home screen installation on a pinned Rich message."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.methods import EditMessageText
from aiogram.types import Chat, InputRichBlockButtons, InputRichBlockParagraph, InputRichMessage, Message, User

from community_bot.group_message_close import (
    HOME_SCREEN_LABEL,
    _home_screen_rich,
    _update_pin_rich,
)


def post(rich):
    return Message(
        message_id=42,
        date=datetime.now(UTC),
        chat=Chat(id=-100123, type="supergroup"),
        from_user=User(id=999, is_bot=True, first_name="NORA"),
        rich_message=rich.model_dump(exclude_none=True),
    )


def test_install_button_is_unique_and_always_last():
    rich = InputRichMessage(blocks=[
        InputRichBlockParagraph(text="Конкурс печенек"),
        InputRichBlockButtons(buttons=[
            {"text": "Получить ссылку", "callback_data": "referral:link:2026"},
            {"text": "❌", "callback_data": "nora:close:0"},
        ]),
    ])
    url = "https://t.me/test_nora?startapp"
    first = _home_screen_rich(rich, url)
    twice = _home_screen_rich(first, url)
    assert len(twice.blocks) == 3
    assert twice.blocks[1].buttons[0].callback_data == "referral:link:2026"
    assert twice.blocks[1].buttons[1].callback_data == "nora:close:0"
    assert twice.blocks[-1].buttons[0].text == HOME_SCREEN_LABEL
    assert twice.blocks[-1].buttons[0].url == "https://t.me/test_nora?startapp=nora_home_screen"
    assert twice.blocks[-1].buttons[0].callback_data is None
    assert sum(
        button.text == HOME_SCREEN_LABEL
        for block in twice.blocks if isinstance(block, InputRichBlockButtons)
        for button in block.buttons
    ) == 1


@pytest.mark.asyncio
async def test_existing_rich_pin_is_edited_in_place_without_new_message():
    original = InputRichMessage(blocks=[
        InputRichBlockParagraph(text="Старый закреп"),
        InputRichBlockButtons(buttons=[
            {"text": "Участвовать", "callback_data": "referral:link:2026"},
        ]),
    ])
    class Bot:
        id = 999
        def __init__(self):
            self.get_chat = AsyncMock(return_value=SimpleNamespace(pinned_message=post(original)))
            self.calls = []
        async def __call__(self, method):
            self.calls.append(method)
            return True
    bot = Bot()
    await _update_pin_rich(bot, -100123, 42, "https://t.me/test_nora?startapp")
    assert len(bot.calls) == 1
    edit = bot.calls[0]
    assert isinstance(edit, EditMessageText)
    assert edit.message_id == 42
    assert edit.reply_markup.inline_keyboard[0][0].text == "НОРА"
    assert edit.rich_message.blocks[-1].buttons[0].url.endswith("startapp=nora_home_screen")
