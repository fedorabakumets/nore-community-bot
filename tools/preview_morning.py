"""Build a local preview using public sources; never starts or contacts the bot."""
from __future__ import annotations

import argparse
import asyncio
import base64
import html
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from community_bot.morning import collect_brief, render_brief, telegram_length

STYLE = """body { margin:0; padding:22px; background:#dce6df; color:#202b29;
       font:15px/1.45 system-ui,sans-serif; }
main { max-width:430px; margin:auto; }
.note { font-size:12px; color:#475951; margin:0 0 12px; }
article { background:#fff; border-radius:17px; overflow:hidden;
          box-shadow:0 3px 20px #293e3020; }
img { display:block; width:100%; max-height:300px; object-fit:cover; }
.text { padding:16px; white-space:pre-wrap; }
details { border-left:3px solid #679b80; background:#eff5f0;
          border-radius:5px; padding:8px 10px; margin:5px 0; white-space:normal; }
summary { cursor:pointer; font-size:14px; font-weight:600; }
details div { padding-top:8px; white-space:pre-wrap; font-size:14px; }
a { color:#287253; text-decoration:none; }
footer { color:#697b72; font-size:11px; padding:0 16px 12px; text-align:right; }
"""


def browser_quotes(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        first, _, rest = match.group(1).partition("\n")
        return f"<details><summary>{first}</summary><div>{rest}</div></details>"

    return re.sub(r"<blockquote expandable>(.*?)</blockquote>", replace, text, flags=re.S)


async def build(output: Path) -> None:
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    brief = await collect_brief(now)
    caption = render_brief(brief)
    image = ""
    if brief.photo:
        encoded = base64.b64encode(await asyncio.to_thread(brief.photo.read_bytes)).decode()
        image = f'<img alt="Существующая фотография Норы" src="data:image/jpeg;base64,{encoded}">'
    note = html.escape(f"Предпросмотр · {now:%d.%m.%Y %H:%M} МСК. Цитаты раскрываются по нажатию.")
    page = (
        '<!doctype html><html lang="ru"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Нора · утренняя сводка</title><style>' + STYLE + '</style>'
        '<main><p class="note">' + note + '</p><article>' + image
        + '<div class="text">' + browser_quotes(caption) + '</div>'
        + f'<footer>{telegram_length(caption)} / 1024 знаков подписи</footer></article>'
        '<p class="note">Макет оформления. В Telegram используются родные раскрывающиеся цитаты.</p></main></html>'
    )
    await asyncio.to_thread(output.write_text, page, encoding="utf-8")
    await asyncio.to_thread(output.with_suffix(".caption.txt").write_text, caption, encoding="utf-8")
    print(f"Preview: {output}; caption length: {telegram_length(caption)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/workspace/nora-morning-preview.html"))
    args = parser.parse_args()
    asyncio.run(build(args.output))


if __name__ == "__main__":
    main()
