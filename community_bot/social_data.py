from __future__ import annotations

import secrets

MAFIA_MIN, MAFIA_MAX = 5, 12
BUNKER_MIN, BUNKER_MAX = 4, 8
BUNKER_CAPACITY = 2

ROLE_LABELS = {
    "civilian": ("Мирный", "role_civilian", "Вы житель города. Найдите мафию днём и не дайте ей перевесить ночью."),
    "mafia": ("Мафия", "role_mafia", "Ночью выбирайте жертву вместе с командой. Днём притворяйтесь мирным."),
    "don": ("Дон", "role_mafia", "Вы глава мафии. Ночью решаете, кого убрать. Днём ведите своих."),
    "doctor": ("Доктор", "role_doctor", "Ночью можете спасти одного человека, в том числе себя."),
    "sheriff": ("Шериф", "role_sheriff", "Ночью проверяете одного игрока: мафия это или мирный."),
}

CATASTROPHES = (
    ("Ядерный закат", "Атмосфера отравлена. В бункере места хватит не всем — лишних выведут на поверхность."),
    ("Вечная зима", "Снаружи −70°. Кто останется за дверью, не доживёт до утра."),
    ("Чума приливов", "Вода поднимается с вирусом. Бункер — единственный сухой карман на сотни километров."),
    ("Тишина после вспышки", "Солнце выжгло технику. Выживают только те, кого пустят под бетон."),
    ("Красный туман", "Туман растворяет лёгкие. Фильтров в бункере мало — как и коек."),
)

PROFESSIONS = (
    "хирург",
    "инженер-ядерщик",
    "фермер",
    "повар",
    "психолог",
    "солдат",
    "химик",
    "радист",
    "юрист",
    "механик",
)
HEALTH = (
    "здоров",
    "астма",
    "сломанная рука",
    "диабет",
    "отличное зрение",
    "хромота",
    "сильный иммунитет",
)
HOBBIES = (
    "стрельба",
    "шахматы",
    "садоводство",
    "йога",
    "радиолюбитель",
    "кулинария",
    "карты",
)
BAGGAGE = (
    "аптечка",
    "набор семян",
    "пистолет",
    "фильтр для воды",
    "гитара",
    "канистра топлива",
    "пачка антибиотиков",
)
FACTS = (
    "умеет чинить генераторы",
    "панически боится темноты",
    "знает 4 языка",
    "не ест мясо",
    "служил 8 лет",
    "кладёт всех в споре",
    "храпит так, что не спят соседи",
)

EVENTS = (
    ("weather", "bunker_weather", "Шторм", "Снаружи ураган вырывает антенны. Кто останется за дверью — замерзнет."),
    (
        "external",
        "bunker_external",
        "Стук снаружи",
        "Кто-то бьёт в люк. Пускать опасно, не пустить — возможно, теряете врача.",
    ),
    ("meeting", "bunker_meeting", "Собрание", "Внутри кончается воздух. Нужно решить, кто занимает койку."),
    (
        "weather",
        "bunker_weather",
        "Кислотный дождь",
        "На поверхности капли жгут кожу. Выход закрыт до следующего круга.",
    ),
    ("external", "bunker_external", "Стая", "За люком слышен звериный хор. Припасы у двери уже не вернуть."),
)

REVEAL_ORDER = ("profession", "health", "hobby", "baggage", "fact")
REVEAL_LABELS = {
    "profession": "Профессия",
    "health": "Здоровье",
    "hobby": "Хобби",
    "baggage": "Багаж",
    "fact": "Факт",
}


def deal_mafia_roles(n: int) -> list[str]:
    if n < MAFIA_MIN:
        raise ValueError("too few")
    if n <= 6:
        mafia = 1
    elif n <= 9:
        mafia = 2
    else:
        mafia = 3
    roles = ["doctor", "sheriff"]
    if mafia >= 2:
        roles.append("don")
        roles.extend(["mafia"] * (mafia - 1))
    else:
        roles.append("mafia")
    roles.extend(["civilian"] * max(0, n - len(roles)))
    secrets.SystemRandom().shuffle(roles)
    return roles[:n]


def deal_bunker_card() -> dict[str, str]:
    return {
        "profession": secrets.choice(PROFESSIONS),
        "health": secrets.choice(HEALTH),
        "hobby": secrets.choice(HOBBIES),
        "baggage": secrets.choice(BAGGAGE),
        "fact": secrets.choice(FACTS),
    }


def pick_catastrophe() -> tuple[str, str]:
    return secrets.choice(CATASTROPHES)


def pick_event() -> tuple[str, str, str, str]:
    return secrets.choice(EVENTS)


def mafia_team(role: str) -> bool:
    return role in {"mafia", "don"}
