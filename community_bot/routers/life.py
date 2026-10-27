from __future__ import annotations

import html
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    ChatJoinRequest,
    ChatPermissions,
    InlineKeyboardMarkup,
    Message,
)

from community_bot.aliases import command_or_alias, remainder_args, remainder_text
from community_bot.audit import person_label
from community_bot.blocks import answer_block
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.ephemeral import keep_in_chat
from community_bot.helpers import (
    effective_role,
    has_permission,
    media_from_message,
    register_telegram_user,
    resolve_reply_target,
    user_link,
)
from community_bot.keyboards import STYLE_GO, ibtn, shop_confirm_keyboard
from community_bot.life import (
    WARN_KICK_AT,
    WARN_MUTE_AT,
    WARN_MUTE_HOURS,
    gift_item_from_args,
    unlock,
)
from community_bot.permissions import PERM_POST
from community_bot.rsvp import attendance_action, event_lock, published_event, refresh_event_markup
from community_bot.shop_catalog import (
    GIFTABLE_ITEMS,
    ITEM_LABELS,
    PET_SUPPLIES,
    shop_prices_for,
)
from community_bot.states import GiftFlow, MailboxForm

router = Router(name="life")

_TG_ERRORS = (TelegramBadRequest, TelegramForbiddenError)


@router.message(command_or_alias("stickers"))
async def sticker_pack(message: Message, bot: Bot) -> None:
    from community_bot.stickers import send_pack_invitation

    await send_pack_invitation(message, bot)


def _captcha_markup(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[ibtn("Я человек", f"captcha:ok:{chat_id}", STYLE_GO)]])


def lottery_markup(lottery_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[ibtn("Участвовать", f"lottery:join:{lottery_id}", STYLE_GO)]])


def _full_chat_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_other_messages=True,
    )


async def _deliver_shop(
    db: Database,
    settings: Settings,
    bot: Bot,
    buyer_id: int,
    target_id: int,
    item: str,
    price: int,
    *,
    intent_id: str,
) -> tuple[bool, str]:
    if item not in GIFTABLE_ITEMS and item not in ITEM_LABELS:
        return False, "Этот товар нельзя подарить."
    if item in PET_SUPPLIES:
        kind, gain, _ = PET_SUPPLIES[item]
        ok, error, _ = await db.purchase_pet_supply(
            target_id, kind, gain, price, item, payer_id=buyer_id, intent_id=intent_id,
        )
        if not ok:
            return False, error
    else:
        ok, error = await db.buy_item(buyer_id, item, price, target_id=target_id, intent_id=intent_id)
        if not ok:
            return False, error
        if item == "forgive" and settings.community_chat_id:
            with suppress(*_TG_ERRORS):
                await bot.restrict_chat_member(
                    settings.community_chat_id,
                    target_id,
                    permissions=_full_chat_permissions(),
                )
    from community_bot.notify import vitrine_consumed

    await vitrine_consumed(bot, db, item)
    if buyer_id != target_id:
        await unlock(db, buyer_id, "gift_first")
    await unlock(db, buyer_id, "shop_first")
    return True, "ok"


async def _confirm_gift(
    message: Message, db: Database, buyer_id: int, target: dict[str, object], item: str, price: int,
) -> None:
    token = await db.create_wallet_intent(
        buyer_id, item, price, target_id=int(target["user_id"]), payload={"gift": True},
    )
    await message.answer(
        f"🎁 <b>Подтвердите подарок</b>\n{html.escape(ITEM_LABELS.get(item, item))}\n"
        f"Получатель: {html.escape(person_label(target))}\nСпишется: <b>{price} 🍪</b>.",
        parse_mode="HTML", reply_markup=shop_confirm_keyboard(token, price),
    )


@router.message(command_or_alias("gift"))
async def gift_command(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    if not message.from_user:
        return
    item = gift_item_from_args(remainder_text(message.text or ""))
    if not item:
        await message.answer("Ответьте на человека: «подарить щит» / плащ / обед / поилка / набор / сова.")
        return
    target = await resolve_reply_target(message, db)
    buyer = await register_telegram_user(db, message.from_user)
    if not target:
        await state.set_state(GiftFlow.target)
        await state.set_data({"gift_item": item})
        await message.answer("Ответьте на сообщение человека или пришлите @username / ID.")
        return
    prices = shop_prices_for(buyer, settings.restricted_reputation_threshold, await db.priced_shop_map())
    if item not in prices:
        await message.answer("Цена этого товара ещё не задана. Администратор выставит её в управлении магазином.")
        return
    await _confirm_gift(message, db, int(buyer["user_id"]), target, item, prices[item])


@router.message(GiftFlow.target)
async def gift_target_text(message: Message, state: FSMContext, db: Database, settings: Settings, bot: Bot) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    item = str(data.get("gift_item") or "")
    target = await resolve_reply_target(message, db)
    if not target:
        token = (message.text or "").strip().lstrip("@")
        if token.isdigit():
            target = await db.get_user(int(token))
        else:
            users = await db.search_users(token)
            target = users[0] if users else None
    if not target or not item:
        await message.answer("Человек не найден.")
        return
    await state.clear()
    buyer = await register_telegram_user(db, message.from_user)
    prices = shop_prices_for(buyer, settings.restricted_reputation_threshold, await db.priced_shop_map())
    if item not in prices:
        await message.answer("Цена этого товара ещё не задана. Администратор выставит её в управлении магазином.")
        return
    await _confirm_gift(message, db, int(buyer["user_id"]), target, item, prices[item])


@router.callback_query(F.data.startswith("shop:g:"))
async def shop_gift_begin(callback: CallbackQuery, state: FSMContext) -> None:
    item = callback.data.rsplit(":", 1)[1]
    if item not in GIFTABLE_ITEMS:
        await callback.answer("Этот товар не дарят.", show_alert=True)
        return
    await state.set_state(GiftFlow.target)
    await state.set_data({"gift_item": item})
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"🎁 Кому подарить «{ITEM_LABELS.get(item, item)}»? Ответьте на сообщение или пришлите @username / ID."
        )


@router.message(command_or_alias("bug"), F.chat.type.in_({"group", "supergroup"}))
async def bug_message(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    if await effective_role(db, settings, message.from_user.id) not in {"admin", "owner"}:
        await message.answer("Команда «баг» доступна администраторам и владельцам.")
        return
    source = message.reply_to_message
    if source is None:
        await message.answer("Ответьте «баг» на сообщение. После слова можно дописать, что сломалось.")
        return
    await register_telegram_user(db, message.from_user)
    target = await resolve_reply_target(message, db)
    # Anonymous/channel posts may have no from_user; the reporter owns this technical note.
    target_id = int(target["user_id"]) if target else message.from_user.id
    media_type, file_id = media_from_message(source)
    if source.sticker:
        media_type, file_id = "sticker", source.sticker.file_id
    elif source.video_note:
        media_type, file_id = "video_note", source.video_note.file_id
    elif source.animation:
        media_type, file_id = "animation", source.animation.file_id
    text = source.text or source.caption or (f"[{media_type}]" if media_type else "[Сообщение без текста]")
    note = remainder_text(message.text or message.caption or "") or "нужно проверить"
    report_id = await db.create_report(
        message.from_user.id, target_id, message.chat.id, source.message_id, text, f"БАГ · {note}",
        attachment=(media_type, file_id) if media_type and file_id else None,
    )
    await message.answer(f"🐞 Баг #{report_id} сохранён: админ-панель → Очередь → Репорты.")


@router.message(command_or_alias("report"), F.chat.type.in_({"group", "supergroup"}))
async def report_message(message: Message, db: Database) -> None:
    if not message.from_user:
        return
    target = await resolve_reply_target(message, db)
    if not target or not message.reply_to_message:
        await message.answer("Ответьте «репорт» на сообщение и коротко напишите причину.")
        return
    reason = remainder_text(message.text or "") or "без причины"
    text = message.reply_to_message.text or message.reply_to_message.caption or ""
    await db.create_report(
        message.from_user.id,
        int(target["user_id"]),
        message.chat.id,
        message.reply_to_message.message_id,
        text,
        reason,
    )
    await message.answer("🚩 Репорт ушёл в очередь модераторов.")


@router.message(command_or_alias("mail"))
async def mail_begin(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        await message.answer("Письмо пишут боту в личке: /mail или «почта».")
        return
    await state.set_state(MailboxForm.text)
    await message.answer("Напишите текст письма. Имя в чате не покажем. До 2000 символов.")


@router.message(MailboxForm.text)
async def mail_save(message: Message, state: FSMContext, db: Database) -> None:
    if not message.from_user:
        return
    text = (message.text or "").strip()
    if not 10 <= len(text) <= 2000:
        await message.answer("Текст — от 10 до 2000 символов.")
        return
    await db.create_mail(message.from_user.id, text)
    await state.clear()
    await message.answer("✉️ Письмо ушло модераторам. Если одобрят — опубликуем без вашего имени.")


@router.message(command_or_alias("board"))
async def show_board(message: Message, db: Database) -> None:
    week_id = datetime.now(UTC).strftime("%G-W%V")
    board = await db.weekly_board(week_id)
    await answer_block(message, "events", _format_board(week_id, board), parse_mode="HTML")


def _format_board(week_id: str, board: dict) -> str:
    def lines(rows: list, score_key: str) -> str:
        if not rows:
            return "пока пусто"
        out = []
        for index, row in enumerate(rows, start=1):
            name = row.get("profile_name") or row.get("telegram_name") or row.get("username") or row["user_id"]
            out.append(f"{index}. {html.escape(str(name))} — {row.get(score_key) or row.get('messages')}")
        return "\n".join(out)

    return (
        f"🏆 <b>Доска недели {html.escape(week_id)}</b>\n\n"
        f"<b>Голос чата</b> (сообщения)\n{lines(board.get('messages') or [], 'messages')}\n\n"
        f"<b>Кого плюсовали</b>\n{lines(board.get('plus') or [], 'score')}\n\n"
        f"<b>Находки тамагочи</b> 🍪\n{lines(board.get('farm') or [], 'score')}"
    )


@router.message(command_or_alias("lottery"), F.chat.type.in_({"group", "supergroup"}))
async def lottery_start(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    if not await has_permission(db, settings, message.from_user.id, PERM_POST):
        return
    tokens = remainder_args(message.text or "")
    fee = int(tokens[0]) if tokens and tokens[0].isdigit() else 5
    lottery_id, error = await db.create_lottery(message.chat.id, message.from_user.id, fee)
    if not lottery_id:
        await message.answer(error)
        return
    with keep_in_chat():
        await message.answer(
            f"🎲 <b>Розыгрыш</b>\nВзнос {fee} 🍪. Кто в котле — жмёт кнопку. Итог: «розыгрыш итог».",
            parse_mode="HTML",
            reply_markup=lottery_markup(lottery_id),
        )


@router.message(command_or_alias("lotterydraw"), F.chat.type.in_({"group", "supergroup"}))
async def lottery_draw_cmd(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    if not await has_permission(db, settings, message.from_user.id, PERM_POST):
        return
    lottery = await db.open_lottery(message.chat.id)
    if not lottery:
        await message.answer("Открытого розыгрыша нет.")
        return
    ok, error, result = await db.draw_lottery(int(lottery["id"]))
    if not ok or not result:
        await message.answer(error)
        return
    winner = await db.get_user(int(result["winner_id"]))
    name = person_label(winner, str(result["winner_id"]))
    with keep_in_chat():
        await message.answer(
            f"🎲 Победитель: {html.escape(name)} · банк {result['pot']} 🍪 · игроков {result['players']}.",
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("lottery:join:"))
async def lottery_join(callback: CallbackQuery, db: Database) -> None:
    lottery_id = int(callback.data.rsplit(":", 1)[1])
    ok, error, count = await db.join_lottery(lottery_id, callback.from_user.id)
    if not ok:
        await callback.answer(error, show_alert=True)
        return
    await unlock(db, callback.from_user.id, "lottery")
    await callback.answer(f"Вы в котле. Участников: {count}")


@router.callback_query(F.data.startswith("rsvp:"))
async def rsvp_join(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    event = await published_event(callback, db, settings.community_chat_id)
    if not event:
        await callback.answer("Запись доступна только под опубликованным постом сообщества.", show_alert=True)
        return
    event_id = str(event["event_id"])
    await register_telegram_user(db, callback.from_user)
    if await db.has_event_payment(event_id, callback.from_user.id):
        await callback.answer("Вы уже оплатили участие. Отмена — через администрацию.", show_alert=True)
        return
    if await db.has_event_rsvp(event_id, callback.from_user.id):
        await callback.answer("Вы уже в списке")
        await callback.message.answer(
            f"Вы записаны на «{html.escape(event['title'])}». Отменить участие?",
            parse_mode="HTML",
            reply_markup=attendance_action(event_id, callback.from_user.id, cancel=True),
        )
        return
    stake = int(event["stake"])
    if stake:
        await callback.answer()
        await callback.message.answer(
            f"Запись на «{html.escape(event['title'])}»: залог {stake} 🍪.\n"
            "При отмене записи залог вернётся. При покупке билета он войдёт в оплату.",
            parse_mode="HTML",
            reply_markup=attendance_action(event_id, callback.from_user.id, cancel=False, stake=stake),
        )
        return
    await _record_attendance(callback, db, event)


async def _record_attendance(callback: CallbackQuery, db: Database, event: dict) -> None:
    event_id = str(event["event_id"])
    async with event_lock(db, event_id):
        ok, error = await db.add_rsvp(event_id, callback.from_user.id, int(event["stake"]), kind="rsvp")
        await callback.answer("Вы в списке!" if ok else error, show_alert=not ok)
        await refresh_event_markup(callback.bot, db, event_id)
    if ok:
        from community_bot.notify import emit

        await emit(callback.bot, db, callback.from_user.id, "events", f"🎟 Вы записаны: {html.escape(event['title'])}.")


@router.callback_query(F.data.startswith("rsvpj:") | F.data.startswith("rsvpc:"))
async def rsvp_confirm_action(callback: CallbackQuery, db: Database) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or parts[2] != str(callback.from_user.id):
        await callback.answer("Эта кнопка предназначена другому участнику.", show_alert=True)
        return
    action, event_id, _ = parts
    event = await db.get_studio_event(event_id)
    if not event or not event["rsvp_enabled"] or not callback.message or callback.message.chat.id != event["chat_id"]:
        await callback.answer("Запись недоступна.", show_alert=True)
        return
    await register_telegram_user(db, callback.from_user)
    if action == "rsvpj":
        await _record_attendance(callback, db, event)
    else:
        async with event_lock(db, event_id):
            ok, text = await db.cancel_event_rsvp(event_id, callback.from_user.id)
            await callback.answer(text, show_alert=True)
            await refresh_event_markup(callback.bot, db, event_id)


@router.callback_query(F.data.startswith("evpay:"))
async def event_pay_open(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    event_id = callback.data.split(":", 1)[1]
    offer = await db.get_event_offer(event_id)
    if not offer:
        await callback.answer("Это мероприятие уже недоступно.", show_alert=True)
        return
    if await db.has_event_payment(event_id, callback.from_user.id):
        await callback.answer("Вы уже в списке участников.", show_alert=True)
        return
    price = int(offer["price"])
    from community_bot.ephemeral import keep_in_chat
    from community_bot.posting import event_pay_keyboard

    body = str(offer.get("body") or "").strip() or "Мероприятие сообщества."
    text = (
        f"🎟 <b>{html.escape(str(offer.get('title') or 'Мероприятие'))}</b>\n"
        f"{body}\n\n"
        f"Участие: <b>{price} 🍪</b>. Скидка репутации не действует."
    )
    await callback.answer()
    with keep_in_chat():
        await callback.message.answer(
            text[:3500],
            parse_mode="HTML",
            reply_markup=event_pay_keyboard(event_id, price),
        )


@router.callback_query(F.data.startswith("evpaygo:"))
async def event_pay_confirm(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    event_id = callback.data.split(":", 1)[1]
    offer = await db.get_event_offer(event_id)
    if not offer:
        await callback.answer("Это мероприятие уже недоступно.", show_alert=True)
        return
    if await db.has_event_payment(event_id, callback.from_user.id):
        await callback.answer("Вы уже оплатили участие.", show_alert=True)
        return
    price = int(offer["price"])
    reservation = await db.get_event_rsvp(event_id, callback.from_user.id)
    deposit = int(reservation["stake"]) if reservation else 0
    charge = max(0, price - deposit)
    refund = max(0, deposit - price)
    from community_bot.posting import event_pay_confirm_keyboard

    await callback.answer()
    await callback.message.answer(
        f"Билет стоит {price} 🍪. Внесён залог: {deposit} 🍪.\nСпишется: {charge} 🍪. "
        + (f"Вернётся остаток залога: {refund} 🍪. " if refund else "") + "Подтвердить оплату?",
        reply_markup=event_pay_confirm_keyboard(f"{event_id}:{price}"),
    )


@router.callback_query(F.data.startswith("evpayyes:"))
async def event_pay_charge(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer("Откройте оплату заново, чтобы подтвердить актуальную цену.", show_alert=True)
        return
    event_id = parts[1]
    offer = await db.get_event_offer(event_id)
    if not offer:
        await callback.answer("Это мероприятие уже недоступно.", show_alert=True)
        return
    if await db.has_event_payment(event_id, callback.from_user.id):
        await callback.answer("Вы уже оплатили участие.", show_alert=True)
        return
    await register_telegram_user(db, callback.from_user)
    async with event_lock(db, event_id):
        ok, error, charged = await db.pay_event_offer(event_id, callback.from_user.id, int(parts[2]))
        if ok:
            await refresh_event_markup(callback.bot, db, event_id)
    if not ok:
        await callback.answer(error, show_alert=True)
        return
    await callback.answer("Участие оплачено.")
    result = f"Списано {charged} 🍪." if charged >= 0 else f"Возвращён остаток залога {-charged} 🍪."
    try:
        await callback.message.edit_text(
            f"✅ Участие оплачено. {result}",
            reply_markup=None,
        )
    except Exception:
        await callback.message.answer(f"✅ Участие оплачено. {result}")
    from community_bot.notify import emit

    await emit(
        callback.bot,
        db,
        callback.from_user.id,
        "events",
        f"🎟 Участие оплачено. {result}",
    )


@router.chat_join_request()
async def captcha_join_request(event: ChatJoinRequest, db: Database, bot: Bot) -> None:
    if not await db.feature_enabled("join_captcha"):
        await event.approve()
        return
    await register_telegram_user(db, event.from_user)
    await db.add_captcha(event.from_user.id, event.chat.id)
    try:
        await bot.send_message(
            event.from_user.id,
            "Нажмите кнопку, чтобы войти в НОРУ.",
            reply_markup=_captcha_markup(event.chat.id),
        )
    except _TG_ERRORS:
        await event.approve()


@router.message(F.new_chat_members)
async def captcha_new_members(message: Message, db: Database, bot: Bot, settings: Settings) -> None:
    if not await db.feature_enabled("join_captcha"):
        return
    if settings.community_chat_id and message.chat.id != settings.community_chat_id:
        return
    for member in message.new_chat_members or []:
        if member.is_bot:
            continue
        await register_telegram_user(db, member)
        await db.add_captcha(member.id, message.chat.id)
        with suppress(*_TG_ERRORS):
            await bot.restrict_chat_member(
                message.chat.id,
                member.id,
                permissions=ChatPermissions(can_send_messages=False),
            )
        try:
            await bot.send_message(
                member.id,
                "Нажмите кнопку «Я человек», чтобы писать в чат.",
                reply_markup=_captcha_markup(message.chat.id),
            )
        except _TG_ERRORS:
            await message.answer(
                f"{user_link(member.id, member.full_name)}, подтвердите, что вы человек.",
                parse_mode="HTML",
                reply_markup=_captcha_markup(message.chat.id),
            )


@router.callback_query(F.data.startswith("captcha:ok:"))
async def captcha_ok(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    chat_id = int(callback.data.rsplit(":", 1)[1])
    if not await db.pop_captcha(callback.from_user.id, chat_id):
        await callback.answer("Уже подтверждено.")
        return
    with suppress(*_TG_ERRORS):
        await bot.restrict_chat_member(
            chat_id,
            callback.from_user.id,
            permissions=_full_chat_permissions(),
        )
    with suppress(*_TG_ERRORS):
        await bot.approve_chat_join_request(chat_id, callback.from_user.id)
    await callback.answer("Добро пожаловать.")
    if callback.message and callback.message.chat.type == "private":
        await callback.message.answer("Можно писать в чат.")


async def apply_warn_ladder(bot: Bot, message: Message, target_id: int, warnings: int) -> str:
    extra = ""
    if warnings >= WARN_KICK_AT:
        with suppress(*_TG_ERRORS):
            await bot.ban_chat_member(message.chat.id, target_id)
            await bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
        extra = " Лесенка: кик."
    elif warnings >= WARN_MUTE_AT:
        with suppress(*_TG_ERRORS):
            await bot.restrict_chat_member(
                message.chat.id,
                target_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.now(UTC) + timedelta(hours=WARN_MUTE_HOURS),
            )
        extra = f" Лесенка: мут {WARN_MUTE_HOURS} ч."
    return extra
