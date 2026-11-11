"""One-time profile and role reset for the opening of the Mini App."""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import replace
from urllib.parse import urldefrag

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from community_bot.access import configure_private_menus
from community_bot.community_reset import RETAINED_OWNER_ID
from community_bot.database import utcnow
from community_bot.release_backup import verify_requested_release_backup

logger = logging.getLogger(__name__)
REQUEST = "profile-access-20261111"
MARKER = f"maintenance:{REQUEST}"
NOTICE = ("Вам открыт доступ к Норе! Заполните профиль и укажите дату рождения, "
          "чтобы открыть Комьюнити и другие разделы.")


async def prepare(db):
    if db.path.is_file():
        await verify_requested_release_backup(db, request=REQUEST)


async def apply(db, settings):
    if not settings.is_owner(RETAINED_OWNER_ID):
        raise RuntimeError("Profile rollout requires the confirmed community owner")
    restricted = replace(settings, owner_id=RETAINED_OWNER_ID,
                         owner_ids=frozenset({RETAINED_OWNER_ID}), moderator_ids=frozenset())
    if await db.get_bot_state(MARKER):
        return restricted

    # Also enforce the backup requirement when this operation is called directly.
    await prepare(db)
    now = utcnow()
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        done = await (await conn.execute("SELECT 1 FROM bot_state WHERE key=?", (MARKER,))).fetchone()
        if not done:
            await conn.execute(
                "UPDATE users SET age=NULL, birth_date=NULL, "
                "role=CASE WHEN user_id=? THEN 'owner' ELSE 'member' END",
                (RETAINED_OWNER_ID,),
            )
            await conn.execute(
                """INSERT INTO notify_inbox(user_id,channel,text,created_at)
                   SELECT user_id,?,?,? FROM users WHERE user_id>0
                   AND lower(COALESCE(username,'')) NOT LIKE '%bot'
                   AND NOT EXISTS (SELECT 1 FROM bot_state
                                   WHERE key='telegram_is_bot:' || users.user_id AND value='1')""",
                (REQUEST, NOTICE, now),
            )
            await conn.execute(
                "INSERT INTO admin_audit_log(actor_id,action,target,details,created_at) VALUES(?,?,?,?,?)",
                (RETAINED_OWNER_ID, "profile_access_reset", "all", REQUEST, now),
            )
            await conn.execute("INSERT INTO bot_state(key,value) VALUES(?, '1')", (MARKER,))
            await conn.commit()
            logger.info("Profile access rollout applied; participant notifications queued")
    return restricted


async def deliver_notices(bot, db):
    url = os.getenv("MINIAPP_URL", "").strip()
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть Нору", web_app=WebAppInfo(url=urldefrag(url).url + "#lk")),
    ]]) if url.startswith("https://") else None
    delivered = unavailable = pending = after = 0
    while rows := await db.fetchall(
        "SELECT id,user_id,text FROM notify_inbox WHERE channel=? AND delivered=0 AND id>? ORDER BY id LIMIT 100",
        (REQUEST, after),
    ):
        for row in rows:
            after = row["id"]
            # Send a separate message so the private Rich panel stays usable.
            method = SendMessage(chat_id=row["user_id"], text=row["text"], reply_markup=markup)
            for attempt in range(3):
                try:
                    await bot.session.make_request(bot, method, timeout=10)
                except TelegramRetryAfter as error:
                    await asyncio.sleep(error.retry_after + 0.1)
                    continue
                except (TelegramForbiddenError, TelegramBadRequest):
                    unavailable += 1
                    break  # The notice remains in the Mini App.
                except TelegramAPIError:
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                    continue
                else:
                    await db.notify_mark_delivered(row["id"])
                    delivered += 1
                    break
            else:
                pending += 1
            await asyncio.sleep(0.075)
    logger.info("Profile access notifications: sent=%d unavailable=%d pending=%d", delivered, unavailable, pending)


async def refresh_private_access(bot, db, settings):
    await deliver_notices(bot, db)
    await configure_private_menus(bot, db, settings)
