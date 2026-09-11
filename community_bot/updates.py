from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ANNOUNCE_LAYOUT = "photo-v1"


@dataclass(frozen=True, slots=True)
class UpdateSection:
    heading: str
    body: str
    example: str | None = None
    image: str | None = None


@dataclass(frozen=True, slots=True)
class BotUpdate:
    number: int
    slug: str
    title: str
    summary: str
    details: tuple[str, ...]
    teasers: tuple[str, ...] = field(default_factory=tuple)
    sections: tuple[UpdateSection, ...] = field(default_factory=tuple)
    staff_details: tuple[str, ...] = field(default_factory=tuple)


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
            "Команды можно писать по-русски: «команды», «профиль», «магазин».",
            "Справка /commands больше не показывает модераторские команды.",
            "Студия постов: шаблоны, медиа и цветные кнопки-ссылки.",
        ),
    ),
    BotUpdate(
        number=4,
        slug="ephemeral-aliases-admin-updates",
        title="Стирание команд и админские обновления",
        summary="Команды в чате стираются сразу, бот понимает слова без «/», список новинок — только в админке.",
        details=(
            "Сообщение-команда удаляется в тот же момент, как бот его увидел (нужны права админа на удаление).",
            "Работают слова без слэша: команды, профиль, магазин, тамагочи, игры, кости, блэкджек.",
            "Короткий ответ бота на команду исчезает через 30 секунд; лобби игр, рулетка, перевод и «халява» остаются.",
            "Блок «Обновления» убран из меню участников и перенесён в админ-панель.",
        ),
    ),
    BotUpdate(
        number=5,
        slug="wallet-alerts-studio-flags",
        title="Кошелёк, алерты игр и студия",
        summary="Кошелёк с кредитом, упоминания из мини-игр, голосования в студии и раздельные стикеры.",
        details=(
            "Мини-игры пишут отдельные упоминания в чат и в личку: лобби, вход, ход, итог, смена ставки.",
            "В лобби блэкджека и костей ставку можно сменить кнопками, пока набор открыт.",
            "Студия постов сохраняет жирный/курсив, аккуратные шаблоны и нативное голосование Telegram.",
            "В «Функциях» есть описания, отдельный фильтр стикеров и сброс до заводских.",
            "Команда «баланс» и кнопка «Кошелёк»: комиссия 10/20/30%, фарм тамагочи, история, кредит 100 🍪.",
        ),
    ),
    BotUpdate(
        number=6,
        slug="media-games-invite-fix",
        title="Медиа в чате, мини-игры и ссылка в заявке",
        summary="Стикеры, фото, ГС и кружки больше не стираются без фильтра. Мини-игры остаются, пока их не скроют.",
        details=(
            "Бот больше не удаляет медиа, стикеры, голосовые и кружки, если фильтр в админке выключен.",
            "Администраторам чата фильтры не применяются.",
            "Сообщения мини-игр не исчезают через 30 секунд: их можно скрыть кнопкой, итог уходит через 2 минуты.",
            "После одобрения заявки в личку приходит приглашение в сообщество.",
        ),
    ),
    BotUpdate(
        number=7,
        slug="living-nora",
        title="Репутация, магазин и тихий тамагочи",
        summary="Репутацию снова нужно заслуживать: новые входят серебром, золото — только за плюсы из чата.",
        teasers=(
            "🥈 Новые входят с 70, не с золота. Автохил не поднимает выше 89.",
            "🛡 В магазине щит на один −реп, плащ на сутки и титулы на карточке.",
            "🐾 Тамагочи больше не пишет в личку. Пинги голода — только в этот чат.",
        ),
        details=(
            "Новые участники начинают с серебра (70). Золото — только за плюсы из чата, автохил не выше 89.",
            "Бронза может только +реп (1 раз в день). Минус — с серебра. Одного человека — не чаще раза в сутки.",
            "В магазине: щит на один −реп, плащ на 24 часа, титулы. Еда питомца — обед и поилка.",
            "Тамагочи молчит и не пишет в личку. Пинги — в общий чат. Сытый питомец редко ловит один −реп в день.",
        ),
        sections=(
            UpdateSection(
                heading="🥈 Репутация снова живая",
                body=(
                    "Новые участники входят серебром: 70, не золотом. Каждый день в полночь по Москве "
                    "репутация поднимается на 5, но не выше 89. Золото (90+) бывает только если вас плюсуют в чате. "
                    "Бронза может только поддержать (+реп, 1 раз в день). Минус доступен с серебра. "
                    "Одного человека отмечают не чаще раза в сутки."
                ),
                example=(
                    "Маша только зашла — у неё сразу 70. Коля сидел на 86: утром стало 89, дальше автохил молчит. "
                    "Чтобы стать золотом, Коле нужен живой «+реп» в чате. Если минусануть того же человека дважды "
                    "за день, второй раз бот скажет подождать до завтра."
                ),
                image="reputation.png",
            ),
            UpdateSection(
                heading="🛡 Магазин: щит, плащ и титулы",
                body=(
                    "На полке репутации: щит на один удар −репа, плащ иммунитета на 24 часа и «поднять репутацию +10» "
                    "(не полный хил до сотни). На профиле — титулы, которые видно всем на карточке. "
                    "Еда питомца схлопнута до обеда и поилки."
                ),
                example=(
                    "Вас минусанули, щит вспыхнул — репутация на месте, щит сгорел. Следующий минус уже пройдёт, "
                    "если нет плаща. Купили титул «Ночная сова» — он появляется в профиле и в команде «карточка»."
                ),
                image="shop.png",
            ),
            UpdateSection(
                heading="🐾 Тихий тамагочи",
                body=(
                    "Питомец больше не разговаривает и не пишет в личку. Если проголодался — пинг в этот чат "
                    "примерно раз в 12 часов. За каждые 120 сообщений еда и вода тихо падают в инвентарь. "
                    "Сытый питомец редко (около 15%, раз в сутки) перехватывает один −реп — плюс больше не удваивает."
                ),
                example=(
                    "«Булочка» спит голодная — в чате появится «нужно покормить», не в личке. "
                    "Кнопки «Поговорить» больше нет: только накормить, напоить и переименовать."
                ),
                image="pet.png",
            ),
        ),
        staff_details=(
            "Админка собрана в четыре комнаты: очередь, люди, чат, система. На очереди виден счётчик анкет и платежей.",
            "В карточке человека: репутация, заметка модератора, титул недели. В чате команда «карточка» ответом.",
            "Витрина магазина и название мероприятия задаются из комнаты «Система».",
        ),
    ),
)


def latest_update() -> BotUpdate:
    return UPDATES[-1]


def announcement_key(item: BotUpdate) -> str:
    return f"{item.number}:{ANNOUNCE_LAYOUT}"


def updates_text() -> str:
    lines = [
        "✨ <b>Обновления НОРЫ</b>",
        "Служебная сводка для админов. Номер больше — новее. Участники этот блок не видят.",
        "",
    ]
    for item in reversed(UPDATES):
        lines.append(f"<b>№{item.number} · {item.title}</b>")
        lines.append(item.summary)
        lines.extend(f"• {line}" for line in item.details)
        lines.extend(f"• {line}" for line in item.staff_details)
        lines.append("")
    lines.append("Открывается только из админ-панели.")
    return "\n".join(lines).strip()


def community_announcement(item: BotUpdate) -> str:
    lines = [
        f"✨ <b>Обновление №{item.number}</b>",
        f"<b>{item.title}</b>",
        "",
        item.summary,
    ]
    if item.teasers:
        lines.append("")
        lines.extend(item.teasers)
    lines.extend(["", "Подробности, примеры и картинки — кнопка ниже."])
    return "\n".join(lines)


def member_details_text(item: BotUpdate) -> str:
    lines = [
        f"✨ <b>Обновление №{item.number}</b>",
        f"<b>{item.title}</b>",
        "",
        item.summary,
        "",
    ]
    if item.sections:
        for section in item.sections:
            lines.append(f"<b>{section.heading}</b>")
            lines.append(section.body)
            if section.example:
                lines.append("")
                lines.append(f"<i>Пример.</i> {section.example}")
            lines.append("")
    else:
        lines.extend(f"• {line}" for line in item.details)
    return "\n".join(lines).strip()


def member_details_nodes(
    item: BotUpdate,
    image_urls: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    urls = image_urls or {}
    nodes: list[dict[str, Any]] = [
        {"tag": "h3", "children": [f"Обновление №{item.number}"]},
        {"tag": "h4", "children": [item.title]},
        {"tag": "p", "children": [item.summary]},
    ]
    sections = item.sections or tuple(
        UpdateSection(heading="", body=line) for line in item.details
    )
    for section in sections:
        if section.heading:
            nodes.append({"tag": "h4", "children": [section.heading]})
        image_url = urls.get(section.image or "")
        if image_url:
            nodes.append(
                {
                    "tag": "figure",
                    "children": [
                        {"tag": "img", "attrs": {"src": image_url}},
                    ],
                }
            )
        if section.body:
            nodes.append({"tag": "p", "children": [section.body]})
        if section.example:
            nodes.append({"tag": "blockquote", "children": [f"Пример. {section.example}"]})
    return nodes
