from __future__ import annotations

import asyncio
import html
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp

logger = logging.getLogger(__name__)

SPB_LATITUDE = 59.9386
SPB_LONGITUDE = 30.3141
MORNING_HOUR = 9
CATCHUP_MINUTES = 150
CAPTION_LIMIT = 1000

WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={SPB_LATITUDE}&longitude={SPB_LONGITUDE}"
    "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation"
    "&daily=sunrise,sunset,weather_code"
    "&hourly=temperature_2m,weather_code"
    "&timezone=Europe%2FMoscow&forecast_days=2"
)
TRAFFIC_URL = "https://export.yandex.ru/bar/reginfo.xml?region=2"
NEWS_URL = "https://www.fontanka.ru/rss-feeds/zen-news.xml"
METRO_URL = "https://metro.spb.ru/rejimrabotystancii.html"
FALLBACK_CLOSED_STATIONS = ("Парк Победы", "Фрунзенская")
_CONTENT_TAG = "{http://purl.org/rss/1.0/modules/content/}encoded"

PHOTOS = Path(__file__).resolve().parent.parent / "assets" / "morning"

WEEKDAYS = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")
MONTHS = (
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

LINE_NAMES = {
    1: "красной",
    2: "синей",
    3: "зелёной",
    4: "оранжевой",
    5: "фиолетовой",
}

FACTS = (
    "В Петербурге насчитывается более 300 мостов, но разводных среди них значительно меньше.",
    "Петропавловская крепость заложена 27 мая 1703 года — с этой даты ведут историю города.",
    "Метро открылось 15 ноября 1955 года: первой стала Кировско-Выборгская линия.",
    "Белые ночи длятся примерно с конца мая до середины июля, когда солнце почти не уходит за горизонт.",
    "Развод мостов на Неве идёт ночью в навигацию, обычно с апреля по ноябрь.",
    "Кунсткамера, открытая в 1714 году, считается старейшим музеем России.",
    "Исаакиевский собор строили с 1818 по 1858 год — сорок лет.",
    "Невский проспект тянется примерно на 4,5 километра от Адмиралтейства до Александро-Невской лавры.",
    "Город назывался Петроградом в 1914–1924 годах и Ленинградом в 1924–1991 годах.",
    "Ростральные колонны на стрелке Васильевского острова когда-то служили маяками.",
    "Крейсер «Аврора» стоит у Петроградской набережной.",
    "Летний сад разбил ещё Пётр I, и он остаётся одним из старейших парков города.",
    "Дворцовая площадь сложилась как главный парадный двор Зимнего дворца.",
    "Медный всадник — памятник Петру I работы Фальконе, открытый в 1782 году.",
    "Казанский собор выходит колоннадой на Невский проспект.",
    "В дельте Невы десятки островов, и город до сих пор живёт между реками и каналами.",
    "Эрмитаж вырос из частной коллекции Екатерины II и занимает Зимний дворец.",
    "Стрелка Васильевского острова — место, где Нева делится на Большую и Малую.",
    "Петропавловский собор долго был самым высоким зданием города.",
    "Навигация и белые ночи — два сезона, ради которых в город специально приезжают.",
)

CRIME_RE = re.compile(
    r"убил|убийств|задержан|арестова|приговор|колони|мошеннич|наркот|изнасил|"
    r"ограб|ножом|стрельб|расчлен|суди?т|полици|маньяк",
    re.IGNORECASE,
)
OTHER_CITY_RE = re.compile(
    r"якут|рязан|вьетнам|франц|иркут|брянск|сочи|нижн|москв|сша|кубан|чукот|тув[аеуы]",
    re.IGNORECASE,
)
LOCAL_RE = re.compile(
    r"петербург|спб|невск|фонтанк|мойк|выборг|петроград|василеостров|купчин|"
    r"кад\b|зда\b|проспект|набережн|шоссе|метро|станци|линии|черн",
    re.IGNORECASE,
)
NIGHT_RE = re.compile(
    r"дтп|авари|пожар|возгоран|затопил|прорыв|отключ|без света|без воды|"
    r"электр|водоснаб|обруш|столкнов|перевернул|разворотил",
    re.IGNORECASE,
)
TRANSPORT_RE = re.compile(
    r"метро|станци|вестибюл|проб|перекры|затрудн|автобус|трамва|троллейбус|"
    r"развязк|съезд|кад\b|шоссе",
    re.IGNORECASE,
)
LINE_RE = re.compile(r"лини[ияею]\s*(\d)", re.IGNORECASE)
RANGE_RE = re.compile(
    r"с\s+(\d{2})\.(\d{2})\.(\d{4})\s+по\s+(\d{2})\.(\d{2})\.(\d{4})",
    re.IGNORECASE,
)
PROBLEM_RE = re.compile(r"увелич|останов|закрыт|огранич|неисправ|задерж", re.IGNORECASE)
RESTORED_RE = re.compile(r"восстанов|обычном режиме|вводится в график", re.IGNORECASE)


@dataclass(slots=True)
class WeatherNow:
    temperature: float
    feels_like: float
    code: int
    wind_kmh: float
    precipitation: float
    sunrise: str
    sunset: str

    @property
    def kind(self) -> str:
        return weather_kind(self.code)


@dataclass(slots=True)
class NewsItem:
    title: str
    published: datetime
    categories: tuple[str, ...] = ()
    link: str = ""
    lead: str = ""

    @property
    def body(self) -> str:
        return self.lead or self.title


@dataclass(slots=True)
class MetroNote:
    when: datetime
    text: str


@dataclass(slots=True)
class MorningBrief:
    when: datetime
    weather: WeatherNow | None = None
    traffic_level: int | None = None
    traffic_hint: str = ""
    transport_notes: list[str] = field(default_factory=list)
    metro_lines: dict[int, str] = field(default_factory=dict)
    station_notes: list[str] = field(default_factory=list)
    night: list[str] = field(default_factory=list)
    day_news: list[NewsItem] = field(default_factory=list)
    closed_stations: list[str] = field(default_factory=list)

    @property
    def photo(self) -> Path | None:
        kind = self.weather.kind if self.weather else "cloudy"
        path = PHOTOS / f"{kind}.jpg"
        return path if path.is_file() else None


def weather_kind(code: int) -> str:
    if code in {45, 48}:
        return "fog"
    if code in {71, 73, 75, 77, 85, 86}:
        return "snow"
    if code in {95, 96, 99}:
        return "storm"
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
        return "rain"
    if code in {0, 1}:
        return "clear"
    return "cloudy"


def weather_label(code: int) -> str:
    labels = {
        "clear": "Ясно",
        "cloudy": "Облачно",
        "rain": "Дождь",
        "snow": "Снег",
        "fog": "Туман",
        "storm": "Гроза",
    }
    return labels[weather_kind(code)]


def format_temp(value: float) -> str:
    rounded = int(round(value))
    if rounded > 0:
        return f"+{rounded}°"
    if rounded < 0:
        return f"−{abs(rounded)}°"
    return "0°"


def clothing_advice(weather: WeatherNow) -> str:
    feels = weather.feels_like
    wind = weather.wind_kmh / 3.6
    wet = weather.precipitation >= 0.2 or weather_kind(weather.code) in {"rain", "snow", "storm"}
    if feels <= -15:
        base = "Пуховик, шапка и тёплые перчатки."
    elif feels <= -5:
        base = "Зимняя куртка и шапка."
    elif feels <= 3:
        base = "Тёплая куртка, шапка и шарф."
    elif feels <= 10:
        base = "Куртка и закрытая обувь."
    elif feels <= 16:
        base = "Лёгкая куртка или плотный плащ."
    else:
        base = "Можно без куртки, лучше слои."
    extra: list[str] = []
    if wet and weather_kind(weather.code) == "snow":
        extra.append("Обувь с запасом на снег.")
    elif wet:
        extra.append("Зонт пригодится.")
    if wind >= 8:
        extra.append("Ветер сильный — берите ветровку.")
    elif weather.temperature - weather.feels_like >= 3:
        extra.append("По ощущениям холоднее, чем показывает градусник.")
    return " ".join([base, *extra])


def format_day(moment: date) -> str:
    return f"{WEEKDAYS[moment.weekday()]}, {moment.day} {MONTHS[moment.month - 1]}"


def clock(iso_stamp: str) -> str:
    try:
        return datetime.fromisoformat(iso_stamp).strftime("%H:%M")
    except ValueError:
        return iso_stamp[-5:]


def fact_for(day: date) -> str:
    return FACTS[day.toordinal() % len(FACTS)]


def due_morning(now: datetime, posted_day: str | None) -> bool:
    if posted_day == now.date().isoformat():
        return False
    start = now.replace(hour=MORNING_HOUR, minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=CATCHUP_MINUTES)
    return start <= now <= end


def seconds_until_morning(now: datetime) -> float:
    target = now.replace(hour=MORNING_HOUR, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return max(30.0, (target - now).total_seconds())


def _local(title: str) -> bool:
    if OTHER_CITY_RE.search(title) and not re.search(r"петербург", title, re.IGNORECASE):
        return False
    if LOCAL_RE.search(title):
        return True
    return bool(re.search(r"проб|метро|дтп|пожар|перекры", title, re.IGNORECASE))


def news_bucket(title: str) -> str | None:
    if CRIME_RE.search(title) or not _local(title):
        return None
    if TRANSPORT_RE.search(title) and not NIGHT_RE.search(title):
        return "transport"
    if NIGHT_RE.search(title):
        return "night"
    if TRANSPORT_RE.search(title):
        return "transport"
    return None


def _markup(node: ET.Element) -> str:
    parts = [node.text or ""]
    for child in list(node):
        parts.append(ET.tostring(child, encoding="unicode"))
        parts.append(child.tail or "")
    return "".join(parts)


def news_lead(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style|figure|figcaption)\b[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    paragraphs = [re.sub(r"\s+", " ", part).strip() for part in text.split("\n")]
    paragraphs = [part for part in paragraphs if part and not part.casefold().startswith("фото:")]
    source = " ".join(paragraphs[:2])
    sentences = [part.strip() for part in re.split(r"(?<=[.!?…])\s+", source) if part.strip()]
    result = " ".join(sentences[:2]).strip()
    if len(result) > 280:
        return result[:279].rstrip() + "…"
    return result


def clean_link(url: str) -> str:
    return url.split("?", 1)[0].strip()


def parse_rss(xml_text: str) -> list[NewsItem]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[NewsItem] = []
    for node in root.findall(".//item"):
        title = re.sub(r"\s+", " ", (node.findtext("title") or "")).strip()
        raw_date = (node.findtext("pubDate") or "").strip()
        if not title or not raw_date:
            continue
        try:
            published = parsedate_to_datetime(raw_date).astimezone(UTC)
        except (TypeError, ValueError, IndexError):
            continue
        categories = tuple((item.text or "").strip() for item in node.findall("category") if item.text)
        encoded = node.find(_CONTENT_TAG)
        description = node.findtext("description") or ""
        lead = news_lead(_markup(encoded) if encoded is not None else description)
        items.append(
            NewsItem(
                title=title,
                published=published,
                categories=categories,
                link=clean_link(node.findtext("link") or ""),
                lead=lead,
            )
        )
    return items


def parse_traffic_xml(xml_text: str) -> tuple[int | None, str]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None, ""
    level_node = root.find(".//level")
    hint = ""
    for node in root.findall(".//hint"):
        if node.attrib.get("lang", "ru") == "ru" and (node.text or "").strip():
            hint = node.text.strip()
            break
    if level_node is None or not (level_node.text or "").strip().isdigit():
        return None, hint
    return int(level_node.text), hint


def parse_weather(payload: dict[str, object]) -> WeatherNow | None:
    current = payload.get("current")
    daily = payload.get("daily")
    if not isinstance(current, dict) or not isinstance(daily, dict):
        return None
    try:
        sun = daily.get("sunrise") or [""]
        moon = daily.get("sunset") or [""]
        return WeatherNow(
            temperature=float(current["temperature_2m"]),
            feels_like=float(current["apparent_temperature"]),
            code=int(current["weather_code"]),
            wind_kmh=float(current.get("wind_speed_10m") or 0),
            precipitation=float(current.get("precipitation") or 0),
            sunrise=str(sun[0]),
            sunset=str(moon[0]),
        )
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def extract_metro_messages(page: str) -> list[MetroNote]:
    times = re.findall(r'<time[^>]*datetime="([^"]+)"', page)
    texts = re.findall(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', page, re.S)
    notes: list[MetroNote] = []
    for raw_time, raw_text in zip(times, texts, strict=False):
        try:
            when = datetime.fromisoformat(raw_time).astimezone(UTC)
        except ValueError:
            continue
        plain = html.unescape(re.sub(r"<[^>]+>", " ", raw_text))
        plain = re.sub(r"\s+", " ", plain).strip()
        if plain:
            notes.append(MetroNote(when=when, text=plain))
    notes.sort(key=lambda item: item.when, reverse=True)
    return notes


def _covers_today(text: str, day: date) -> bool:
    for match in RANGE_RE.finditer(text):
        start = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        end = date(int(match.group(6)), int(match.group(5)), int(match.group(4)))
        if start <= day <= end:
            return True
    return False


def _focus_sentence(text: str) -> str:
    cleaned = re.sub(r"[\U0001F300-\U0001FAFF❗⚠🚧✅🚩⚡]+", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" !")
    parts = re.split(r"(?<=[.!])\s+", cleaned)
    chosen = cleaned
    for part in parts:
        if re.search(r"станци|вестибюл|лини", part, re.IGNORECASE) and PROBLEM_RE.search(part):
            chosen = part.strip()
            break
    station = re.search(r"«([^»]{2,40})»", cleaned)
    if station and station.group(1) not in chosen:
        chosen = f"«{station.group(1)}»: {chosen}"
    return chosen


def _short(text: str, limit: int = 140) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:") + "…"


def metro_status(notes: list[MetroNote], now: datetime) -> tuple[dict[int, str], list[str]]:
    day = now.astimezone(ZoneInfo("Europe/Moscow")).date()
    recent_after = now.astimezone(UTC) - timedelta(hours=20)
    notes = sorted(notes, key=lambda item: item.when, reverse=True)
    lines: dict[int, str] = {}
    stations: list[str] = []
    for note in notes:
        fresh = note.when >= recent_after
        active_range = _covers_today(note.text, day)
        if not fresh and not active_range:
            continue
        for match in LINE_RE.finditer(note.text):
            number = int(match.group(1))
            if number not in LINE_NAMES or number in lines:
                continue
            if RESTORED_RE.search(note.text) and not PROBLEM_RE.search(note.text.split("восстанов")[-1]):
                lines[number] = ""
            elif PROBLEM_RE.search(note.text):
                lines[number] = _short(_focus_sentence(note.text), 110)
        if active_range and PROBLEM_RE.search(note.text) and "станции" in note.text.casefold():
            short = _short(_focus_sentence(note.text), 120)
            if short not in stations:
                stations.append(short)
    return lines, stations[:2]


def select_news(items: list[NewsItem], now: datetime) -> tuple[list[str], list[str]]:
    local = now.astimezone(ZoneInfo("Europe/Moscow"))
    night_start = local.replace(hour=21, minute=0, second=0, microsecond=0)
    if local.hour < 21:
        night_start -= timedelta(days=1)
    night_from = night_start.astimezone(UTC)
    moment = local.astimezone(UTC)
    night_end = local.replace(hour=MORNING_HOUR, minute=0, second=0, microsecond=0)
    if local < night_end:
        night_end = local
    night_until = night_end.astimezone(UTC)
    transport_from = moment - timedelta(hours=20)
    night: list[str] = []
    transport: list[str] = []
    for item in sorted(items, key=lambda row: row.published, reverse=True):
        bucket = news_bucket(item.title)
        if bucket == "night" and night_from <= item.published <= night_until:
            if item.title not in night:
                night.append(item.title)
        elif bucket == "transport" and item.published >= transport_from:
            if item.title not in transport:
                transport.append(item.title)
    return transport[:3], night[:5]


def _traffic_line(level: int | None, hint: str) -> str:
    if level is None:
        return "🚗 Балл пробок сейчас не пришёл."
    hint_clean = hint.strip().rstrip(".")
    if hint_clean:
        hint_clean = hint_clean[:1].lower() + hint_clean[1:]
        return f"🚗 Пробки: {level}, {hint_clean}."
    return f"🚗 Пробки: {level}."


def parse_closed_stations(page: str) -> list[str] | None:
    if "вестибюль станции" not in page.casefold():
        return None
    stations: list[str] = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", page, flags=re.IGNORECASE | re.DOTALL):
        text = re.sub(r"<[^>]+>", " ", row)
        text = html.unescape(text).replace("\xa0", " ")
        text = re.sub(r"\s+", " ", text).strip()
        match = re.search(r"^\d+\s+(.+?)\s+станция закрыта\b", text, flags=re.IGNORECASE)
        if not match:
            continue
        name = match.group(1).strip()
        if name and name not in stations:
            stations.append(name)
    return stations


DAY_NEWS_SKIP_RE = re.compile(r"убил|убийств|изнасил|расчлен|маньяк", re.IGNORECASE)


def select_day_news(items: list[NewsItem], now: datetime, limit: int = 2) -> list[NewsItem]:
    moment = now.astimezone(UTC)
    start = moment - timedelta(hours=24)
    fresh = [
        item
        for item in items
        if start <= item.published <= moment + timedelta(minutes=5)
        and not DAY_NEWS_SKIP_RE.search(f"{item.title} {item.lead}")
    ]
    fresh.sort(key=lambda item: item.published, reverse=True)
    local = [item for item in fresh if _local(f"{item.title} {item.lead}")]
    return (local or fresh)[:limit]


def render_news_line(item: NewsItem) -> str:
    text = html.escape(item.body)
    link = clean_link(item.link)
    if not link:
        return text
    url = html.escape(link, quote=True)
    visible = html.escape(link)
    return f"{text} (<a href=\"{url}\">{visible}</a>)"


def upcoming_lines(payload: dict[str, object], now: datetime, count: int = 4) -> list[str]:
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        return []
    times = hourly.get("time") or []
    temperatures = hourly.get("temperature_2m") or []
    codes = hourly.get("weather_code") or []
    if not isinstance(times, list) or not isinstance(temperatures, list) or not isinstance(codes, list):
        return []
    lines: list[str] = []
    local_now = now.astimezone(ZoneInfo("Europe/Moscow"))
    for raw_time, temperature, code in zip(times, temperatures, codes, strict=False):
        try:
            moment = datetime.fromisoformat(str(raw_time))
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=ZoneInfo("Europe/Moscow"))
        if moment <= local_now or moment.hour % 3 != 0:
            continue
        lines.append(f"{moment:%H:%M} {format_temp(float(temperature))}, {weather_label(int(code)).lower()}")
        if len(lines) >= count:
            break
    return lines


def render_weather_command(payload: dict[str, object], now: datetime) -> str | None:
    weather = parse_weather(payload)
    if weather is None:
        return None
    emoji = {"clear": "☀️", "cloudy": "🌥", "rain": "🌧", "snow": "❄️", "fog": "🌫", "storm": "⛈"}[weather.kind]
    wind = max(0, int(round(weather.wind_kmh / 3.6)))
    rain = "Осадков нет" if weather.precipitation < 0.1 else f"Осадки {weather.precipitation:.1f} мм"
    lines = [
        f"{emoji} <b>Погода в Петербурге</b>",
        "",
        f"Сейчас: {format_temp(weather.temperature)}, ощущается как {format_temp(weather.feels_like)}.",
        f"{weather_label(weather.code)}, ветер {wind} м/с. {rain}.",
        f"👕 {html.escape(clothing_advice(weather))}",
    ]
    later = upcoming_lines(payload, now)
    if later:
        lines.extend(["", "<b>Дальше</b>", *later])
    lines.extend(["", "Источник: Open-Meteo"])
    return "\n".join(lines)


def _closed_stations_line(stations: list[str]) -> str:
    if not stations:
        return "🚇 Закрытых станций нет."
    names = ", ".join(html.escape(station) for station in stations)
    return f"🚇 Не работают: {names}"


def _metro_block(lines: dict[int, str], stations: list[str]) -> list[str]:
    problems = [number for number, text in sorted(lines.items()) if text]
    quiet = [number for number in LINE_NAMES if number not in problems]
    rows: list[str] = []
    if problems:
        for number in problems:
            rows.append(f"⚠️ На {LINE_NAMES[number]} линии: {html.escape(lines[number])}")
        if quiet and len(quiet) >= 3:
            names = ", ".join(LINE_NAMES[number] for number in quiet)
            rows.insert(0, f"🚇 На {names} линиях без серьёзных задержек.")
    else:
        rows.append("🚇 На линиях без серьёзных задержек.")
    rows.extend(f"🚧 {html.escape(note)}" for note in stations[:2])
    return rows


def brief_title(moment: datetime) -> str:
    local = moment.astimezone(ZoneInfo("Europe/Moscow"))
    if local.hour < 12:
        return "🌅 <b>Доброе утро</b>"
    return "🌅 <b>Сводка на сегодня</b>"


def render_brief(brief: MorningBrief) -> str:
    day = brief.when.astimezone(ZoneInfo("Europe/Moscow")).date()
    weather_lines = ["🌤 Погода сейчас недоступна."]
    sun = "—"
    moon = "—"
    if brief.weather:
        emoji = {"clear": "☀️", "cloudy": "🌥", "rain": "🌧", "snow": "❄️", "fog": "🌫", "storm": "⛈"}[
            brief.weather.kind
        ]
        weather_lines = [
            f"{emoji} {format_temp(brief.weather.temperature)}, {weather_label(brief.weather.code).lower()}",
        ]
        sun = clock(brief.weather.sunrise)
        moon = clock(brief.weather.sunset)
    if brief.day_news:
        news = ["📰 <b>За сутки</b>", *[render_news_line(item) for item in brief.day_news[:2]]]
    else:
        news = ["📰 <b>За сутки</b>", "За сутки в ленте Фонтанки нет новых материалов."]
    parts = [
        brief_title(brief.when),
        "",
        *weather_lines,
        _traffic_line(brief.traffic_level, brief.traffic_hint),
        _closed_stations_line(brief.closed_stations),
        "",
        *news,
        "",
        "🕐 <b>Сегодня</b>",
        f"📅 {format_day(day)}",
        f"🌅 Рассвет — {sun}",
        f"🌇 Закат — {moon}",
        "",
        "🏛 <b>Факт дня</b>",
        html.escape(fact_for(day)),
    ]
    text = "\n".join(parts)
    if len(text) > CAPTION_LIMIT and len(brief.day_news) > 1:
        brief.day_news.pop()
        return render_brief(brief)
    if len(text) > CAPTION_LIMIT:
        return text[: CAPTION_LIMIT - 1].rsplit("\n", 1)[0]
    return text


async def _get_text(session: aiohttp.ClientSession, url: str) -> str:
    try:
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.text()
    except aiohttp.ClientSSLError:
        if "metro.spb.ru" not in url:
            raise
        logger.warning("Сертификат metro.spb.ru не прошёл проверку, повторяю запрос к официальной странице")
        async with session.get(url, ssl=False) as response:
            response.raise_for_status()
            return await response.text()


async def _get_json(session: aiohttp.ClientSession, url: str) -> dict[str, object]:
    async with session.get(url) as response:
        response.raise_for_status()
        payload = await response.json(content_type=None)
    return payload if isinstance(payload, dict) else {}


async def collect_brief(now: datetime) -> MorningBrief:
    brief = MorningBrief(when=now)
    timeout = aiohttp.ClientTimeout(total=12)
    headers = {"User-Agent": "NoraMorning/1.0"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        weather_raw, traffic_raw, news_raw, metro_raw = await asyncio.gather(
            _get_json(session, WEATHER_URL),
            _get_text(session, TRAFFIC_URL),
            _get_text(session, NEWS_URL),
            _get_text(session, METRO_URL),
            return_exceptions=True,
        )
    if isinstance(weather_raw, dict):
        brief.weather = parse_weather(weather_raw)
    else:
        logger.warning("Утренняя погода не ответила")
    if isinstance(traffic_raw, str):
        brief.traffic_level, brief.traffic_hint = parse_traffic_xml(traffic_raw)
    else:
        logger.warning("Утренние пробки не ответили")
    if isinstance(news_raw, str):
        brief.day_news = select_day_news(parse_rss(news_raw), now)
    else:
        logger.warning("Утренняя лента новостей не ответила")
    if isinstance(metro_raw, str):
        stations = parse_closed_stations(metro_raw)
        brief.closed_stations = list(FALLBACK_CLOSED_STATIONS) if stations is None else stations
    else:
        logger.warning("Сводка метро не ответила")
        brief.closed_stations = list(FALLBACK_CLOSED_STATIONS)
    return brief


async def weather_reply(now: datetime) -> str:
    timeout = aiohttp.ClientTimeout(total=12)
    headers = {"User-Agent": "NoraMorning/1.0"}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            payload = await _get_json(session, WEATHER_URL)
        text = render_weather_command(payload, now)
    except (aiohttp.ClientError, TimeoutError):
        logger.warning("Команда погоды не ответила")
        text = None
    if not text:
        return "Не удалось получить погоду. Попробуйте ещё раз через минуту."
    return text


async def publish_morning_digest(bot, db, settings, *, force: bool = False) -> bool:
    if not settings.community_chat_id:
        return True
    if not force and not await db.feature_enabled("morning_digest"):
        return True
    timezone = ZoneInfo(settings.timezone)
    now = datetime.now(timezone)
    posted = await db.get_bot_state("morning_digest_day")
    if not force and not due_morning(now, posted):
        return True
    brief = await collect_brief(now)
    text = render_brief(brief)
    from aiogram.types import FSInputFile

    chat_id = settings.community_chat_id
    photo = brief.photo
    if photo:
        sent = await bot.send_photo(chat_id, FSInputFile(photo), caption=text, parse_mode="HTML")
    else:
        sent = await bot.send_message(chat_id, text, parse_mode="HTML")
    old_pin = await db.get_bot_state("morning_pin_message_id")
    if old_pin:
        try:
            await bot.unpin_chat_message(chat_id, int(old_pin))
        except Exception:
            logger.info("Старый утренний закреп уже снят")
    try:
        await bot.pin_chat_message(chat_id, sent.message_id, disable_notification=True)
        await db.set_bot_state("morning_pin_message_id", str(sent.message_id))
    except Exception:
        logger.warning("Утренний пост ушёл в чат, но закрепить его не удалось")
    await db.set_bot_state("morning_digest_day", now.date().isoformat())
    logger.info("Сводка за %s отправлена в чат", now.date().isoformat())
    return True


CATCHUP_DAY = "2026-10-05"


async def publish_missed_today(bot, db, settings) -> None:
    """One catch-up for 5 October. Later days stay on the 09:00 schedule."""
    if await db.get_bot_state("morning_catchup_done") == CATCHUP_DAY:
        return
    timezone = ZoneInfo(settings.timezone)
    today = datetime.now(timezone).date().isoformat()
    if today != CATCHUP_DAY:
        return
    if await db.get_bot_state("morning_digest_day") == today:
        await db.set_bot_state("morning_catchup_done", CATCHUP_DAY)
        return
    await publish_morning_digest(bot, db, settings, force=True)
    await db.set_bot_state("morning_catchup_done", CATCHUP_DAY)
