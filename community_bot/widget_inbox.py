"""Individual private notifications and controls for previously sent inbox widgets."""
from __future__ import annotations

import json
import logging
import re
import zlib
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from time import time
from uuid import uuid4

from aiogram.exceptions import (
    ClientDecodeError,
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.methods import DeleteMessage, EditMessageCaption, EditMessageReplyMarkup, SendMessage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from community_bot.message_widgets import AnswerWidgetQuery, EditMessageWidgetData, SendNotificationWidget
from community_bot.rsvp import event_lock
from community_bot.widget_notifications import (
    BLOCKED_INTERVAL,
    DELETE_DELAY,
    DELETE_WINDOW,
    SEND_INTERVAL,
    TARGETS,
    TEST_CATEGORY,
    snippet,
)

logger = logging.getLogger(__name__)
TEMPLATE = Path(__file__).with_name("widgets") / "notification.html"
QUERY = re.compile(r"nwi:(page|close|read):([0-9a-f]{1,32})")
UNREAD = "delivery IN ('inbox_queued','inbox_open','inbox_paused') AND read_at IS NULL"
PENDING = "delivery IN ('inbox_queued','inbox_open','inbox_paused','inbox_closing')"
NOTICE_PENDING = "delivery IN ('notice_queued','notice_paused','notice_closing','notice_text_closing')"


def widget_html() -> str:
    html = TEMPLATE.read_text(encoding="utf-8")
    raw = html.encode()
    if not 1 <= len(raw) <= 32768 or len(zlib.compress(raw, 9)) > 4096:
        raise ValueError("Telegram widget exceeds the mini-HTML limits")
    return html


def pack(data: dict) -> str:
    while True:
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode()) <= 1024:
            return encoded
        # Each field is already bounded. Trim the longest until UTF-8 and JSON fit the wire limit.
        page = data["p"]
        key = max(("title", "details", "sender", "context"), key=lambda name: len(page[name].encode()))
        page[key] = snippet(page[key], max(1, len(page[key]) // 2))


async def snapshot(db, uid, username, index=0) -> dict:
    stats = await db.fetchone(
        f"SELECT COALESCE(MAX(rowid),0) AS revision, COUNT(CASE WHEN {UNREAD} THEN 1 END) AS count "
        "FROM widget_notifications WHERE recipient_id=? AND delivery LIKE 'inbox_%'",
        (uid,),
    )
    count = stats["count"]
    state = {"r": stats["revision"], "n": count, "i": min(max(index, 0), max(count - 1, 0))}
    if count:
        row = await db.fetchone(
            f"SELECT * FROM widget_notifications WHERE recipient_id=? AND {UNREAD} "
            "ORDER BY rowid DESC LIMIT 1 OFFSET ?",
            (uid, state["i"]),
        )
        state["p"] = notice_page(row, username)
    return state


def notice_page(row, username):
    return {
        "id": row["id"], "title": snippet(row["title"], 52), "sender": snippet(row["sender_label"], 28),
        "context": snippet(row["context"], 35), "details": snippet(row["details"] or row["preview"], 148),
        "date": datetime.fromisoformat(row["event_at"]).strftime("%d.%m.%Y %H:%M UTC"),
        "url": f"https://t.me/{username}?startapp=nora_notice_{row['id']}",
    }


def caption(state: dict) -> str:
    count = state["n"]
    if not count:
        return "НОРА · Уведомления прочитаны"
    last, tail = count % 10, count % 100
    noun = "уведомлений"
    if tail not in range(11, 15):
        if last == 1:
            noun = "уведомление"
        elif last in range(2, 5):
            noun = "уведомления"
    return f'<a href="{state["p"]["url"]}">У вас {count} {noun}!</a>'


async def schedule(db, uid, when) -> None:
    await db.execute(f"UPDATE widget_notifications SET next_action_at=? WHERE recipient_id=? AND {PENDING}",
                     (when, uid))


async def telegram_raw(bot, method):
    # The target is a stored widget message. Caption/delete must bypass navigation and admin UI capture.
    return await bot.session.make_request(bot, method, timeout=5)


async def sync_message(bot, anchor, state) -> None:
    uid, mid = anchor["chat_id"], anchor["message_id"]
    for method in (
        EditMessageWidgetData(chat_id=uid, message_id=mid, chat_data=pack(state)),
        EditMessageCaption(chat_id=uid, message_id=mid, caption=caption(state), parse_mode="HTML"),
    ):
        try:
            await telegram_raw(bot, method)
        except TelegramBadRequest as error:
            if "not modified" not in str(error).lower().replace("_", " "):
                raise


def missing(error: TelegramBadRequest) -> bool:
    message = str(error).casefold().replace("_", " ")
    return "not found" in message or "message id invalid" in message


async def delete_inbox(bot, db, anchor, *, closed_status="inbox_closed") -> bool:
    now = int(time())
    try:
        if now < anchor["created_at"] + DELETE_WINDOW:
            await telegram_raw(bot, DeleteMessage(chat_id=anchor["chat_id"], message_id=anchor["message_id"]))
        elif anchor["delivery"] == "notice_text_closing":
            await telegram_raw(bot, EditMessageReplyMarkup(chat_id=anchor["chat_id"], message_id=anchor["message_id"]))
        else:
            # Telegram cannot delete old messages. Clear their pages and caption instead.
            await sync_message(bot, anchor, {"closed": True, "n": 0, "i": 0})
    except TelegramBadRequest as error:
        if not missing(error) and not any(reason in str(error).casefold().replace("_", " ") for reason in (
            "can't be deleted", "can't be edited", "not modified",
        )):
            return False
    except (TelegramAPIError, ClientDecodeError):
        return False

    await db.execute(
        "UPDATE widget_notifications SET delivery=?,next_action_at=NULL WHERE id=?",
        (closed_status, anchor["id"]),
    )
    return True


async def flush(bot, db, uid) -> str:
    """Reconcile one recipient under the recipient lock."""
    now = int(time())
    anchor = await db.fetchone(
        "SELECT * FROM widget_notifications WHERE recipient_id=? "
        "AND delivery IN ('inbox_open','inbox_closing') LIMIT 1", (uid,),
    )
    if anchor and anchor["delivery"] == "inbox_closing":
        due = anchor["next_action_at"] or now
        if due > now:
            await schedule(db, uid, due)
            return "queued"
        if not await delete_inbox(bot, db, anchor):
            await schedule(db, uid, now + 60)
            return "queued"
        anchor = None

    paused = await db.fetchone(
        "SELECT next_action_at FROM widget_notifications WHERE recipient_id=? AND delivery='inbox_paused'", (uid,),
    )
    if paused and (paused["next_action_at"] or 0) > now:
        await schedule(db, uid, paused["next_action_at"])
        return "blocked"

    try:
        me = await bot.me()
    except (TelegramAPIError, ClientDecodeError):
        await schedule(db, uid, now + 60)
        return "queued"
    if not me.username or not re.fullmatch(r"[A-Za-z0-9_]+", me.username):
        await schedule(db, uid, now + 300)
        return "failed"

    state = await snapshot(db, uid, me.username)
    if not state["n"]:
        await schedule(db, uid, None)
        return "suppressed"

    if anchor:
        try:
            await sync_message(bot, anchor, state)
        except TelegramBadRequest as error:
            if not missing(error):
                await schedule(db, uid, now + 60)
                return "queued"
            # The user removed the card manually. Keep any unread entries for its replacement.
            await db.execute(
                "UPDATE widget_notifications SET delivery='inbox_queued',chat_id=NULL,message_id=NULL WHERE id=?",
                (anchor["id"],),
            )
        except (TelegramAPIError, ClientDecodeError):
            await schedule(db, uid, now + 60)
            return "queued"
        else:
            await schedule(db, uid, None)
            return "updated"

    row = await db.fetchone(
        f"SELECT id FROM widget_notifications WHERE recipient_id=? AND {UNREAD} ORDER BY rowid LIMIT 1", (uid,),
    )
    # A crash or lost response during sendWidget cannot safely retry the same delivery.
    await db.execute(
        "UPDATE widget_notifications SET delivery='inbox_unconfirmed' "
        "WHERE recipient_id=? AND delivery='inbox_sending'", (uid,),
    )
    await db.execute(
        f"UPDATE widget_notifications SET delivery='inbox_sending',next_action_at=NULL "
        f"WHERE recipient_id=? AND {UNREAD}", (uid,),
    )
    try:
        sent = await bot(SendNotificationWidget(
            chat_id=uid, html=widget_html(), caption=caption(state), allow_queries=True, chat_data=pack(state),
        ), request_timeout=5)
    except TelegramForbiddenError:
        delivery, delay, outcome = "inbox_paused", BLOCKED_INTERVAL, "blocked"
    except TelegramRetryAfter as error:
        delivery, delay, outcome = "inbox_paused", max(5, error.retry_after), "queued"
    except (TelegramNetworkError, TelegramServerError, ClientDecodeError):
        delivery, delay, outcome = "inbox_unconfirmed", 60, "unconfirmed"
    except TelegramAPIError as error:
        logger.info("Widget notification rejected (%s)", type(error).__name__)
        delivery, delay, outcome = "inbox_paused", 300, "failed"
    else:
        if sent.chat.id == uid and sent.message_id > 0:
            async with db.connect() as connection:
                await connection.execute(
                    "UPDATE widget_notifications SET delivery='inbox_queued' "
                    "WHERE recipient_id=? AND delivery='inbox_sending' AND rowid<=?",
                    (uid, state["r"]),
                )
                await connection.execute(
                    "UPDATE widget_notifications SET delivery='inbox_open',chat_id=?,message_id=?,created_at=? "
                    "WHERE id=?", (uid, sent.message_id, now, row["id"]),
                )
                await connection.commit()
            return "sent"
        delivery, delay, outcome = "inbox_unconfirmed", 60, "unconfirmed"

    async with db.connect() as connection:
        await connection.execute(
            "UPDATE widget_notifications SET delivery=?,next_action_at=? "
            "WHERE recipient_id=? AND delivery='inbox_sending' AND rowid<=?",
            (delivery if outcome == "unconfirmed" else "inbox_queued",
             None if outcome == "unconfirmed" else now + delay, uid, state["r"]),
        )
        if delivery == "inbox_paused":
            await connection.execute(
                "UPDATE widget_notifications SET delivery='inbox_paused' WHERE id=?", (row["id"],),
            )
        await connection.commit()
    return outcome


async def enqueue(bot, db, uid, sender, title, preview, details, target, category, event_key,
                  *, context="", event_at=None, required=False) -> str:
    if uid <= 0 or target not in TARGETS or not title.strip() or not preview.strip() or not event_key:
        raise ValueError("Invalid widget notification")
    if event_at is not None and event_at.utcoffset() is None:
        raise ValueError("Widget event time must have a timezone")
    now = int(time())
    event_at = (event_at or datetime.fromtimestamp(now, UTC)).astimezone(UTC).isoformat()
    async with event_lock(db, f"widget-inbox:{uid}"):
        async with db.connect() as connection:
            cursor = await connection.execute(
                """INSERT INTO widget_notifications(
                       id,recipient_id,sender_type,sender_id,sender_label,title,preview,details,
                       category,target,context,event_at,event_key,created_at,delivery,next_action_at)
                   SELECT ?,user_id,?,?,?,?,?,?,?,?,?,?,?,?,'notice_queued',? FROM users
                   WHERE user_id=? AND (? OR EXISTS (
                       SELECT 1 FROM notify_prefs WHERE user_id=users.user_id AND channel=? AND enabled=1
                   )) AND NOT EXISTS (
                       SELECT 1 FROM widget_notifications WHERE recipient_id=users.user_id
                       AND category=? AND created_at>? AND ?=?
                   )
                   ON CONFLICT(recipient_id,category,event_key) DO NOTHING RETURNING id""",
                (uuid4().hex, sender.kind, sender.user_id, sender.label, title, preview, details, category, target,
                 context, event_at, event_key, now, now, uid, required, category, TEST_CATEGORY, now - SEND_INTERVAL,
                 category, TEST_CATEGORY),
            )
            row = await cursor.fetchone()
            await cursor.close()
            await connection.commit()
        return await deliver_notice(bot, db, uid, row["id"]) if row else "suppressed"


async def send_card(bot, uid, row, state):
    try:
        return await bot(SendNotificationWidget(
            chat_id=uid, html=widget_html(), caption=caption(state), allow_queries=True, chat_data=pack(state),
        ), request_timeout=5), "notice_sent"
    except (TelegramBadRequest, TelegramNotFound):
        # Older API routes can reject the widget. Send a new, visible text card in the same chat.
        text = f"🔔 <b>{escape(snippet(row['title'], 150))}</b>\n\n{escape((row['details'] or row['preview'])[:1600])}"
        return await telegram_raw(bot, SendMessage(
            chat_id=uid, text=text, parse_mode="HTML", disable_notification=False,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Открыть Нору", url=state["p"]["url"]),
                InlineKeyboardButton(text="Прочитано", callback_data=f"nwn:{row['id']}"),
            ]]),
        )), "notice_text"


async def deliver_notice(bot, db, uid, notice_id):
    now = int(time())
    row = await db.fetchone(
        "SELECT rowid,* FROM widget_notifications WHERE id=? AND recipient_id=? "
        "AND delivery IN ('notice_queued','notice_paused') AND read_at IS NULL", (notice_id, uid),
    )
    if not row:
        return "suppressed"
    paused = await db.fetchone(
        "SELECT MAX(next_action_at) AS due FROM widget_notifications "
        "WHERE recipient_id=? AND delivery='notice_paused'", (uid,),
    )
    if (paused["due"] or 0) > now:
        await db.execute("UPDATE widget_notifications SET next_action_at=? WHERE id=?", (paused["due"], notice_id))
        return "blocked"
    try:
        me = await bot.me()
    except (TelegramAPIError, ClientDecodeError):
        await db.execute("UPDATE widget_notifications SET next_action_at=? WHERE id=?", (now + 60, notice_id))
        return "queued"
    if not me.username or not re.fullmatch(r"[A-Za-z0-9_]+", me.username):
        await db.execute("UPDATE widget_notifications SET next_action_at=? WHERE id=?", (now + 300, notice_id))
        return "failed"

    state = {"r": row["rowid"], "n": 1, "i": 0, "p": notice_page(row, me.username)}
    # A failed or interrupted request can leave delivery uncertain. Avoid sending duplicates.
    await db.execute(
        "UPDATE widget_notifications SET delivery='notice_unconfirmed',next_action_at=NULL WHERE id=?", (notice_id,),
    )
    try:
        sent, delivery = await send_card(bot, uid, row, state)
    except TelegramForbiddenError:
        delay, outcome = BLOCKED_INTERVAL, "blocked"
    except TelegramRetryAfter as error:
        delay, outcome = max(5, error.retry_after), "queued"
    except (TelegramNetworkError, TelegramServerError, ClientDecodeError):
        return "unconfirmed"
    except TelegramAPIError as error:
        logger.info("Private notification rejected (%s)", type(error).__name__)
        delay, outcome = 300, "failed"
    else:
        if sent.chat.id != uid or sent.message_id <= 0:
            return "unconfirmed"
        await db.execute(
            "UPDATE widget_notifications SET delivery=?,chat_id=?,message_id=?,created_at=? WHERE id=?",
            (delivery, uid, sent.message_id, now, notice_id),
        )
        return "sent"
    await db.execute(
        "UPDATE widget_notifications SET delivery='notice_paused',next_action_at=? WHERE id=?",
        (now + delay, notice_id),
    )
    return outcome


async def settle_notice(bot, db, uid, notice_id):
    row = await db.fetchone("SELECT * FROM widget_notifications WHERE id=?", (notice_id,))
    if not row or (row["next_action_at"] or 0) > int(time()):
        return
    if row["delivery"] not in {"notice_closing", "notice_text_closing"}:
        await deliver_notice(bot, db, uid, notice_id)
        return
    if not await delete_inbox(bot, db, row, closed_status="notice_closed"):
        await db.execute("UPDATE widget_notifications SET next_action_at=? WHERE id=?", (int(time()) + 60, notice_id))


async def mark_notice_read(db, uid, notice_id, *, delay=0):
    from community_bot.profile_access_rollout import clear_profile_notice_if_read

    now = int(time())
    async with db.connect() as conn:
        await conn.execute(
            "UPDATE widget_notifications SET read_at=?,next_action_at=?,"
            "delivery=CASE WHEN delivery='notice_text' THEN 'notice_text_closing' ELSE 'notice_closing' END "
            "WHERE id=? AND recipient_id=? AND delivery IN ('notice_sent','notice_text')",
            (now, now + delay, notice_id, uid),
        )
        await clear_profile_notice_if_read(conn, uid)
        await conn.commit()


async def handle_fallback_read(bot, db, callback):
    chat = getattr(callback.message, "chat", None)
    notice_id = (callback.data or "")[4:]
    if not chat or chat.type != "private" or chat.id != callback.from_user.id:
        await callback.answer()
        return
    uid = chat.id
    async with event_lock(db, f"widget-inbox:{uid}"):
        row = await db.fetchone(
            "SELECT id FROM widget_notifications WHERE id=? AND recipient_id=? AND chat_id=? AND message_id=? "
            "AND delivery='notice_text'", (notice_id, uid, uid, callback.message.message_id),
        )
        if row:
            await mark_notice_read(db, uid, notice_id)
        await callback.answer("Прочитано" if row else None)
        if row:
            await settle_notice(bot, db, uid, notice_id)


async def schedule_after_read(conn, uid, anchor_id, now, *, delay):
    remaining = await (await conn.execute(
        f"SELECT 1 FROM widget_notifications WHERE recipient_id=? AND {UNREAD} LIMIT 1", (uid,),
    )).fetchone()
    if remaining:
        await conn.execute("UPDATE widget_notifications SET next_action_at=? WHERE id=?", (now, anchor_id))
    else:
        await conn.execute(
            "UPDATE widget_notifications SET delivery='inbox_closing',next_action_at=? WHERE id=?",
            (now + delay, anchor_id),
        )
    return bool(remaining)


async def handle_query(bot, db, query) -> bool:
    data = query.get("data")
    match = QUERY.fullmatch(data) if isinstance(data, str) else None
    if not match:
        return False
    query_id = query.get("id")
    if not isinstance(query_id, str) or not query_id:
        return True
    chat, sender, kind = query.get("chat"), query.get("from"), query.get("type")
    uid = chat.get("id") if isinstance(chat, dict) else None
    mid = query.get("message_id")
    if (type(uid) is not int or uid <= 0 or chat.get("type") != "private"
            or not isinstance(sender, dict) or sender.get("id") != uid
            or not isinstance(kind, dict) or kind.get("type") != "data"
            or type(mid) is not int or mid <= 0 or query.get("inline_message_id") or query.get("widget_id")):
        await answer(bot, query_id, {})
        return True

    action, argument = match.groups()
    async with event_lock(db, f"widget-inbox:{uid}"):
        notice = await db.fetchone(
            "SELECT rowid,id,delivery FROM widget_notifications WHERE recipient_id=? AND chat_id=? AND message_id=? "
            "AND delivery IN ('notice_sent','notice_closing','notice_closed')", (uid, uid, mid),
        )
        if notice:
            if notice["delivery"] != "notice_sent":
                await answer(bot, query_id, {"closed": True})
            elif (action == "read" and argument == notice["id"]
                    or action == "close" and argument == str(notice["rowid"])):
                await mark_notice_read(db, uid, notice["id"], delay=DELETE_DELAY if action == "read" else 0)
                await answer(bot, query_id, {"closed": True})
                if action == "close":
                    await settle_notice(bot, db, uid, notice["id"])
                else:
                    try:
                        await sync_message(bot, {"chat_id": uid, "message_id": mid}, {"closed": True, "n": 0, "i": 0})
                    except (TelegramAPIError, ClientDecodeError):
                        pass
            else:
                await answer(bot, query_id, {})
            return True
        anchor = await db.fetchone(
            "SELECT id,delivery FROM widget_notifications WHERE recipient_id=? AND chat_id=? AND message_id=? "
            "AND delivery IN ('inbox_open','inbox_closing','inbox_closed')", (uid, uid, mid),
        )
        if not anchor:
            await answer(bot, query_id, {})
            return True
        if anchor["delivery"] != "inbox_open":
            await answer(bot, query_id, {"closed": True})
            return True
        me = await bot.me()
        state = await snapshot(db, uid, me.username, int(argument) if action == "page" and argument.isdecimal() else 0)
        if action == "page":
            await answer(bot, query_id, state)
            return True
        now = int(time())
        if action == "close" and argument != str(state["r"]):
            await answer(bot, query_id, dict(state, changed=True))
            return True
        async with db.connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            await connection.execute(
                f"UPDATE widget_notifications SET read_at=?,"
                "delivery=CASE WHEN delivery='inbox_open' THEN delivery ELSE 'inbox_read' END,"
                f"next_action_at=NULL WHERE recipient_id=? AND {UNREAD}"
                + (" AND id=?" if action == "read" else ""),
                (now, uid, argument) if action == "read" else (now, uid),
            )
            from community_bot.profile_access_rollout import clear_profile_notice_if_read

            await clear_profile_notice_if_read(connection, uid)
            remaining = await schedule_after_read(
                connection, uid, anchor["id"], now, delay=0 if action == "close" else DELETE_DELAY,
            )
            await connection.commit()
        state = await snapshot(db, uid, me.username)
        if not remaining:
            await answer(bot, query_id, dict(state, closed=True))
            if action == "close":
                await flush(bot, db, uid)
            else:
                try:
                    await sync_message(bot, {"chat_id": uid, "message_id": mid}, state)
                except (TelegramAPIError, ClientDecodeError):
                    pass
        else:
            await answer(bot, query_id, state)
            await flush(bot, db, uid)
    return True


async def answer(bot, query_id, data) -> None:
    try:
        await bot(AnswerWidgetQuery(widget_query_id=query_id, data=pack(data)), request_timeout=5)
    except (TelegramAPIError, ClientDecodeError):
        logger.info("Widget inbox query could not be answered")


async def settle_due(bot, db) -> None:
    notices = await db.fetchall(
        f"SELECT id,recipient_id FROM widget_notifications WHERE {NOTICE_PENDING} AND next_action_at<=? "
        "ORDER BY next_action_at,rowid LIMIT 25", (int(time()),),
    )
    for notice in notices:
        uid = notice["recipient_id"]
        async with event_lock(db, f"widget-inbox:{uid}"):
            await settle_notice(bot, db, uid, notice["id"])
    rows = await db.fetchall(
        f"SELECT recipient_id FROM widget_notifications WHERE {PENDING} AND next_action_at<=? "
        "GROUP BY recipient_id ORDER BY MIN(next_action_at) LIMIT 25", (int(time()),),
    )
    for row in rows:
        uid = row["recipient_id"]
        async with event_lock(db, f"widget-inbox:{uid}"):
            await flush(bot, db, uid)
