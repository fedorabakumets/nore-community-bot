"""Native event editor backed by the existing studio registry and RSVP ledger."""

from __future__ import annotations

import asyncio
import html
import json
import re
import secrets
from datetime import UTC, datetime
from io import BytesIO
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import BufferedInputFile
from aiohttp import web

from community_bot.ephemeral import keep_in_chat
from community_bot.helpers import has_permission, rank_of_user
from community_bot.permissions import PERM_ADMIN_PANEL, PERM_MENTION, PERM_POST
from community_bot.rsvp import event_lock, refresh_event_markup


def config_key(eid):
    return "event_config:" + eid


async def config(db, eid):
    raw = await db.get_bot_state(config_key(eid))
    return json.loads(raw) if raw else {}


async def has_room(connection, eid):
    row = await (await connection.execute("SELECT value FROM bot_state WHERE key=?", (config_key(eid),))).fetchone()
    cap = int(json.loads(row["value"]).get("capacity", 0)) if row else 0
    count = await (await connection.execute("SELECT COUNT(*) n FROM event_rsvps WHERE event_id=?", (eid,))).fetchone()
    return not cap or count["n"] < cap


async def allowed(db, settings, uid):
    return await rank_of_user(db, settings, uid) >= 70 and all(
        [
            await has_permission(db, settings, uid, PERM_ADMIN_PANEL),
            await has_permission(db, settings, uid, PERM_POST),
        ]
    )


async def authorize(request):
    if not await allowed(request.app["db"], request.app["settings"], request["actor"]["id"]):
        raise web.HTTPForbidden(reason="Конструктор доступен администраторам с правом публикации")


def render_post(event, cfg, price):
    text = f"🎟 <b>{html.escape(event['title'])}</b>"
    if event.get("starts_at"):
        label = (
            datetime.fromisoformat(event["starts_at"])
            .astimezone(ZoneInfo("Europe/Moscow"))
            .strftime("%d.%m.%Y · %H:%M")
        )
        text += f"\n📅 {label} МСК"
    if cfg.get("location"):
        text += "\n📍 " + html.escape(cfg["location"])
    text += "\n" + (f"🍪 Участие: {price} печенек" if price else "🎫 Бесплатное участие")
    if cfg.get("capacity"):
        text += f" · Мест: {cfg['capacity']}"
    if event.get("description"):
        text += "\n\n<blockquote expandable>" + html.escape(event["description"]) + "</blockquote>"
    if cfg.get("links"):
        text += "\n\n<b>Доп. информация</b>\n" + "\n".join(
            f'↗ <a href="{html.escape(link["url"], quote=True)}">{html.escape(link["label"])}</a>'
            for link in cfg["links"]
        )
    return text


def validate(body):
    if not isinstance(body, dict):
        raise ValueError("Ожидаются настройки мероприятия")
    title, description = body.get("title", ""), body.get("description", "")
    location, links, poll = body.get("location", ""), body.get("links", []), body.get("poll")
    if not isinstance(title, str) or not 2 <= len(title.strip()) <= 80:
        raise ValueError("Название: от 2 до 80 символов")
    if not isinstance(description, str) or len(description) > 2500:
        raise ValueError("Описание: до 2500 символов")
    if not isinstance(location, str) or len(location) > 200:
        raise ValueError("Локация: до 200 символов")
    price, capacity = body.get("price", 0), body.get("capacity", 0)
    if type(price) is not int or not 0 <= price <= 1_000_000:
        raise ValueError("Цена: целое число от 0 до 1 000 000. Ноль — бесплатно")
    if type(capacity) is not int or not 0 <= capacity <= 100000:
        raise ValueError("Лимит участников: от 0 до 100 000. Ноль — без ограничения")
    if not isinstance(links, list) or len(links) > 8:
        raise ValueError("Можно добавить до 8 ссылок")
    for link in links:
        if not isinstance(link, dict) or not isinstance(link.get("label"), str) or not isinstance(link.get("url"), str):
            raise ValueError("Каждой ссылке нужны название и адрес")
        u = urlparse(link["url"])
        if (
            not 1 <= len(link["label"].strip()) <= 60
            or len(link["url"]) > 2000
            or (u.scheme not in {"https", "http"} or not u.hostname or u.username or u.password)
        ):
            raise ValueError("Укажи название ссылки и корректный адрес http(s)")
    starts = body.get("starts_at") or None
    if starts:
        try:
            dt = datetime.fromisoformat(starts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("Europe/Moscow"))
            starts = dt.astimezone(UTC).isoformat()
        except (ValueError, TypeError):
            raise ValueError("Проверь дату и время начала") from None
    if poll:
        if (
            not isinstance(poll, dict)
            or not isinstance(poll.get("question"), str)
            or not (1 <= len(poll["question"].strip()) <= 300)
            or not isinstance(poll.get("options"), list)
            or not 2 <= len(poll["options"]) <= 10
            or any(not isinstance(o, str) or not 1 <= len(o.strip()) <= 100 for o in poll["options"])
        ):
            raise ValueError("Опрос: вопрос до 300 символов и 2–10 вариантов до 100 символов")
        if len({o.strip().casefold() for o in poll["options"]}) != len(poll["options"]):
            raise ValueError("Варианты опроса не должны повторяться")
        poll = {
            "question": poll["question"].strip(),
            "options": [o.strip() for o in poll["options"]],
            "anonymous": bool(poll.get("anonymous", True)),
        }
    return {
        "title": title.strip(),
        "description": description.strip(),
        "starts_at": starts,
        "price": price,
        "location": location.strip(),
        "capacity": capacity,
        "links": links,
        "poll": poll,
    }


async def public_events(db, uid):
    rows = await db.fetchall(
        "SELECT * FROM studio_events WHERE status='active' ORDER BY starts_at IS NULL,starts_at,created_at"
    )
    result = []
    for e in rows:
        cfg, offer = await config(db, e["event_id"]), await db.get_event_offer(e["event_id"])
        result.append(
            {
                "id": e["event_id"],
                "title": e["title"],
                "description": e["description"],
                "starts_at": e["starts_at"],
                "price": int(offer["price"]) if offer else 0,
                "location": cfg.get("location", ""),
                "capacity": cfg.get("capacity", 0),
                "links": cfg.get(
                    "links",
                    [{"label": b["text"], "url": b["url"]} for b in json.loads(e["buttons_json"]) if b.get("url")],
                ),
                "has_media": bool(cfg.get("cover_id")),
                "count": await db.event_participant_count(e["event_id"]),
                "joined": await db.has_event_rsvp(e["event_id"], uid),
                "paid": await db.has_event_payment(e["event_id"], uid),
            }
        )
    return result


async def editor(request):
    await authorize(request)
    db = request.app["db"]
    rows = await db.fetchall(
        "SELECT * FROM studio_events WHERE status IN ('active','disabled') ORDER BY created_at DESC"
    )
    items = []
    for e in rows:
        c, offer = await config(db, e["event_id"]), await db.get_event_offer(e["event_id"])
        items.append(
            {
                **{k: e[k] for k in ("title", "description", "starts_at", "status", "revision")},
                "id": e["event_id"],
                "price": int(offer["price"]) if offer else 0,
                **{
                    k: c.get(k, default)
                    for k, default in [
                        ("location", ""),
                        ("capacity", 0),
                        (
                            "links",
                            [
                                {"label": b["text"], "url": b["url"]}
                                for b in json.loads(e["buttons_json"])
                                if b.get("url")
                            ],
                        ),
                        ("poll", None),
                    ]
                },
                "has_media": bool(c.get("media_id") or e["media_type"]),
                "published": e["message_id"] > 0,
                "count": await db.event_participant_count(e["event_id"]),
            }
        )
    return web.json_response(
        {
            "items": items,
            "can_mention": await has_permission(db, request.app["settings"], request["actor"]["id"], PERM_MENTION),
        }
    )


async def save(request):
    await authorize(request)
    body = await request.json()
    values = validate(body)
    eid = body.get("id")
    if not isinstance(eid, str) or not re.fullmatch(r"e[a-f0-9]{20}", eid):
        # Existing studio IDs can also be UUID strings; never interpolate them into SQL.
        if not isinstance(eid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", eid):
            raise ValueError("Некорректный ID мероприятия")
    db, settings, uid = request.app["db"], request.app["settings"], request["actor"]["id"]
    async with event_lock(db, eid):
        old, cfg = await db.get_studio_event(eid), await config(db, eid)
        if old and (old["revision"] != body.get("revision") or old["status"] not in {"active", "disabled"}):
            return web.json_response({"error": "Мероприятие изменилось. Открой редактор заново"}, status=409)
        count = await db.event_participant_count(eid) if old else 0
        offer = await db.get_event_offer(eid)
        if count and values["price"] != (int(offer["price"]) if offer else 0):
            raise ValueError("Цена уже зафиксирована для участников. Для другой цены создай новое мероприятие")
        if values["capacity"] and values["capacity"] < count:
            raise ValueError("Лимит не может быть меньше числа уже записавшихся участников")
        if cfg.get("poll_sent") and values["poll"] != cfg.get("poll"):
            raise ValueError("Отправленный опрос нельзя изменить. Остальные поля можно редактировать")
        if old:
            cfg.setdefault("media_type", old["media_type"])
        token = body.get("media_token")
        if token:
            raw = await db.get_bot_state("event_upload:" + str(token))
            upload = json.loads(raw) if raw else {}
            if upload.get("owner") != uid:
                raise ValueError("Загрузи медиа заново")
            cfg.update({k: upload[k] for k in ("media_id", "media_type", "cover_id")})
        if body.get("remove_media"):
            if old and old["message_id"] > 0:
                raise ValueError("У опубликованного поста можно заменить медиа, но нельзя убрать его тип")
            cfg.update(media_id="", media_type="", cover_id="")
        if old and old["message_id"] > 0 and cfg.get("media_type", "") != old["media_type"]:
            raise ValueError("Для опубликованного поста сохраняется тип медиа. Создай новый пост для другого типа")
        cfg.update({k: values[k] for k in ("location", "capacity", "links", "poll")})
        text = render_post(values, cfg, values["price"])
        plain = html.unescape(re.sub("<[^>]+>", "", text))
        if len(plain.encode("utf-16-le")) // 2 > (1024 if cfg.get("media_type") else 4096):
            raise ValueError("Пост слишком длинный: с медиа доступно 1024 символа, без медиа — 4096")
        async with db.connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            # Capacity/price rechecked under SQLite lock against native bot registrations too.
            n = await (await conn.execute("SELECT COUNT(*) n FROM event_rsvps WHERE event_id=?", (eid,))).fetchone()
            if n["n"] != count:
                raise ValueError("Список участников изменился. Сохрани настройки ещё раз")
            if not old:
                await conn.execute(
                    "INSERT INTO studio_events(event_id,chat_id,message_id,title,created_by,created_at,status) "
                    "VALUES(?,?,?,?,?,?,'disabled')",
                    (
                        eid,
                        settings.community_chat_id,
                        -int(secrets.token_hex(7), 16),
                        values["title"],
                        uid,
                        datetime.now(UTC).isoformat(),
                    ),
                )
            await conn.execute(
                "UPDATE studio_events SET title=?,description=?,starts_at=?,"
                "rsvp_enabled=?,media_type=?,revision=revision+1,"
                "content_dirty=1,markup_dirty=1,buttons_json='[]' WHERE event_id=?",
                (
                    values["title"],
                    values["description"],
                    values["starts_at"],
                    int(values["price"] == 0),
                    cfg.get("media_type", ""),
                    eid,
                ),
            )
            await conn.execute(
                "INSERT INTO bot_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (config_key(eid), json.dumps(cfg, ensure_ascii=False)),
            )
            if values["price"]:
                await conn.execute(
                    "INSERT INTO event_offers(event_id,chat_id,message_id,title,body,price,"
                    "button_text,created_by,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET "
                    "title=excluded.title,body=excluded.body,"
                    "price=excluded.price,button_text=excluded.button_text",
                    (
                        eid,
                        settings.community_chat_id,
                        old["message_id"] if old else 0,
                        values["title"],
                        values["description"],
                        values["price"],
                        f"Билет · {values['price']} 🍪",
                        uid,
                        datetime.now(UTC).isoformat(),
                    ),
                )
            else:
                await conn.execute("DELETE FROM event_offers WHERE event_id=?", (eid,))
            await conn.commit()
        if old and old["message_id"] > 0:
            await refresh_event_markup(request.app["bot"], db, eid)
    await db.log_admin_action(uid, "event_edit" if old else "event_create", eid,
                              f"price={values['price']}; capacity={values['capacity']}")
    return web.json_response({"ok": True, "id": eid, "message": "Настройки сохранены"})


async def cover(request):
    db, eid = request.app["db"], request.match_info["event_id"]
    event = await db.get_studio_event(eid)
    if not event or (
        event["status"] != "active" and not await allowed(db, request.app["settings"], request["actor"]["id"])
    ):
        raise web.HTTPNotFound()
    cfg = await config(db, eid)
    if not cfg.get("cover_id"):
        raise web.HTTPNotFound()
    output = BytesIO()
    await request.app["bot"].download(cfg["cover_id"], destination=output)
    from community_bot.miniapp import normalized_photo

    photo = await asyncio.to_thread(normalized_photo, output.getvalue())
    return web.Response(body=photo, content_type="image/jpeg")


async def upload(request):
    await authorize(request)
    bot, uid = request.app["bot"], request["actor"]["id"]
    raw = await request.read()
    if request.content_type in {"image/jpeg", "image/png", "image/webp"}:
        if len(raw) > 5 * 1024 * 1024:
            raise ValueError("Фото должно быть не больше 5 МБ")
        from community_bot.miniapp import normalized_photo

        photo = await asyncio.to_thread(normalized_photo, raw)
        sent = await bot.send_photo(
            uid,
            BufferedInputFile(photo, filename="event.jpg"),
            caption="Медиа для мероприятия · ещё не опубликовано",
            disable_notification=True,
        )
        media = {"media_type": "photo", "media_id": sent.photo[-1].file_id, "cover_id": sent.photo[-1].file_id}
    elif request.content_type == "video/mp4" and len(raw) <= 20 * 1024 * 1024 and raw[4:8] == b"ftyp":
        sent = await bot.send_video(
            uid,
            BufferedInputFile(raw, filename="event.mp4"),
            caption="Медиа для мероприятия · ещё не опубликовано",
            disable_notification=True,
        )
        media = {
            "media_type": "video",
            "media_id": sent.video.file_id,
            "cover_id": sent.video.thumbnail.file_id if sent.video.thumbnail else "",
        }
    else:
        raise ValueError("Загрузи фото JPG/PNG/WebP до 5 МБ или видео MP4 до 20 МБ")
    token = secrets.token_urlsafe(24)
    await request.app["db"].set_bot_state("event_upload:" + token, json.dumps({"owner": uid, **media}))
    return web.json_response({"token": token, "type": media["media_type"]})


async def publish(request):
    await authorize(request)
    body = await request.json()
    db, bot, settings, uid = request.app["db"], request.app["bot"], request.app["settings"], request["actor"]["id"]
    eid = str(body.get("id", ""))
    async with event_lock(db, eid):
        event, cfg = await db.get_studio_event(eid), await config(db, eid)
        if not event or event["status"] == "cancelled" or event["revision"] != body.get("revision"):
            raise ValueError("Открой актуальные настройки мероприятия")
        if not settings.community_chat_id:
            raise ValueError("Чат сообщества не настроен")
        if body.get("notify") and not await has_permission(db, settings, uid, PERM_MENTION):
            raise web.HTTPForbidden(reason="Для уведомлений нужно право упоминать участников")
        offer = await db.get_event_offer(eid)
        price = int(offer["price"]) if offer else 0
        from community_bot.posting import compose_post_markup, send_studio_poll, send_studio_post

        async def persist():
            await db.set_bot_state(config_key(eid), json.dumps(cfg, ensure_ascii=False))

        async def once(key, action):
            if cfg.get(key) == "sending":
                raise ValueError("Доставка прошлого запроса не подтверждена. Проверь чат перед повторной публикацией")
            if cfg.get(key):
                return None
            cfg[key] = "sending"
            await persist()
            try:
                result = await action()
            except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter):
                cfg[key] = False
                await persist()
                raise ValueError("Telegram отклонил действие. Проверь права бота и настройки поста") from None
            cfg[key] = True
            if key == "post_sent":
                cfg["applied_media_id"] = cfg.get("media_id", "")
            await persist()
            return result

        if event["message_id"] < 0:
            markup = compose_post_markup(
                [], None if price else eid, pay=(f"Билет · {price} 🍪", eid) if price else None
            )
            with keep_in_chat():
                # Persist Telegram's message ID before marking the send complete.
                async def send():
                    sent = await send_studio_post(
                        bot,
                        settings.community_chat_id,
                        render_post(event, cfg, price),
                        cfg.get("media_type"),
                        cfg.get("media_id"),
                        markup,
                    )
                    await db.execute(
                        "UPDATE studio_events SET message_id=?,status='active',content_dirty=0 WHERE event_id=?",
                        (sent.message_id, eid),
                    )
                    await db.execute("UPDATE event_offers SET message_id=? WHERE event_id=?", (sent.message_id, eid))
                    event.update(message_id=sent.message_id, status="active")

                await once("post_sent", send)
        elif event["status"] != "active":
            await db.execute(
                "UPDATE studio_events SET status='active',content_dirty=1,markup_dirty=1 WHERE event_id=?", (eid,)
            )
        await db.set_bot_state("current_studio_event", eid)
        await refresh_event_markup(bot, db, eid)
        await once(
            "pinned",
            lambda: bot.pin_chat_message(settings.community_chat_id, event["message_id"], disable_notification=False),
        )
        if cfg.get("poll"):
            with keep_in_chat():
                await once("poll_sent", lambda: send_studio_poll(bot, settings.community_chat_id, cfg["poll"]))
        if body.get("notify"):
            if "notify_ids" not in cfg:
                from community_bot.community_api import people

                cfg["notify_ids"] = [p["user_id"] for p in await people(db, settings, uid)]
                await persist()
            ids = cfg["notify_ids"]
            for offset in range(0, len(ids), 25):
                text = "🎉 <b>Встречаемся в Норе!</b>\n" + " ".join(
                    f'<a href="tg://user?id={i}">🎟</a>' for i in ids[offset : offset + 25]
                )
                with keep_in_chat():
                    await once(
                        f"notify_{offset}",
                        lambda t=text: bot.send_message(
                            settings.community_chat_id, t, parse_mode="HTML", disable_notification=False
                        ),
                    )
                await asyncio.sleep(0.05)
        from community_bot.stickers import send_context_sticker

        await send_context_sticker(bot, db, settings.community_chat_id, "event", event["message_id"])
    await db.log_admin_action(uid, "event_publish", eid, f"post={event['message_id']}")
    return web.json_response({"ok": True, "message": "Пост опубликован и закреплён"})


async def delete(request):
    await authorize(request)
    body = await request.json()
    db, eid = request.app["db"], str(body.get("id", ""))
    from community_bot.event_manager import cancel_event

    async with event_lock(db, eid):
        ok, refund = await cancel_event(db, eid, body.get("revision"))
        if not ok:
            raise ValueError("Мероприятие уже изменилось. Обнови список")
        event = await db.get_studio_event(eid)
        if event["message_id"] > 0:
            await refresh_event_markup(request.app["bot"], db, eid)
            try:
                await request.app["bot"].unpin_chat_message(event["chat_id"], event["message_id"])
            except TelegramAPIError:
                pass
    await db.log_admin_action(request["actor"]["id"], "event_cancel", eid, f"Возвращено {refund} 🍪")
    return web.json_response({"ok": True, "message": f"Мероприятие удалено из актуальных. Возвращено {refund} 🍪"})
