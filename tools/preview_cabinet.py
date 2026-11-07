"""Render the real cabinet/wallet copy with example data. No Telegram or production DB."""
from __future__ import annotations

import argparse
import asyncio
import base64
import html
from pathlib import Path
from types import SimpleNamespace

from community_bot.blocks import cover_path
from community_bot.cabinet import cabinet_text
from community_bot.keyboards import private_menu_keyboard, wallet_keyboard
from community_bot.routers.wallet import wallet_text


def card(title: str, block: str, text: str, markup) -> str:
    path = cover_path(block)
    picture = ""
    if path:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        picture = f'<img class="cover" alt="" src="data:image/jpeg;base64,{encoded}">'
    buttons = []
    for row in markup.inline_keyboard:
        buttons.append('<div class="row">' + "".join(
            f'<button type="button">{html.escape(button.text)}</button>' for button in row
        ) + "</div>")
    return (
        f'<section><h2>{html.escape(title)}</h2><div class="phone"><div class="top">'
        '<span class="avatar">Н</span><div><strong>Нора</strong><small>бот · пример интерфейса</small></div>'
        f'</div><div class="chat"><article>{picture}<div class="body">{text.replace(chr(10), "<br>")}</div>'
        f'</article><div class="keyboard">{"".join(buttons)}</div></div></div></section>'
    )


async def preview(output: Path) -> None:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    user = {
        "user_id": 7, "profile_name": "Анна", "telegram_name": "Анна", "cookies": 120, "cookie_debt": 35,
        "reputation": 80, "age": 25, "hobbies": "Петербург и кино", "profile_bio": "", "avatar_file_id": "",
    }
    pet = {"name": "Булочка", "expedition_until": ""}

    class ExampleDatabase:
        async def get_active_loan(self, _user_id):
            return None

    settings = SimpleNamespace(restricted_reputation_threshold=0, timezone="Europe/Moscow")
    panels = [
        card("1. Главный экран", "cabinet", cabinet_text(user, pet, unread=2), private_menu_keyboard(unread=2)),
        card("2. Кошелёк", "wallet", await wallet_text(ExampleDatabase(), settings, user),
             wallet_keyboard(False, has_debt=True)),
        card("3. Подтверждение погашения", "wallet",
             "💳 <b>Погасить просроченный долг?</b>\n\nСпишется: <b>35 🍪</b>\n"
             "Останется на балансе: 85 🍪\nОстанется долга: 0 🍪",
             InlineKeyboardMarkup(inline_keyboard=[
                 [InlineKeyboardButton(text="Погасить 35 🍪", callback_data="preview")],
                 [InlineKeyboardButton(text="↩️ Назад", callback_data="preview")],
             ])),
    ]
    page = """<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Нора · кабинет и кошелёк</title>
<style>
*{box-sizing:border-box}body{margin:0;padding:30px;background:#eef2ed;color:#19332e;
font:15px/1.45 system-ui,-apple-system,sans-serif}header{max-width:1200px;margin:auto auto 25px}
h1{font-size:25px;margin:0 0 8px}header p{margin:0;color:#557068;max-width:800px}
main{max-width:1200px;margin:auto;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px}
h2{font-size:16px;margin:0 0 12px}.phone{border:1px solid #cad6cc;border-radius:22px;overflow:hidden;
background:#e1e9df;box-shadow:0 8px 25px #25433612;min-height:710px}.top{display:flex;align-items:center;
gap:12px;background:#fff;padding:16px}.avatar{display:grid;place-items:center;width:42px;height:42px;
border-radius:50%;background:#314e37;color:#fff;font-size:23px}.top strong{display:block;font-size:17px}
small{display:block;font-size:12px;color:#7a8c80}.chat{padding:16px 11px 24px}article{background:white;
border-radius:12px;overflow:hidden}.cover{display:block;width:100%;height:auto}
.body{padding:14px 13px;font-size:14px;overflow-wrap:anywhere}.keyboard{margin-top:7px;display:grid;gap:5px}
.row{display:flex;gap:5px}button{flex:1;min-width:0;border:0;border-radius:8px;background:#f8fbf8e8;
padding:12px 4px;color:#254735;font:600 12px system-ui;cursor:pointer}button:hover{background:white}
#hint{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:#243c30;color:white;
padding:12px 20px;border-radius:12px;display:none;max-width:90vw;text-align:center}
@media(max-width:900px){main{grid-template-columns:1fr;max-width:410px}.phone{min-height:0}body{padding:22px 16px}}
</style><header><h1>Кабинет и экономика Норы</h1><p>Предпросмотр на вымышленных данных.
Тексты и кнопки взяты из подготовленного кода; окончательный вид зависит от Telegram.
Нажатия здесь не отправляют запросов и не меняют баланс.</p></header><main>"""
    page += "".join(panels) + """</main><div id="hint">Это макет. Списаний и отправки сообщений нет.</div>
<script>let timer;document.querySelectorAll('button').forEach(b=>b.onclick=()=>{
const hint=document.getElementById('hint');hint.style.display='block';clearTimeout(timer);
timer=setTimeout(()=>hint.style.display='none',2500)});</script></html>"""
    await asyncio.to_thread(output.write_text, page, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/workspace/nora-cabinet-preview.html"))
    args = parser.parse_args()
    asyncio.run(preview(args.output))
    print(args.output)


if __name__ == "__main__":
    main()
