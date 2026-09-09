from __future__ import annotations

import contextlib
from collections.abc import Sequence

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from community_bot.ephemeral import keep_in_chat
from community_bot.helpers import user_link


def _player_name(player: dict[str, object]) -> str:
    return str(player.get("profile_name") or player.get("telegram_name") or player.get("username") or player["user_id"])


def mention_fragment(player: dict[str, object]) -> str:
    username = str(player.get("username") or "").strip().lstrip("@")
    name = _player_name(player)
    if username:
        return f"@{username}"
    return user_link(int(player["user_id"]), name)


def mentions_line(players: Sequence[dict[str, object]]) -> str:
    return " ".join(mention_fragment(player) for player in players)


async def notify_game_event(
    bot: Bot,
    chat_id: int,
    players: Sequence[dict[str, object]],
    group_text: str,
    dm_text: str,
) -> None:
    if not players:
        return
    tagged = f"{group_text}\n\n{mentions_line(players)}"
    with keep_in_chat():
        with contextlib.suppress(TelegramBadRequest, TelegramForbiddenError):
            await bot.send_message(chat_id, tagged, parse_mode="HTML")
    for player in players:
        with contextlib.suppress(TelegramBadRequest, TelegramForbiddenError):
            await bot.send_message(int(player["user_id"]), dm_text, parse_mode="HTML")
