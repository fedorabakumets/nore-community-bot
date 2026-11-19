"""Publish the requested December meetup once in NORA's production service."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import FSInputFile

from community_bot import events_api
from community_bot.access import private_allowed
from community_bot.ephemeral import keep_in_chat
from community_bot.posting import compose_post_markup
from community_bot.release_backup import verify_requested_release_backup
from community_bot.rsvp import event_lock

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


async def upgrade_meetup(db, settings, bot):
    async with event_lock(db, EVENT_ID):
        event = await db.get_studio_event(EVENT_ID)
        cfg = await events_api.config(db, EVENT_ID)
        if not event or event["status"] != "active" or event["chat_id"] != settings.community_chat_id:
            return
        key = events_api.config_key(EVENT_ID)
        organizer_id = cfg.get("organizer_id")
        if not organizer_id or not cfg.get("registration_only") or not cfg.get("post_buttons"):
            raise RuntimeError("December meetup registration configuration is incomplete")
        grant = events_api.editor_grant_key(organizer_id)
        if not cfg.get("editor_granted"):
            if await db.get_bot_state(grant) != "1":
                await verify_requested_release_backup(db, request=EVENT_ID + "-rich")
                await db.set_bot_state(grant, "1")
            cfg["editor_granted"] = True
            await db.set_bot_state(key, json.dumps(cfg, ensure_ascii=False))
            logger.info("December meetup organizer event editor access granted; mini app access=%s",
                        await private_allowed(db, settings, organizer_id))

        if cfg.get("rich_post") and not cfg.get("previous_message_id"):
            return
        if not cfg.get("rich_post"):
            payload = await events_api.rich_registration_payload(db, event, cfg)
            with keep_in_chat():
                await apply_rich_post(db, bot, event, cfg, payload)

        previous_id = cfg.get("previous_message_id")
        if previous_id:
            await bot.pin_chat_message(event["chat_id"], event["message_id"], disable_notification=True)
            try:
                await bot.edit_message_reply_markup(
                    chat_id=event["chat_id"], message_id=previous_id,
                    reply_markup=compose_post_markup(cfg["post_buttons"]),
                )
            except TelegramBadRequest as error:
                if not any(reason in error.message.casefold() for reason in ("not modified", "not found")):
                    raise
            try:
                await bot.unpin_chat_message(event["chat_id"], previous_id)
            except TelegramBadRequest as error:
                if not any(reason in error.message.casefold() for reason in ("not found", "not pinned")):
                    raise
            cfg.pop("previous_message_id")
            await db.set_bot_state(key, json.dumps(cfg, ensure_ascii=False))
        logger.info("December meetup Rich Message pinned: chat=%s message=%s", event["chat_id"], event["message_id"])


async def apply_rich_post(db, bot, event, cfg, payload):
    key = events_api.config_key(EVENT_ID)
    chat_id, old_id = event["chat_id"], event["message_id"]
    if cfg.get("rich_replacement_sending"):
        raise RuntimeError("December meetup Rich Message delivery is unconfirmed")
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=old_id, parse_mode=None, **payload)
    except TelegramBadRequest as error:
        message = error.message.casefold()
        if not any(reason in message for reason in (
            "no text", "not a text message", "can't be edited", "message type", "message content type",
            "message_id_invalid", "not modified",
        )):
            raise
        if "not modified" not in message:
            cfg["rich_replacement_sending"] = True
            await db.set_bot_state(key, json.dumps(cfg, ensure_ascii=False))
            try:
                sent = await bot.send_rich_message(chat_id, **payload)
            except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter):
                cfg.pop("rich_replacement_sending")
                await db.set_bot_state(key, json.dumps(cfg, ensure_ascii=False))
                raise
            cfg.pop("rich_replacement_sending")
            cfg["previous_message_id"] = old_id
            event["message_id"] = sent.message_id
    cfg["rich_post"] = True
    async with db.connect() as conn:
        await conn.execute(
            "UPDATE studio_events SET message_id=?,content_dirty=0,markup_dirty=0 WHERE event_id=?",
            (event["message_id"], EVENT_ID),
        )
        await conn.execute("UPDATE bot_state SET value=? WHERE key=?", (json.dumps(cfg, ensure_ascii=False), key))
        await conn.commit()


async def run(db, settings, bot):
    if (
        os.getenv("RAILWAY_SERVICE_ID") != PRODUCTION_SERVICE
        or os.getenv("RAILWAY_ENVIRONMENT_ID") != PRODUCTION_ENVIRONMENT
        or datetime.now(UTC) >= datetime(2026, 12, 3, 9, tzinfo=UTC)
    ):
        return
    try:
        await publish_meetup(db, settings, bot)
        await upgrade_meetup(db, settings, bot)
    except (ValueError, RuntimeError) as error:
        logger.error("December meetup publication stopped: %s", error)
    except TelegramBadRequest as error:
        logger.error("December meetup Telegram update rejected: %s", error.message)
    except Exception as error:
        logger.error("December meetup publication interrupted (%s)", type(error).__name__)
