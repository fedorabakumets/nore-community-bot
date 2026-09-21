from community_bot.routers.contest import router as contest_router
from community_bot.routers.cookie_games import router as cookie_games_router
from community_bot.routers.flows import router as flows_router
from community_bot.routers.games import router as games_router
from community_bot.routers.group import router as group_router
from community_bot.routers.life import router as life_router
from community_bot.routers.notices import router as notices_router
from community_bot.routers.pets import router as pets_router
from community_bot.routers.private import router as private_router
from community_bot.routers.profile import router as profile_router
from community_bot.routers.shop_admin import router as shop_admin_router
from community_bot.routers.social_games import router as social_games_router
from community_bot.routers.wallet import router as wallet_router

__all__ = [
    "cookie_games_router",
    "contest_router",
    "flows_router",
    "games_router",
    "group_router",
    "life_router",
    "notices_router",
    "pets_router",
    "private_router",
    "profile_router",
    "shop_admin_router",
    "social_games_router",
    "wallet_router",
]
