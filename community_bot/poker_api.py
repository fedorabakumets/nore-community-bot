"""Telegram-authenticated access to the Hold'em engine over a private subprocess pipe."""

import asyncio
import json
import logging
from pathlib import Path

from aiohttp import web

DIST = Path(__file__).resolve().parents[1] / "poker" / "dist"
ENGINE = DIST / "engine.mjs"
log = logging.getLogger(__name__)


class PokerEngine:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._process = None

    async def _stop(self):
        process, self._process = self._process, None
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.communicate()

    async def _start(self):
        self._process = await asyncio.create_subprocess_exec(
            "deno", "run", "--no-prompt", str(ENGINE),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={},
            limit=256 * 1024,
        )

    async def request(self, payload):
        async with self._lock:
            try:
                if self._process is None or self._process.returncode is not None:
                    await self._start()
                process = self._process
                process.stdin.write(json.dumps(payload).encode("utf-8") + b"\n")
                async with asyncio.timeout(3):
                    await process.stdin.drain()
                    line = await process.stdout.readline()
                return json.loads(line)
            except asyncio.CancelledError:
                await self._stop()
                raise
            except (OSError, ValueError, TimeoutError):
                await self._stop()
                log.warning("Poker engine unavailable")
                return {"status": 503, "error": "Покер пока недоступен. Попробуй чуть позже"}

    async def close(self):
        async with self._lock:
            await self._stop()


async def action(request):
    actor = request["actor"]
    name = ""
    kind = request.match_info.get("kind", "create" if request.method == "POST" else "state")
    code = request.match_info.get("code")
    body = None
    if kind == "command":
        try:
            await request.content.readexactly(4097)
        except asyncio.IncompleteReadError as error:
            body = json.loads(error.partial)
            if not isinstance(body, dict):
                raise ValueError("Проверь действие") from None
        else:
            raise web.HTTPRequestEntityTooLarge(max_size=4096, actual_size=4097)
    if kind in {"create", "join"}:
        user = await request.app["db"].get_user(actor["id"]) or {}
        name = user.get("profile_name") or actor.get("first_name") or "Участник"
    payload = {
        "action": "state" if kind == "link" else kind,
        "uid": str(actor["id"]),
        "name": name,
        "code": code,
        "body": body,
    }
    result = await request.app[ENGINE_KEY].request(payload)
    status = result.pop("status", 200)
    if kind == "link" and status == 200:
        if not result.get("snapshot"):
            return web.json_response({"error": "Сначала займи место за столом"}, status=403)
        bot = request.app["bot"]
        if not bot or not (name := (await bot.me()).username):
            return web.json_response({"error": f"Приглашение недоступно. Код стола {code}"}, status=503)
        result = {"url": f"https://t.me/{name}?startapp=nora_poker_{code}"}
    return web.json_response(result, status=status)


ENGINE_KEY = web.AppKey("poker_engine", PokerEngine)


def register(app):
    engine = PokerEngine()
    app[ENGINE_KEY] = engine

    async def cleanup(_):
        await engine.close()

    app.on_cleanup.append(cleanup)
    if (DIST / "public").is_dir():
        app.router.add_static("/poker-assets/", DIST / "public", show_index=False)

    room = r"/api/poker/rooms/{code:[A-HJ-NP-Z2-9]{8}}"
    app.router.add_post("/api/poker/rooms", action)
    app.router.add_get(room, action)
    app.router.add_get(room + "/{kind:link}", action)
    app.router.add_post(room + "/{kind:join|command}", action)
