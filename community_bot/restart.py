from __future__ import annotations

import asyncio
import contextlib
import html
import os
import sys
from typing import Any

RESTART_SECONDS = 10

_in_progress = False


def try_begin() -> bool:
    global _in_progress
    if _in_progress:
        return False
    _in_progress = True
    return True


def reset_guard() -> None:
    global _in_progress
    _in_progress = False


def countdown_text(seconds: int, *, done: bool = False, owner_name: str = "") -> str:
    who = html.escape(owner_name) if owner_name else "Владелец"
    if done or seconds <= 0:
        return (
            "🔄 <b>Перезапуск…</b>\n\n"
            f"{who} перезапустил бота. Сейчас вернусь — настройки, роли, флаги и печеньки на месте."
        )
    return (
        "🔄 <b>Перезапуск бота</b>\n\n"
        f"{who} перезапускает Нору. Это не сброс: роли, флаги, печеньки и журнал остаются.\n\n"
        f"Старт через <b>{int(seconds)}</b> сек."
    )


def relaunch_command() -> list[str]:
    return [sys.executable, "-m", "community_bot.main"]


def relaunch() -> None:
    os.execvp(sys.executable, relaunch_command())


async def play_countdown(
    bot: Any,
    chat_id: int,
    *,
    seconds: int = RESTART_SECONDS,
    owner_name: str = "",
) -> int | None:
    try:
        message = await bot.send_message(
            chat_id,
            countdown_text(seconds, owner_name=owner_name),
            parse_mode="HTML",
        )
    except Exception:
        return None
    message_id = getattr(message, "message_id", None)
    for remaining in range(seconds - 1, -1, -1):
        await asyncio.sleep(1)
        if message_id is None:
            continue
        with contextlib.suppress(Exception):
            await bot.edit_message_text(
                countdown_text(remaining, done=remaining <= 0, owner_name=owner_name),
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="HTML",
            )
    return message_id
