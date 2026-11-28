"""Shared pet-care limits for Telegram, Mini App and level abilities."""

from __future__ import annotations

from typing import Mapping

MIN_PET_NEEDS = 50
HUNGER_DECAY_PER_HOUR = 4
THIRST_DECAY_PER_HOUR = 6


def needs_care(pet: Mapping[str, object]) -> bool:
    return int(pet["hunger"]) < MIN_PET_NEEDS or int(pet["thirst"]) < MIN_PET_NEEDS


def care_error(pet: Mapping[str, object]) -> str | None:
    if not needs_care(pet):
        return None
    return (
        "Питомцу нужен уход: сытость и вода должны быть не ниже "
        f"{MIN_PET_NEEDS}/100. Покорми и напои питомца через «Питомец»."
    )
