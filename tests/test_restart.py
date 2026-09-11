from __future__ import annotations

import asyncio

from community_bot.audit import ACTION_LABELS
from community_bot.keyboards import admin_restart_keyboard, admin_system_keyboard
from community_bot.restart import (
    countdown_text,
    play_countdown,
    relaunch_command,
    reset_guard,
    try_begin,
)


def test_restart_button_only_for_owners() -> None:
    admin_menu = admin_system_keyboard(["*"], is_owner=False)
    admin_data = [button.callback_data for row in admin_menu.inline_keyboard for button in row]
    assert "admin:restart" not in admin_data
    owner_menu = admin_system_keyboard(["audit"], is_owner=True)
    owner_data = [button.callback_data for row in owner_menu.inline_keyboard for button in row]
    assert "admin:restart" in owner_data
    confirm = admin_restart_keyboard()
    confirm_data = [button.callback_data for row in confirm.inline_keyboard for button in row]
    assert confirm_data == ["admin:restart:yes", "admin:restart:no"]


def test_countdown_text_does_not_reset_settings() -> None:
    text = countdown_text(10, owner_name="Анна")
    assert "Старт через <b>10</b> сек." in text
    assert "Анна" in text
    assert "сброс" in text.casefold() or "на месте" in text
    assert "роли" in text.casefold()
    done = countdown_text(0, done=True, owner_name="<script>")
    assert "&lt;script&gt;" in done
    assert "на месте" in done


def test_relaunch_keeps_same_module() -> None:
    command = relaunch_command()
    assert command[-2:] == ["-m", "community_bot.main"]
    assert ACTION_LABELS["restart"] == "Перезапуск бота"


def test_restart_guard_blocks_second_click() -> None:
    reset_guard()
    assert try_begin() is True
    assert try_begin() is False
    reset_guard()
    assert try_begin() is True
    reset_guard()


async def test_play_countdown_edits_chat_each_second(monkeypatch) -> None:
    sent: list[str] = []
    edited: list[str] = []

    class FakeMessage:
        message_id = 42

    class FakeBot:
        async def send_message(self, chat_id: int, text: str, parse_mode: str | None = None):
            assert chat_id == -1004331642093
            sent.append(text)
            return FakeMessage()

        async def edit_message_text(self, text: str, chat_id: int, message_id: int, parse_mode: str | None = None):
            edited.append(text)

    async def instant_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)
    message_id = await play_countdown(FakeBot(), -1004331642093, seconds=3, owner_name="Федя")
    assert message_id == 42
    assert len(sent) == 1
    assert "Старт через <b>3</b> сек." in sent[0]
    assert "Федя" in sent[0]
    assert any("Старт через <b>2</b> сек." in text for text in edited)
    assert "Перезапуск…" in edited[-1]
    assert "на месте" in edited[-1]


async def test_play_countdown_returns_none_when_send_fails() -> None:
    class BrokenBot:
        async def send_message(self, *args, **kwargs):
            raise RuntimeError("no chat")

    assert await play_countdown(BrokenBot(), -1, seconds=1) is None
