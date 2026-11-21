"""Offline illustrative preview of the actual Rich Message blocks; no bot or network."""
from __future__ import annotations

import argparse
import base64
import html
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram.types import (
    InputRichBlockButtons,
    InputRichBlockDetails,
    InputRichBlockDivider,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichBlockSectionHeading,
    RichTextUrl,
)

from community_bot.day_note import DayEvent
from community_bot.morning import MorningBrief, NewsItem, WeatherNow
from community_bot.morning_rich import render_rich_brief


def text_html(text):
    if isinstance(text, str):
        return html.escape(text).replace("\n", "<br>")
    if isinstance(text, RichTextUrl):
        return f'<a href="{html.escape(text.url, quote=True)}">{text_html(text.text)}</a>'
    return "".join(text_html(part) for part in text)


def render_blocks(blocks):
    parts = []
    for block in blocks:
        if isinstance(block, InputRichBlockSectionHeading):
            parts.append(f'<h{block.size}>{text_html(block.text)}</h{block.size}>')
        elif isinstance(block, InputRichBlockParagraph):
            parts.append(f'<p>{text_html(block.text)}</p>')
        elif isinstance(block, InputRichBlockDivider):
            parts.append('<hr>')
        elif isinstance(block, InputRichBlockDetails):
            parts.append(f'<details><summary>{text_html(block.summary)}</summary>{render_blocks(block.blocks)}</details>')
        elif isinstance(block, InputRichBlockPhoto):
            encoded = base64.b64encode(Path(block.photo.media.path).read_bytes()).decode("ascii")
            parts.append(f'<img alt="Иллюстрация утра" src="data:image/jpeg;base64,{encoded}">')
        elif isinstance(block, InputRichBlockButtons):
            parts.append('<div class="buttons">' + ''.join(
                f'<span class="button">{text_html(button.text)}</span>' for button in block.buttons
            ) + '</div>')
    return "".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    now = datetime(2026, 10, 26, 9, tzinfo=ZoneInfo("Europe/Moscow"))
    brief = MorningBrief(
        now, weather=WeatherNow(8, 5, 3, 14, 0, "", ""), traffic_level=4,
        day_news=[
            NewsItem("В Петербурге открылось новое общественное пространство для прогулок и встреч",
                     now, link="https://example.org/one", lead="В городе появился новый адрес для встреч.",
                     source="Пример источника"),
            NewsItem("Городской музей подготовил новую выставку об истории Петербурга",
                     now, link="https://example.org/two", lead="Экспозиция рассказывает о жизни города.",
                     source="Пример источника"),
        ],
        history=DayEvent(1930, "В городе состоялась премьера.", "Премьера", "https://example.org/history",
                         "Контекст события.", 10, 26),
    )
    rich = render_rich_brief(brief, "example_bot")
    style = """body{background:#e6ece8;color:#26302d;font:15px/1.45 system-ui;margin:0;padding:18px}
main{max-width:410px;margin:auto}small{display:block;color:#51625b;margin-bottom:12px}
article{background:white;border-radius:16px;padding:18px;box-shadow:0 4px 18px #293e3022}
h1{font-size:26px;letter-spacing:.06em;margin:0}h2{font-size:20px;margin:16px 0 8px}
h3{font-size:17px;margin:16px 0 5px}p{margin:10px 0}img{width:100%;border-radius:12px;margin:6px 0}
hr{border:0;border-top:1px solid #d7dfdb;margin:18px 0}details{border-left:3px solid #7cac97;
background:#f0f6f2;padding:10px;margin:8px 0;border-radius:5px}summary{cursor:pointer;font-weight:600}
a{color:#25805d}.buttons{text-align:center}.button{display:inline-block;border-radius:8px;
background:#e2f1e9;color:#236c4d;padding:10px 30px;font-weight:700}"""
    page = ('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1"><title>NORA DAILY · Rich</title><style>' + style +
            '</style><main><small>Макет Rich Message. Данные и ссылки вымышлены; '
            'точный вид зависит от клиента Telegram. '
            'Нажмите на заголовок, чтобы раскрыть раздел.</small><article>' + render_blocks(rich.blocks) +
            '</article></main></html>')
    args.output.write_text(page, encoding="utf-8")
    print(f"Preview: {args.output}")


if __name__ == "__main__":
    main()
