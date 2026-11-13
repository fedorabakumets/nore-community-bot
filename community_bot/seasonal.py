"""Season-one physical collectible: free entry and one irreversible, server-side draw."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from datetime import UTC, datetime
from io import BytesIO
from urllib.parse import urlsplit

from aiogram.types import BufferedInputFile
from aiohttp import web

from community_bot.helpers import has_permission
from community_bot.permissions import PERM_ADMIN_PANEL, PERM_CONTEST
from community_bot.profile_fill import profile_is_complete

# Persistent raffle identity: changing the displayed prize must never reset entries or results.
ITEM = "season1-crimson-guardian"
TITLE = "Розовый Хранитель Норы"
AUTHOR = "Пушистая Лавка"
LINKS = [
    {"label": "Заказать игрушку · @Sdt_order_bot", "url": "https://t.me/Sdt_order_bot"},
    {"label": "Склад · игрушки в наличии", "url": "https://clck.ru/3VYkJA"},
    {"label": "Отзывы покупателей", "url": "https://clck.ru/3VYkLX"},
    {"label": "TikTok · Пушистая Лавка", "url": "https://www.tiktok.com/@pushistaya_lavka?_r=1&_t=ZP-99LURFF60pa"},
    {"label": "YouTube · Sadkittytime", "url": "https://www.youtube.com/@Sadkittytime"},
    {"label": "ВКонтакте · Sadkittytime", "url": "https://vk.com/sadkittytime229508710"},
]
SCHEMA = """
CREATE TABLE IF NOT EXISTS seasonal_raffles (
 id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','drawn')),
 winner_id INTEGER REFERENCES users(user_id), drawn_at TEXT, drawn_by INTEGER REFERENCES users(user_id),
 entry_count INTEGER, entries_digest TEXT
);
INSERT OR IGNORE INTO seasonal_raffles(id) VALUES('season1-crimson-guardian');
CREATE TABLE IF NOT EXISTS seasonal_entries (
 raffle_id TEXT NOT NULL REFERENCES seasonal_raffles(id), user_id INTEGER NOT NULL REFERENCES users(user_id),
 joined_at TEXT NOT NULL, PRIMARY KEY(raffle_id,user_id)
);
CREATE TABLE IF NOT EXISTS seasonal_draw_tokens (
 token TEXT PRIMARY KEY, actor_id INTEGER NOT NULL REFERENCES users(user_id),
 entries_digest TEXT NOT NULL, expires_at REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0
);
"""


async def can_manage(db, settings, uid):
    return await has_permission(db, settings, uid, PERM_ADMIN_PANEL) and await has_permission(
        db, settings, uid, PERM_CONTEST
    )


async def one(conn, sql, args=()):
    row = await (await conn.execute(sql, args)).fetchone()
    return dict(row) if row else None


def fingerprint(ids, item_id=ITEM):
    value = ids if item_id == ITEM else [item_id, ids]
    return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


async def snapshot(db, settings, uid, item_id=ITEM):
    async with db.connect() as conn:
        await conn.execute("BEGIN")
        row = await one(conn, "SELECT * FROM seasonal_raffles WHERE id=?", (item_id,))
        joined = await one(conn, "SELECT 1 FROM seasonal_entries WHERE raffle_id=? AND user_id=?", (item_id, uid))
        count = await one(conn, "SELECT COUNT(*) n FROM seasonal_entries WHERE raffle_id=?", (item_id,))
        if not row:
            raise ValueError("Предмет не найден")
        user = await one(conn, "SELECT * FROM users WHERE user_id=?", (uid,))
        winner = await one(conn, "SELECT profile_name,telegram_name FROM users WHERE user_id=?", (row["winner_id"],))
    result = {
        "id": item_id,
        "title": TITLE,
        "season": 1,
        "status": row["status"],
        "joined": bool(joined),
        "count": count["n"],
        "image": "/seasonal/pink-guardian-season1.jpg",
        "image_alt": "Розовый плюшевый мишка с чёрным бантом и глазом-пуговицей — Пушистая Лавка",
        "description": "Мягкий снаружи, с характером внутри. Розовый мишка с глазом-пуговицей, "
                       "контрастными стежками и чёрным бантом — новый хранитель первой главы Норы. "
                       "Игрушка от «Пушистой Лавки» станет призом этого розыгрыша.",
        "author": AUTHOR,
        "author_url": "https://t.me/sadkittytime",
        "links": LINKS,
        "eligible": bool(user and profile_is_complete(user)),
        "can_manage": await can_manage(db, settings, uid),
        "winner": (winner["profile_name"] or winner["telegram_name"]) if winner else None,
        "won": row["winner_id"] == uid,
        "drawn_at": row["drawn_at"],
    }
    raw = await db.get_bot_state("seasonal_item_metadata" if item_id == ITEM else "seasonal_item:" + item_id)
    if raw:
        result.update(json.loads(raw))
    return result


def validate_metadata(body):
    if not isinstance(body, dict) or set(body) != {"title", "description", "image", "author", "author_url", "links"}:
        raise ValueError("Проверьте поля предмета")
    result = {}
    for key, limit in (("title", 100), ("description", 1500), ("author", 100)):
        value = body[key]
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
            raise ValueError("Проверьте название, описание и автора")
        result[key] = value.strip()

    def safe_url(value, *, allow_existing=False):
        if allow_existing and isinstance(value, str) and (value == "/seasonal/pink-guardian-season1.jpg"
                or re.fullmatch(r"/seasonal/media/[0-9a-f]{48}", value)):
            return value
        if not isinstance(value, str) or len(value) > 2048:
            raise ValueError("Укажите корректную HTTPS-ссылку")
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Укажите корректную HTTPS-ссылку")
        return value

    result["image"] = safe_url(body["image"], allow_existing=True)
    result["image_alt"] = result["title"]
    result["author_url"] = safe_url(body["author_url"])
    if not isinstance(body["links"], list) or len(body["links"]) > 12:
        raise ValueError("Можно указать не более 12 ссылок")
    result["links"] = []
    for link in body["links"]:
        if not isinstance(link, dict) or set(link) != {"label", "url"}:
            raise ValueError("Проверьте источники")
        label = link["label"]
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 100:
            raise ValueError("Укажите название каждой ссылки")
        result["links"].append({"label": label.strip(), "url": safe_url(link["url"])})
    return result


async def save_item(db, settings, uid, item_id, body):
    if not await can_manage(db, settings, uid):
        raise web.HTTPForbidden()
    if not isinstance(body, dict):
        raise ValueError("Проверьте поля предмета")
    mode, price = body.get("mode"), body.get("price")
    enabled = body.get("enabled", True)
    if type(enabled) is not bool:
        raise ValueError("Проверьте доступность предмета")
    if mode not in ("raffle", "paid") or type(price) is not int or not 0 <= price <= 1000000:
        raise ValueError("Проверьте способ получения и цену")
    if mode == "paid" and price < 1 or mode == "raffle" and price != 0:
        raise ValueError("Укажите цену платного предмета")
    fields = ("title", "description", "image", "author", "author_url", "links")
    metadata = validate_metadata({k: body.get(k) for k in fields})
    if metadata["image"].startswith("/seasonal/media/"):
        token = metadata["image"].rsplit("/", 1)[-1]
        if not await db.get_bot_state("seasonal_media:" + token):
            raise ValueError("Изображение не найдено. Загрузите его заново")
    metadata.update(mode=mode, price=price, enabled=enabled)
    is_new = item_id is None
    if is_new:
        item_id = "seasonal-" + secrets.token_hex(12)
    if not isinstance(item_id, str) or len(item_id) > 80:
        raise ValueError("Предмет не найден")
    key = "seasonal_item_metadata" if item_id == ITEM else "seasonal_item:" + item_id
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        row = await one(conn, "SELECT * FROM seasonal_raffles WHERE id=?", (item_id,))
        old = await one(conn, "SELECT value FROM bot_state WHERE key=?", (key,))
        if row:
            previous = json.loads(old["value"]) if old else {}
            count = await one(conn, "SELECT COUNT(*) n FROM seasonal_entries WHERE raffle_id=?", (item_id,))
            if (count["n"] or row["status"] != "open") and previous.get("mode", "raffle") != mode:
                raise ValueError("Нельзя менять способ получения после первой заявки или покупки")
        else:
            if not is_new:
                raise ValueError("Предмет не найден")
            await conn.execute("INSERT INTO seasonal_raffles(id) VALUES(?)", (item_id,))
        await conn.execute("INSERT INTO bot_state(key,value) VALUES(?,?) "
                           "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                           (key, json.dumps(metadata, ensure_ascii=False)))
        await conn.commit()
    return item_id


async def all_items(db, settings, uid):
    rows = await db.fetchall("SELECT key FROM bot_state WHERE key LIKE 'seasonal_item:%' ORDER BY key")
    items = [await snapshot(db, settings, uid, item_id) for item_id in
             [ITEM, *(row["key"].removeprefix("seasonal_item:") for row in rows)]]
    return [item for item in items if item.get("enabled", True) or item["can_manage"]]


async def buy_prepare(db, settings, uid, item_id):
    item = await snapshot(db, settings, uid, item_id)
    if item.get("mode") != "paid" or not item.get("enabled", True) or item["status"] != "open" or item["joined"]:
        raise ValueError("Предмет недоступен для покупки")
    if not item["eligible"]:
        raise ValueError("Заполни профиль на 100% в ЛК")
    key = "seasonal_item_metadata" if item_id == ITEM else "seasonal_item:" + item_id
    raw = await db.get_bot_state(key)
    if not raw:
        raise ValueError("Предмет недоступен для покупки")
    metadata = json.loads(raw)
    if metadata.get("mode") != "paid" or type(metadata.get("price")) is not int or metadata["price"] < 1:
        raise ValueError("Условия изменились. Откройте предмет заново")
    revision = hashlib.sha256(raw.encode()).hexdigest()
    token = await db.create_wallet_intent(uid, item_id, metadata["price"],
                                          payload={"seasonal": True, "revision": revision})
    return {"token": token, "price": metadata["price"], "title": metadata["title"]}


async def buy_confirm(db, uid, token):
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        intent = await one(conn, "SELECT * FROM wallet_intents WHERE token=? AND user_id=?", (token, uid))
        now = datetime.now(UTC).isoformat()
        if not intent or intent["status"] != "pending" or intent["expires_at"] <= now:
            raise ValueError("Подтверждение устарело или уже использовано")
        item_id = intent["item"]
        payload = json.loads(intent["payload_json"])
        if not payload.get("seasonal"):
            raise ValueError("Некорректное подтверждение")
        key = "seasonal_item_metadata" if item_id == ITEM else "seasonal_item:" + item_id
        raw = await one(conn, "SELECT value FROM bot_state WHERE key=?", (key,))
        item = json.loads(raw["value"]) if raw else {}
        raffle = await one(conn, "SELECT status FROM seasonal_raffles WHERE id=?", (item_id,))
        existing = await one(conn, "SELECT 1 FROM seasonal_entries WHERE raffle_id=? AND user_id=?", (item_id, uid))
        user = await one(conn, "SELECT * FROM users WHERE user_id=?", (uid,))
        if (not raw or not item.get("enabled", True)
                or hashlib.sha256(raw["value"].encode()).hexdigest() != payload.get("revision")
                or not raffle or raffle["status"] != "open" or existing or item.get("mode") != "paid"
                or item.get("price") != intent["price"] or not user or not profile_is_complete(user)):
            raise ValueError("Условия изменились. Откройте предмет заново")
        changed = await conn.execute("UPDATE users SET cookies=cookies-?,updated_at=? "
                                     "WHERE user_id=? AND cookies>=?", (intent["price"], now, uid, intent["price"]))
        if not changed.rowcount:
            raise ValueError("Недостаточно печенек")
        await conn.execute("INSERT INTO seasonal_entries VALUES(?,?,?)", (item_id, uid, now))
        await conn.execute("INSERT INTO transactions(user_id,amount,kind,details,created_at) VALUES(?,?,?,?,?)",
                           (uid, -intent["price"], "seasonal_purchase", item["title"], now))
        await conn.execute("UPDATE wallet_intents SET status='completed',completed_at=? WHERE token=?", (now, token))
        await conn.commit()
    return item_id


async def join(db, uid, item_id=ITEM):
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        row = await one(conn, "SELECT status FROM seasonal_raffles WHERE id=?", (item_id,))
        existing = await one(conn, "SELECT 1 FROM seasonal_entries WHERE raffle_id=? AND user_id=?", (item_id, uid))
        metadata = await one(conn, "SELECT value FROM bot_state WHERE key=?",
                             ("seasonal_item_metadata" if item_id == ITEM else "seasonal_item:" + item_id,))
        config = json.loads(metadata["value"]) if metadata else {}
        if not row or not config.get("enabled", True) or config.get("mode") == "paid":
            raise ValueError("Розыгрыш недоступен")
        if existing:
            return "Вы участвуете. Одна заявка — один шанс"
        if row["status"] != "open":
            raise ValueError("Розыгрыш завершён, новые заявки не принимаются")
        user = await one(conn, "SELECT * FROM users WHERE user_id=?", (uid,))
        if not user or not profile_is_complete(user):
            raise ValueError("Заполни профиль на 100% в ЛК, чтобы участвовать")
        await conn.execute("INSERT INTO seasonal_entries VALUES(?,?,?)", (item_id, uid, datetime.now(UTC).isoformat()))
        await conn.commit()
    return "Заявка принята! Вы участвуете в розыгрыше"


async def prepare_draw(db, settings, uid, item_id=ITEM):
    if not await can_manage(db, settings, uid):
        raise web.HTTPForbidden()
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        if not await can_manage(db, settings, uid):
            raise web.HTTPForbidden()
        row = await one(conn, "SELECT status FROM seasonal_raffles WHERE id=?", (item_id,))
        raw = await one(conn, "SELECT value FROM bot_state WHERE key=?",
                        ("seasonal_item_metadata" if item_id == ITEM else "seasonal_item:" + item_id,))
        if raw and json.loads(raw["value"]).get("mode") == "paid":
            raise ValueError("Это платный предмет, а не розыгрыш")
        ids = [
            r[0]
            for r in await (
                await conn.execute("SELECT user_id FROM seasonal_entries WHERE raffle_id=? ORDER BY user_id",
                                   (item_id,))
            ).fetchall()
        ]
        if not row or row["status"] != "open":
            raise ValueError("Победитель уже определён. Повторный выбор запрещён")
        if not ids:
            raise ValueError("Пока нет участников")
        token = secrets.token_urlsafe(32)
        await conn.execute("DELETE FROM seasonal_draw_tokens WHERE expires_at<? OR consumed=1", (time.time(),))
        await conn.execute(
            "INSERT INTO seasonal_draw_tokens VALUES(?,?,?,?,0)",
            (token, uid, fingerprint(ids, item_id), time.time() + 300)
        )
        await conn.commit()
    return {"token": token, "count": len(ids), "title": TITLE}


async def draw(db, settings, uid, token, item_id=ITEM):
    if not await can_manage(db, settings, uid):
        raise web.HTTPForbidden()
    if not isinstance(token, str) or not 20 <= len(token) <= 100:
        raise ValueError("Открой подтверждение итогов заново")
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        if not await can_manage(db, settings, uid):
            raise web.HTTPForbidden()
        intent = await one(conn, "SELECT * FROM seasonal_draw_tokens WHERE token=? AND actor_id=?", (token, uid))
        raffle = await one(conn, "SELECT * FROM seasonal_raffles WHERE id=?", (item_id,))
        raw = await one(conn, "SELECT value FROM bot_state WHERE key=?",
                        ("seasonal_item_metadata" if item_id == ITEM else "seasonal_item:" + item_id,))
        if raw and json.loads(raw["value"]).get("mode") == "paid":
            raise ValueError("Это платный предмет, а не розыгрыш")
        if not raffle or raffle["status"] != "open":
            raise ValueError("Победитель уже определён. Повторный выбор запрещён")
        if not intent or intent["consumed"] or intent["expires_at"] <= time.time():
            raise ValueError("Подтверждение устарело или принадлежит другому администратору")
        ids = [
            r[0]
            for r in await (
                await conn.execute("SELECT user_id FROM seasonal_entries WHERE raffle_id=? ORDER BY user_id",
                                   (item_id,))
            ).fetchall()
        ]
        if not ids or fingerprint(ids, item_id) != intent["entries_digest"]:
            raise ValueError("Список участников изменился. Открой подтверждение заново")
        winner = ids[secrets.randbelow(len(ids))]
        now = datetime.now(UTC).isoformat()
        await conn.execute(
            "UPDATE seasonal_raffles SET status='drawn',winner_id=?,drawn_at=?,drawn_by=?,"
            "entry_count=?,entries_digest=? WHERE id=?",
            (winner, now, uid, len(ids), fingerprint(ids, item_id), item_id),
        )
        await conn.execute("UPDATE seasonal_draw_tokens SET consumed=1 WHERE token=?", (token,))
        metadata = await one(conn, "SELECT value FROM bot_state WHERE key=?",
                             ("seasonal_item_metadata" if item_id == ITEM else "seasonal_item:" + item_id,))
        title = json.loads(metadata["value"])["title"] if metadata else TITLE
        await conn.execute(
            "INSERT INTO notify_inbox(user_id,channel,text,created_at,read,delivered) VALUES(?,'shop',?,?,0,0)",
            (
                winner,
                f"Вы выиграли «{title}» — эксклюзив 1 сезона! "
                "Свяжитесь с командой Норы, чтобы договориться о получении приза.",
                now,
            ),
        )
        await conn.commit()
    return winner


async def status(request):
    from community_bot.miniapp import actor

    user = await actor(request)
    return web.json_response(await snapshot(request.app["db"], request.app["settings"], user["user_id"]))


async def items_endpoint(request):
    from community_bot.miniapp import actor

    user = await actor(request)
    return web.json_response({"items": await all_items(request.app["db"], request.app["settings"], user["user_id"])})


async def upload_image(request):
    from community_bot.media_cache import images
    from community_bot.miniapp import actor

    user = await actor(request)
    db, settings = request.app["db"], request.app["settings"]
    if not await can_manage(db, settings, user["user_id"]):
        raise web.HTTPForbidden()
    raw = await request.read()
    if request.content_type not in {"image/jpeg", "image/png", "image/webp"} or len(raw) > 5 * 1024 * 1024:
        raise ValueError("Выберите фото JPG, PNG или WebP до 5 МБ")
    photo = await images(request).normalize(raw)
    sent = await request.app["bot"].send_photo(
        user["user_id"], BufferedInputFile(photo, filename="seasonal.jpg"),
        caption="Изображение сезонного предмета", disable_notification=True,
    )
    token = secrets.token_hex(24)
    await db.set_bot_state("seasonal_media:" + token, sent.photo[-1].file_id)
    return web.json_response({"image": "/seasonal/media/" + token})


async def image(request):
    token = request.match_info["token"]
    if not re.fullmatch(r"[0-9a-f]{48}", token):
        raise web.HTTPNotFound()
    file_id = await request.app["db"].get_bot_state("seasonal_media:" + token)
    if not file_id:
        raise web.HTTPNotFound()
    output = BytesIO()
    await request.app["bot"].download(file_id, destination=output)
    return web.Response(body=output.getvalue(), content_type="image/jpeg")


async def save_endpoint(request):
    from community_bot.miniapp import actor

    user = await actor(request)
    body = await request.json()
    if not isinstance(body, dict) or set(body) != {"id", "item"}:
        raise ValueError("Проверьте поля предмета")
    await save_item(request.app["db"], request.app["settings"], user["user_id"], body["id"], body["item"])
    return web.json_response({"items": await all_items(request.app["db"], request.app["settings"], user["user_id"])})


async def buy_prepare_endpoint(request):
    from community_bot.miniapp import actor

    user = await actor(request)
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get("id"), str):
        raise ValueError("Предмет не найден")
    return web.json_response(await buy_prepare(request.app["db"], request.app["settings"], user["user_id"], body["id"]))


async def buy_confirm_endpoint(request):
    from community_bot.miniapp import actor

    user = await actor(request)
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get("token"), str):
        raise ValueError("Открой подтверждение покупки заново")
    await buy_confirm(request.app["db"], user["user_id"], body["token"])
    return web.json_response({"message": "Покупка готова! Администрация свяжется с вами в ближайшее время.",
                              "items": await all_items(request.app["db"], request.app["settings"], user["user_id"])})


async def participate(request):
    from community_bot.miniapp import actor

    user = await actor(request)
    body = await request.json()
    item_id = body.get("id", ITEM) if isinstance(body, dict) else ITEM
    if not isinstance(item_id, str):
        raise ValueError("Предмет не найден")
    message = await join(request.app["db"], user["user_id"], item_id)
    return web.json_response(
        {"message": message,
         "seasonal": await snapshot(request.app["db"], request.app["settings"], user["user_id"], item_id)}
    )


async def manage(request):
    from community_bot.miniapp import actor

    user = await actor(request)
    db, settings, uid = request.app["db"], request.app["settings"], user["user_id"]
    if not await can_manage(db, settings, uid):
        raise web.HTTPForbidden()
    raw = request.query.get("offset", "0")
    if not raw.isdigit() or len(raw) > 6:
        raise ValueError("Некорректная страница")
    offset = int(raw)
    item_id = request.query.get("id", ITEM)
    entries = await db.fetchall(
        "SELECT u.user_id,u.username,u.profile_name,u.telegram_name,e.joined_at "
        "FROM seasonal_entries e JOIN users u ON u.user_id=e.user_id "
        "WHERE e.raffle_id=? ORDER BY e.joined_at,u.user_id LIMIT 21 OFFSET ?",
        (item_id, offset),
    )
    return web.json_response(
        {
            "items": entries[:20],
            "has_more": len(entries) > 20,
            "offset": offset,
            "seasonal": await snapshot(db, settings, uid, item_id),
        }
    )


async def draw_prepare(request):
    from community_bot.miniapp import actor

    await actor(request)
    body = await request.json()
    item_id = body.get("id", ITEM) if isinstance(body, dict) else ITEM
    return web.json_response(
        await prepare_draw(request.app["db"], request.app["settings"], request["actor"]["id"], item_id))


async def draw_confirm(request):
    from community_bot.miniapp import actor

    await actor(request)
    body = await request.json()
    if not isinstance(body, dict) or set(body) not in ({"token"}, {"token", "id"}):
        raise ValueError("Некорректное подтверждение")
    item_id = body.get("id", ITEM)
    await draw(request.app["db"], request.app["settings"], request["actor"]["id"], body["token"], item_id)
    return web.json_response(
        {
            "message": "Победитель определён. Итог сохранён",
            "seasonal": await snapshot(request.app["db"], request.app["settings"], request["actor"]["id"], item_id),
        }
    )
