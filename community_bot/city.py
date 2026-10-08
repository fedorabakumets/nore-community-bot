from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import LinkPreviewOptions

from community_bot.config import Settings
from community_bot.database import Database

logger = logging.getLogger(__name__)

USER_AGENT = "NoreCommunityBot/1.0"
SPB_LATITUDE = 59.9343
SPB_LONGITUDE = 30.3351
TRAFFIC_URL = "https://export.yandex.ru/bar/reginfo.xml?region=2"
METRO_URL = "https://metro.spb.ru/rejimrabotystancii.html"
NEWS_URL = "https://www.fontanka.ru/rss-feeds/zen-news.xml"
FALLBACK_CLOSED_STATIONS = ("Парк Победы", "Фрунзенская")
DIGEST_WINDOW_HOURS = 4
NEWS_LIMIT = 2
_CONTENT_TAG = "{http://purl.org/rss/1.0/modules/content/}encoded"
_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
_LOCAL_MARKERS = (
    "петербург",
    "петербурж",
    "спб",
    "питер",
    "невск",
    "василеостров",
    "петроград",
    "красногвард",
    "красносель",
    "калининск",
    "фрунзенск",
    "колпин",
    "пушкин",
    "петергоф",
    "кронштадт",
    "сестрорецк",
    "зеленогорск",
    "павловск",
    "шушар",
    "кудрово",
    "мурино",
    "девяткино",
    "парнас",
    "купчино",
    "лахт",
    "крестовск",
    "метро",
    "проспект",
    "набережн",
    "улице",
    "улица",
)
_WEATHER_PHRASES = {
    0: "ясно",
    1: "преимущественно ясно",
    2: "переменная облачность",
    3: "облачно",
    45: "туман",
    48: "туман",
    51: "слабая морось",
    53: "морось",
    55: "сильная морось",
    56: "ледяная морось",
    57: "сильная ледяная морось",
    61: "небольшой дождь",
    63: "дождь",
    65: "сильный дождь",
    66: "ледяной дождь",
    67: "сильный ледяной дождь",
    71: "небольшой снег",
    73: "снег",
    75: "сильный снег",
    77: "снежные зёрна",
    80: "небольшой ливень",
    81: "ливень",
    82: "сильный ливень",
    85: "небольшой снегопад",
    86: "сильный снегопад",
    95: "гроза",
    96: "гроза с градом",
    99: "гроза с сильным градом",
}
_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


@dataclass(frozen=True, slots=True)
class NewsItem:
    title: str
    link: str
    published: datetime
    lead: str

    @property
    def body(self) -> str:
        return self.lead or self.title


def weather_url() -> str:
    return (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={SPB_LATITUDE}&longitude={SPB_LONGITUDE}"
        "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation"
        "&hourly=temperature_2m,weather_code"
        "&forecast_days=2&timezone=Europe%2FMoscow&wind_speed_unit=ms"
    )


def is_weather_text(text: str | None) -> bool:
    if not isinstance(text, str):
        return False
    raw = text.strip()
    if not raw:
        return False
    if raw.startswith("/"):
        token = raw[1:].split(maxsplit=1)[0]
        if raw[1:].strip() != token:
            return False
        command = token.split("@", 1)[0]
        return command.casefold() in {"pogoda", "погода"}
    return raw.casefold().strip("!?.…") == "погода"


def digest_is_due(now: datetime, hour: int, sent_date: str | None, window_hours: int = DIGEST_WINDOW_HOURS) -> bool:
    if sent_date == now.date().isoformat():
        return False
    end = min(24, hour + window_hours)
    return hour <= now.hour < end


def format_temp(value: float) -> str:
    rounded = round_half_away_from_zero(value)
    if rounded > 0:
        return f"+{rounded}°"
    return f"{rounded}°"


def round_half_away_from_zero(value: float) -> int:
    if value >= 0:
        return int(value + 0.5)
    return int(value - 0.5)


def weather_phrase(code: int) -> str:
    return _WEATHER_PHRASES.get(code, "без уточнения")


def weather_emoji(code: int) -> str:
    if code in {0, 1}:
        return "☀️"
    if code == 2:
        return "🌤"
    if code == 3:
        return "☁️"
    if code in {45, 48}:
        return "🌫"
    if code in {71, 73, 75, 77, 85, 86}:
        return "❄️"
    if code in {95, 96, 99}:
        return "⛈"
    if code >= 51:
        return "🌧"
    return "🌤"


def render_weather_brief(payload: dict) -> str:
    current = payload["current"]
    code = int(current["weather_code"])
    return f"{weather_emoji(code)} {format_temp(float(current['temperature_2m']))}, {weather_phrase(code)}"


def render_weather_detail(payload: dict, now: datetime) -> str:
    current = payload["current"]
    code = int(current["weather_code"])
    phrase = weather_phrase(code)
    wind = round_half_away_from_zero(float(current["wind_speed_10m"]))
    precipitation = float(current["precipitation"])
    rain = "Осадков нет" if precipitation < 0.1 else f"Осадки {precipitation:.1f} мм"
    lines = [
        f"{weather_emoji(code)} <b>Погода в Петербурге</b>",
        "",
        f"Сейчас: {format_temp(float(current['temperature_2m']))}, "
        f"ощущается как {format_temp(float(current['apparent_temperature']))}. {phrase.capitalize()}.",
        f"Ветер {wind} м/с. {rain}.",
    ]
    slots = upcoming_slots(payload, now)
    if slots:
        lines.extend(["", "<b>Дальше</b>"])
        for moment, temperature, slot_code in slots:
            lines.append(
                f"{moment:%H:%M} {format_temp(temperature)}, {weather_phrase(slot_code)}"
            )
    lines.extend(["", "Источник: Open-Meteo"])
    return "\n".join(lines)


def upcoming_slots(payload: dict, now: datetime, count: int = 4) -> list[tuple[datetime, float, int]]:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    temperatures = hourly.get("temperature_2m") or []
    codes = hourly.get("weather_code") or []
    slots: list[tuple[datetime, float, int]] = []
    for raw_time, temperature, code in zip(times, temperatures, codes, strict=False):
        moment = datetime.fromisoformat(str(raw_time))
        if moment.tzinfo is None and now.tzinfo is not None:
            moment = moment.replace(tzinfo=now.tzinfo)
        if moment <= now or moment.hour % 3 != 0:
            continue
        slots.append((moment, float(temperature), int(code)))
        if len(slots) >= count:
            break
    return slots


def parse_traffic(xml_text: str) -> tuple[int, str] | None:
    level_match = re.search(r"<level>(\d+)</level>", xml_text)
    if not level_match:
        return None
    hint_match = re.search(r'<hint lang="ru">([^<]*)</hint>', xml_text)
    hint = html.unescape(hint_match.group(1)).strip() if hint_match else ""
    return int(level_match.group(1)), hint


def traffic_assessment(level: int, hint: str) -> str:
    if hint:
        return hint[:1].lower() + hint[1:]
    if level <= 2:
        return "свободно"
    if level <= 4:
        return "небольшие затруднения"
    if level <= 6:
        return "затруднено"
    if level <= 8:
        return "серьёзные пробки"
    return "город стоит"


def render_traffic_line(level: int | None, hint: str | None) -> str:
    if level is None:
        return "🚗 Балл пробок сейчас недоступен"
    return f"🚗 Пробки: {level}, {html.escape(traffic_assessment(level, hint or ''))}"


def parse_closed_stations(page: str) -> list[str] | None:
    if "вестибюль станции" not in page.casefold():
        return None
    stations: list[str] = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", page, flags=re.IGNORECASE | re.DOTALL):
        text = html_to_text(row)
        match = re.search(r"^\d+\s+(.+?)\s+станция закрыта\b", text, flags=re.IGNORECASE)
        if not match:
            continue
        name = re.sub(r"\s+", " ", match.group(1)).strip()
        if name and name not in stations:
            stations.append(name)
    return stations


def render_metro_line(stations: list[str]) -> str:
    if not stations:
        return "🚇 Закрытых станций нет"
    names = ", ".join(html.escape(station) for station in stations)
    return f"🚇 Не работают: {names}"


def parse_news(xml_text: str, now: datetime) -> list[NewsItem]:
    root = ET.fromstring(xml_text)
    window_start = now.astimezone(ZoneInfo("UTC")) - timedelta(hours=24)
    window_end = now.astimezone(ZoneInfo("UTC")) + timedelta(minutes=5)
    items: list[NewsItem] = []
    seen: set[str] = set()
    for node in root.findall("./channel/item"):
        title = html_to_text(node.findtext("title") or "")
        link = clean_link((node.findtext("link") or "").strip())
        published_raw = (node.findtext("pubDate") or "").strip()
        if not title or not link or not published_raw:
            continue
        published = parsedate_to_datetime(published_raw).astimezone(ZoneInfo("UTC"))
        if published < window_start or published > window_end:
            continue
        if link in seen:
            continue
        seen.add(link)
        encoded = node.find(_CONTENT_TAG)
        lead = news_lead(element_markup(encoded) if encoded is not None else "")
        items.append(NewsItem(title=title, link=link, published=published, lead=lead))
    return select_news(items)


def select_news(items: list[NewsItem], limit: int = NEWS_LIMIT) -> list[NewsItem]:
    ordered = sorted(items, key=lambda item: item.published, reverse=True)
    local = [item for item in ordered if is_local_news(item)]
    return (local or ordered)[:limit]


def is_local_news(item: NewsItem) -> bool:
    haystack = f"{item.title} {item.lead}".casefold()
    return any(marker in haystack for marker in _LOCAL_MARKERS)


def news_lead(encoded: str, sentences: int = 2, max_chars: int = 360) -> str:
    paragraphs = [
        part.strip()
        for part in html_to_text(encoded).split("\n")
        if part.strip() and not part.strip().casefold().startswith("фото:")
    ]
    source = " ".join(paragraphs[:2])
    return first_sentences(source, sentences, max_chars)


def first_sentences(text: str, count: int = 2, max_chars: int = 360) -> str:
    parts = [part.strip() for part in re.split(r"(?<=[.!?…])\s+", text.strip()) if part.strip()]
    result = " ".join(parts[:count]).strip()
    if len(result) > max_chars:
        return result[: max_chars - 1].rstrip() + "…"
    return result


def render_news_line(item: NewsItem) -> str:
    url = html.escape(item.link, quote=True)
    visible = html.escape(item.link)
    return f"{html.escape(item.body)} (<a href=\"{url}\">{visible}</a>)"


def render_digest(
    now: datetime,
    weather_line: str,
    traffic_line: str,
    metro_line: str,
    news_lines: list[str],
    news_note: str | None = None,
) -> str:
    lines = [
        f"<b>Сводка на {now.day} {_MONTHS[now.month - 1]}</b>",
        "",
        weather_line,
        traffic_line,
        metro_line,
        "",
        "<b>За сутки</b>",
    ]
    if news_lines:
        lines.extend(news_lines)
    elif news_note:
        lines.append(html.escape(news_note))
    return "\n".join(lines)


def element_markup(node: ET.Element) -> str:
    parts = [node.text or ""]
    for child in list(node):
        parts.append(ET.tostring(child, encoding="unicode"))
        parts.append(child.tail or "")
    return "".join(parts)


def html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style|figure|figcaption)\b[^>]*>.*?</\1>", " ", value)
    value = re.sub(r"(?is)<img\b[^>]*>", " ", value)
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</p>", "\n", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value).replace("\xa0", " ")
    value = "".join(char for char in value if char in "\n\t" or char >= " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    return value.strip()


def clean_link(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _read_url(url: str, timeout: float = 20, insecure: bool = False) -> str:
    context = ssl._create_unverified_context() if insecure else None
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        raw = response.read(2_000_000)
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, "replace")


async def fetch_text(url: str) -> str:
    try:
        return await asyncio.to_thread(_read_url, url)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLError) and url.startswith("https://metro.spb.ru/"):
            logger.warning("Сертификат metro.spb.ru не прошёл проверку, повторяю запрос к официальной странице")
            return await asyncio.to_thread(_read_url, url, 20, True)
        raise


async def _fetch_optional(url: str) -> str | None:
    try:
        return await fetch_text(url)
    except Exception:
        logger.warning("Не удалось загрузить %s", url, exc_info=True)
        return None


async def weather_report(now: datetime) -> str:
    raw = await _fetch_optional(weather_url())
    if raw is None:
        return "Не удалось получить погоду. Попробуйте ещё раз через минуту."
    try:
        payload = json.loads(raw)
        return render_weather_detail(payload, now)
    except (KeyError, TypeError, ValueError):
        logger.warning("Неожиданный ответ погоды", exc_info=True)
        return "Не удалось получить погоду. Попробуйте ещё раз через минуту."


async def build_digest(now: datetime) -> str:
    weather_raw, traffic_raw, metro_raw, news_raw = await asyncio.gather(
        _fetch_optional(weather_url()),
        _fetch_optional(TRAFFIC_URL),
        _fetch_optional(METRO_URL),
        _fetch_optional(NEWS_URL),
    )
    weather_line = "🌤 Погода сейчас недоступна"
    if weather_raw:
        try:
            weather_line = render_weather_brief(json.loads(weather_raw))
        except (KeyError, TypeError, ValueError):
            logger.warning("Неожиданный ответ погоды для сводки", exc_info=True)

    traffic_line = render_traffic_line(None, None)
    if traffic_raw:
        parsed = parse_traffic(traffic_raw)
        if parsed:
            traffic_line = render_traffic_line(*parsed)

    if metro_raw and (stations := parse_closed_stations(metro_raw)) is not None:
        metro_line = render_metro_line(stations)
    else:
        metro_line = render_metro_line(list(FALLBACK_CLOSED_STATIONS))

    news_lines: list[str] = []
    news_note = "Новости Фонтанки сейчас недоступны."
    if news_raw:
        try:
            selected = parse_news(news_raw, now)
            news_lines = [render_news_line(item) for item in selected]
            news_note = "За сутки в ленте Фонтанки нет новых материалов."
        except ET.ParseError:
            logger.warning("Не удалось разобрать ленту Фонтанки", exc_info=True)
    return render_digest(now, weather_line, traffic_line, metro_line, news_lines, news_note)


async def publish_morning_digest(bot: Bot, db: Database, settings: Settings, now: datetime) -> None:
    text = await build_digest(now)
    message = await bot.send_message(
        settings.community_chat_id,
        text,
        parse_mode="HTML",
        link_preview_options=_NO_PREVIEW,
    )
    previous_id = await db.get_bot_state("city_digest_message_id")
    if previous_id:
        try:
            await bot.unpin_chat_message(settings.community_chat_id, int(previous_id))
        except Exception:
            logger.warning("Не удалось снять предыдущий закреп сводки", exc_info=True)
    try:
        await bot.pin_chat_message(
            settings.community_chat_id,
            message.message_id,
            disable_notification=True,
        )
    except Exception:
        logger.warning("Сводка отправлена, но закрепить её не удалось", exc_info=True)
    await db.set_bot_state("city_digest_message_id", str(message.message_id))
    await db.set_bot_state("city_digest_date", now.date().isoformat())


async def city_digest_job(db: Database, settings: Settings, bot: Bot) -> None:
    timezone = ZoneInfo(settings.timezone)
    while True:
        now = datetime.now(timezone)
        sent_date = await db.get_bot_state("city_digest_date")
        if settings.community_chat_id and digest_is_due(now, settings.digest_hour, sent_date):
            try:
                await publish_morning_digest(bot, db, settings, now)
            except Exception:
                logger.exception("Не удалось отправить утреннюю сводку")
                await asyncio.sleep(120)
                continue
        now = datetime.now(timezone)
        target = now.replace(hour=settings.digest_hour, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep(max(1, (target - now).total_seconds()))
