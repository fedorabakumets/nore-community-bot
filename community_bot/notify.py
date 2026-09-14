from __future__ import annotations

import asyncio
import html
import logging
from collections import defaultdict
from typing import Any

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup

from community_bot.database import Database
from community_bot.keyboards import STYLE_FUN, STYLE_GO, back_btn, close_btn, ibtn

logger = logging.getLogger(__name__)

CHANNELS: dict[str, tuple[str, str]] = {
    "pet": ("🐾 Питомец", "Голод, жажда, возврат из похода, перехват −реп."),
    "games": ("🎮 Игры", "Старт партии, ваш ход, итог. Роли мафии и бункера — всегда."),
    "events": ("🎟 События", "Анонс студии и RSVP с залогом."),
    "shop": ("🛒 Магазин", "Новая витрина и конец тиража."),
}


async def emit(bot: Any, db: Database, user_id: int, channel: str, text: str) -> bool:
    if channel not in CHANNELS:
        return False
    if not await db.notify_channel_on(user_id, channel):
        return False
    inbox_id = await db.notify_inbox_add(user_id, channel, text)
    if await db.notify_digest_on(user_id, channel):
        return True
    try:
        await bot.send_message(user_id, text, parse_mode="HTML")
        await db.notify_mark_delivered(inbox_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.info("notify dm skipped user=%s channel=%s", user_id, channel)
    except Exception:
        logger.exception("notify dm failed user=%s channel=%s", user_id, channel)
    return True


async def emit_many(bot: Any, db: Database, user_ids: list[int], channel: str, text: str) -> None:
    seen: set[int] = set()
    for user_id in user_ids:
        if user_id in seen:
            continue
        seen.add(user_id)
        await emit(bot, db, user_id, channel, text)


async def fanout(bot: Any, db: Database, channel: str, text: str) -> None:
    await emit_many(bot, db, await db.list_channel_subscribers(channel), channel, text)


async def deliver_digests(bot: Any, db: Database) -> int:
    pending = await db.notify_pending_digest()
    by_user: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in pending:
        by_user[int(row["user_id"])].append(row)
    sent = 0
    for user_id, items in by_user.items():
        lines = ["📬 <b>Дайджест за день</b>", ""]
        for item in items[:20]:
            lines.append(f"• {item['text']}")
        if len(items) > 20:
            lines.append(f"… и ещё {len(items) - 20}")
        try:
            await bot.send_message(user_id, "\n".join(lines), parse_mode="HTML")
            await db.notify_mark_delivered_ids([int(item["id"]) for item in items])
            sent += 1
        except (TelegramBadRequest, TelegramForbiddenError):
            logger.info("digest skipped user=%s", user_id)
        except Exception:
            logger.exception("digest failed user=%s", user_id)
        await asyncio.sleep(0.05)
    return sent


async def vitrine_consumed(bot: Any, db: Database, item: str) -> bool:
    closed = await db.consume_vitrine(item)
    if closed:
        from community_bot.shop_catalog import ITEM_LABELS

        label = ITEM_LABELS.get(item, item)
        await fanout(bot, db, "shop", f"🛒 Тираж «{html.escape(str(label))}» закончился.")
    return closed


def notices_text(
    prefs: dict[str, dict[str, int]],
    unread: list[dict[str, Any]],
    unread_count: int,
) -> str:
    lines = [
        "🔔 <b>Уведомления</b>",
        "",
        "Личка по подписке. По умолчанию всё выкл.",
        "Роли мафии и бункера, тикет и решение анкеты приходят всегда.",
        "Системное (био, потолок серебра) живёт в профиле и не отключается.",
        "",
    ]
    for key, (label, hint) in CHANNELS.items():
        row = prefs.get(key) or {}
        on = "вкл" if row.get("enabled") else "выкл"
        digest = "раз в день" if row.get("digest") else "сразу"
        lines.append(f"{label} — <b>{on}</b> · {digest}")
        lines.append(hint)
    lines.append("")
    if unread_count:
        lines.append(f"Лента: <b>{unread_count}</b> непрочитанных.")
        for item in unread[:6]:
            snippet = str(item["text"]).replace("\n", " ")
            if len(snippet) > 80:
                snippet = snippet[:77] + "…"
            lines.append(f"• {snippet}")
    else:
        lines.append("Лента пустая.")
    return "\n".join(lines)


def notices_keyboard(prefs: dict[str, dict[str, int]]) -> InlineKeyboardMarkup:
    rows = []
    for key, (label, _hint) in CHANNELS.items():
        row = prefs.get(key) or {}
        on = bool(row.get("enabled"))
        digest = bool(row.get("digest"))
        toggle = "выкл" if on else "вкл"
        style = STYLE_GO if on else None
        digest_label = "сразу" if digest else "раз в день"
        rows.append(
            [
                ibtn(f"{label}: {toggle}", f"n:ch:{key}", style if on else STYLE_FUN),
                ibtn(digest_label, f"n:dg:{key}"),
            ]
        )
    rows.append([ibtn("Прочитать всё", "n:read", STYLE_FUN)])
    rows.append([back_btn("menu:home"), close_btn("ui:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
