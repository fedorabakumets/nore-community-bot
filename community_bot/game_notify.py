from __future__ import annotations

from typing import Any

from aiogram.types import Message

from community_bot.ephemeral import expire_game_result, keep_in_chat
from community_bot.helpers import user_link
from community_bot.keyboards import game_hide_keyboard


def _player_name(player: dict[str, object]) -> str:
    return str(player.get("profile_name") or player.get("telegram_name") or player.get("username") or player["user_id"])


def mention_fragment(player: dict[str, object]) -> str:
    username = str(player.get("username") or "").strip().lstrip("@")
    name = _player_name(player)
    if username:
        return f"@{username}"
    return user_link(int(player["user_id"]), name)


async def send_game_finale(target: Message, text: str, **kwargs: Any) -> Message:
    kwargs.setdefault("reply_markup", game_hide_keyboard())
    kwargs.setdefault("parse_mode", "HTML")
    with keep_in_chat():
        sent = await target.answer(text, **kwargs)
    expire_game_result(sent)
    return sent
