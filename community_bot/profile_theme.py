"""Account-wide Mini App appearance unlocked by received profile likes."""

from community_bot.social_likes import COUNT_PREFIX, count

MIN_LIKES = 50
THEME_PREFIX = "profile_theme:"
THEMES = frozenset({"black", "red", "white", "purple", "pink"})


async def appearance(db, user_id: int) -> tuple[int, str | None]:
    likes = await count(db, user_id)
    theme = await db.get_bot_state(f"{THEME_PREFIX}{user_id}") if likes >= MIN_LIKES else None
    return likes, theme if theme in THEMES else None


async def set_theme(db, user_id: int, theme: str) -> bool:
    # A moderator may adjust likes concurrently. Check the threshold in the same write.
    async with db.connect() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO bot_state(key, value)
            SELECT ?, ? FROM bot_state WHERE key=? AND CAST(value AS INTEGER)>=?
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (f"{THEME_PREFIX}{user_id}", theme, f"{COUNT_PREFIX}{user_id}", MIN_LIKES),
        )
        await conn.commit()
        return cursor.rowcount == 1
