"""Publish the requested December meetup once in NORA's production service."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile

from community_bot import events_api
from community_bot.release_backup import verify_requested_release_backup

logger = logging.getLogger(__name__)
EVENT_ID = "december-cabin-2026"
ORGANIZER_USERNAME = "alice230305"
PRODUCTION_SERVICE = "dae67cd6-25ee-4710-b11a-7c8f6801e35b"
PRODUCTION_ENVIRONMENT = "136c278e-4a0f-4b54-986c-8b64f9d69ad6"
COVER = Path(__file__).resolve().parent.parent / "assets" / "events" / "december-cabin.png"
DESCRIPTION = """Дорогие друзья!!!!!!!!!!!!
Хватит спасаться от городской суеты в душных квартирах!
Зову вас на настоящую перезагрузку
📆 02.12.26 — заезд с 14:00, можно подъехать позже.
03.12.26 — выезд до 12:00.

Я хочу предложить вам, снять вместе чудесный домик 🥺

**Что Нас там ждёт?**
> • Треск поленьев в камине и огромная гостиная для наших вечерних разговоров.
> • Баня на дровах и купель под открытым небом.
> • Мангальная зона, где мы наконец-то приготовим шашлыки.
Поиграем в бильярд, в настольные игры, пообщаемся и выпьем 🤭"""


class EventRequest(dict):
    def __init__(self, db, settings, bot, body):
        super().__init__(actor={"id": settings.owner_id})
        self.app = {"db": db, "settings": settings, "bot": bot}
        self.body = body

    async def json(self):
        return self.body


def is_organizer(user) -> bool:
    return not user.is_bot and (user.username or "").casefold() == ORGANIZER_USERNAME


async def organizer_profile(db, settings, bot):
    rows = await db.fetchall(
        "SELECT user_id FROM users WHERE user_id>0 AND "
        "(role!='member' OR LOWER(username) LIKE '%alice%' OR profile_name LIKE '%лиса%' "
        "OR telegram_name LIKE '%лиса%' OR LOWER(profile_name) LIKE '%alice%' "
        "OR LOWER(telegram_name) LIKE '%alice%') ORDER BY updated_at DESC"
    )
    for member in await bot.get_chat_administrators(settings.community_chat_id):
        if is_organizer(member.user) and await db.get_user(member.user.id):
            return member.user.id
    for row in rows:
        try:
            member = await bot.get_chat_member(settings.community_chat_id, row["user_id"])
        except TelegramBadRequest:
            continue
        if is_organizer(member.user):
            return member.user.id
    raise RuntimeError("December meetup organizer username could not be verified against a NORA profile")


async def publish_meetup(db, settings, bot):
    event = await db.get_studio_event(EVENT_ID)
    cfg = await events_api.config(db, EVENT_ID)
    if event and (event["status"] == "cancelled" or cfg.get("pinned") is True):
        return
    if not settings.community_chat_id or not settings.owner_id:
        raise RuntimeError("December meetup requires a configured community chat and owner")
    actor = await bot.me()
    member = await bot.get_chat_member(settings.community_chat_id, actor.id)
    if member.status != "creator" and not getattr(member, "can_pin_messages", False):
        raise RuntimeError("December meetup requires permission to pin messages in the community chat")
    if not event:
        organizers = await db.fetchall(
            "SELECT user_id FROM users WHERE LOWER(username)=? AND user_id>0 LIMIT 2", (ORGANIZER_USERNAME,)
        )
        organizer_id = (
            organizers[0]["user_id"] if len(organizers) == 1 else await organizer_profile(db, settings, bot)
        )
        if not COVER.is_file():
            raise RuntimeError("December meetup cover is missing")
        await verify_requested_release_backup(db, request=EVENT_ID)
        await events_api.save(
            EventRequest(db, settings, bot, {
                "id": EVENT_ID,
                "title": "Перезагрузка в домике",
                "starts_at": "2026-12-02T14:00:00+03:00",
                "description": DESCRIPTION,
            }),
            organizer_id=organizer_id,
            registration_only=True,
        )
        event = await db.get_studio_event(EVENT_ID)
    if event["message_id"] < 0 and not COVER.is_file():
        raise RuntimeError("December meetup cover is missing")
    await events_api.publish(
        EventRequest(db, settings, bot, {"id": EVENT_ID, "revision": event["revision"]}),
        photo=FSInputFile(COVER) if event["message_id"] < 0 else None,
        send_sticker=False,
    )
    event = await db.get_studio_event(EVENT_ID)
    logger.info("December meetup published and pinned: chat=%s message=%s", event["chat_id"], event["message_id"])


async def run(db, settings, bot):
    if (
        os.getenv("RAILWAY_SERVICE_ID") != PRODUCTION_SERVICE
        or os.getenv("RAILWAY_ENVIRONMENT_ID") != PRODUCTION_ENVIRONMENT
        or datetime.now(UTC) >= datetime(2026, 12, 3, 9, tzinfo=UTC)
    ):
        return
    try:
        await publish_meetup(db, settings, bot)
    except (ValueError, RuntimeError) as error:
        logger.error("December meetup publication stopped: %s", error)
    except Exception as error:
        logger.error("December meetup publication interrupted (%s)", type(error).__name__)
