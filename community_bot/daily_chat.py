from __future__ import annotations

import html
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from community_bot.morning import format_day

logger = logging.getLogger(__name__)


def _name(row: dict[str, object]) -> str:
    for key in ("profile_name", "telegram_name", "username"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return "участник"


def render_daily_chat(day: date, rows: list[dict[str, object]], *, awarded: bool) -> str:
    lines = [f"🌙 <b>Сутки · {html.escape(format_day(day))}</b>", ""]
    if not rows:
        lines.append("За сутки в чате было тихо.")
        return "\n".join(lines)
    for index, row in enumerate(rows[:10], start=1):
        count = int(row.get("messages") or 0)
        lines.append(f"{index}. {html.escape(_name(row))} — {count}")
    if awarded:
        lines.extend(["", f"Лидер суток — {html.escape(_name(rows[0]))}. На баланс +1 🍪."])
    return "\n".join(lines)


async def publish_daily_chat(bot: object, db: object, settings: object, day: date) -> bool:
    from community_bot.database import Database

    if not isinstance(db, Database):
        return False
    chat_id = int(getattr(settings, "community_chat_id", 0) or 0)
    if not chat_id:
        return False
    key = f"daily_chat:{day.isoformat()}"
    if await db.get_bot_state(key):
        return False
    rows = await db.daily_message_board(day.isoformat(), chat_id)
    awarded = False
    if rows:
        already = await db.fetchone(
            "SELECT 1 AS ok FROM transactions WHERE kind = 'daily_chat' AND details = ?",
            (day.isoformat(),),
        )
        if not already:
            await db.add_cookies(int(rows[0]["user_id"]), 1, "daily_chat", day.isoformat())
        awarded = True
    text = render_daily_chat(day, rows, awarded=awarded)
    try:
        await bot.send_message(  # type: ignore[attr-defined]
            chat_id,
            text,
            parse_mode="HTML",
            disable_notification=True,
        )
    except Exception:
        logger.exception("Не удалось отправить сводку суток")
        return False
    await db.set_bot_state(key, day.isoformat())
    return True


def seconds_until_midnight(now: datetime) -> float:
    tz = now.tzinfo or ZoneInfo("Europe/Moscow")
    local = now.astimezone(tz)
    nxt = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), tz)
    return max(1.0, (nxt - local).total_seconds())


def due_daily_chat(now: datetime, posted_day: str | None) -> date | None:
    """Yesterday's board is due from 00:00 until 08:00, once."""
    local = now.astimezone(ZoneInfo("Europe/Moscow"))
    if local.hour >= 8:
        return None
    day = local.date() - timedelta(days=1)
    if posted_day == day.isoformat():
        return None
    return day
