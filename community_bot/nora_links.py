"""Navigation from bot replies to the corresponding Mini App screens."""
from __future__ import annotations

import re

from aiogram.exceptions import TelegramAPIError
from aiogram.types import InputRichBlockButtons, RichMessageButton

_PROFILE = {"profile", "card", "menu:profile", "👤 мой профиль"}
_PROFILE_PREFIXES = ("profile:", "profile_action:", "profile_transfer:")
_SHOP_ACTIONS = {"shop", "store", "gift", "menu:shop", "shop:home", "shop:close"}
_SCREENS = {
    "pet": "pet", "menu:pet": "pet", "menu:notices": "notices",
    "games": "games", "cgames": "games", "mafia": "mafia", "crash": "rocket",
    "participants": "events", "events": "events", "community": "community",
}


def profile_reply(action: str, buttons: set[str], state: str | None = None) -> bool:
    return (action in _PROFILE or action.startswith(_PROFILE_PREFIXES)
            or any(button.startswith(_PROFILE_PREFIXES) for button in buttons)
            or bool(state and state.startswith("ProfileEdit:")))


def reply_destination(action: str, buttons: set[str], text: str) -> tuple[str, str]:
    text = text.casefold()
    if (action in {"balance", "menu:wallet", "buycookies", "shop:buy_cookies"}
            or action.startswith(("wallet:", "cookies:sbp:"))
            or any(button.startswith("cookies:sbp:") for button in buttons)
            or "недостаточно печенек" in text or "не хватает печенек" in text):
        return "Пополнить через Нору", "nora_to_cookies"
    category = re.fullmatch(r"shop:cat:([a-zA-Z0-9_-]{1,64})", action)
    if category:
        return "Купить через Нору", f"nora_cat_{category[1]}"
    if action in _SHOP_ACTIONS or "shop:buy_cookies" in buttons or action.startswith("shop:"):
        sku = re.fullmatch(r"shop:(?:g:)?([a-zA-Z0-9_-]{1,64})", action)
        if sku and action not in _SHOP_ACTIONS:
            return "Купить через Нору", f"nora_item_{sku[1]}"
        return "Купить через Нору", "nora_to_shop"
    if action == "cinema":
        return "Открыть в Норе", "nora_lobby"
    if action == "commands_guide":
        return "гайд по командам", "nora_to_commands"
    screen = _SCREENS.get(action)
    if action.startswith("pet:"):
        screen = "pet"
    elif action.startswith(("game:", "cg:", "roulette:")):
        screen = "games"
    return "Открыть в Норе", f"nora_to_{screen}" if screen else ""


async def nora_link_block(bot, action: str, buttons: set[str], text: str) -> InputRichBlockButtons | None:
    try:
        username = (await bot.me()).username
    except TelegramAPIError:
        return None
    if not username:
        return None
    label, target = reply_destination(action, buttons, text)
    suffix = f"startapp={target}" if target else "startapp"
    return InputRichBlockButtons(align="center", buttons=[
        RichMessageButton(text=label, url=f"https://t.me/{username}?{suffix}", style="primary"),
    ])
