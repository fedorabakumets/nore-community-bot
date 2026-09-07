from community_bot.routers.cookie_games import router as cookie_games_router
from community_bot.routers.flows import router as flows_router
from community_bot.routers.games import router as games_router
from community_bot.routers.group import router as group_router
from community_bot.routers.pets import router as pets_router
from community_bot.routers.private import router as private_router
from community_bot.routers.profile import router as profile_router

__all__ = [
    "cookie_games_router",
    "flows_router",
    "games_router",
    "group_router",
    "pets_router",
    "private_router",
    "profile_router",
]
