from __future__ import annotations

from typing import Any

from aiogram.filters import Filter
from aiogram.filters.command import CommandObject
from aiogram.types import Message

# Canonical English/Latin command → Russian (and extra) spoken aliases.
# Staff aliases exist so moderators can type them, but they are not listed in /commands.
COMMAND_ALIASES: dict[str, tuple[str, ...]] = {
    "commands": ("команды", "справка"),
    "help": ("помощь", "хелп"),
    "start": ("старт",),
    "apply": ("анкета", "заявка"),
    "question": ("вопрос",),
    "close": ("закрыть",),
    "profile": ("профиль",),
    "shop": ("магазин",),
    "store": ("стор", "магазинсправка"),
    "reputation": ("репутация",),
    "pet": ("тамагочи", "питомец", "пет"),
    "buycookies": ("купитьпеченьки",),
    "admin": ("админка",),
    "games": ("игры",),
    "cgames": ("печенеигры",),
    "blackjack": ("блэкджек",),
    "dice": ("кости",),
    "roulette": ("рулетка",),
    "gamecancel": ("отменитьигру",),
    "transfer": ("трансфер",),
    "updates": ("обновления", "обновление"),
    "freebie": ("халява",),
    "id": ("айди",),
    "mute": ("мут",),
    "unmute": ("размут",),
    "warn": ("варн", "пред"),
    "unwarn": ("разварн",),
    "kick": ("кик", "кикнуть"),
    "ban": ("бан", "забанить"),
    "unban": ("разбан",),
    "role": ("роль",),
    "setstatus": ("сетстатус",),
    "givecookies": ("выдатьпеченьки",),
    "setcookies": ("сетпеченьки",),
}

MULTIWORD_ALIASES: dict[str, str] = {
    "купить печеньки": "buycookies",
    "задать вопрос": "question",
    "заполнить анкету": "apply",
    "отменить игру": "gamecancel",
}

_ALIAS_TO_COMMAND: dict[str, str] = {}
for _command, _aliases in COMMAND_ALIASES.items():
    _ALIAS_TO_COMMAND[_command] = _command
    for _alias in _aliases:
        _ALIAS_TO_COMMAND[_alias.casefold()] = _command


def canonical_command(token: str) -> str | None:
    return _ALIAS_TO_COMMAND.get(token.casefold())


def parse_trigger(text: str) -> tuple[str, str] | None:
    """Return (canonical_command, args) if the message starts with a command or alias."""
    raw = (text or "").strip()
    if not raw:
        return None
    folded = raw.casefold()
    for alias, command in sorted(MULTIWORD_ALIASES.items(), key=lambda item: -len(item[0])):
        if folded == alias or folded.startswith(f"{alias} "):
            return command, raw[len(alias) :].strip()
    first, _, rest = raw.partition(" ")
    token = first
    if token.startswith("/"):
        token = token[1:].split("@", 1)[0]
    command = canonical_command(token)
    if not command:
        return None
    return command, rest.strip()


def remainder_args(text: str) -> list[str]:
    parsed = parse_trigger(text)
    if parsed is None:
        parts = (text or "").split()
        return parts[1:] if parts else []
    _, args = parsed
    return args.split() if args else []


def is_command_trigger(text: str) -> bool:
    return parse_trigger(text) is not None


class CommandOrAlias(Filter):
    def __init__(self, *commands: str) -> None:
        self.commands = {item.casefold() for item in commands}

    async def __call__(self, message: Message) -> bool | dict[str, Any]:
        parsed = parse_trigger(message.text or "")
        if not parsed:
            return False
        name, args = parsed
        if name not in self.commands:
            return False
        return {
            "command": CommandObject(
                prefix="/",
                command=name,
                mention=None,
                args=args or None,
            )
        }


def command_or_alias(*commands: str) -> CommandOrAlias:
    return CommandOrAlias(*commands)
