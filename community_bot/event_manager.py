"""Staff event lifecycle: editable metadata, archive with once-only refunds, retryable post sync."""

from __future__ import annotations

import html
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup

from community_bot.ephemeral import keep_in_chat
from community_bot.helpers import has_permission
from community_bot.keyboards import STYLE_CLOSE, ibtn
from community_bot.permissions import PERM_ADMIN_PANEL, PERM_EVENT_PARTICIPANTS, PERM_POST
from community_bot.rsvp import event_lock
from community_bot.shop_text import plain_shop_text
from community_bot.states import AdminFlow


async def can_read(db, settings, uid):
    return await has_permission(db, settings, uid, PERM_ADMIN_PANEL) and (
        await has_permission(db, settings, uid, PERM_POST)
        or await has_permission(db, settings, uid, PERM_EVENT_PARTICIPANTS)
    )


async def visible_events(db, offset=0, limit=9):
    return await db.fetchall(
        "SELECT s.*, (SELECT COUNT(*) FROM event_rsvps r WHERE r.event_id=s.event_id) AS participants "
        "FROM studio_events s WHERE s.status IN ('active','disabled') "
        "ORDER BY s.created_at DESC,s.event_id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )


async def set_enabled(db, eid, revision, enabled):
    target, source = ("active", "disabled") if enabled else ("disabled", "active")
    async with db.connect() as connection:
        await connection.execute("BEGIN IMMEDIATE")
        cursor = await connection.execute(
            "UPDATE studio_events SET status=?,revision=revision+1,content_dirty=1,markup_dirty=1 "
            "WHERE event_id=? AND revision=? AND status=?",
            (target, eid, revision, source),
        )
        if cursor.rowcount != 1:
            await connection.rollback()
            return False
        if enabled:
            await connection.execute(
                "INSERT INTO bot_state(key,value) VALUES('current_studio_event',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (eid,),
            )
        await connection.commit()
        return True


async def update_metadata(db, eid, field, value, revision):
    if field not in {"title", "description", "starts_at"}:
        raise ValueError("Неизвестное поле события")
    async with db.connect() as connection:
        await connection.execute("BEGIN IMMEDIATE")
        if field == "title":
            previous = await (
                await connection.execute(
                    "SELECT s.*,o.body AS offer_body FROM studio_events s LEFT JOIN event_offers o USING(event_id) "
                    "WHERE s.event_id=?",
                    (eid,),
                )
            ).fetchone()
            if previous:
                description = plain_shop_text(previous["description"] or previous["offer_body"])
                lines = description.splitlines()
                if lines and lines[0].strip() == plain_shop_text(previous["title"]):
                    description = "\n".join(lines[1:]).strip()
                await connection.execute("UPDATE studio_events SET description=? WHERE event_id=?", (description, eid))
                await connection.execute("UPDATE event_offers SET body=? WHERE event_id=?", (description, eid))
        cursor = await connection.execute(
            f"UPDATE studio_events SET {field}=?, revision=revision+1, content_dirty=1, markup_dirty=1 "
            "WHERE event_id=? AND revision=? AND status IN ('active','disabled')",
            (value, eid, revision),
        )
        if cursor.rowcount != 1:
            await connection.rollback()
            return False
        if field in {"title", "description"}:
            target = "title" if field == "title" else "body"
            await connection.execute(f"UPDATE event_offers SET {target}=? WHERE event_id=?", (value, eid))
        await connection.commit()
        return True


async def cancel_event(db, eid, revision):
    async with db.connect() as connection:
        await connection.execute("BEGIN IMMEDIATE")
        cursor = await connection.execute(
            "UPDATE studio_events SET status='cancelled', revision=revision+1, content_dirty=1, markup_dirty=1 "
            "WHERE event_id=? AND revision=? AND status IN ('active','disabled')",
            (eid, revision),
        )
        if cursor.rowcount != 1:
            await connection.rollback()
            return False, 0
        rows = await (
            await connection.execute(
                "SELECT * FROM event_rsvps WHERE event_id=? AND kind IN ('payment','rsvp') AND stake>0",
                (eid,),
            )
        ).fetchall()
        total, now = 0, datetime.now(UTC).isoformat()
        for row in rows:
            amount = int(row["stake"])
            total += amount
            await connection.execute(
                "UPDATE users SET cookies=cookies+?,updated_at=? WHERE user_id=?", (amount, now, row["user_id"])
            )
            await connection.execute(
                "INSERT INTO transactions(user_id,amount,kind,details,created_at) VALUES(?,?,?,?,?)",
                (row["user_id"], amount, "rsvp_refund", eid, now),
            )
        # Preserve reservations, offers and ledger as evidence, including ambiguous legacy payments.
        await connection.commit()
        return True, total


def date_label(value, timezone):
    if not value:
        return "Не указана"
    return datetime.fromisoformat(value).astimezone(ZoneInfo(timezone)).strftime("%d.%m.%Y %H:%M")


async def show(message, db, settings, uid, eid):
    event = await db.get_studio_event(eid)
    if not event:
        await message.answer(
            "Для старого события доступен журнал участников.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [ibtn("Участники и оплаты", f"admin:attendees:{eid}:0")],
                    [ibtn("К событиям", "admin:events:0")],
                ],
            ),
        )
        return
    offer = await db.get_event_offer(eid)
    description = plain_shop_text(event["description"] or (offer or {}).get("body", ""))
    rows = []
    if event["status"] in {"active", "disabled"} and await has_permission(db, settings, uid, PERM_POST):
        rows += [
            [
                ibtn("Название", f"admin:event:edit:{eid}:title"),
                ibtn("Описание", f"admin:event:edit:{eid}:description"),
            ],
            [ibtn("Дата и время", f"admin:event:edit:{eid}:starts_at")],
            [
                ibtn(
                    "Выключить мероприятие" if event["status"] == "active" else "Включить мероприятие",
                    f"admin:event:{'disable' if event['status'] == 'active' else 'enable'}:{eid}:{event['revision']}",
                )
            ],
            [ibtn("Удалить мероприятие", f"admin:event:delete:{eid}", STYLE_CLOSE)],
        ]
    if await has_permission(db, settings, uid, PERM_EVENT_PARTICIPANTS):
        rows.append([ibtn("Участники и оплаты", f"admin:attendees:{eid}:0")])
    rows.append([ibtn("К событиям", "admin:events:0")])
    status = {"active": "Актуальное", "disabled": "Выключено · запись и оплата приостановлены"}.get(
        event["status"], "Удалено из актуальных · история сохранена"
    )
    text = (
        f"🎟 <b>{html.escape(event['title'])}</b>\n{status}\n\n"
        f"Дата: {date_label(event['starts_at'], settings.timezone)} ({settings.timezone})\n"
        f"Участие: {int(offer['price']) if offer else 0} 🍪\n"
        f"Участников: {await db.event_participant_count(eid)}\n\n{html.escape(description[:750])}"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def handle(callback, state, db, settings, bot):
    uid = callback.from_user.id
    if not callback.message or not await can_read(db, settings, uid):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) < 4:
        return
    action, eid = parts[2:4]
    if action == "new":
        from community_bot.routers.private import begin_event_creation

        await begin_event_creation(callback, state, db, settings)
        return
    if action == "view":
        await callback.answer()
        await show(callback.message, db, settings, uid, eid)
        return
    if not await has_permission(db, settings, uid, PERM_POST):
        await callback.answer("Нужно право «Пост в сообщество».", show_alert=True)
        return
    event = await db.get_studio_event(eid)
    if not event or event["status"] not in {"active", "disabled"}:
        await callback.answer("Мероприятие уже закрыто.", show_alert=True)
        return
    if action in {"disable", "enable"} and len(parts) == 5 and parts[4].isdigit():
        async with event_lock(db, eid):
            ok = await set_enabled(db, eid, int(parts[4]), action == "enable")
            if ok:
                from community_bot.rsvp import refresh_event_markup

                await refresh_event_markup(bot, db, eid)
        await callback.answer("Сохранено" if ok else "Экран устарел, открой событие заново", show_alert=not ok)
        await show(callback.message, db, settings, uid, eid)
        return
    if action == "edit" and len(parts) == 5 and parts[4] in {"title", "description", "starts_at"}:
        field = parts[4]
        prompts = {
            "title": "Новое название: от 2 до 80 символов.",
            "description": "Новое описание: до 750 символов. «-» — убрать описание.",
            "starts_at": "Новая дата: ДД.ММ.ГГГГ ЧЧ:ММ, время по " + settings.timezone + ". «-» — убрать дату.",
        }
        await state.set_state(AdminFlow.user_value)
        await state.set_data({"admin_action": "event_meta:" + field, "event_id": eid, "revision": event["revision"]})
        await callback.answer()
        await callback.message.answer(prompts[field])
    elif action == "delete":
        legacy = await db.fetchone(
            "SELECT COUNT(*) n FROM event_rsvps WHERE event_id=? AND kind='legacy' AND stake>0", (eid,)
        )
        warning = "\nСтарые неоднозначные оплаты требуют ручного разбора." if legacy["n"] else ""
        await callback.answer()
        await callback.message.answer(
            "Удалить мероприятие из актуальных? Запись и оплата закроются. Известные оплаты и залоги вернутся "
            "участникам один раз. Журнал останется." + warning,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        ibtn(
                            "Да, удалить и вернуть оплаты", f"admin:event:cancel:{eid}:{event['revision']}", STYLE_CLOSE
                        )
                    ],
                    [ibtn("Оставить мероприятие", f"admin:event:view:{eid}")],
                ]
            ),
        )
    elif action == "cancel" and len(parts) == 5 and parts[4].isdigit():
        async with event_lock(db, eid):
            ok, total = await cancel_event(db, eid, int(parts[4]))
            if ok:
                await sync_content(bot, db, eid)
                from community_bot.rsvp import refresh_event_markup

                await refresh_event_markup(bot, db, eid)
        await callback.answer("Удалено." if ok else "Событие изменилось. Открой его заново.", show_alert=not ok)
        if ok:
            await db.log_admin_action(uid, "event_cancel", eid, f"Возвращено {total} 🍪")
            await callback.message.answer(f"Мероприятие убрано из актуальных. Возвращено {total} 🍪.")
            from community_bot.routers.private import admin_event_list

            await admin_event_list(callback.model_copy(update={"data": "admin:events:0"}), db, settings)


async def save_field(message, state, db, settings, bot):
    if not await has_permission(db, settings, message.from_user.id, PERM_POST) or not await can_read(
        db,
        settings,
        message.from_user.id,
    ):
        await state.clear()
        await message.answer("Прав на редактирование события больше нет.")
        return
    data = await state.get_data()
    field = data["admin_action"].split(":", 1)[1]
    value = (message.text or "").strip()
    if field == "title" and not 2 <= len(value) <= 80:
        await message.answer("Название: от 2 до 80 символов.")
        return
    if field == "description":
        value = "" if value == "-" else value
        if len(value.encode("utf-16-le")) // 2 > 750:
            await message.answer("Описание: максимум 750 символов, эмодзи могут занимать два.")
            return
    if field == "starts_at":
        if value == "-":
            value = None
        else:
            try:
                value = (
                    datetime.strptime(value, "%d.%m.%Y %H:%M")
                    .replace(
                        tzinfo=ZoneInfo(settings.timezone),
                    )
                    .astimezone(UTC)
                    .isoformat()
                )
            except ValueError:
                await message.answer("Формат даты: ДД.ММ.ГГГГ ЧЧ:ММ.")
                return
    eid = data["event_id"]
    async with event_lock(db, eid):
        ok = await update_metadata(db, eid, field, value, data["revision"])
        if ok:
            from community_bot.rsvp import refresh_event_markup

            synced = await refresh_event_markup(bot, db, eid)
        else:
            synced = False
    await state.clear()
    await message.answer(
        "Сохранено и обновлено в посте."
        if ok and synced
        else (
            "Сохранено. Обновление поста поставлено в очередь." if ok else "Событие уже изменилось. Открой его заново."
        )
    )
    if ok:
        await db.log_admin_action(message.from_user.id, "event_edit", eid, field)
    await show(message, db, settings, message.from_user.id, eid)


async def sync_content(bot, db, eid):
    event = await db.get_studio_event(eid)
    if not event or event["content_dirty"] != 1:
        return True
    offer = await db.get_event_offer(eid)
    description = plain_shop_text(event["description"] or (offer or {}).get("body", ""))
    when = "\n📅 " + date_label(event["starts_at"], "Europe/Moscow") + " МСК" if event["starts_at"] else ""
    cancelled = {
        "cancelled": "❌ <b>Мероприятие отменено</b>\n\n",
        "disabled": "⏸ <b>Запись на мероприятие приостановлена</b>\n\n",
    }.get(event["status"], "")
    text = cancelled + f"<b>{html.escape(event['title'])}</b>{when}\n\n{html.escape(description)}"
    try:
        with keep_in_chat():
            kwargs = {"chat_id": event["chat_id"], "message_id": event["message_id"], "parse_mode": "HTML"}
            if event["media_type"]:
                await bot.edit_message_caption(caption=text, **kwargs)
            else:
                try:
                    await bot.edit_message_text(text=text, **kwargs)
                except TelegramBadRequest as error:
                    if "no text" not in error.message.casefold():
                        raise
                    await bot.edit_message_caption(caption=text, **kwargs)
    except TelegramBadRequest as error:
        if "not modified" not in error.message.casefold():
            return False
    except TelegramAPIError:
        return False
    await db.execute(
        "UPDATE studio_events SET content_dirty=0 WHERE event_id=? AND revision=?", (eid, event["revision"])
    )
    return True
