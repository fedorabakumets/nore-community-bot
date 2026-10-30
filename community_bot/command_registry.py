from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from community_bot.aliases import COMMAND_ALIASES

_WORD = re.compile(r"^[\w][\w \-]{0,40}$", re.UNICODE)

BUILTIN_TITLES: dict[str, tuple[str, str]] = {
    "commands": ("Команды", "Полный список команд."),
    "help": ("Помощь", "Короткая справка."),
    "start": ("Старт", "Приветствие в личке."),
    "apply": ("Анкета", "Заявка в сообщество."),
    "question": ("Вопрос", "Тикет модераторам, только в личке."),
    "close": ("Закрыть", "Закрыть открытый тикет."),
    "profile": ("Профиль", "Карточка участника."),
    "shop": ("Магазин", "Полки магазина."),
    "store": ("Стор", "Справка по полкам."),
    "reputation": ("Репутация", "Уровни и лимиты репутации."),
    "pet": ("Питомец", "Питомец и экспедиция."),
    "pogoda": ("Погода", "Погода в Петербурге сейчас и на ближайшие часы."),
    "buycookies": ("Купить печеньки", "Пакеты печенек через СБП."),
    "admin": ("Админка", "Админ-панель."),
    "games": ("Игры", "Правила игр."),
    "cgames": ("Печенеигры", "Игры на печеньки."),
    "blackjack": ("Блэкджек", "Партия в блэкджек на печеньки."),
    "dice": ("Кубик", "Партия в кости на печеньки."),
    "roulette": ("Рулетка", "Рулетка на мут."),
    "gamecancel": ("Отменить игру", "Отмена своей партии."),
    "crash": ("Рейс", "Рейс с растущим множителем."),
    "trap": ("Капкан", "Три двери: капкан и кладовая."),
    "mafia": ("Мафия", "Партия в мафию."),
    "bunker": ("Бункер", "Партия в бункер."),
    "purge": ("Чистка", "Удалить последние сообщения чата."),
    "botsweep": ("Чистка бота", "Удалить последние сообщения бота."),
    "transfer": ("Перевод", "Перевод печенек ответом."),
    "balance": ("Кошелёк", "Баланс, история, кредит."),
    "updates": ("Обновления", "Служебный список обновлений."),
    "freebie": ("Халява", "Печеньки за подписку на канал."),
    "id": ("Айди", "Telegram ID."),
    "card": ("Карточка", "Служебная карточка ответом."),
    "gift": ("Подарок", "Подарить товар ответом."),
    "report": ("Репорт", "Жалоба ответом на сообщение."),
    "bug": ("Баг", "Админская заметка об ошибке ответом на сообщение; журнал репортов."),
    "participants": ("Участники", "Участники текущего мероприятия и журнал оплат; по праву роли."),
    "stickers": ("Стикеры", "Набор стикеров Норы."),
    "mail": ("Почта", "Анонимное письмо модераторам."),
    "board": ("Доска", "Доска недели."),
    "lottery": ("Розыгрыш", "Розыгрыш печенек."),
    "lotterydraw": ("Итог розыгрыша", "Подвести итог розыгрыша."),
    "mute": ("Мут", "Закрыть человеку чат."),
    "unmute": ("Размут", "Снять мут."),
    "warn": ("Варн", "Предупреждение."),
    "unwarn": ("Разварн", "Снять предупреждение."),
    "kick": ("Кик", "Исключить из чата."),
    "ban": ("Бан", "Заблокировать в чате."),
    "unban": ("Разбан", "Снять блокировку."),
    "role": ("Роль", "Назначить роль."),
    "givecookies": ("Выдать печеньки", "Начислить печеньки."),
    "setcookies": ("Баланс печенек", "Поставить точный баланс."),
    "nora": ("Нора", "Ответ на обращение «Нора, …»: погода, новости, музыка, кино и вопрос про бота."),
}

NORA_OPTIONS = {"music_limit": "5", "news_limit": "2"}
OPTION_LABELS = {
    "music_limit": "Треков в чарте",
    "news_limit": "Новостей за раз",
}


@dataclass(slots=True)
class CommandView:
    slug: str
    title: str
    description: str
    aliases: tuple[str, ...]
    enabled: bool = True
    ttl: float | None = None
    scope: str = "both"
    reply_text: str = ""
    kind: str = "builtin"
    options: dict[str, str] = field(default_factory=dict)

    def allows(self, chat_type: str) -> bool:
        if self.scope == "group":
            return chat_type in {"group", "supergroup"}
        if self.scope == "private":
            return chat_type == "private"
        return True


_COMMANDS: dict[str, CommandView] = {}
_ALIAS: dict[str, str] = {}
_PHRASES: list[tuple[str, str]] = []
_READY = False
_DEFAULT_TTL = 30.0


def default_reply_ttl() -> float:
    return _DEFAULT_TTL


def set_default_reply_ttl(seconds: float) -> None:
    global _DEFAULT_TTL
    _DEFAULT_TTL = max(0.0, float(seconds))


def catalog_ttl(slug: str) -> float | None:
    if slug == "pogoda":
        return 60.0
    return None


def explicit_ttl(slug: str | None) -> float | None:
    if not slug:
        return None
    view = _COMMANDS.get(slug)
    if view is None or view.ttl is None:
        return None
    return view.ttl


def get_command(slug: str) -> CommandView | None:
    return _COMMANDS.get(slug)


def list_commands() -> list[CommandView]:
    return sorted(_COMMANDS.values(), key=lambda item: (item.kind != "builtin", item.title.casefold()))


def option_value(slug: str, key: str, fallback: str) -> str:
    view = _COMMANDS.get(slug)
    if view is None:
        return fallback
    return str(view.options.get(key) or fallback)


def nora_enabled() -> bool:
    view = _COMMANDS.get("nora")
    return True if view is None else view.enabled


def is_exact_slug(slug: str) -> bool:
    view = _COMMANDS.get(slug)
    return bool(view and view.kind == "custom")


def resolve_alias(token: str) -> str:
    """Slug, or empty string when the registry does not know this word."""
    if not _READY:
        return ""
    return _ALIAS.get(token, "")


def phrase_command(folded: str) -> tuple[str, str] | None:
    for alias, slug in _PHRASES:
        if folded == alias or folded.startswith(f"{alias} "):
            return slug, alias
    return None


def _builtin_view(slug: str) -> CommandView:
    title, description = BUILTIN_TITLES.get(slug, (slug, slug))
    aliases = COMMAND_ALIASES.get(slug, ())
    options = dict(NORA_OPTIONS) if slug == "nora" else {}
    return CommandView(
        slug=slug,
        title=title,
        description=description,
        aliases=tuple(aliases),
        ttl=catalog_ttl(slug),
        options=options,
    )


def restore_defaults() -> None:
    global _READY
    _COMMANDS.clear()
    slugs = set(COMMAND_ALIASES) | set(BUILTIN_TITLES)
    for slug in slugs:
        _COMMANDS[slug] = _builtin_view(slug)
    _reindex()
    _READY = True


def _reindex() -> None:
    _ALIAS.clear()
    _PHRASES.clear()
    for view in _COMMANDS.values():
        if not view.enabled:
            continue
        names = {view.slug, *view.aliases}
        for name in names:
            folded = name.casefold().strip()
            if not folded or folded == "нора":
                continue
            if " " in folded:
                _PHRASES.append((folded, view.slug))
            else:
                _ALIAS.setdefault(folded, view.slug)
    _PHRASES.sort(key=lambda item: len(item[0]), reverse=True)


def apply_override_row(row: dict[str, object]) -> None:
    slug = str(row.get("slug") or "").strip()
    if not slug or slug == "setstatus":
        return
    kind = str(row.get("kind") or "builtin")
    base = _COMMANDS.get(slug) if kind == "builtin" else None
    try:
        aliases_raw = json.loads(str(row.get("aliases_json") or "[]"))
    except json.JSONDecodeError:
        aliases_raw = []
    if isinstance(aliases_raw, list):
        aliases = tuple(str(item).strip() for item in aliases_raw if str(item).strip())
    else:
        aliases = ()
    try:
        options_raw = json.loads(str(row.get("options_json") or "{}"))
    except json.JSONDecodeError:
        options_raw = {}
    options = {str(key): str(value) for key, value in options_raw.items()} if isinstance(options_raw, dict) else {}
    if base is not None:
        options = {**base.options, **options}
    ttl_raw = row.get("ttl_seconds")
    ttl = None if ttl_raw is None else float(int(ttl_raw))
    if kind == "builtin" and ttl is None and base is not None:
        ttl = base.ttl
    title = str(row.get("title") or "").strip() or (base.title if base else slug)
    description = str(row.get("description") or "").strip() or (base.description if base else "")
    if not aliases and base is not None:
        aliases = base.aliases
    _COMMANDS[slug] = CommandView(
        slug=slug,
        title=title,
        description=description,
        aliases=aliases,
        enabled=bool(int(row.get("enabled") if row.get("enabled") is not None else 1)),
        ttl=ttl,
        scope=str(row.get("scope") or "both"),
        reply_text=str(row.get("reply_text") or ""),
        kind=kind if kind in {"builtin", "custom"} else "builtin",
        options=options,
    )


def apply_rows(rows: list[dict[str, object]]) -> None:
    for row in rows:
        apply_override_row(row)
    _reindex()


async def load_registry(db: object) -> None:
    from community_bot.database import Database

    if not isinstance(db, Database):
        return
    restore_defaults()
    raw = await db.get_bot_state("reply_ttl_default")
    if raw and raw.isdigit():
        set_default_reply_ttl(int(raw))
    apply_rows(await db.list_command_overrides())


def view_payload(view: CommandView) -> dict[str, object]:
    return {
        "kind": view.kind,
        "enabled": view.enabled,
        "title": view.title,
        "description": view.description,
        "aliases": list(view.aliases),
        "ttl_seconds": None if view.ttl is None else int(view.ttl),
        "scope": view.scope,
        "reply_text": view.reply_text,
        "options": dict(view.options),
    }


def clean_aliases(raw: str, *, slug: str) -> tuple[list[str] | None, str]:
    parts = re.split(r"[,;\n]+", raw)
    aliases: list[str] = []
    for part in parts:
        token = part.strip().casefold()
        if not token:
            continue
        if token in {"нора", slug}:
            continue
        if not _WORD.match(token):
            return None, "Слово вызова: буквы, цифры и пробел, до 40 знаков."
        if token not in aliases:
            aliases.append(token)
    if not aliases and slug.startswith("c_"):
        return None, "Нужно хотя бы одно слово вызова."
    return aliases, ""


def slug_for_alias(alias: str) -> str:
    from community_bot.permissions import slugify_role

    base = slugify_role(alias)[:18] or "cmd"
    slug = f"c_{base}"
    if slug not in _COMMANDS:
        return slug
    index = 2
    while f"{slug}{index}" in _COMMANDS:
        index += 1
    return f"{slug}{index}"[:24]


def alias_taken(alias: str, *, ignore: str = "") -> bool:
    folded = alias.casefold().strip()
    owner = _ALIAS.get(folded)
    if owner and owner != ignore:
        return True
    for phrase, slug in _PHRASES:
        if phrase == folded and slug != ignore:
            return True
    return False


restore_defaults()
