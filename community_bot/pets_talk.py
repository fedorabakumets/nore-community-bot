from __future__ import annotations

import random
from typing import Any

SPECIES = {
    "cat": ("🐈", "кот", "m"),
    "dog": ("🐕", "пёс", "m"),
    "raccoon": ("🦝", "енот", "m"),
    "fox": ("🦊", "лиса", "f"),
    "dragon": ("🐉", "дракончик", "m"),
}


def species_meta(species: str) -> tuple[str, str]:
    emoji, label, _gender = SPECIES.get(species, ("🐾", "питомец", "m"))
    return emoji, label


def species_gender(species: str) -> str:
    meta = SPECIES.get(species)
    return str(meta[2]) if meta else "m"


def is_feminine(species: str) -> bool:
    return species_gender(species) == "f"


def pet_pronouns(species: str) -> dict[str, str]:
    if is_feminine(species):
        return {
            "he": "она",
            "him": "её",
            "his": "её",
            "went": "ушла",
            "returned": "вернулась",
            "brought": "принесла",
            "said": "сказала",
            "sits": "сидит",
            "melts": "тает",
            "sleeps": "спит",
            "guards": "охраняет",
            "name_how": "её",
            "pet_acc": "питомицу",
            "awake": "бодрствует и светится",
            "sleep_status": "сладко спит от голода или жажды",
        }
    return {
        "he": "он",
        "him": "его",
        "his": "его",
        "went": "ушёл",
        "returned": "вернулся",
        "brought": "принёс",
        "said": "сказал",
        "sits": "сидит",
        "melts": "тает",
        "sleeps": "спит",
        "guards": "охраняет",
        "name_how": "его",
        "pet_acc": "питомца",
        "awake": "бодрствует и светится",
        "sleep_status": "сладко спит от голода или жажды",
    }


def pet_species_of(pet: dict[str, Any] | None) -> str:
    return str((pet or {}).get("species") or "")


_TALK = {
    "cat": (
        "мяу-мяу~ {name} трётся щёчкой о тебя 🐈💕✨ ты самый тёплый человек на свете 🌸🫶",
        "прррр… {name} свернулся калачиком и мурчит только для тебя 🧸💛🐈💫💕",
        "{name} принёс воображаемую мышку-звёздочку ⭐🐭 и смотрит глазами-сердечками 😻💖",
        "если бы у {name} были слова, он сказал бы «я тебя очень-очень люблю» 💌🐈🌷✨",
    ),
    "dog": (
        "тяв-тяв!! {name} виляет хвостиком так быстро, что разлетаются сердечки 🐕💞💫🫶",
        "{name} принёс любимую игрушку и смотрит: «ну поиграй, самый лучший человек» 🎾💛🐕✨",
        "обнимашки-обнимашки!! {name} кладёт мордочку тебе на колени 🧸💕🐶🌸",
        "{name} гордо сидит рядом: ты его целый мир 🌍💖🐕🫶✨",
    ),
    "raccoon": (
        "{name} полоскает в лапках воображаемое печенье 🍪🦝💧 и дарит его тебе 🥹💕",
        "хихихи~ {name} прячет носик в твоих ладонях 🌙🦝✨ ты самое уютное сокровище 💎🫶",
        "{name} притащил блестяшку: это ты ✨💖🦝🌷",
        "маленький бандит {name} ворует грусть и оставляет только радость 🦝🍭💕🌟",
    ),
    "fox": (
        "{name} взмахивает пушистым хвостом и шепчет: ты моя звёздочка 🦊⭐💕🌸",
        "хитрая, но очень нежная {name} тычется носом в щёку 🧡🦊🫶✨",
        "{name} принесла лучик заката и кладёт его рядом с тобой 🌅💖🦊💫",
        "если обнять {name}, она тает как зефирка 🦊🍡💕🌷",
    ),
    "dragon": (
        "{name} выпускает крошечное облачко тёплого пара и обнимает крылышками 🐉💗✨",
        "храбрый {name} охраняет тебя лучше всех сокровищ 💎🐉🫶🌸",
        "{name} кладёт голову на плечо и мурлычет по-драконьи 🌙💚🐉💕",
        "ты — любимый человек {name}. это официальный королевский указ 👑🐉💖✨",
    ),
}

_FEED = (
    "{name} счастливо чавкает и светится от радости 🍽️✨💕 ты волшебный повар 🪄",
    "ням-ням-ням!! {name} танцует маленький танец благодарности 💃🐾💖",
    "{name} облизал носик и прошептал «ещё капельку любви, пожалуйста» 🥺💞✨",
)

_FEED_F = (
    "{name} счастливо чавкает и светится от радости 🍽️✨💕 ты волшебный повар 🪄",
    "ням-ням-ням!! {name} танцует маленький танец благодарности 💃🐾💖",
    "{name} облизала носик и прошептала «ещё капельку любви, пожалуйста» 🥺💞✨",
)

_DRINK = (
    "{name} делает глоточек и довольно жмурится 💧😇💕",
    "бульк~ {name} свежий как утренняя роса 🌿💧✨💖",
    "{name} стучит лапкой: «лучший поильник в мире — это ты» 🫶💧🌸",
)

_DRINK_F = (
    "{name} делает глоточек и довольно жмурится 💧😇💕",
    "бульк~ {name} свежая как утренняя роса 🌿💧✨💖",
    "{name} стучит лапкой: «лучший поильник в мире — это ты» 🫶💧🌸",
)

_IDLE = (
    "{name} скучает и шлёт воздушный поцелуй 😘💨💕🐾 открой /pet, обнимемся",
    "пс-пс-пс… {name} спрятал для тебя звёздочку ⭐🥺💖 загляни в тамагочи",
    "{name} нарисовал сердечко лапкой 🖼️💗✨ и ждёт тебя в /pet",
    "тихий писк: {name} хочет нос к носу 🐽💕🌸 совсем капельку внимания",
)

_IDLE_F = (
    "{name} скучает и шлёт воздушный поцелуй 😘💨💕🐾 открой /pet, обнимемся",
    "пс-пс-пс… {name} спрятала для тебя звёздочку ⭐🥺💖 загляни в тамагочи",
    "{name} нарисовала сердечко лапкой 🖼️💗✨ и ждёт тебя в /pet",
    "тихий писк: {name} хочет нос к носу 🐽💕🌸 совсем капельку внимания",
)


def talk_line(pet: dict[str, object]) -> str:
    name = str(pet.get("name") or "малыш")
    species = str(pet.get("species") or "")
    lines = _TALK.get(species, _TALK["cat"])
    return random.choice(lines).format(name=name)


def aftercare_line(pet: dict[str, object], kind: str) -> str:
    name = str(pet.get("name") or "малыш")
    species = str(pet.get("species") or "")
    if kind == "water":
        pool = _DRINK_F if is_feminine(species) else _DRINK
    else:
        pool = _FEED_F if is_feminine(species) else _FEED
    return random.choice(pool).format(name=name)


def idle_ping(pet: dict[str, object]) -> str:
    name = str(pet.get("name") or "малыш")
    species = str(pet.get("species") or "")
    pool = _IDLE_F if is_feminine(species) else _IDLE
    return random.choice(pool).format(name=name)
