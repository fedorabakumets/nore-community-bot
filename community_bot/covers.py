from __future__ import annotations

from pathlib import Path

from community_bot.updates import BotUpdate

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "updates"
FONT_PATH = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Inter-Bold.ttf"
COVER_BASE = ASSETS / "cover-base.png"


def cover_cache_path(number: int, cache_dir: Path | None = None) -> Path:
    root = cache_dir or Path("/tmp/nora-covers")
    return root / f"update-{number}.png"


def render_update_cover(number: int, title: str, dest: Path) -> Path | None:
    if not COVER_BASE.is_file():
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return COVER_BASE if COVER_BASE.is_file() else None
    image = Image.open(COVER_BASE).convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = image.size
    bar_top = int(height * 0.72)
    draw.rectangle((0, bar_top, width, height), fill=(8, 14, 32, 210))
    headline = f"Обновление №{number}"
    subtitle = title.strip()
    size_lg = max(28, int(height * 0.075))
    size_sm = max(18, int(height * 0.038))
    try:
        font_lg = ImageFont.truetype(str(FONT_PATH), size_lg) if FONT_PATH.is_file() else ImageFont.load_default()
        font_sm = ImageFont.truetype(str(FONT_PATH), size_sm) if FONT_PATH.is_file() else font_lg
    except OSError:
        font_lg = ImageFont.load_default()
        font_sm = font_lg
    headline_box = draw.textbbox((0, 0), headline, font=font_lg)
    headline_w = headline_box[2] - headline_box[0]
    x = (width - headline_w) // 2
    y = bar_top + int(height * 0.035)
    draw.text((x, y), headline, font=font_lg, fill=(255, 236, 200, 255))
    if subtitle:
        sub_box = draw.textbbox((0, 0), subtitle, font=font_sm)
        sub_w = sub_box[2] - sub_box[0]
        draw.text(
            ((width - sub_w) // 2, y + size_lg + int(height * 0.012)),
            subtitle,
            font=font_sm,
            fill=(214, 201, 168, 255),
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.alpha_composite(image, overlay).convert("RGB").save(dest, "PNG", optimize=True)
    return dest


def cover_path_for(item: BotUpdate, cache_dir: Path | None = None) -> Path | None:
    for suffix in (".png", ".jpg", ".jpeg", ".webp"):
        numbered = ASSETS / f"{item.number}{suffix}"
        if numbered.is_file():
            return numbered
    dest = cover_cache_path(item.number, cache_dir)
    if COVER_BASE.is_file() and dest.is_file() and dest.stat().st_mtime >= COVER_BASE.stat().st_mtime:
        return dest
    rendered = render_update_cover(item.number, item.title, dest)
    if rendered and rendered.is_file():
        return rendered
    return COVER_BASE if COVER_BASE.is_file() else None
