from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime

import aiohttp

from community_bot.command_registry import default_reply_ttl, explicit_ttl, nora_enabled, option_value
from community_bot.texts import GROUP_COMMANDS_TEXT

logger = logging.getLogger(__name__)

_ADDRESS = re.compile(r"^\s*нора\b[\s,!:.\-—]*", re.IGNORECASE)
_FILLERS = re.compile(
    r"\b(где|какой|какая|какое|какие|что|посмотреть|глянуть|посоветуй|посоветуйте|"
    r"подскажи|подскажите|найди|найти|фильм|кино|сериал|песню|песня|трек|музыку|"
    r"мне|пожалуйста|сегодня|вечером)\b",
    re.IGNORECASE,
)
_GENRES = (
    ("комеди", "35"),
    ("драм", "18"),
    ("ужас", "27"),
    ("фантаст", "878"),
    ("боевик", "28"),
    ("детектив", "9648"),
    ("мульт", "16"),
    ("мелодрам", "10749"),
    ("триллер", "53"),
)
COMMANDS_BRIEF = """Коротко, что я умею.

«погода» или «Нора, какая погода» — Петербург сейчас и на ближайшие часы.
«Нора, новости» — город за сутки.
«Нора, топ чартов» — что сейчас слушают. «Нора, найди песню …» — конкретный трек.
«Нора, какой фильм посмотреть» и «Нора, где сериал …» — что включить и где.
«магазин», «профиль», «баланс», «игры», «тамагочи» — как и раньше.

Полный список: «команды»."""

_HELP_PROMPT = """Ты Нора, бот сообщества. Ответь на вопрос коротко, на «ты», по-русски.
Используй только этот список команд. Не выдумывай команды и цены.

Вопрос: {question}

Список:
{commands}
"""

_ROUTE_PROMPT = """Ты диспетчер бота Нора. Верни один JSON без пояснений:
{{"tool":"weather|news|music_chart|music_search|suggest_title|find_title|help|none","query":"","kind":"movie|tv|any","genre":"","avoid":""}}

weather — погода.
news — новости.
music_chart — что послушать, чарт, топ, без названия.
music_search — названы песня или исполнитель, query — строка поиска.
suggest_title — посоветовать фильм или сериал без названия. kind movie, tv или any.
find_title — назван конкретный фильм или сериал. query — название как сказал человек.
help — вопрос про бота и команды.
none — не про это.

Фраза: {question}
"""


def strip_address(text: str) -> str | None:
    raw = (text or "").strip()
    if not _ADDRESS.match(raw):
        return None
    return _ADDRESS.sub("", raw).strip()


def _genre(text: str) -> str:
    for needle, code in _GENRES:
        if needle in text:
            return code
    return ""


def _query_after(text: str) -> str:
    cleaned = _FILLERS.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?!.,")
    return cleaned


def rule_intent(text: str) -> dict[str, str] | None:
    raw = text.casefold().replace("ё", "е").replace("-", " ")
    raw = re.sub(r"\s+", " ", raw).strip(" ?!.,")
    if not raw:
        return {"tool": "help"}
    if "погод" in raw:
        return {"tool": "weather"}
    if "новост" in raw:
        return {"tool": "news"}
    if any(word in raw for word in ("команд", "что умеешь", "что ты умеешь")):
        return {"tool": "help"}
    music = any(word in raw for word in ("чарт", "топ", "музык", "песн", "трек", "послуша"))
    cinema = any(word in raw for word in ("фильм", "кино", "сериал", "посмотреть", "глянуть"))
    if music and not cinema:
        named = any(word in raw for word in ("песн", "трек", "найди", "найти", "исполнител"))
        if named and "чарт" not in raw and "топ" not in raw:
            return {"tool": "music_search", "query": _query_after(raw)}
        return {"tool": "music_chart"}
    if cinema or raw.startswith("где "):
        kind = "tv" if "сериал" in raw else "movie" if any(word in raw for word in ("фильм", "кино")) else "any"
        suggest = any(word in raw for word in ("какой", "какая", "какое", "посовет", "подскаж", "что "))
        titled = _query_after(raw)
        if suggest or not titled:
            return {
                "tool": "suggest_title",
                "kind": "movie" if kind == "any" else kind,
                "genre": _genre(raw),
                "avoid": "27" if any(word in raw for word in ("не ужас", "не кровь", "без крови")) else "",
            }
        return {"tool": "find_title", "kind": kind, "query": titled}
    return None


def render_tracks(heading: str, tracks: list[tuple[str, str, str]]) -> str:
    if not tracks:
        return "Сейчас ничего не нашлось. Назови исполнителя или трек точнее."
    lines = [heading, ""]
    for index, (artist, title, _link) in enumerate(tracks[:5], start=1):
        lines.append(f"{index}. {html.escape(artist)} — {html.escape(title)}")
    link = next((item[2] for item in tracks if item[2]), "")
    if link:
        url = html.escape(link, quote=True)
        lines.extend(["", f"<a href=\"{url}\">Открыть</a>"])
    return "\n".join(lines)


def render_watch(name: str, year: str, overview: str, providers: list[str], link: str, *, series: bool) -> str:
    kind = "Сериал" if series else "Фильм"
    year_bit = f" ({html.escape(year)})" if year else ""
    sentence = html.escape(overview.strip()) or "Короткого описания нет."
    if len(sentence) > 280:
        sentence = sentence[:279].rsplit(" ", 1)[0] + "…"
    lines = [f"🎬 <b>{html.escape(name)}</b>{year_bit}", sentence, ""]
    if providers:
        shown = ", ".join(html.escape(item) for item in providers[:3])
        lines.append(f"Смотреть: {shown}")
        if link:
            url = html.escape(link, quote=True)
            lines.append(f"<a href=\"{url}\">Страница просмотра</a>")
    else:
        lines.append("В каталоге для России площадок не видно.")
    lines.extend(["", f"{kind}. Каталог: TMDB"])
    return "\n".join(lines)


def _tracks_from_itunes_chart(payload: dict[str, object]) -> list[tuple[str, str, str]]:
    feed = payload.get("feed")
    if not isinstance(feed, dict):
        return []
    entries = feed.get("entry")
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return []
    tracks: list[tuple[str, str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("im:name")
        artist = entry.get("im:artist")
        title = str(name.get("label") if isinstance(name, dict) else name or "").strip()
        who = str(artist.get("label") if isinstance(artist, dict) else artist or "").strip()
        link = ""
        links = entry.get("link")
        if isinstance(links, dict):
            links = [links]
        if isinstance(links, list):
            for item in links:
                if isinstance(item, dict) and str((item.get("attributes") or {}).get("rel")) in {"", "alternate"}:
                    href = str((item.get("attributes") or {}).get("href") or "")
                    if href:
                        link = href
                        break
        if title:
            tracks.append((who or "—", title, link))
    return tracks


def _tracks_from_itunes_search(payload: dict[str, object]) -> list[tuple[str, str, str]]:
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    tracks: list[tuple[str, str, str]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("trackName") or "").strip()
        artist = str(item.get("artistName") or "").strip()
        link = str(item.get("trackViewUrl") or "")
        if title:
            tracks.append((artist or "—", title, link))
    return tracks


def _providers(payload: dict[str, object]) -> tuple[list[str], str]:
    results = payload.get("results")
    if not isinstance(results, dict):
        return [], ""
    region = results.get("RU")
    if not isinstance(region, dict):
        return [], ""
    names: list[str] = []
    for bucket in ("flatrate", "free", "ads", "rent", "buy"):
        rows = region.get(bucket)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("provider_name") or "").strip()
            if name and name not in names:
                names.append(name)
    return names[:3], str(region.get("link") or "")


async def _get_json(
    session: aiohttp.ClientSession,
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, object]:
    async with session.get(url, headers=headers) as response:
        response.raise_for_status()
        payload = await response.json(content_type=None)
    return payload if isinstance(payload, dict) else {}


async def music_chart(limit: int) -> str:
    url = f"https://itunes.apple.com/ru/rss/topsongs/limit={max(1, min(limit, 10))}/json"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as session:
            payload = await _get_json(session, url)
    except (aiohttp.ClientError, TimeoutError):
        logger.warning("Чарт музыки не ответил")
        return "Чарт сейчас не открылся. Попробуй через минуту."
    return render_tracks("🎵 <b>Сейчас в топе</b>", _tracks_from_itunes_chart(payload))


async def music_search(query: str) -> str:
    if not query:
        return "Назови песню или исполнителя."
    url = "https://itunes.apple.com/search"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as session:
            async with session.get(
                url,
                params={"term": query, "country": "ru", "media": "music", "entity": "song", "limit": "5"},
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError):
        logger.warning("Поиск музыки не ответил")
        return "Поиск песни сейчас не открылся. Попробуй через минуту."
    if not isinstance(payload, dict):
        payload = {}
    return render_tracks("🎵 <b>Нашла</b>", _tracks_from_itunes_search(payload))


def _ai_ready(settings: object) -> str:
    gemini = str(getattr(settings, "gemini_api_key", "") or "").strip()
    groq = str(getattr(settings, "groq_api_key", "") or "").strip()
    if gemini:
        return "gemini"
    if groq:
        return "groq"
    return ""


async def ask_model(prompt: str, settings: object) -> str | None:
    provider = _ai_ready(settings)
    if not provider:
        return None
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if provider == "gemini":
                key = str(settings.gemini_api_key)
                url = (
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    f"gemini-2.5-flash:generateContent?key={key}"
                )
                async with session.post(
                    url,
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 400},
                    },
                ) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
                candidates = payload.get("candidates") if isinstance(payload, dict) else None
                if not isinstance(candidates, list) or not candidates:
                    return None
                content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
                parts = content.get("parts") if isinstance(content, dict) else None
                if not isinstance(parts, list) or not parts:
                    return None
                text = str(parts[0].get("text") or "").strip()
                return text or None
            key = str(settings.groq_api_key)
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 400,
                },
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
            choices = payload.get("choices") if isinstance(payload, dict) else None
            if not isinstance(choices, list) or not choices:
                return None
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            text = str(message.get("content") or "").strip() if isinstance(message, dict) else ""
            return text or None
    except (aiohttp.ClientError, TimeoutError, KeyError, TypeError):
        logger.warning("Модель Норы не ответила")
        return None


def _parse_route(raw: str) -> dict[str, str] | None:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    tool = str(data.get("tool") or "")
    if tool not in {"weather", "news", "music_chart", "music_search", "suggest_title", "find_title", "help", "none"}:
        return None
    return {
        "tool": tool,
        "query": str(data.get("query") or ""),
        "kind": str(data.get("kind") or "any"),
        "genre": str(data.get("genre") or ""),
        "avoid": str(data.get("avoid") or ""),
    }


async def _tmdb(path: str, settings: object, params: dict[str, str]) -> dict[str, object] | None:
    key = str(getattr(settings, "tmdb_api_key", "") or "").strip()
    if not key:
        return None
    params = {"api_key": key, "language": "ru-RU", **params}
    url = f"https://api.themoviedb.org/3/{path}"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as session:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError):
        logger.warning("Каталог кино не ответил")
        return {}
    return payload if isinstance(payload, dict) else {}


def _pick_title(payload: dict[str, object] | None, kind: str) -> dict[str, object] | None:
    if not payload:
        return None
    results = payload.get("results")
    if not isinstance(results, list):
        return None
    for item in results:
        if not isinstance(item, dict):
            continue
        media = str(item.get("media_type") or kind or "")
        if kind in {"movie", "tv"} and media not in {kind, ""}:
            continue
        if media not in {"movie", "tv", ""}:
            continue
        name = str(item.get("title") or item.get("name") or "").strip()
        if name:
            copied = dict(item)
            series = media == "tv" or (bool(item.get("name")) and not item.get("title"))
            copied["_media"] = "tv" if series else "movie"
            return copied
    return None


async def _watch_line(settings: object, media: str, title_id: int) -> tuple[list[str], str]:
    payload = await _tmdb(f"{media}/{title_id}/watch/providers", settings, {})
    if not payload:
        return [], ""
    return _providers(payload)


async def suggest_title(settings: object, *, kind: str, genre: str, avoid: str) -> str:
    if not str(getattr(settings, "tmdb_api_key", "") or "").strip():
        return "С кино сейчас не связаться. Попробуй позже."
    params: dict[str, str] = {"sort_by": "popularity.desc", "watch_region": "RU", "include_adult": "false"}
    path = "discover/movie" if kind != "tv" else "discover/tv"
    if genre.isdigit():
        params["with_genres"] = genre
    if avoid.isdigit():
        params["without_genres"] = avoid
    payload = await _tmdb(path, settings, params)
    if payload == {}:
        return "Каталог кино сейчас не открылся. Попробуй через минуту."
    item = _pick_title(payload, "tv" if kind == "tv" else "movie")
    if item is None:
        return "Сейчас не нашла подходящий вариант. Назови жанр или название."
    return await _describe(settings, item)


async def find_title(settings: object, query: str, kind: str) -> str:
    if not query:
        return "Назови фильм или сериал."
    if not str(getattr(settings, "tmdb_api_key", "") or "").strip():
        return "С кино сейчас не связаться. Попробуй позже."
    if kind == "tv":
        payload = await _tmdb("search/tv", settings, {"query": query, "include_adult": "false"})
        media = "tv"
    elif kind == "movie":
        payload = await _tmdb("search/movie", settings, {"query": query, "include_adult": "false"})
        media = "movie"
    else:
        payload = await _tmdb("search/multi", settings, {"query": query, "include_adult": "false"})
        media = "any"
    if payload == {}:
        return "Каталог кино сейчас не открылся. Попробуй через минуту."
    item = _pick_title(payload, media)
    if item is None and kind == "any":
        return "Не нашла такое название. Напиши его чуть точнее."
    if item is None:
        return "Не нашла такое название. Напиши его чуть точнее."
    return await _describe(settings, item)


async def _describe(settings: object, item: dict[str, object]) -> str:
    media = "tv" if str(item.get("_media") or "") == "tv" or (item.get("name") and not item.get("title")) else "movie"
    name = str(item.get("name") if media == "tv" else item.get("title") or item.get("name") or "").strip()
    year = str(item.get("first_air_date") or item.get("release_date") or "")[:4]
    overview = str(item.get("overview") or "").strip()
    try:
        title_id = int(item.get("id") or 0)
    except (TypeError, ValueError):
        title_id = 0
    providers: list[str] = []
    link = ""
    if title_id:
        providers, link = await _watch_line(settings, media, title_id)
    return render_watch(name, year, overview, providers, link, series=media == "tv")


async def help_reply(question: str, settings: object) -> str:
    if _ai_ready(settings) and question and "команд" not in question.casefold():
        text = await ask_model(_HELP_PROMPT.format(question=question, commands=GROUP_COMMANDS_TEXT), settings)
        if text:
            return html.escape(text)
    return COMMANDS_BRIEF


async def reply_for(text: str, settings: object, now: datetime) -> str:
    if not nora_enabled():
        return ""
    body = strip_address(text)
    if body is None:
        return ""
    intent = rule_intent(body)
    if intent is None and _ai_ready(settings) and body:
        routed = _parse_route(await ask_model(_ROUTE_PROMPT.format(question=body), settings) or "")
        intent = routed
    if intent is None or intent.get("tool") in {None, "", "none"}:
        return "Могу подсказать погоду, новости, музыку и кино. Или спроси про команды."
    tool = intent["tool"]
    if tool == "weather":
        from community_bot.morning import weather_reply

        return await weather_reply(now)
    if tool == "news":
        from community_bot.morning import news_digest

        limit = int(option_value("nora", "news_limit", "2") or "2")
        return await news_digest(now, max(1, min(limit, 3)))
    if tool == "music_chart":
        limit = int(option_value("nora", "music_limit", "5") or "5")
        return await music_chart(max(1, min(limit, 10)))
    if tool == "music_search":
        return await music_search(intent.get("query") or _query_after(body))
    if tool == "suggest_title":
        return await suggest_title(
            settings,
            kind=intent.get("kind") or "movie",
            genre=intent.get("genre") or "",
            avoid=intent.get("avoid") or "",
        )
    if tool == "find_title":
        return await find_title(settings, intent.get("query") or _query_after(body), intent.get("kind") or "any")
    if tool == "help":
        return await help_reply(body, settings)
    return COMMANDS_BRIEF


def reply_ttl_seconds(text: str) -> float:
    body = strip_address(text) or ""
    intent = rule_intent(body) or {}
    if intent.get("tool") == "weather":
        return explicit_ttl("pogoda") or 60.0
    own = explicit_ttl("nora")
    if own is not None:
        return own
    return default_reply_ttl()
