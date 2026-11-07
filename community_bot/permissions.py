from __future__ import annotations

import json
import re

PERM_ADMIN_PANEL = "admin.panel"
PERM_APPLICATIONS = "applications"
PERM_PAYMENTS = "payments"
PERM_TICKETS = "tickets"
PERM_ROLES_ASSIGN = "roles.assign"
PERM_ROLES_EDIT = "roles.edit"
PERM_USERS_EDIT = "users.edit"
PERM_USERS_COOKIES = "users.cookies"
PERM_MUTE = "mod.mute"
PERM_WARN = "mod.warn"
PERM_KICK = "mod.kick"
PERM_BAN = "mod.ban"
PERM_CHAT_LOCK = "chat.lock"
PERM_BROADCAST = "chat.broadcast"
PERM_MENTION = "chat.mention"
PERM_POST = "chat.post"
PERM_EVENT_PARTICIPANTS = "events.participants"
PERM_FEATURES = "features"
PERM_AUTOMESSAGES = "automessages"
PERM_AUDIT = "audit"
PERM_GAMES = "games.admin"
PERM_SEE_PRIVATE = "profile.see_private"
PERM_PURGE = "mod.purge"
PERM_CONTEST = "contest.cookies"
PERM_COMMANDS = "commands.studio"

PERMISSIONS: tuple[tuple[str, str], ...] = (
    (PERM_ADMIN_PANEL, "Админ-панель"),
    (PERM_APPLICATIONS, "Анкеты"),
    (PERM_PAYMENTS, "Платежи СБП"),
    (PERM_TICKETS, "Тикеты"),
    (PERM_ROLES_ASSIGN, "Назначать роли людям"),
    (PERM_ROLES_EDIT, "Создавать и править роли"),
    (PERM_USERS_EDIT, "Править профили"),
    (PERM_USERS_COOKIES, "Начислять 🍪"),
    (PERM_MUTE, "Мут"),
    (PERM_WARN, "Варны"),
    (PERM_KICK, "Кик"),
    (PERM_BAN, "Бан / разбан"),
    (PERM_CHAT_LOCK, "Общий мут чата"),
    (PERM_BROADCAST, "Рассылка в ЛС"),
    (PERM_MENTION, "Упомянуть всех"),
    (PERM_POST, "Пост в сообщество"),
    (PERM_EVENT_PARTICIPANTS, "Мероприятия: участники и журнал оплат"),
    (PERM_FEATURES, "Функции и флаги"),
    (PERM_AUTOMESSAGES, "Автосообщения"),
    (PERM_AUDIT, "Журнал"),
    (PERM_GAMES, "Отмена игр"),
    (PERM_SEE_PRIVATE, "Видеть скрытые профили"),
    (PERM_PURGE, "Чистить сообщения чата"),
    (PERM_CONTEST, "Конкурс на печеньки"),
    (PERM_COMMANDS, "Команды бота"),
)

PERMISSION_KEYS = [key for key, _ in PERMISSIONS]

_MODERATOR = [
    PERM_ADMIN_PANEL,
    PERM_APPLICATIONS,
    PERM_TICKETS,
    PERM_MUTE,
    PERM_WARN,
    PERM_KICK,
    PERM_SEE_PRIVATE,
]
_OWNER_ONLY_DEFAULT = {PERM_ROLES_EDIT, PERM_CONTEST}
_ADMIN = [key for key in PERMISSION_KEYS if key not in _OWNER_ONLY_DEFAULT]

DEFAULT_STAFF_ROLES: tuple[tuple[str, str, int, list[str], int], ...] = (
    ("member", "Участник", 0, [], 1),
    ("moderator", "Модератор", 40, _MODERATOR, 1),
    ("admin", "Админ", 70, _ADMIN, 1),
    ("owner", "Владелец", 100, ["*"], 1),
)

BUILTIN_ROLE_SLUGS = {"member", "moderator", "admin", "owner"}

_CYRILLIC = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def permission_label(key: str) -> str:
    return next((label for perm, label in PERMISSIONS if perm == key), key)


def dump_permissions(perms: list[str]) -> str:
    unique = []
    seen: set[str] = set()
    for item in perms:
        if item not in seen:
            unique.append(item)
            seen.add(item)
    return json.dumps(unique, ensure_ascii=False)


def parse_permissions(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if item]


def role_has_permission(perms: list[str], key: str) -> bool:
    return "*" in perms or key in perms


def slugify_role(name: str) -> str:
    chars: list[str] = []
    for char in name.strip().casefold():
        if char in _CYRILLIC:
            chars.append(_CYRILLIC[char])
        elif char.isascii() and char.isalnum():
            chars.append(char)
        elif char in {" ", "-", "_"}:
            chars.append("_")
    slug = re.sub(r"_+", "_", "".join(chars)).strip("_")[:24]
    return slug or "role"
