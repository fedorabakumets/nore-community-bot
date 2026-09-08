from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BotUpdate:
    number: int
    slug: str
    title: str
    summary: str
    details: tuple[str, ...]


UPDATES: tuple[BotUpdate, ...] = (
    BotUpdate(
        number=1,
        slug="colors-shelves",
        title="Цвета, полки и тамагочи",
        summary="Цветные кнопки, полки магазина и карточка профиля с приватностью.",
        details=(
            "Зелёные, синие и красные кнопки в магазине, играх и профиле.",
            "Полки: тамагочи, репутация, профиль и мероприятия.",
            "Приватный и кастомный профиль покупаются за 🍪.",
        ),
    ),
    BotUpdate(
        number=2,
        slug="roles-games-menu",
        title="Роли, игры и нижнее меню",
        summary="Свои роли в админке, блэкджек и кости на 🍪, кнопки «Профиль» и «Меню».",
        details=(
            "Внизу лички всегда зелёный «Профиль» и синее «Меню» — даже во время анкеты.",
            "Кастомные роли с тумблерами прав вместо жёстких admin/moderator.",
            "Игры на печеньки на 2–4 человека: /blackjack, /dice или «кости».",
            "Сытый питомец может съесть −реп или удвоить +реп; принос 🍪 пишется в чат.",
        ),
    ),
    BotUpdate(
        number=3,
        slug="audit-commands-studio",
        title="Журнал, команды и студия",
        summary="Понятный журнал модерации, русские команды и расширенные посты в чат.",
        details=(
            "Журнал аудита: кто, что сделал и статус 🟢🟡🔴.",
            "Команды можно писать по-русски: «команды», «профиль», «магазин», «обновления».",
            "Справка /commands больше не показывает модераторские команды.",
            "Студия постов: шаблоны, медиа и цветные кнопки-ссылки.",
            "Команды в чате удаляются сразу, ответы бота — через 30 секунд (кроме магазинов и игр).",
        ),
    ),
)


def latest_update() -> BotUpdate:
    return UPDATES[-1]


def updates_text() -> str:
    lines = [
        "✨ <b>Обновления НОРЫ</b>",
        "Сводка того, что уже работает. Номер больше — новее.",
        "",
    ]
    for item in reversed(UPDATES):
        lines.append(f"<b>№{item.number} · {item.title}</b>")
        lines.append(item.summary)
        lines.extend(f"• {line}" for line in item.details)
        lines.append("")
    lines.append("Написать боту «обновления» можно в любой момент.")
    return "\n".join(lines).strip()


def community_announcement(item: BotUpdate) -> str:
    return (
        f"✨ <b>Обновление №{item.number} «{item.title}»</b> уже доступно.\n\n"
        f"{item.summary}\n\n"
        "Узнать больше — напишите боту <b>обновления</b> или откройте это в «Меню»."
    )
