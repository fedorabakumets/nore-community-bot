from __future__ import annotations

import asyncio
import html
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import aiohttp

if TYPE_CHECKING:
    from community_bot.day_note import DayEvent

logger = logging.getLogger(__name__)

SPB_LATITUDE = 59.9386
SPB_LONGITUDE = 30.3141
MORNING_HOUR = 9
CATCHUP_MINUTES = 150
CAPTION_LIMIT = 1000
MORNING_LAYOUT = "city-quotes-v1"

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
NEWS_FEEDS = (
    ("Фонтанка", NEWS_URL),
    ("47news", "https://47news.ru/rss/"),
    ("ТАСС", "https://tass.ru/rss/v2.xml"),
)
METRO_URL = "https://metro.spb.ru/rejimrabotystancii.html"
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
    source: str = ""

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
    news_available: bool = True
    metro_available: bool = True
    history: DayEvent | None = None

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
    try:
        parts = urlsplit(url.strip())
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return ""
        query = [(key, value) for key, value in parse_qsl(parts.query)
                 if not key.startswith("utm_") and key not in {"from", "yclid", "fbclid"}]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    except ValueError:
        return ""


def parse_rss(xml_text: str, source: str = "") -> list[NewsItem]:
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
            parsed = parsedate_to_datetime(raw_date)
            if parsed.tzinfo is None:
                continue
            published = parsed.astimezone(UTC)
        except (TypeError, ValueError, IndexError, OverflowError):
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
                source=source,
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


DAY_NEWS_SKIP_RE = re.compile(
    r"убил|убийств|изнасил|расчлен|маньяк|сожител|избил|избива|насили|"
    r"полици|арестова|задержан|приговор|мошеннич|наркот|ножом|стрельб|ограб|"
    r"попал[аи]? в больниц|госпитализ|получил\w* травм", re.IGNORECASE,
)
CITY_NEWS_RE = re.compile(
    r"петербург|\bспб\b|петроград|кронштадт|колпино|сестрорецк|василеостров|"
    r"купчино|коломяж|невский проспект|набережн\w* (?:мойки|фонтанки)|пулково", re.IGNORECASE,
)
REGION_NEWS_RE = re.compile(
    r"ленобласт|ленинградск\w* област|всеволож|гатчин|выборг|кингисепп|"
    r"соснов\w* бор|тихвин|тосно|кириш|мурино|кудрово", re.IGNORECASE,
)
RUSSIA_NEWS_RE = re.compile(
    r"росси[яиюй]|россиян|госдум|федеральн\w* закон|москв|казан|новосибир|екатеринбург|"
    r"нижн\w* новгород|владивосток|калининград", re.IGNORECASE,
)


def news_region(item: NewsItem) -> int | None:
    # A publisher being based in SPb does not make every article local.
    for text in (item.title, f"{item.title} {item.lead} {' '.join(item.categories)}"):
        if CITY_NEWS_RE.search(text):
            return 0
        if REGION_NEWS_RE.search(text):
            return 1
    return 2 if RUSSIA_NEWS_RE.search(f"{item.title} {item.lead} {' '.join(item.categories)}") else None


def _same_story(left: NewsItem, right: NewsItem) -> bool:
    if clean_link(left.link) and clean_link(left.link) == clean_link(right.link):
        return True
    # Separate follow-up articles about the same road's congestion should occupy
    # one slot, even when their headlines use different verbs.
    left_title, right_title = left.title.casefold(), right.title.casefold()
    common_road = any(re.search(pattern, left_title) and re.search(pattern, right_title)
                      for pattern in (r"\bкад\b", r"\bзсд\b", r"невск\w* проспект"))
    if common_road and any(re.search(pattern, left_title) and re.search(pattern, right_title)
                           for pattern in (r"ремонт|перекры", r"пробк|затор|затруднен")):
        return True
    generic = {"в", "на", "и", "петербурге", "петербург", "санкт", "спб", "новый", "новую", "новая", "открыли"}
    a = " ".join(word for word in re.findall(r"[а-яёa-z0-9]+", left.title.casefold()) if word not in generic)
    b = " ".join(word for word in re.findall(r"[а-яёa-z0-9]+", right.title.casefold()) if word not in generic)
    if not a or not b:
        return left.title.casefold() == right.title.casefold()
    return a == b or SequenceMatcher(None, a, b).ratio() >= 0.72


def news_value(item: NewsItem, now: datetime) -> int | None:
    title = item.title.casefold()
    # The feed mixes breaking news with archive reprints and historical features.
    # A fresh publication date alone does not make a 1917 event today's news.
    years = re.findall(r"\b((?:17|18|19|20)\d{2})\s*(?:году|года|г\.)", title)
    retrospective = any(int(year) < now.year for year in years)
    current_action = re.search(r"сегодня|завтра|откро|откры|возобнов|покаж|ремонт|реставр|восстанов", title)
    if retrospective and not current_action:
        return None
    if re.search(r"лет назад|этот день|гороскоп|знак\w* зодиака|рецепт|драка|подрались", title):
        return None
    if re.search(r"перекры|маршрут|проезд|ремонт|откры|запуст|школ|больниц|поликлиник|музе|выстав|закон", title):
        return 2
    if re.search(r"погод|температур|потепл|похолод", title):
        return 0  # A separate weather block already covers ordinary weather.
    return 1


def select_day_news(items: list[NewsItem], now: datetime, limit: int = 2) -> list[NewsItem]:
    moment = now.astimezone(UTC)
    start = moment - timedelta(hours=24)
    fresh = [
        item
        for item in items
        if item.published.tzinfo is not None and start <= item.published <= moment
        and not DAY_NEWS_SKIP_RE.search(f"{item.title} {item.lead}")
        and clean_link(item.link) and news_region(item) is not None
        and news_value(item, now) is not None
    ]
    fresh.sort(key=lambda item: (news_region(item), -int(news_value(item, now) or 0), -item.published.timestamp()))
    selected: list[NewsItem] = []
    if not fresh or limit <= 0:
        return selected
    # Keep the best available geography tier: never pad a single local story
    # with an unrelated national headline just to fill a second slot.
    tier = news_region(fresh[0])
    for item in fresh:
        if news_region(item) != tier:
            break
        if selected and news_value(item, now) == 0:
            continue
        if not any(_same_story(item, old) for old in selected):
            selected.append(item)
        if len(selected) >= min(limit, 2):
            break
    return selected


def render_news_line(item: NewsItem) -> str:
    title = html.escape(_short(item.title, 85))
    body = html.escape(_short(item.body, 160)) if item.body != item.title else ""
    link = clean_link(item.link)
    source = html.escape(item.source or "Источник")
    citation = f'<a href="{html.escape(link, quote=True)}">{source}</a>' if link else ""
    return "\n".join(part for part in (f"<b>{title}</b>", body, citation) if part)


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
    # Budget plain text before escaping. Never truncate a finished HTML document,
    # and never mutate the brief while trying shorter layouts.
    for detail_limit in (240, 170, 125, 80, 40):
        text = _render_compact_brief(brief, detail_limit)
        if telegram_length(text) <= CAPTION_LIMIT:
            return text
    raise ValueError("Morning brief exceeds the Telegram caption budget")


def telegram_length(text: str) -> int:
    plain = html.unescape(re.sub(r"<[^>]+>", "", text))
    return len(plain.encode("utf-16-le")) // 2


def _quote(parts: list[str]) -> str:
    return '<blockquote expandable>' + "\n".join(part for part in parts if part) + '</blockquote>'


def _render_compact_brief(brief: MorningBrief, detail_limit: int) -> str:
    local = brief.when.astimezone(ZoneInfo("Europe/Moscow"))
    day = local.date()
    parts = [brief_title(local) + ", Петербург", format_day(day), ""]
    if brief.weather:
        weather = brief.weather
        emoji = {"clear": "☀️", "cloudy": "🌥", "rain": "🌧", "snow": "❄️", "fog": "🌫", "storm": "⛈"}[
            weather.kind
        ]
        advice = clothing_advice(weather).split(".", 1)[0] + "."
        if weather.kind in {"rain", "storm"}:
            advice += " Зонт пригодится."
        parts.extend([
            f"{emoji} {format_temp(weather.temperature)}, {weather_label(weather.code).lower()} · "
            f"ощущается {format_temp(weather.feels_like)}",
            html.escape(advice),
        ])
    else:
        parts.append("🌤 Погоду сейчас получить не удалось.")
    transport = []
    if brief.traffic_level is not None:
        transport.append(f"пробки {brief.traffic_level}/10")
    if brief.metro_available and brief.closed_stations:
        transport.append("закрыты: " + _short(", ".join(brief.closed_stations), 65))
    if transport:
        parts.append("🚦 " + html.escape(" · ".join(transport)))
    if brief.day_news:
        parts.extend(["", "<b>За сутки</b>"])
        for item in brief.day_news[:2]:
            link = clean_link(item.link)
            source = html.escape(item.source or "Источник")
            citation = f'<a href="{html.escape(link, quote=True)}">{source}</a>' if link else ""
            body = _short(item.body, detail_limit) if item.body != item.title else ""
            parts.append(_quote([
                "<b>" + html.escape(_short(item.title, 72)) + "</b>",
                html.escape(body), citation,
            ]))
    elif not brief.news_available:
        parts.extend(["", "Новости пока не загрузились."])
    else:
        parts.extend(["", "Подходящих новостей за сутки в доступных лентах не нашлось."])
    parts.extend(["", "<b>Этот день в Петербурге</b>"])
    event = brief.history
    if event and event.year < day.year and (event.month, event.day) == (day.month, day.day):
        from community_bot.day_note import years_ago

        link = clean_link(event.url)
        citation = f'<a href="{html.escape(link, quote=True)}">Подробнее</a>' if link else ""
        parts.append(_quote([
            f"<b>{event.year} · {html.escape(_short(event.title or 'Событие в городе', 55))}</b>",
            f"{day.day} {MONTHS[day.month - 1]} · {years_ago(day.year - event.year)}",
            html.escape(_short(event.text, 155)),
            html.escape(_short(event.context, detail_limit)), citation,
        ]))
    else:
        parts.append("Подтверждённого события на эту дату пока нет.")
    return "\n".join(parts)


async def _get_text(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url) as response:
        response.raise_for_status()
        return await response.text()


async def _get_json(session: aiohttp.ClientSession, url: str) -> dict[str, object]:
    async with session.get(url) as response:
        response.raise_for_status()
        payload = await response.json(content_type=None)
    return payload if isinstance(payload, dict) else {}


async def collect_news(session: aiohttp.ClientSession) -> tuple[list[NewsItem], bool]:
    responses = await asyncio.gather(
        *(_get_text(session, url) for _, url in NEWS_FEEDS), return_exceptions=True,
    )
    items: list[NewsItem] = []
    available = False
    for (source, _), raw in zip(NEWS_FEEDS, responses, strict=True):
        if not isinstance(raw, str):
            logger.warning("Лента %s не ответила", source)
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            logger.warning("Лента %s вернула невалидный RSS", source)
            continue
        if root.tag.rsplit("}", 1)[-1].lower() not in {"rss", "rdf"}:
            continue
        available = True
        items.extend(parse_rss(raw, source))
    return items, available


async def collect_brief(now: datetime) -> MorningBrief:
    from community_bot.day_note import DayEvent, city_event_for

    brief = MorningBrief(when=now)
    timeout = aiohttp.ClientTimeout(total=12)
    headers = {"User-Agent": "NoraMorning/1.0"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers, trust_env=True) as session:
        weather_raw, traffic_raw, news_raw, metro_raw, history = await asyncio.gather(
            _get_json(session, WEATHER_URL),
            _get_text(session, TRAFFIC_URL),
            collect_news(session),
            _get_text(session, METRO_URL),
            city_event_for(now.astimezone(ZoneInfo("Europe/Moscow")).date()),
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
    if isinstance(news_raw, tuple):
        items, brief.news_available = news_raw
        brief.day_news = select_day_news(items, now)
    else:
        brief.news_available = False
    if isinstance(metro_raw, str):
        stations = parse_closed_stations(metro_raw)
        brief.metro_available = stations is not None
        brief.closed_stations = stations or []
    else:
        logger.warning("Сводка метро не ответила")
        brief.metro_available = False
    if isinstance(history, DayEvent):
        brief.history = history
    return brief


async def news_digest(now: datetime, limit: int = 2) -> str:
    timeout = aiohttp.ClientTimeout(total=12)
    headers = {"User-Agent": "NoraMorning/1.0"}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers, trust_env=True) as session:
            raw, available = await collect_news(session)
        if not available:
            return "Новости сейчас не открылись. Попробуй через минуту."
        items = select_day_news(raw, now, max(1, limit))
    except (aiohttp.ClientError, TimeoutError):
        logger.warning("Новости для Норы не ответили")
        return "Новости сейчас не открылись. Попробуй через минуту."
    if not items:
        return "📰 <b>За сутки</b>\nПодходящих новостей в доступных лентах не нашлось."
    return "\n".join(["📰 <b>За сутки</b>", *[_quote([render_news_line(item)]) for item in items]])


async def weather_reply(now: datetime) -> str:
    timeout = aiohttp.ClientTimeout(total=12)
    headers = {"User-Agent": "NoraMorning/1.0"}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers, trust_env=True) as session:
            payload = await _get_json(session, WEATHER_URL)
        text = render_weather_command(payload, now)
    except (aiohttp.ClientError, TimeoutError):
        logger.warning("Команда погоды не ответила")
        text = None
    if not text:
        return "Не удалось получить погоду. Попробуйте ещё раз через минуту."
    return text


async def publish_morning_digest(bot, db, settings, *, force: bool = False) -> bool:
    # The scheduler and the manual button share one Bot instance.
    lock = getattr(bot, "_morning_publish_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        bot._morning_publish_lock = lock
    async with lock:
        return await _publish_morning_digest(bot, db, settings, force=force)


async def _publish_morning_digest(bot, db, settings, *, force: bool = False) -> bool:
    if not settings.community_chat_id:
        return True
    if not force and not await db.feature_enabled("morning_digest"):
        return True
    timezone = ZoneInfo(settings.timezone)
    now = datetime.now(timezone)
    today = now.date().isoformat()
    posted = await db.get_bot_state("morning_digest_day")
    if not force and posted == today and await db.get_bot_state("morning_layout_version") != MORNING_LAYOUT:
        return await _refresh_today(bot, db, settings, now)
    if not force and not due_morning(now, posted):
        return True
    pending_day = await db.get_bot_state("morning_pending_day")
    pending_id = await db.get_bot_state("morning_pending_message_id")
    # A sent but unpinned post is retried in place, rather than sent a second time.
    if pending_day == today and pending_id:
        return await _pin_morning(bot, db, settings.community_chat_id, int(pending_id), today)

    brief = await collect_brief(now)
    text = render_brief(brief)
    from aiogram.types import FSInputFile

    from community_bot.ephemeral import keep_in_chat

    chat_id = settings.community_chat_id
    photo = brief.photo
    with keep_in_chat():
        if photo:
            sent = await bot.send_photo(chat_id, FSInputFile(photo), caption=text, parse_mode="HTML")
        else:
            from aiogram.types import LinkPreviewOptions

            sent = await bot.send_message(
                chat_id, text, parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
    await db.set_bot_state("morning_pending_message_id", str(sent.message_id))
    await db.set_bot_state("morning_pending_day", today)
    if brief.history:
        await db.set_bot_state("morning_history_day", today)
    return await _pin_morning(bot, db, chat_id, sent.message_id, today)


async def _refresh_today(bot, db, settings, now: datetime) -> bool:
    """Migrate today's known morning caption in place, preserving its photo and pin."""
    from aiogram.exceptions import TelegramBadRequest

    message_id = await db.get_bot_state("morning_pin_message_id")
    if not message_id:
        return False  # Never create an unsolicited duplicate if the old post cannot be identified.
    brief = await collect_brief(now)
    text = render_brief(brief)
    try:
        await bot.edit_message_caption(
            chat_id=settings.community_chat_id, message_id=int(message_id), caption=text, parse_mode="HTML",
        )
    except TelegramBadRequest as exc:
        reason = str(exc).casefold()
        if "message is not modified" in reason:
            pass
        elif "no caption" in reason:
            from aiogram.types import LinkPreviewOptions

            await bot.edit_message_text(
                chat_id=settings.community_chat_id, message_id=int(message_id), text=text, parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        else:
            logger.warning("Не удалось обновить подпись существующего утреннего закрепа")
            return False
    await db.set_bot_state("morning_layout_version", MORNING_LAYOUT)
    if brief.history:
        await db.set_bot_state("morning_history_day", now.date().isoformat())
    logger.info("Утренний закреп обновлён до %s без повторной отправки", MORNING_LAYOUT)
    return True


async def _pin_morning(bot, db, chat_id: int, message_id: int, today: str) -> bool:
    from community_bot.stickers import send_context_sticker

    await send_context_sticker(bot, db, chat_id, "morning", message_id)
    old_pin = await db.get_bot_state("morning_pin_message_id")
    try:
        await bot.pin_chat_message(chat_id, message_id, disable_notification=True)
    except Exception:
        logger.warning("Утренний пост ушёл в чат, но закрепить его не удалось")
        return False
    await db.set_bot_state("morning_pin_message_id", str(message_id))
    await db.set_bot_state("morning_digest_day", today)
    await db.set_bot_state("morning_layout_version", MORNING_LAYOUT)
    await db.set_bot_state("morning_pending_day", "")
    await db.set_bot_state("morning_pending_message_id", "")
    if old_pin and int(old_pin) != message_id:
        try:
            await bot.unpin_chat_message(chat_id, int(old_pin))
        except Exception:
            logger.info("Старый утренний закреп уже снят или недоступен")
    logger.info("Сводка за %s отправлена и закреплена", today)
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
