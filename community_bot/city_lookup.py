"""Shared city selection for Telegram Rich prompts and the Mini App.

Open-Meteo Geocoding uses GeoNames; no Telegram IDs or profile fields are sent.
Only a selected, known location can be written into the profile.
"""
from __future__ import annotations

import asyncio
import re
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
ALIASES = {"спб": "Санкт-Петербург", "питер": "Санкт-Петербург",
           "петербург": "Санкт-Петербург", "мск": "Москва",
           "екб": "Екатеринбург", "нск": "Новосибирск"}
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


def _normalize(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").replace("-", " ").split())


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
    alias = ALIASES.get(normalized, query)
    local = [_popular_item(i) for i, (name, country) in enumerate(POPULAR)
             if normalized in _normalize(name) or _normalize(alias) == _normalize(name)]
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
    # Local exact matches first, then the source's population-ranked candidates.
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
