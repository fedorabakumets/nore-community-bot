"""Resolve the signed-in player's current game when they confirm leaving."""
import time

from aiohttp import web

from community_bot import durak_rooms, mafia_api, rocket_api, sea_api


async def exit_game(db, uid, game, *, now=None):
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        now = time.time() if now is None else now
        room_id = None
        if game in {"durak", "barricade"}:
            room_id = await durak_rooms.leave_current(conn, uid, game, now)
        elif game == "sea":
            await sea_api.leave_current(conn, uid, now)
        elif game == "mafia":
            await mafia_api.leave_current(conn, uid, now)
        elif game == "rocket":
            await rocket_api.leave_current(conn, uid, now)
        else:
            raise ValueError("Неизвестная игра")
        await conn.commit()
    return room_id


async def leave(request):
    room_id = await exit_game(request.app["db"], request["actor"]["id"], request.match_info["game"])
    if room_id:
        request.app["durak_updates"].notify(room_id)
    return web.json_response({"ok": True})
