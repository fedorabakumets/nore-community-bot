from __future__ import annotations

import re
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
    "pogoda": ("погода",),
    "buycookies": ("купитьпеченьки",),
    "admin": ("админка",),
    "games": ("игры",),
    "cgames": ("печенеигры",),
    "blackjack": ("блэкджек",),
    "dice": ("кости", "кубик"),
    "roulette": ("рулетка",),
    "gamecancel": ("отменитьигру",),
    "crash": ("рейс", "взлёт", "взлет"),
    "trap": ("капкан", "налёт", "налет"),
    "mafia": ("мафия",),
    "bunker": ("бункер",),
    "purge": ("чистить", "очистить", "пурж"),
    "botsweep": ("чиститьбота", "убратьбота"),
    "transfer": ("трансфер",),
    "balance": ("баланс", "кошелек", "кошелёк"),
    "updates": ("обновления", "обновление"),
    "freebie": ("халява",),
    "id": ("айди",),
    "card": ("карточка",),
    "gift": ("подарить",),
    "report": ("репорт", "жалоба"),
    "mail": ("почта", "письмо"),
    "board": ("доска", "таблица"),
    "lottery": ("розыгрыш", "лотерея"),
    "lotterydraw": ("розыгрышитог", "итогрозыгрыша"),
    "mute": ("мут",),
    "unmute": ("размут",),
    "warn": ("варн", "пред"),
    "unwarn": ("разварн",),
    "kick": ("кик", "кикнуть"),
    "ban": ("бан", "забанить"),
    "unban": ("разбан",),
    "role": ("роль",),
    "givecookies": ("выдатьпеченьки",),
    "setcookies": ("сетпеченьки",),
}

MULTIWORD_ALIASES: dict[str, str] = {
    "купить печеньки": "buycookies",
    "задать вопрос": "question",
    "заполнить анкету": "apply",
    "отменить игру": "gamecancel",
    "розыгрыш итог": "lotterydraw",
    "итог розыгрыша": "lotterydraw",
    "чистить бота": "botsweep",
    "убрать бота": "botsweep",
}

_PUNCT = re.compile(r"^[^\w]+|[^\w]+$", re.UNICODE)
_SLASH_PREFIXES = "/!.／"

_ALIAS_TO_COMMAND: dict[str, str] = {}
for _command, _aliases in COMMAND_ALIASES.items():
    _ALIAS_TO_COMMAND[_command] = _command
    for _alias in _aliases:
        _ALIAS_TO_COMMAND[_alias.casefold()] = _command


def canonical_command(token: str) -> str | None:
    cleaned = _PUNCT.sub("", token).casefold()
    if not cleaned:
        return None
    from community_bot.command_registry import resolve_alias

    resolved = resolve_alias(cleaned)
    if resolved:
        return resolved
    return None


# Bare aliases that must match the whole message, not the first word.
# Slash commands like /shop still accept arguments.
# Ordinary words («вопрос», «магазин», «помощь») must not eat the rest of a sentence.
_EXACT_TEXT_COMMANDS = {
    "admin",
    "apply",
    "balance",
    "board",
    "bunker",
    "card",
    "cgames",
    "close",
    "commands",
    "freebie",
    "gamecancel",
    "games",
    "help",
    "id",
    "mafia",
    "mail",
    "pet",
    "pogoda",
    "profile",
    "question",
    "reputation",
    "roulette",
    "shop",
    "start",
    "store",
    "updates",
}

# These only do something in a private chat. Do not delete them from the group:
# a sentence or a lone «вопрос» is not a reason to erase the message.
_PRIVATE_CHAT_COMMANDS = frozenset({"apply", "close", "question", "start"})


def parse_trigger(text: str) -> tuple[str, str] | None:
    """Return (canonical_command, args) if the message starts with a command or alias."""
    raw = (text or "").strip()
    if not raw:
        return None
    folded = raw.casefold()
    from community_bot.command_registry import is_exact_slug, phrase_command

    phrase = phrase_command(folded)
    if phrase:
        command, alias = phrase
        if folded == alias:
            return command, ""
        if command in _EXACT_TEXT_COMMANDS or is_exact_slug(command):
            return None
        return command, raw[len(alias) :].strip()
    for alias, command in sorted(MULTIWORD_ALIASES.items(), key=lambda item: -len(item[0])):
        if folded == alias:
            return command, ""
        if folded.startswith(f"{alias} "):
            if command in _EXACT_TEXT_COMMANDS:
                return None
            return command, raw[len(alias) :].strip()
    first, _, rest = raw.partition(" ")
    token = first
    slash = token[:1] in _SLASH_PREFIXES
    if slash:
        token = token.lstrip(_SLASH_PREFIXES).split("@", 1)[0]
    command = canonical_command(token)
    if not command:
        return None
    if (command in _EXACT_TEXT_COMMANDS or is_exact_slug(command)) and not slash:
        body = _PUNCT.sub("", raw).casefold()
        from community_bot.command_registry import get_command

        view = get_command(command)
        live_aliases = view.aliases if view else ()
        allowed = {
            command,
            *(alias.casefold() for alias in COMMAND_ALIASES.get(command, ())),
            *(alias.casefold() for alias in live_aliases),
        }
        if body not in allowed:
            return None
        return command, ""
    return command, rest.strip()


def remainder_args(text: str) -> list[str]:
    parsed = parse_trigger(text)
    if parsed is None:
        parts = (text or "").split()
        return parts[1:] if parts else []
    _, args = parsed
    return args.split() if args else []


def remainder_text(text: str) -> str:
    return " ".join(remainder_args(text))


def is_command_trigger(text: str) -> bool:
    return parse_trigger(text) is not None


def is_command_message(text: str) -> bool:
    stripped = (text or "").lstrip()
    if not stripped:
        return False
    if stripped[:1] in _SLASH_PREFIXES:
        return True
    return is_command_trigger(stripped)


def message_has_media_payload(message: Message) -> bool:
    return bool(
        message.sticker
        or message.photo
        or message.video
        or message.video_note
        or message.voice
        or message.animation
        or message.audio
        or message.document
        or getattr(message, "paid_media", None)
    )


def is_group_command_to_sweep(message: Message) -> bool:
    """Delete only real commands. Media, stickers, voice and circles are never swept as commands."""
    caption = (message.caption or "").strip()
    text = (message.text or "").strip()
    if message_has_media_payload(message):
        source = caption
    else:
        source = text or caption
    if not source:
        return False
    parsed = parse_trigger(source)
    if source[:1] in {"/", "／"}:
        return not (parsed and parsed[0] in _PRIVATE_CHAT_COMMANDS)
    if not parsed:
        return False
    return parsed[0] not in _PRIVATE_CHAT_COMMANDS


class CommandOrAlias(Filter):
    """Match /command, /command@bot and a bare Russian/English alias in text or caption."""

    def __init__(self, *commands: str) -> None:
        self.commands = {item.casefold() for item in commands}

    async def __call__(self, message: Message, **kwargs: Any) -> bool | dict[str, Any]:
        del kwargs
        parsed = parse_trigger(message.text or message.caption or "")
        if not parsed:
            return False
        name, args = parsed
        if name not in self.commands:
            return False
        from community_bot.command_registry import get_command

        view = get_command(name)
        chat = getattr(message, "chat", None)
        chat_type = str(getattr(chat, "type", "") or "")
        if view is not None and not view.enabled:
            return False
        if view is not None and chat_type and not view.allows(chat_type):
            return False
        return {
            "command": CommandObject(
                prefix="/",
                command=name,
                mention=None,
                args=args or None,
            )
        }


def command_or_alias(*commands: str) -> Filter:
    # Only CommandOrAlias: aiogram Command() requires a leading slash and `bot: Bot`.
    # Nested in or_f it can fail before the alias filter ever runs.
    return CommandOrAlias(*commands)
