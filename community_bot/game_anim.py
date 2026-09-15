from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message

from community_bot.blocks import edit_block

LOBBY_INTERVAL = 1.7
_HEADS = (
    "✦ · · · 🍪 · · · ✦",
    "· ✦ · · 🍪 · · ✦ ·",
    "· · ✦ · 🍪 · ✦ · ·",
    "· · · ✦ 🍪 ✦ · · ·",
    "✧ · · · ✨🍪✨ · · · ✧",
    "· · · ✦ 🍪 ✦ · · ·",
    "· · ✦ · 🍪 · ✦ · ·",
    "· ✦ · · 🍪 · · ✦ ·",
)
_BARS = (
    "░▒▓██████▓▒░",
    "▒▓██████▓▒░▒",
    "▓██████▓▒░▒▓",
    "██████▓▒░▒▓█",
    "█████▓▒░▒▓██",
    "████▓▒░▒▓███",
    "███▓▒░▒▓████",
    "██▓▒░▒▓█████",
)

_JOBS: dict[int, asyncio.Task[None]] = {}
_LOCKS: dict[int, asyncio.Lock] = {}


def decorate(body: str, frame: int) -> str:
    head = _HEADS[frame % len(_HEADS)]
    bar = _BARS[frame % len(_BARS)]
    return f"<code>{head}</code>\n<code>{bar}</code>\n\n{body}"


def _lock(game_id: int) -> asyncio.Lock:
    lock = _LOCKS.get(game_id)
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[game_id] = lock
    return lock


def stop_lobby_anim(game_id: int) -> None:
    task = _JOBS.pop(game_id, None)
    if task and not task.done():
        task.cancel()


async def edit_lobby_now(
    message: Message,
    game_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    async with _lock(game_id):
        with suppress(TelegramBadRequest):
            await edit_block(message, text, parse_mode="HTML", reply_markup=markup)


def start_lobby_anim(
    message: Message,
    game_id: int,
    render: Callable[[int], Awaitable[str]],
    markup: Callable[[], InlineKeyboardMarkup | None] | None = None,
    interval: float = LOBBY_INTERVAL,
) -> None:
    stop_lobby_anim(game_id)

    async def _loop() -> None:
        current = asyncio.current_task()
        frame = 1
        try:
            while True:
                await asyncio.sleep(interval)
                text = await render(frame)
                keyboard = markup() if markup else None
                await edit_lobby_now(message, game_id, text, keyboard)
                frame += 1
        except asyncio.CancelledError:
            raise
        finally:
            if _JOBS.get(game_id) is current:
                _JOBS.pop(game_id, None)

    _JOBS[game_id] = asyncio.create_task(_loop())
