"""Regression tests for real-place city matching and forged selection tokens."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from community_bot import city_lookup
from community_bot.application_form import validate_city
from community_bot.database import Database
from community_bot.miniapp import save_profile, submit_application
from community_bot.profile_fields import profile_revision


@pytest.mark.parametrize("text", [
    "12345", "???", "😺😺", "!!!Москва!!!", "Москв@",
    "аааааа", " ", "а", "Москва\\n<script>",
])
def test_invalid_city_names_are_rejected_early(text):
    with pytest.raises(ValueError, match="выбери"):
        validate_city(text)


@pytest.mark.asyncio
@pytest.mark.parametrize(("typed", "expected"), [
    ("Масква", "Москва"),
    ("Vjcrdf", "Москва"),  # Russian Moscow typed with an English layout.
    ("gbnth", "Санкт-Петербург"),  # Piter typed with an English layout.
    ("СПБ", "Санкт-Петербург"),
    ("moskva", "Москва"),
    ("St Petersburg", "Санкт-Петербург"),
])
async def test_city_picker_corrects_typo_and_aliases_offline(monkeypatch, typed, expected):
    monkeypatch.setattr(city_lookup, "_city_cache", {})

    async def offline(*_args, **_kwargs):
        raise ValueError("offline")

    monkeypatch.setattr(city_lookup, "_geocoding", offline)
    matches = await city_lookup.search_cities(typed)
    assert matches
    assert matches[0]["name"] == expected
    assert matches[0]["id"].startswith("p:")


@pytest.mark.asyncio
async def test_real_foreign_city_is_not_mistaken_for_keyboard_layout(monkeypatch):
    monkeypatch.setattr(city_lookup, "_city_cache", {})
    calls = []

    async def geocode(endpoint, params):
        calls.append((endpoint, params))
        return {"results": [{
            "id": 2950159, "feature_code": "PPLA",
            "name": "Берлин", "country": "Германия",
        }]}

    monkeypatch.setattr(city_lookup, "_geocoding", geocode)
    cities = await city_lookup.search_cities("Berlin")
    assert calls[0][1]["name"] == "Berlin"
    assert cities[0]["name"] == "Берлин"
    assert cities[0]["id"] == "g:2950159"


@pytest.mark.asyncio
async def test_city_picker_does_not_accept_unverified_gibberish(monkeypatch):
    monkeypatch.setattr(city_lookup, "_city_cache", {})

    async def empty(*_args, **_kwargs):
        return {"results": []}

    monkeypatch.setattr(city_lookup, "_geocoding", empty)
    assert await city_lookup.search_cities("Непонятноград") == []
    with pytest.raises(ValueError, match="Выбери город"):
        await city_lookup.resolve_city_text("Непонятноград")


@pytest.mark.asyncio
async def test_miniapp_profile_rejects_mismatched_city_id(tmp_path):
    db = Database(tmp_path / "profile-city.db")
    await db.initialize()
    await db.ensure_user(7, telegram_name="Участник")
    await db.update_profile(7, "city", "Москва")
    old = await db.get_user(7)

    class Request(dict):
        app = {"db": db}

        async def json(self):
            return {"fields": {"city": "Казань"}, "city_id": "p:0",
                    "revision": profile_revision(old)}

    with pytest.raises(ValueError, match="не совпадает"):
        await save_profile(Request(actor={"id": 7, "first_name": "Участник"}))
    assert (await db.get_user(7))["city"] == "Москва"


@pytest.mark.asyncio
async def test_application_rejects_city_that_disagrees_with_choice(tmp_path):
    db = Database(tmp_path / "onboard-city.db")
    await db.initialize()

    class Request(dict):
        app = {"db": db, "settings": SimpleNamespace(owner_id=99)}

        async def json(self):
            return {
                "name": "Анна", "age": 20, "city": "Казань", "city_id": "p:0",
                "bio": "Увлечения", "ban_version": None,
            }

    request = Request(actor={"id": 17, "first_name": "Анна"}, application_ban={})
    response = await submit_application(request)
    assert response.status == 400
    assert "не совпадает" in json.loads(response.body)["error"]
    assert await db.get_user(17) is None


def test_real_city_spellings_are_validated_without_guessing():
    assert validate_city("Санкт-Петербург") == "Санкт-Петербург"
    assert validate_city("  Нью-Йорк  ") == "Нью-Йорк"
    assert city_lookup.city_label_matches("санкт петербург", "Санкт-Петербург")
    assert not city_lookup.city_label_matches("Казань", "Москва")
