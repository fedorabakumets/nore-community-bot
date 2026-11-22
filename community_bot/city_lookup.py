"""Shared city selection for Telegram Rich prompts and the Mini App.

Open-Meteo Geocoding uses GeoNames; no Telegram IDs or profile fields are sent.
Only a selected, known location can be written into the profile.
"""
from __future__ import annotations

import asyncio
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any

import aiohttp

from community_bot.application_form import validate_city

# Stable local choices keep the onboarding functional if geocoding is unreachable.
POPULAR = (
    ("Москва", "Россия"), ("Санкт-Петербург", "Россия"),
    ("Новосибирск", "Россия"), ("Екатеринбург", "Россия"),
    ("Казань", "Россия"), ("Нижний Новгород", "Россия"),
    ("Челябинск", "Россия"), ("Красноярск", "Россия"),
    ("Самара", "Россия"), ("Уфа", "Россия"),
    ("Ростов-на-Дону", "Россия"), ("Омск", "Россия"),
    ("Краснодар", "Россия"), ("Воронеж", "Россия"),
    ("Пермь", "Россия"), ("Волгоград", "Россия"),
    ("Саратов", "Россия"), ("Тюмень", "Россия"),
    ("Тольятти", "Россия"), ("Ижевск", "Россия"),
    ("Барнаул", "Россия"), ("Ульяновск", "Россия"),
    ("Иркутск", "Россия"), ("Хабаровск", "Россия"),
    ("Владивосток", "Россия"), ("Ярославль", "Россия"),
    ("Томск", "Россия"), ("Калининград", "Россия"),
    ("Сочи", "Россия"), ("Севастополь", "Россия"),
    ("Минск", "Беларусь"), ("Алматы", "Казахстан"),
    ("Астана", "Казахстан"), ("Ташкент", "Узбекистан"),
    ("Ереван", "Армения"), ("Баку", "Азербайджан"),
    ("Тбилиси", "Грузия"),
)
ALIASES = {
    "спб": "Санкт-Петербург", "питер": "Санкт-Петербург",
    "петербург": "Санкт-Петербург", "санкт питербург": "Санкт-Петербург",
    "спбг": "Санкт-Петербург", "spb": "Санкт-Петербург",
    "saint petersburg": "Санкт-Петербург", "st petersburg": "Санкт-Петербург",
    "piter": "Санкт-Петербург",
    "мск": "Москва", "moskva": "Москва", "moscow": "Москва",
    "екб": "Екатеринбург", "нск": "Новосибирск",
    "н новгород": "Нижний Новгород", "нн": "Нижний Новгород",
    "kazan": "Казань", "novosibirsk": "Новосибирск",
}
# Russian words accidentally entered with an English keyboard layout.
_LATIN_KEYS = "qwertyuiop[]asdfghjkl;'zxcvbnm,."
_RUSSIAN_KEYS = "йцукенгшщзхъфывапролджэячсмитьбю"
_KEYBOARD_TRANSLATION = str.maketrans(_LATIN_KEYS, _RUSSIAN_KEYS)
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/"
_city_cache: dict[str, list[dict[str, Any]]] = {}


def popular_cities(page: int = 0, page_size: int = 6) -> tuple[list[dict], int]:
    size = max(1, min(12, page_size))
    pages = (len(POPULAR) + size - 1) // size
    page = max(0, min(pages - 1, page))
    return [_popular_item(i) for i in range(page * size, min(len(POPULAR), (page + 1) * size))], pages


def _popular_item(index: int) -> dict[str, Any]:
    name, country = POPULAR[index]
    return {"id": f"p:{index}", "name": name, "region": "", "country": country}


@lru_cache(maxsize=1)
def _russian_places() -> tuple[tuple[str, str], ...]:
    """Bundled Apache-2.0 list of verified Russian settlements and transliterations."""
    filename = Path(__file__).with_name("city_catalog_ru.csv")
    return tuple(
        (parts[0], parts[1])
        for line in filename.read_text(encoding="utf-8-sig").splitlines()
        if len(parts := line.split(",", 1)) == 2
    )


def _russian_item(index: int) -> dict[str, Any]:
    return {"id": f"r:{index}", "name": _russian_places()[index][0],
            "region": "", "country": "Россия"}


def _russian_matches(query: str) -> list[dict[str, Any]]:
    """Typos in less-popular place names still work when geocoding is offline."""
    normalized = _normalize(query)
    scored: list[tuple[float, int]] = []
    for i, (name, english) in enumerate(_russian_places()):
        name_key = _normalize(name)
        translit_key = _normalize(english)
        if normalized == name_key or normalized == translit_key:
            score = 4.0
        elif name_key.startswith(normalized) or translit_key.startswith(normalized):
            score = 3.0 + len(normalized) / max(len(name_key), 1)
        elif normalized in name_key or normalized in translit_key:
            score = 2.0
        elif len(normalized) >= 4:
            likeness = max(
                SequenceMatcher(None, normalized, name_key).ratio(),
                SequenceMatcher(None, normalized, translit_key).ratio(),
            )
            score = 1.0 + likeness if likeness >= 0.78 else 0
        else:
            score = 0
        if score:
            scored.append((score, i))
    scored.sort(reverse=True)
    return [_russian_item(i) for _, i in scored[:12]]


def _normalize(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").replace("-", " ").split())


def city_label_matches(value: str, selected: str) -> bool:
    """The displayed input must agree with the verified selection token."""
    return _normalize(value) == _normalize(selected)


def _search_alias(value: str) -> str:
    normalized = _normalize(value)
    if normalized in ALIASES:
        return ALIASES[normalized]
    if re.fullmatch(r"[a-z\\[\\];',.\\s]+", normalized) and any("a" <= c <= "z" for c in normalized):
        corrected = _normalize(normalized.translate(_KEYBOARD_TRANSLATION))
        if corrected in ALIASES:
            return ALIASES[corrected]
        if max(SequenceMatcher(None, corrected, _normalize(name)).ratio()
               for name, _ in (*POPULAR, *_russian_places())) >= 0.80:
            return corrected
    # Keep Latin city names (Berlin, Paris, etc.) for the worldwide geocoder.
    return value


def _from_geocoder(row: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(row, dict) or not str(row.get("feature_code", "")).startswith("PPL"):
        return None
    if not isinstance(row.get("id"), int):
        return None
    name = row.get("name")
    country = row.get("country")
    if not isinstance(name, str) or not isinstance(country, str):
        return None
    try:
        name = validate_city(name)
    except ValueError:
        return None
    return {"id": f"g:{row['id']}", "name": name,
            "region": str(row.get("admin1") or ""),
            "country": country}


async def _geocoding(endpoint: str, params: dict[str, Any]) -> dict:
    timeout = aiohttp.ClientTimeout(total=5)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(GEOCODING_URL + endpoint, params=params) as response:
            response.raise_for_status()
            result = await response.json(content_type=None)
            if not isinstance(result, dict) or result.get("error"):
                raise ValueError("Справочник городов временно недоступен")
            return result


async def search_cities(query: str, limit: int = 12) -> list[dict]:
    query = validate_city(query)
    normalized = _normalize(query)
    key = normalized
    if key in _city_cache:
        return _city_cache[key][:limit]
    alias = _search_alias(query)
    target = _normalize(alias)
    popular = [_popular_item(i) for i, (name, _country) in enumerate(POPULAR)
               if target in _normalize(name) or _normalize(name) in target]
    if not popular and len(normalized) >= 4:
        close = sorted(
            ((SequenceMatcher(None, target, _normalize(name)).ratio(), index)
             for index, (name, _) in enumerate(POPULAR)),
            reverse=True,
        )
        popular = [_popular_item(index) for score, index in close if score >= 0.77][:3]
    local = popular + _russian_matches(target)
    external = []
    try:
        response = await _geocoding("search", {"name": alias, "count": 20, "language": "ru"})
        external = [item for row in response.get("results", [])
                    if (item := _from_geocoder(row)) is not None]
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError):
        if not local:
            raise ValueError("Не удалось проверить город. Попробуй ещё раз чуть позже.") from None
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in local + external:
        unique = (_normalize(item["name"]), _normalize(item["country"]))
        if unique in seen:
            # Retain geographically distinct results if they are in different regions.
            if not item["region"]:
                continue
            if any(_normalize(old["name"]) == unique[0] and
                   _normalize(old["country"]) == unique[1] and
                   _normalize(old["region"]) == _normalize(item["region"]) for old in found):
                continue
        seen.add(unique)
        found.append(item)
    # Exact and strong name matches first; geocoder candidates remain verified
    # towns, but distant matches must never silently overwrite typed text.
    found.sort(key=lambda item: (
        city_label_matches(item["name"], alias),
        _normalize(item["name"]).startswith(target),
        SequenceMatcher(None, target, _normalize(item["name"])).ratio(),
    ), reverse=True)
    result = found[:20]
    if len(_city_cache) >= 200:
        _city_cache.pop(next(iter(_city_cache)))
    _city_cache[key] = result
    return result[:limit]


async def resolve_city_id(choice: str) -> str:
    if not isinstance(choice, str):
        raise ValueError("Выбери город из списка")
    if choice.startswith("p:") and re.fullmatch(r"p:[0-9]{1,2}", choice):
        index = int(choice[2:])
        if 0 <= index < len(POPULAR):
            return POPULAR[index][0]
    if re.fullmatch(r"r:[0-9]{1,5}", choice):
        index = int(choice[2:])
        if index < len(_russian_places()):
            return _russian_places()[index][0]
    if re.fullmatch(r"g:[0-9]{1,12}", choice):
        try:
            row = await _geocoding("get", {"id": int(choice[2:]), "language": "ru"})
        except (aiohttp.ClientError, asyncio.TimeoutError, TypeError, ValueError):
            raise ValueError("Не удалось подтвердить город. Попробуй ещё раз.") from None
        item = _from_geocoder(row)
        if item is not None and item["id"] == choice:
            return item["name"]
    raise ValueError("Город не найден. Выбери вариант из списка")


async def resolve_city_text(value: str) -> str:
    """Compatible with older clients, without accepting arbitrary strings."""
    value = validate_city(value)
    # Older Mini App builds still post text; accept only exact known places.
    for name, _country in POPULAR:
        if _normalize(name) == _normalize(value):
            return name
    matches = await search_cities(value)
    exact = [item for item in matches if _normalize(item["name"]) == _normalize(value)]
    if len(exact) == 1:
        return await resolve_city_id(exact[0]["id"])
    raise ValueError("Выбери город из предложенного списка")
