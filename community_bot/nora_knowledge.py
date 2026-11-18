"""Member-facing facts for the conversational assistant."""

from __future__ import annotations

import re
from functools import cache

from community_bot.chat_memory import extract_search_terms
from community_bot.domain import ai_limits_text
from community_bot.updates import UPDATES

_RELEASE_WORD = re.compile(r"\b(?:обнов(?:а|у|ы|е|л[а-яё]+)|релиз\w*|выпуск\w*|патч\w*)\b", re.IGNORECASE)
_FEATURE = re.compile(
    r"\b(?:кинотеатр|лобби|таверн|тамагочи|питом|печен|репутац|мини.?апп|старт[её]р.пак|поднебес|"
    r"воспоминани|обсерватори|морск\w+ бо[йяю])",
    re.IGNORECASE,
)


def is_release_question(prompt: str) -> bool:
    return bool(_RELEASE_WORD.search(prompt))


def is_nora_topic(prompt: str) -> bool:
    return is_release_question(prompt) or bool(_FEATURE.search(prompt))


@cache
def _journal() -> str:
    return "\n".join(f"№{item.number} · {item.journal_date} · {item.title}. {item.summary}" for item in UPDATES)


@cache
def _public_details() -> tuple[str, ...]:
    return tuple(
        "\n".join((
            f"№{item.number} · {item.journal_date} · {item.title}",
            *item.details,
            *(f"{section.heading}. {section.body}" for section in item.sections),
        ))
        for item in UPDATES
    )


def nora_knowledge(question: str) -> str:
    text = question.casefold()
    numbers = {
        int(number)
        for number in re.findall(r"(?:№\s*|#\s*|(?:обновлени\w*|релиз\w*|выпуск\w*)\s+)(\d{1,3})\b", text)
    }
    if is_release_question(question) and any(word in text for word in ("последн", "свеж", "новейш", "сейчас")):
        numbers.add(UPDATES[-1].number)
    terms = {word[:5] for word in extract_search_terms(text) if len(word) >= 4}
    terms.difference_update({"обнов", "релиз", "выпус", "каком", "какие", "после"})
    scores = []
    for item, details in zip(UPDATES, _public_details(), strict=True):
        title = f"{item.title} {item.summary}".casefold()
        body = details.casefold()
        score = sum(3 * (term in title) + (term in body) for term in terms)
        if item.journal_date in text:
            score += 30
        if item.number in numbers:
            score += 100
        if score and (numbers or is_nora_topic(question)):
            scores.append((score, item.number, details))
    relevant = "\n\n".join(details[:4200] for _, _, details in sorted(scores, reverse=True)[:3])
    return (
        "Актуальная справка сообщества. При расхождении она важнее старых анонсов.\n"
        "Нора — закрытое петербургское сообщество с входом по анкете. Mini App объединяет главную, "
        "магазин, сообщество, события и личный профиль. Печеньки 🍪 — внутренняя валюта магазина, "
        "подарков, переводов и некоторых игр. Репутация влияет на скидку и отметки +реп/−реп. "
        "В Норе есть друзья, сезонные коллекции, Морской бой, Мафия и 3D-игра. "
        "В лобби есть выходы к таверне, на остров и в «Воспоминание». "
        "Первое прохождение «Воспоминания» приносит 50 🍪 с учётом прежнего приза за обсерваторию. "
        "Чат игры связан с Telegram. В кинотеатре общий сеанс с YouTube, MP4 и видео из группы.\n"
        "Питомец уходит на 24 часа. Досрочный возврат через «Питомец» в боте или Mini App "
        "сразу восстанавливает доступные функции, при этом поход заканчивается без награды и возмещения ухода. "
        "Видео открывается на 3 уровне питомца, личный разговор с ИИ — на 2 уровне. "
        "В основном чате ИИ и память доступны всем участникам с репутацией бронза и выше. "
        f"Лимит запросов ИИ в день по репутации: {ai_limits_text()}. Сброс в полночь по часовому поясу сообщества. "
        "В походе владельцу временно недоступны ИИ и скачивание видео. "
        "Из истории Нора видит сохранённый текст и подписи к медиа основного чата за 48 часов.\n"
        "Журнал публичных обновлений. Даты относятся к появлению записи в ветке выпуска. "
        "Они не подтверждают час доставки объявления в Telegram.\n"
        f"{_journal()}\n\nПодробности по теме вопроса:\n{relevant}"
    )
