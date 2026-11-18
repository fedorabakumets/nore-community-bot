"""Isolated localhost Mini App for Playwright. Start with python -m tests.durak_web_fixture."""
import argparse
import json
import random
import secrets
import tempfile
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp import web
from PIL import Image, ImageDraw

from community_bot import durak_rules
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.miniapp import ROOT, create_app
from tests.test_miniapp import signed

NAMES = ["Ася", "Марк", "Лера", "Лев", "Ника", "Ян", "Иван", "Мира", "Вера", "Кир", "Рита", "Лина"]


async def fixture(folder):
    db = Database(folder / "isolated.sqlite3")
    await db.initialize()
    token = secrets.token_urlsafe(32)
    settings = Settings(token, 1, frozenset({1}), frozenset(), 0, db.path, None, 0, 0, 0,
                        "Europe/Moscow", 1, 0, "", "", "", "", "")
    for uid, name in enumerate(NAMES, 1):
        await db.ensure_user(uid, telegram_name=name)
        icon = Image.new("RGB", (80, 80), ("#9c554d", "#445f54", "#534461")[uid % 3])
        draw = ImageDraw.Draw(icon)
        draw.ellipse((25, 13, 55, 43), fill="#e0bc9c")
        draw.ellipse((11, 46, 69, 108), fill="#d7b89a")
        with BytesIO() as output:
            icon.save(output, "JPEG")
            await db.execute("INSERT INTO bot_state(key,value) VALUES(?,?)", (f"nora-avatar:{uid}", output.getvalue()))
        await db.execute("UPDATE users SET profile_name=?,birth_date='1996-02-01',hobbies='Игры',"
                         "profile_bio='Играю в карты',avatar_file_id=?,role='moderator' WHERE user_id=?",
                         (name, f"nora-avatar:{uid}", uid))
        await db.add_cookies(uid, 20000, "fixture")
        await db.execute("INSERT OR REPLACE INTO notify_prefs(user_id,channel,enabled,digest) VALUES(?,'games',0,0)",
                         (uid,))
        if uid > 1:
            await db.execute("INSERT INTO mini_friendships VALUES(1,?,1,'accepted',?,'now','now',0,0)",
                             (uid, f"fixture-{uid}"))
    app = create_app(db, settings, None)

    @web.middleware
    async def local_assets(request, handler):
        if request.path == "/":
            uid = int(request.query.get("player", "1"))
            if not 1 <= uid <= len(NAMES):
                raise web.HTTPNotFound()
            html = (ROOT / "index.html").read_text(encoding="utf-8").replace(
                "https://telegram.org/js/telegram-web-app.js", f"/fixture-telegram.js?player={uid}")
            return web.Response(text=html, content_type="text/html")
        return await handler(request)

    async def telegram(request):
        uid = int(request.query["player"])
        if not 1 <= uid <= len(NAMES):
            raise web.HTTPNotFound()
        actor = {"id": uid, "first_name": NAMES[uid-1]}
        script = """
        const back = {show(){},hide(){},onClick(fn){this.click=fn},offClick(){}};
        window.Telegram={WebApp:{ready(){},expand(){},onEvent(){},offEvent(){},BackButton:back,HapticFeedback:{},
        isVersionAtLeast(){return false},openTelegramLink(url){window.fixtureShared=url},
        initData:AUTH,initDataUnsafe:{user:ACTOR,start_param:new URLSearchParams(location.search).get('startapp')}}};
        """
        script = script.replace("AUTH", json.dumps(signed(uid, int(time.time()), token)))
        script = script.replace("ACTOR", json.dumps(actor))
        return web.Response(text=script, content_type="text/javascript")

    class FixtureBot:
        async def me(self):
            return SimpleNamespace(username="nora_durak_fixture_bot")

    async def mock_links(app):
        app["bot"] = FixtureBot()

    async def repeatable_deals(_):
        deal = durak_rules.deal
        with patch.object(durak_rules, "deal", side_effect=lambda config: deal(config, rng=random.Random(0))):
            yield

    app.middlewares.insert(0, local_assets)
    app.cleanup_ctx.append(repeatable_deals)
    app.router.add_get("/fixture-telegram.js", telegram)
    app.on_startup.append(mock_links)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18761)
    with tempfile.TemporaryDirectory(prefix="nora-durak-web-") as tmp:
        web.run_app(fixture(Path(tmp)), host="127.0.0.1", port=parser.parse_args().port, access_log=None)
