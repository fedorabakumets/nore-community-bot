"""Daily allowance readout for Telegram profile cards.

Read the same counters as the AI, video, music and reputation handlers.
The remaining values are display-only; only an actual shop purchase resets
the counters, and never the per-song 60-second cooldown.
"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from community_bot.domain import reputation_tier
from community_bot.pet_progress import VIDEO_DAILY_LIMIT, moscow_now
from community_bot.routers.song_requests import DAILY_LIMIT as SONG_DAILY_LIMIT


async def profile_limits(db, settings, user: dict) -> list[tuple[str, str]]:
    user_id = int(user["user_id"])
    tier = reputation_tier(int(user["reputation"]), settings.restricted_reputation_threshold)
    local_date = datetime.now(ZoneInfo(getattr(settings, "timezone", "Europe/Moscow"))).date()
    day = moscow_now().date().isoformat()

    ai_record = await db.get_bot_state(f"nora_ai_daily:{user_id}")
    try:
        ai_data = json.loads(ai_record) if ai_record else {}
        ai_used = int(ai_data.get("used", 0)) if ai_data.get("day") == local_date.isoformat() else 0
    except (ValueError, TypeError, AttributeError):
        ai_used = 0

    row = await db.fetchone(
        "SELECT COUNT(*) AS total FROM pet_video_deliveries WHERE user_id=? AND day=?",
        (user_id, day),
    )
    video_used = int(row["total"]) if row else 0
    music_used = int(await db.get_bot_state(f"song:daily:{user_id}:{day}") or 0)
    reputation_used = await db.reputation_actions_today(user_id, local_date)

    def remainder(used: int, limit: int) -> str:
        return f"{max(0, limit - max(0, used))}/{limit}"

    return [
        ("🐩", remainder(ai_used, tier.ai_daily_requests)),
        ("📹", remainder(video_used, VIDEO_DAILY_LIMIT)),
        ("🎧", remainder(music_used, SONG_DAILY_LIMIT)),
        ("⚖️", remainder(reputation_used, tier.daily_actions)),
    ]
