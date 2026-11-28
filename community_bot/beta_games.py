"""Authorization for closed game alphas."""
from aiohttp import web

from community_bot.helpers import effective_role


async def allowed(db, settings, uid: int) -> bool:
    return await effective_role(db, settings, uid) in {"owner", "admin"}


async def dice_access(request):
    if not await allowed(request.app["db"], request.app["settings"], int(request["actor"]["id"])):
        return web.json_response({"error": "SOON"}, status=403)
    return web.json_response({"allowed": True})
