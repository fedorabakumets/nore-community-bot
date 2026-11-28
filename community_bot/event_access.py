"""Current-event shop and staff roster, sharing the published event ledger."""
from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from community_bot.aliases import command_or_alias
from community_bot.helpers import has_permission, register_telegram_user, user_link
from community_bot.permissions import PERM_EVENT_PARTICIPANTS

router = Router(name="event_access")


async def current_event(db):
    selected = await db.get_bot_state("current_studio_event")
    if selected:
        event = await db.get_studio_event(selected)
        if event and event['status'] == 'active':
            return event
    return await db.fetchone("SELECT * FROM studio_events WHERE status='active' ORDER BY created_at DESC LIMIT 1")


async def open_event_purchase(callback, db):
    event = await current_event(db)
    if not event:
        await callback.answer("Сейчас нет опубликованного мероприятия.", show_alert=True)
        return
    event_id = event["event_id"]
    await register_telegram_user(db, callback.from_user)
    offer = await db.get_event_offer(event_id)
    if offer and int(offer["price"]) > 0:
        from community_bot.routers.life import event_pay_open

        await event_pay_open(callback.model_copy(update={"data": f"evpay:{event_id}"}), db)
        return
    ok, error = await db.add_rsvp(event_id, callback.from_user.id, 0, kind="rsvp")
    await callback.answer()
    await callback.message.answer(
        f"🎟 <b>{html.escape(event['title'])}</b>\n"
        + ("Это мероприятие бесплатное, вы записаны в список участников!" if ok else error), parse_mode="HTML",
    )
    from community_bot.rsvp import event_lock, refresh_event_markup

    async with event_lock(db, event_id):
        await refresh_event_markup(callback.bot, db, event_id)


async def roster(db, event_id, page=0, ledger=False):
    event = await db.get_studio_event(event_id)
    if not event:
        return "Мероприятие не найдено.", None
    if ledger:
        rows = await db.fetchall(
            """SELECT t.*, u.telegram_name FROM transactions t JOIN users u USING(user_id)
            WHERE t.details=? AND t.kind IN ('rsvp','rsvp_refund') ORDER BY t.id DESC LIMIT 11 OFFSET ?""",
            (event_id, page * 10),
        )
        lines = [f"💳 <b>Журнал оплат · {html.escape(event['title'])}</b>", ""]
        for row in rows[:10]:
            lines.append(f"{user_link(row['user_id'], row['telegram_name'] or str(row['user_id']))}: "
                         f"{row['amount']:+} 🍪 · {html.escape(row['created_at'][:16])}")
    else:
        rows = await db.list_rsvps(event_id, offset=page * 10, limit=11)
        lines = [f"🎟 <b>{html.escape(event['title'])}</b>",
                 f"Участников: {await db.event_participant_count(event_id)}", ""]
        for row in rows[:10]:
            status = f"оплачено {row['stake']} 🍪" if row['kind'] == 'payment' else (
                f"внесено {row['stake']} 🍪" if row['stake'] else 'бесплатная запись')
            lines.append(f"{user_link(row['user_id'], row['telegram_name'] or str(row['user_id']))} — {status}")
    if not rows:
        lines.append("Пока записей нет.")
    mode = int(ledger)
    buttons = []
    if page:
        buttons.append(InlineKeyboardButton(text="←", callback_data=f"eventlist:{event_id}:{mode}:{page-1}"))
    if len(rows) > 10:
        buttons.append(InlineKeyboardButton(text="→", callback_data=f"eventlist:{event_id}:{mode}:{page+1}"))
    keyboard = [buttons] if buttons else []
    keyboard.append([InlineKeyboardButton(text="Участники" if ledger else "Журнал оплат",
                                         callback_data=f"eventlist:{event_id}:{1-mode}:0")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.message(command_or_alias("participants"))
async def participants(message: Message, db, settings):
    if not message.from_user or not await has_permission(db, settings, message.from_user.id, PERM_EVENT_PARTICIPANTS):
        await message.answer("Недостаточно прав: нужен доступ к участникам мероприятий.")
        return
    event = await current_event(db)
    if not event:
        await message.answer("Сейчас нет опубликованного мероприятия.")
        return
    text, markup = await roster(db, event['event_id'])
    await message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data.startswith("eventlist:"))
async def participant_page(callback: CallbackQuery, db, settings):
    if not await has_permission(db, settings, callback.from_user.id, PERM_EVENT_PARTICIPANTS):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return
    _, event_id, mode, page = callback.data.split(":")
    if not page.isdigit() or mode not in {'0', '1'}:
        return
    text, markup = await roster(db, event_id, int(page), bool(int(mode)))
    await callback.answer()
    await callback.message.answer(text, parse_mode="HTML", reply_markup=markup)
