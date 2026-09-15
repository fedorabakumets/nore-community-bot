from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "pets"
CACHE = Path("/tmp/nora-pet-cache")

# Milli-cookies per hour added to the live farm rate while the item is equipped.
COSMETIC_BONUS_MILLI = {
    "pet_hat": 2,
    "pet_scarf": 2,
    "pet_glasses": 3,
}

COSMETIC_ITEMS = {
    "pet_hat": {
        "label": "🧢 Шапочка питомца",
        "intro": "Тёплая шапка на ушках. Слегка ускоряет фарм 🍪.",
        "bonus_milli": COSMETIC_BONUS_MILLI["pet_hat"],
        "layer": "hat",
    },
    "pet_scarf": {
        "label": "🧣 Шарфик уюта",
        "intro": "Мягкий шарф на шейке. Слегка ускоряет фарм 🍪.",
        "bonus_milli": COSMETIC_BONUS_MILLI["pet_scarf"],
        "layer": "scarf",
    },
    "pet_glasses": {
        "label": "🕶 Солнечные очки",
        "intro": "Модные очки. Слегка ускоряет фарм 🍪.",
        "bonus_milli": COSMETIC_BONUS_MILLI["pet_glasses"],
        "layer": "glasses",
    },
}

COSMETIC_ORDER = ("pet_hat", "pet_scarf", "pet_glasses")
SPECIES_FALLBACK = {"kitty": "cat"}


def cosmetic_bonus_milli(equipped: list[str] | tuple[str, ...] | set[str]) -> int:
    return sum(int(COSMETIC_BONUS_MILLI.get(item, 0)) for item in equipped)


def pet_hourly_milli(pet: dict[str, Any] | None, equipped: list[str] | tuple[str, ...] | set[str] = ()) -> int:
    if not pet:
        return 0
    hunger = int(pet["hunger"])
    thirst = int(pet["thirst"])
    if hunger == 0 or thirst == 0 or int(pet.get("sleeping") or 0):
        return 0
    average = (hunger + thirst) // 2
    base = 50 if average >= 70 else 34 if average >= 35 else 17
    return base + cosmetic_bonus_milli(equipped)


def species_base_path(species: str) -> Path | None:
    key = SPECIES_FALLBACK.get(species, species)
    path = ASSETS / f"{key}.png"
    return path if path.is_file() else None


def _draw_hat(overlay: Image.Image) -> None:
    draw = ImageDraw.Draw(overlay, "RGBA")
    w, h = overlay.size
    cx, top = w // 2, int(h * 0.10)
    rw, rh = int(w * 0.28), int(h * 0.16)
    draw.ellipse([cx - rw, top, cx + rw, top + rh * 2], fill=(196, 48, 72, 235), outline=(110, 22, 38, 255), width=10)
    brim_y = top + int(rh * 1.15)
    draw.rounded_rectangle(
        [cx - int(rw * 1.15), brim_y, cx + int(rw * 1.15), brim_y + int(h * 0.045)],
        radius=24,
        fill=(150, 28, 52, 240),
    )
    pom = 36
    draw.ellipse(
        [cx - pom, top - 18, cx + pom, top + 54],
        fill=(248, 244, 236, 255),
        outline=(210, 200, 190, 255),
        width=4,
    )


def _draw_scarf(overlay: Image.Image) -> None:
    draw = ImageDraw.Draw(overlay, "RGBA")
    w, h = overlay.size
    y = int(h * 0.58)
    draw.rounded_rectangle(
        [int(w * 0.18), y, int(w * 0.82), y + int(h * 0.11)],
        radius=48,
        fill=(36, 122, 98, 230),
        outline=(18, 72, 58, 255),
        width=8,
    )
    tail_x = int(w * 0.62)
    draw.polygon(
        [
            (tail_x, y + int(h * 0.08)),
            (tail_x + int(w * 0.12), y + int(h * 0.28)),
            (tail_x - int(w * 0.04), y + int(h * 0.12)),
        ],
        fill=(48, 150, 118, 230),
    )


def _draw_glasses(overlay: Image.Image) -> None:
    draw = ImageDraw.Draw(overlay, "RGBA")
    w, h = overlay.size
    y = int(h * 0.38)
    r = int(w * 0.11)
    gap = int(w * 0.035)
    left = w // 2 - gap // 2 - r * 2
    right = w // 2 + gap // 2
    color = (28, 28, 32, 245)
    lens = (40, 70, 110, 90)
    for x0 in (left, right):
        box = [x0, y, x0 + r * 2, y + int(r * 1.55)]
        draw.ellipse(box, fill=lens, outline=color, width=12)
    bridge_y = y + int(r * 0.7)
    draw.line([(left + r * 2, bridge_y), (right, bridge_y)], fill=color, width=10)
    draw.line([(left, bridge_y), (left - int(w * 0.06), bridge_y - 8)], fill=color, width=8)
    draw.line([(right + r * 2, bridge_y), (right + r * 2 + int(w * 0.06), bridge_y - 8)], fill=color, width=8)


_LAYERS = {
    "pet_hat": _draw_hat,
    "pet_scarf": _draw_scarf,
    "pet_glasses": _draw_glasses,
}


def render_pet_image(species: str, equipped: list[str] | tuple[str, ...] | set[str]) -> Path | None:
    base_path = species_base_path(species)
    if base_path is None:
        return None
    items = [item for item in COSMETIC_ORDER if item in set(equipped)]
    if not items:
        return base_path
    CACHE.mkdir(parents=True, exist_ok=True)
    stamp = "-".join(items) if items else "base"
    out = CACHE / f"{species}_{stamp}.png"
    try:
        if out.is_file() and out.stat().st_mtime >= base_path.stat().st_mtime:
            return out
        base = Image.open(base_path).convert("RGBA")
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        for item in items:
            drawer = _LAYERS.get(item)
            if drawer:
                drawer(overlay)
        Image.alpha_composite(base, overlay).save(out, "PNG")
        return out
    except OSError:
        return base_path
