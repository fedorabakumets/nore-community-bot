from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import quote, urlsplit

import aiohttp

from community_bot.morning import MONTHS

logger = logging.getLogger(__name__)

WIKI_URL = "https://ru.wikipedia.org/api/rest_v1/feed/onthisday/events/{month:02d}/{day:02d}"
_GRIM = re.compile(
    r"убил|убий|смерт|войн|расстрел|теракт|катастроф|голод|эпидем|блокад|"
    r"взрыв|пожар|землетряс|авар|трагед|казн|геноцид|оккупац|репресс|"
    r"концлагер|расчлен|изнасил|самоубий|крушен|бомб|расправ",
    re.IGNORECASE,
)
_LOCAL = re.compile(r"петербург|петроград|ленинград|росси|российск|русск|невск|москв|ссср|импер", re.IGNORECASE)
_CITY = re.compile(r"петербург|петроград|ленинград", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class DayEvent:
    year: int
    text: str
    title: str
    url: str
    context: str = ""
    month: int | None = None
    day: int | None = None


# Editorial entries: exact Gregorian dates and consequences checked against the linked source.
# They supplement the daily calendar; they are never rotated onto another date.
VERIFIED_EVENTS = {
    (10, 26): DayEvent(
        1930,
        "В Ленинграде впервые показали балет Шостаковича «Золотой век».",
        "Золотой век",
        "https://site.mariinsky.ru/about/exhibitions/shostakovich111/golden_age1930/",
        "Постановка стала площадкой для хореографических экспериментов. "
        "Впервые для работы над балетом здесь пригласили оперного режиссёра; "
        "впоследствии эта практика закрепилась в театре.",
        10, 26,
    ),
    (10, 27): DayEvent(
        2007,
        "В Петербурге началась первая конференция русскоязычной Википедии.",
        "Первая Вики-конференция",
        "https://ru.wikipedia.org/wiki/Википедия:Вики-конференция_2007/Итоговый_пресс-релиз",
        "В ИТМО встретились 90 участников из нескольких стран. Они обсудили проверку "
        "источников и авторские права, а по итогам предложили сделать конференцию ежегодной.",
        10, 27,
    ),
}


def _first_sentence(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return ""
    match = re.search(r"^.{20,}?[.!?]", clean)
    sentence = match.group(0) if match else clean
    if len(sentence) > 280:
        return sentence[:279].rsplit(" ", 1)[0] + "…"
    return sentence


def parse_onthisday(payload: dict[str, object], today: date | None = None) -> list[DayEvent]:
    raw = payload.get("events")
    if not isinstance(raw, list):
        return []
    events: list[DayEvent] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            year = int(item.get("year") or 0)
        except (TypeError, ValueError):
            continue
        text = str(item.get("text") or "").strip()
        if year <= 0 or not text:
            continue
        pages = item.get("pages")
        title, url, context = "", "", ""
        # The first linked page is often just a year or the city itself. Do not use
        # those generic descriptions as an explanation of this particular event.
        words = set(re.findall(r"[а-яё]{5,}", text.casefold()))
        ranked = []
        for page in pages if isinstance(pages, list) else []:
            if not isinstance(page, dict):
                continue
            name = str(page.get("title") or "").replace("_", " ")
            if re.fullmatch(r"\d+.*|Санкт-Петербург|Ленинград|Петроград", name, re.IGNORECASE):
                continue
            extract = str(page.get("extract") or "").strip()
            overlap = len(words & set(re.findall(r"[а-яё]{5,}", name.casefold())))
            content = page.get("content_urls") or {}
            desktop = content.get("desktop") or {} if isinstance(content, dict) else {}
            link = str(desktop.get("page") or "") if isinstance(desktop, dict) else ""
            if overlap and extract and urlsplit(link).scheme == "https":
                ranked.append((overlap, name, link, extract))
        if ranked:
            _, title, url, context = max(ranked)
        if not url and today:
            calendar_title = f"{today.day}_{MONTHS[today.month - 1]}"
            url = "https://ru.wikipedia.org/wiki/" + quote(calendar_title) + "#События"
        events.append(DayEvent(year, text, title, url, context,
                               today.month if today else None, today.day if today else None))
    return events


def _score(event: DayEvent, today_year: int) -> float | None:
    blob = f"{event.text} {event.title}"
    if _GRIM.search(blob) or not _CITY.search(event.text):
        return None
    if event.year >= today_year:
        return None
    age = min(today_year - event.year, 400)
    score = age / 20
    if _LOCAL.search(blob):
        score += 40
    if _CITY.search(blob):
        score += 25
    return score


def pick_day_event(events: list[DayEvent], today: date) -> DayEvent | None:
    ranked: list[tuple[float, int, DayEvent]] = []
    for event in events:
        if event.month is not None and (event.month, event.day) != (today.month, today.day):
            continue
        score = _score(event, today.year)
        if score is None:
            continue
        ranked.append((score, -event.year, event))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return ranked[0][2]


def render_day_note(today: date, event: DayEvent) -> str:
    sentence = html.escape(_first_sentence(event.text))
    month = MONTHS[today.month - 1]
    lines = [
        "📅 <b>Этот день в Петербурге</b>",
        "",
        "<blockquote expandable>",
        f"<b>{today.day} {month} {event.year} · {years_ago(today.year - event.year)}</b>",
        sentence,
    ]
    if event.context:
        lines.append(html.escape(_first_sentence(event.context)))
    if urlsplit(event.url).scheme == "https":
        url = html.escape(event.url, quote=True)
        lines.append(f'<a href="{url}">Подробнее</a>')
    lines.append("</blockquote>")
    return "\n".join(lines)


def years_ago(age: int) -> str:
    if 11 <= age % 100 <= 14:
        word = "лет"
    elif age % 10 == 1:
        word = "год"
    elif age % 10 in {2, 3, 4}:
        word = "года"
    else:
        word = "лет"
    return f"{age} {word} назад"


async def fetch_day_events(today: date) -> list[DayEvent]:
    url = WIKI_URL.format(month=today.month, day=today.day)
    timeout = aiohttp.ClientTimeout(total=12)
    headers = {
        "User-Agent": "NoraCommunityBot/2.0 (telegram community bot; calendar note)",
        "Accept": "application/json",
    }
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers, trust_env=True) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError):
        logger.warning("Лента этого дня не ответила")
        return []
    if not isinstance(payload, dict):
        return []
    return parse_onthisday(payload, today)


async def city_event_for(today: date) -> DayEvent | None:
    verified = VERIFIED_EVENTS.get((today.month, today.day))
    if verified and verified.year < today.year:
        return verified
    return pick_day_event(await fetch_day_events(today), today)


async def day_note_text(moment: datetime) -> str | None:
    today = moment.date()
    event = await city_event_for(today)
    if event is None:
        return None
    return render_day_note(today, event)
