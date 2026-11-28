"""Account-wide Mini App appearance and public profile palette."""

from community_bot.social_likes import count

DEFAULT_THEME = "black"
THEME_PREFIX = "profile_theme:"
THEMES = frozenset({DEFAULT_THEME, "white", "blue", "yellow", "mint", "pink", "purple", "red"})


async def appearance(db, user_id: int) -> tuple[int, str]:
    likes = await count(db, user_id)
    theme = await db.get_bot_state(f"{THEME_PREFIX}{user_id}")
    return likes, theme if theme in THEMES else DEFAULT_THEME


async def set_theme(db, user_id: int, theme: str) -> None:
    await db.set_bot_state(f"{THEME_PREFIX}{user_id}", theme)
