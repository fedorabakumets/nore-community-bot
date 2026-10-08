from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime

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


def _first_sentence(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return ""
    match = re.search(r"^.{20,}?[.!?]", clean)
    sentence = match.group(0) if match else clean
    if len(sentence) > 280:
        return sentence[:279].rsplit(" ", 1)[0] + "…"
    return sentence


def parse_onthisday(payload: dict[str, object]) -> list[DayEvent]:
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
        title = ""
        url = ""
        if isinstance(pages, list) and pages and isinstance(pages[0], dict):
            title = str(pages[0].get("title") or pages[0].get("normalizedtitle") or "").strip()
            content = pages[0].get("content_urls")
            if isinstance(content, dict):
                desktop = content.get("desktop")
                if isinstance(desktop, dict):
                    url = str(desktop.get("page") or "").strip()
        events.append(DayEvent(year=year, text=text, title=title, url=url))
    return events


def _score(event: DayEvent, today_year: int) -> float | None:
    blob = f"{event.text} {event.title}"
    if _GRIM.search(blob):
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
        "📅 <b>Этот день</b>",
        "",
        f"{today.day} {month} {event.year} года — {sentence}",
    ]
    if event.url and event.title:
        url = html.escape(event.url, quote=True)
        title = html.escape(event.title)
        lines.append(f"(<a href=\"{url}\">{title}</a>)")
    return "\n".join(lines)


async def fetch_day_events(today: date) -> list[DayEvent]:
    url = WIKI_URL.format(month=today.month, day=today.day)
    timeout = aiohttp.ClientTimeout(total=12)
    headers = {
        "User-Agent": "NoraCommunityBot/2.0 (telegram community bot; calendar note)",
        "Accept": "application/json",
    }
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError):
        logger.warning("Лента этого дня не ответила")
        return []
    if not isinstance(payload, dict):
        return []
    return parse_onthisday(payload)


async def day_note_text(moment: datetime) -> str | None:
    today = moment.date()
    event = pick_day_event(await fetch_day_events(today), today)
    if event is None:
        return None
    return render_day_note(today, event)
