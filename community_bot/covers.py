from __future__ import annotations

from pathlib import Path

from community_bot.menu_art import STYLE, render_cover
from community_bot.updates import BotUpdate


def cover_cache_path(number: int, cache_dir: Path | None = None) -> Path:
    root = cache_dir or Path("/tmp/nora-covers") / STYLE
    return root / f"update-{number}.png"


def render_update_cover(number: int, title: str, dest: Path) -> Path:
    # The full release title stays in the caption; artwork uses the common fixed-size heading.
    del title
    return render_cover("updates", destination=dest, subtitle=f"#{number}")


def cover_path_for(item: BotUpdate, cache_dir: Path | None = None) -> Path:
    return render_update_cover(item.number, item.title, cover_cache_path(item.number, cache_dir))
