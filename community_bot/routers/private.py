from __future__ import annotations

import asyncio
import contextlib
import html
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    ChatPermissions,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    User,
)

from community_bot.aliases import command_or_alias
from community_bot.audit import format_audit_log, person_label
from community_bot.blocks import answer_block
from community_bot.config import Settings
from community_bot.database import Database, utcnow
from community_bot.helpers import (
    application_block_reason,
    can_manage_user,
    effective_role,
    has_permission,
    media_from_message,
    rank_of_user,
    register_telegram_user,
    render_profile,
    role_title,
    safe_send,
    user_link,
    user_permissions,
)
from community_bot.keyboards import (
    STYLE_CLOSE,
    STYLE_GO,
    YES_NO_KEYBOARD,
    admin_chat_keyboard,
    admin_mail_keyboard,
    admin_panel_keyboard,
    admin_people_keyboard,
    admin_queue_keyboard,
    admin_reports_keyboard,
    admin_restart_keyboard,
    admin_stopwords_keyboard,
    admin_system_keyboard,
    admin_user_keyboard,
    admin_users_keyboard,
    admin_vitrine_keyboard,
    application_review_keyboard,
    automessage_target_keyboard,
    automessages_keyboard,
    cookie_order_review_keyboard,
    feature_flags_keyboard,
    feature_reset_keyboard,
    features_panel_text,
    flow_reply_keyboard,
    main_private_keyboard,
    role_selection_keyboard,
    role_users_keyboard,
    roles_hub_keyboard,
    staff_role_view_keyboard,
    staff_roles_keyboard,
    start_apply_keyboard,
    ticket_keyboard,
)
from community_bot.permissions import (
    PERM_ADMIN_PANEL,
    PERM_APPLICATIONS,
    PERM_AUTOMESSAGES,
    PERM_BROADCAST,
    PERM_CHAT_LOCK,
    PERM_FEATURES,
    PERM_MENTION,
    PERM_PAYMENTS,
    PERM_POST,
    PERM_ROLES_ASSIGN,
    PERM_ROLES_EDIT,
    PERM_TICKETS,
    PERM_USERS_COOKIES,
    PERM_USERS_EDIT,
    slugify_role,
)
from community_bot.restart import play_countdown, try_begin
from community_bot.routers.flows import restore_private_menu
from community_bot.staff_guide import staff_guide_text
from community_bot.states import AdminFlow, ApplicationForm, ModeratorReply, TicketForm
from community_bot.texts import (
    APPLICATION_INTRO,
    APPLICATION_QUESTIONS,
    APPLICATION_REJECTED_INTERVIEW,
    REPUTATION_HELP_TEXT,
    STORE_HELP_TEXT,
    WELCOME_MEMBER_TEXT,
    WELCOME_PENDING_TEXT,
    WELCOME_TEXT,
)
from community_bot.updates import updates_text

logger = logging.getLogger(__name__)
router = Router(name="private")
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

EMERGENCY_STOP_COMMAND = "nore_stop_9x4q"
EMERGENCY_STOP_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="⛔ Да, отключить бота", callback_data="emergency:stop:confirm", style="danger")],
        [InlineKeyboardButton(text="Отмена", callback_data="emergency:stop:cancel", style=STYLE_CLOSE)],
    ]
)


async def _private_keyboard(user_id: int, db: Database, settings: Settings):
    del user_id, db, settings
    return main_private_keyboard()


async def _panel_markup(db: Database, settings: Settings, user_id: int):
    return admin_panel_keyboard(await user_permissions(db, settings, user_id), await db.dashboard_stats())


async def _send_welcome(message: Message, db: Database, settings: Settings, reply_markup) -> None:
    cover = settings.welcome_cover
    user_id = message.from_user.id if message.from_user else 0
    apply_markup = None
    if await db.has_approved_application(user_id):
        text = WELCOME_MEMBER_TEXT
    elif await db.has_pending_application(user_id):
        text = WELCOME_PENDING_TEXT
    else:
        apply_markup = start_apply_keyboard()
        text = WELCOME_TEXT
    first_markup = apply_markup or reply_markup
    if not cover:
        await message.answer(text, reply_markup=first_markup, parse_mode="HTML")
        if apply_markup:
            await message.answer(
                "Это анкета вступления. Отвечай по одному вопросу — решение придёт сюда.",
                reply_markup=reply_markup,
            )
        return
    source: str | FSInputFile = cover
    if await asyncio.to_thread(Path(cover).is_file):
        source = FSInputFile(cover)
    try:
        await message.answer_photo(source, caption=text, reply_markup=first_markup, parse_mode="HTML")
    except (TelegramBadRequest, OSError):
        await message.answer(text, reply_markup=first_markup, parse_mode="HTML")
    if apply_markup:
        await message.answer(
            "Это анкета вступления. Отвечай по одному вопросу — решение придёт сюда.",
            reply_markup=reply_markup,
        )


@router.message(Command(EMERGENCY_STOP_COMMAND))
async def emergency_stop_request(message: Message, settings: Settings) -> None:
    if not message.from_user or message.from_user.id != settings.owner_id:
        return
    with contextlib.suppress(TelegramBadRequest):
        await message.delete()
    await message.answer(
        "⚠️ <b>Аварийное отключение</b>\n\n"
        "Бот немедленно покинет известные чаты и останется выключенным даже после перезапуска VPS. "
        "Отменить это действие через Telegram будет нельзя.",
        parse_mode="HTML",
        reply_markup=EMERGENCY_STOP_KEYBOARD,
    )


@router.callback_query(F.data == "emergency:stop:cancel")
async def emergency_stop_cancel(callback: CallbackQuery, settings: Settings) -> None:
    if callback.from_user.id != settings.owner_id:
        await callback.answer("Недостаточно прав.", show_alert=True)
        return
    await callback.answer("Отменено")
    if callback.message:
        await callback.message.edit_text("Аварийное отключение отменено.")


@router.callback_query(F.data == "emergency:stop:confirm")
async def emergency_stop_confirm(
    callback: CallbackQuery,
    bot: Bot,
    db: Database,
    settings: Settings,
    emergency_stop: asyncio.Event,
) -> None:
    if callback.from_user.id != settings.owner_id:
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    await db.set_bot_state("emergency_disabled", "1")
    await db.set_bot_state("emergency_disabled_by", str(callback.from_user.id))
    await db.set_bot_state("emergency_disabled_at", datetime.now(UTC).isoformat())
    await callback.answer("Бот отключается", show_alert=True)
    if callback.message:
        await callback.message.edit_text("⛔ Бот аварийно отключён.")

    chat_ids = {settings.community_chat_id}
    stored_channel_id = await db.get_bot_state("freebie_channel_id")
    if stored_channel_id:
        with contextlib.suppress(ValueError):
            chat_ids.add(int(stored_channel_id))
    for chat_id in chat_ids:
        if chat_id:
            with contextlib.suppress(TelegramBadRequest, TelegramForbiddenError):
                await bot.leave_chat(chat_id)
    emergency_stop.set()


@router.message(CommandStart())
@router.message(F.text.func(lambda text: (text or "").casefold() == "старт"))
async def start(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    await register_telegram_user(db, message.from_user)
    await state.clear()
    await _send_welcome(message, db, settings, await _private_keyboard(message.from_user.id, db, settings))


@router.message(command_or_alias("pogoda"), F.chat.type == "private")
async def private_weather(message: Message, settings: Settings) -> None:
    from community_bot.morning import weather_reply

    now = datetime.now(ZoneInfo(settings.timezone))
    await message.answer(
        await weather_reply(now),
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@router.message(command_or_alias("help", "commands"), F.chat.type == "private")
async def help_command(message: Message, db: Database) -> None:
    if not message.from_user:
        return
    from community_bot.commands_guide import send_commands_card

    await send_commands_card(message, db)


@router.message(command_or_alias("store"))
async def private_store(message: Message) -> None:
    await answer_block(message, "shop", STORE_HELP_TEXT, parse_mode="HTML")


@router.message(command_or_alias("reputation"))
async def private_reputation(message: Message) -> None:
    await answer_block(message, "reputation", REPUTATION_HELP_TEXT, parse_mode="HTML")


@router.message(command_or_alias("updates"))
async def private_updates_command(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user or not await has_permission(db, settings, message.from_user.id, PERM_ADMIN_PANEL):
        await message.answer("Раздел «Обновления» доступен только администраторам.")
        return
    await message.answer(updates_text(), parse_mode="HTML")


@router.callback_query(F.data.in_({"admin:updates", "menu:updates"}))
async def admin_updates(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    await callback.answer()
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="↩️ В панель", callback_data="admin:panel")]]
    )
    try:
        await callback.message.edit_text(updates_text(), parse_mode="HTML", reply_markup=markup)
    except TelegramBadRequest:
        await callback.message.answer(updates_text(), parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data == "menu:apply")
async def menu_apply(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not callback.message or not callback.from_user:
        return
    await callback.answer()
    await _start_application(callback.message, state, db, callback.from_user)


@router.callback_query(F.data == "menu:profile")
async def menu_profile(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not callback.from_user:
        return
    from community_bot.routers.profile import send_profile_card

    user = await register_telegram_user(db, callback.from_user)
    text = await render_profile(db, settings, user)
    await callback.answer()
    await send_profile_card(callback.message, user, settings, editable=True, text=text, replace=True, db=db)


@router.callback_query(F.data == "menu:wallet")
async def menu_wallet(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not callback.from_user:
        return
    from community_bot.routers.wallet import send_wallet

    await callback.answer()
    await send_wallet(callback.message, db, settings)


@router.callback_query(F.data == "menu:question")
async def menu_question(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    if not callback.message:
        return
    await callback.answer()
    await open_ticket(callback.message, state, db, settings, bot)


@router.callback_query(F.data == "menu:shop")
async def menu_shop(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not callback.from_user:
        return
    from community_bot.routers.group import _shop_home_markup, _shop_home_text

    user = await register_telegram_user(db, callback.from_user)
    await callback.answer()
    await answer_block(
        callback.message,
        "shop",
        await _shop_home_text(db, user, settings),
        parse_mode="HTML",
        reply_markup=await _shop_home_markup(db),
    )


@router.callback_query(F.data == "menu:pet")
async def menu_pet(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not callback.from_user:
        return
    from community_bot.routers.pets import _show_pet

    await callback.answer()
    await _show_pet(callback.message, db, callback.from_user.id, settings, replace=True)


@router.callback_query(F.data == "menu:admin")
async def menu_admin(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    await callback.answer()
    await callback.message.answer(
        await _admin_panel_text(db),
        parse_mode="HTML",
        reply_markup=await _panel_markup(db, settings, callback.from_user.id),
    )


async def _admin_role(user_id: int, db: Database, settings: Settings) -> str | None:
    if await has_permission(db, settings, user_id, PERM_ADMIN_PANEL):
        return await effective_role(db, settings, user_id)
    return None


async def _admin_callback(
    callback: CallbackQuery,
    db: Database,
    settings: Settings,
    permission: str = PERM_ADMIN_PANEL,
) -> str | None:
    role = await _admin_role(callback.from_user.id, db, settings)
    if not role or not await has_permission(db, settings, callback.from_user.id, permission):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return None
    return role


async def _admin_panel_text(db: Database) -> str:
    stats = await db.dashboard_stats()
    return (
        "🛡 <b>Админ-панель</b>\n\n"
        f"Пользователей: <b>{stats['users']}</b> · питомцев: <b>{stats['pets']}</b>\n"
        f"Очередь: анкет <b>{stats['pending_applications']}</b> · платежей <b>{stats['pending_orders']}</b>"
        f" · тикетов <b>{stats.get('open_tickets', 0)}</b>\n"
        f"Активных игр: <b>{stats['active_games']}</b>\n\n"
        "Комнаты: очередь, люди, чат, система. Конкурс на печеньки — отдельный блок у владельцев."
    )


@router.message(command_or_alias("admin"))
@router.message(F.text == "🛡 Админ-панель")
async def admin_panel(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user or not await _admin_role(message.from_user.id, db, settings):
        return
    await answer_block(
        message,
        "admin",
        await _admin_panel_text(db),
        parse_mode="HTML",
        reply_markup=await _panel_markup(db, settings, message.from_user.id),
    )


@router.callback_query(F.data == "admin:panel")
async def admin_panel_callback(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    await callback.answer()
    await callback.message.edit_text(
        await _admin_panel_text(db),
        parse_mode="HTML",
        reply_markup=await _panel_markup(db, settings, callback.from_user.id),
    )


@router.callback_query(F.data == "admin:queue")
async def admin_queue(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    stats = await db.dashboard_stats()
    tickets = await db.list_open_tickets(8)
    lines = [
        "📋 <b>Очередь</b>",
        f"Анкет: <b>{stats['pending_applications']}</b> · платежей: <b>{stats['pending_orders']}</b> · "
        f"тикетов: <b>{stats.get('open_tickets', 0)}</b>",
        "",
    ]
    if tickets:
        lines.append("Открытые тикеты:")
        for row in tickets:
            name = row.get("profile_name") or row.get("telegram_name") or row.get("username") or row["user_id"]
            lines.append(f"• №{row['id']} · {html.escape(str(name))}")
    else:
        lines.append("Открытых тикетов нет.")
    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=admin_queue_keyboard(await user_permissions(db, settings, callback.from_user.id), stats),
    )


@router.callback_query(F.data == "admin:reports")
async def admin_reports(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_TICKETS):
        return
    rows = await db.list_pending_reports()
    lines = ["🚩 <b>Репорты</b>", ""]
    if not rows:
        lines.append("Очередь пуста.")
    for row in rows:
        snippet = html.escape((str(row.get("text") or "")[:80]).replace("\n", " "))
        reason = html.escape(str(row.get("reason") or ""))
        lines.append(f"#{row['id']} на {row['target_id']} · {reason}")
        if snippet:
            lines.append(f"<i>{snippet}</i>")
        lines.append("")
    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines).strip(),
        parse_mode="HTML",
        reply_markup=admin_reports_keyboard(rows),
    )


@router.callback_query(F.data.startswith("admin:report:"))
async def admin_report_review(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message or not await _admin_callback(callback, db, settings, PERM_TICKETS):
        return
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("Нет.", show_alert=True)
        return
    action, report_id = parts[2], int(parts[3])
    status = "approved" if action == "ok" else "rejected"
    if not await db.review_report(report_id, callback.from_user.id, status):
        await callback.answer("Уже разобрали.", show_alert=True)
        return
    await callback.answer("Принято." if action == "ok" else "Отклонено.")
    await admin_reports(callback, db, settings)


@router.callback_query(F.data == "admin:mail")
async def admin_mail(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_TICKETS):
        return
    rows = await db.list_pending_mail()
    lines = ["✉️ <b>Почта</b>", "📢 — опубликовать без имени. ❌ — отклонить.", ""]
    if not rows:
        lines.append("Очередь пуста.")
    for row in rows:
        snippet = html.escape((str(row.get("text") or "")[:200]).replace("\n", " "))
        lines.append(f"#{row['id']}\n{snippet}")
        lines.append("")
    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines).strip(),
        parse_mode="HTML",
        reply_markup=admin_mail_keyboard(rows),
    )


@router.callback_query(F.data.startswith("admin:mail:"))
async def admin_mail_review(
    callback: CallbackQuery,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    if not callback.data or not callback.message or not await _admin_callback(callback, db, settings, PERM_TICKETS):
        return
    parts = callback.data.split(":")
    if len(parts) < 4:
        await callback.answer("Нет.", show_alert=True)
        return
    action, mail_id = parts[2], int(parts[3])
    status = "approved" if action == "ok" else "rejected"
    row = await db.review_mail(mail_id, callback.from_user.id, status)
    if not row:
        await callback.answer("Уже разобрали.", show_alert=True)
        return
    if action == "ok" and settings.community_chat_id:
        from community_bot.ephemeral import keep_in_chat

        with keep_in_chat():
            await bot.send_message(
                settings.community_chat_id,
                f"✉️ <b>Письмо в нору</b>\n<blockquote>{html.escape(str(row['text']))}</blockquote>",
                parse_mode="HTML",
            )
    await callback.answer("Опубликовано." if action == "ok" else "Отклонено.")
    await admin_mail(callback, db, settings)


@router.callback_query(F.data == "admin:stopwords")
async def admin_stopwords(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_FEATURES):
        return
    words = await db.list_stop_words()
    listing = ", ".join(html.escape(str(row["word"])) for row in words) or "пусто"
    await callback.answer()
    await callback.message.edit_text(
        f"🚫 <b>Стоп-слова</b>\n\nСейчас: {listing}\nФлаг «Стоп-слова» в Функциях включает фильтр.",
        parse_mode="HTML",
        reply_markup=admin_stopwords_keyboard(words),
    )


@router.callback_query(F.data == "admin:stopword:add")
async def admin_stopword_add_begin(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_FEATURES):
        return
    await state.set_state(AdminFlow.user_value)
    await state.set_data({"admin_action": "stopword_add", "target_user_id": 0})
    await callback.answer()
    await callback.message.answer("Напишите стоп-слово (1–40 символов).", reply_markup=flow_reply_keyboard())


@router.callback_query(F.data.startswith("admin:stopword:del:"))
async def admin_stopword_delete(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message or not await _admin_callback(callback, db, settings, PERM_FEATURES):
        return
    word_id = int(callback.data.rsplit(":", 1)[1])
    await db.delete_stop_word(word_id)
    await callback.answer("Удалено.")
    await admin_stopwords(callback, db, settings)


@router.callback_query(F.data == "admin:people")
async def admin_people(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    await callback.answer()
    await callback.message.edit_text(
        "👤 <b>Люди</b>\n\nПоиск, роли, карточка, заметка и титул недели.",
        parse_mode="HTML",
        reply_markup=admin_people_keyboard(await user_permissions(db, settings, callback.from_user.id)),
    )


@router.callback_query(F.data == "admin:chatroom")
async def admin_chatroom(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    await callback.answer()
    await callback.message.edit_text(
        "💬 <b>Чат</b>\n\nПост, автосообщения, мут, упоминание, рассылка и флаги.",
        parse_mode="HTML",
        reply_markup=admin_chat_keyboard(await user_permissions(db, settings, callback.from_user.id)),
    )


def _system_text(*, is_owner: bool) -> str:
    text = "🛠 <b>Система</b>\n\nСводка дня, журнал, витрина, залог RSVP, обновления и справка админки."
    if is_owner:
        text += "\n\nКнопка перезапуска внизу. Отсчёт уйдёт в чат, настройки не сбросятся."
    return text


async def _show_system(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    is_owner = settings.is_owner(callback.from_user.id)
    await callback.message.edit_text(
        _system_text(is_owner=is_owner),
        parse_mode="HTML",
        reply_markup=admin_system_keyboard(
            await user_permissions(db, settings, callback.from_user.id),
            is_owner=is_owner,
        ),
    )


@router.callback_query(F.data == "admin:system")
async def admin_system(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    await callback.answer()
    await _show_system(callback, db, settings)


@router.callback_query(F.data == "admin:restart")
async def admin_restart_ask(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    if not settings.is_owner(callback.from_user.id):
        await callback.answer("Только владелец.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        "🔄 <b>Перезапуск</b>\n\n"
        "В чат сообщества уйдёт отсчёт, затем бот поднимется заново в этом же процессе.\n\n"
        "Не сбросится: роли, флаги, печеньки, журнал, витрина, RSVP и закреп.\n"
        "Это не аварийный выключатель — бот не выйдет из чатов и не заблокируется.",
        parse_mode="HTML",
        reply_markup=admin_restart_keyboard(),
    )


@router.callback_query(F.data == "admin:restart:no")
async def admin_restart_cancel(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    await callback.answer("Отменено")
    await _show_system(callback, db, settings)


@router.callback_query(F.data == "admin:restart:yes")
async def admin_restart_confirm(
    callback: CallbackQuery,
    bot: Bot,
    db: Database,
    settings: Settings,
    restart_stop: asyncio.Event,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    if not settings.is_owner(callback.from_user.id):
        await callback.answer("Только владелец.", show_alert=True)
        return
    if not try_begin():
        await callback.answer("Перезапуск уже идёт.", show_alert=True)
        return
    await db.log_admin_action(
        callback.from_user.id,
        "restart",
        str(settings.community_chat_id or ""),
        "in-place exec, state preserved",
        reason="перезапуск без сброса",
        actor_name=callback.from_user.full_name,
        status="green",
    )
    await callback.answer("Отсчёт ушёл в чат")
    with contextlib.suppress(TelegramBadRequest):
        await callback.message.edit_text(
            "🔄 Отсчёт в чате сообщества. Настройки на месте — бот сейчас вернётся.",
            parse_mode="HTML",
        )
    owner_name = callback.from_user.full_name
    chat_id = settings.community_chat_id or callback.from_user.id
    message_id = await play_countdown(bot, chat_id, owner_name=owner_name)
    if message_id is None and chat_id != callback.from_user.id:
        await play_countdown(bot, callback.from_user.id, owner_name=owner_name)
    restart_stop.set()


@router.callback_query(F.data == "admin:staffguide")
async def admin_staff_guide(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    await callback.answer()
    url = await db.get_bot_state("staff_guide_url")
    back = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад", callback_data="admin:system", style=STYLE_CLOSE)]]
    )
    if url:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Открыть Telegraph", url=url, style=STYLE_GO)],
                [InlineKeyboardButton(text="↩️ Назад", callback_data="admin:system", style=STYLE_CLOSE)],
            ]
        )
        await answer_block(
            callback.message,
            "admin",
            "📚 <b>Справка админки</b>\nПолный разбор штабных команд с примерами. Участники эту страницу не видят.",
            parse_mode="HTML",
            reply_markup=markup,
        )
        return
    text = staff_guide_text()
    await answer_block(
        callback.message,
        "admin",
        "📚 <b>Справка админки</b>\nTelegraph недоступен — полный текст ниже.",
        parse_mode="HTML",
        reply_markup=back,
    )
    remaining = text
    while remaining:
        chunk, remaining = remaining[:3500], remaining[3500:]
        await callback.message.answer(chunk, parse_mode="HTML")


@router.callback_query(F.data == "admin:search")
async def admin_search_begin(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    await state.set_state(AdminFlow.user_value)
    await state.set_data({"admin_action": "search", "target_user_id": 0})
    await callback.answer()
    await callback.message.answer("Имя, @username или Telegram ID:", reply_markup=flow_reply_keyboard())


@router.callback_query(F.data.startswith("admin:weekstar:"))
async def admin_weekstar(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not await _admin_callback(callback, db, settings, PERM_USERS_EDIT):
        return
    user_id = int(callback.data.rsplit(":", 1)[1])
    if not await db.get_user(user_id):
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    await db.set_weekly_star(user_id)
    await callback.answer("Титул недели выдан.", show_alert=True)


@router.callback_query(F.data == "admin:vitrine")
async def admin_vitrine(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    current = await db.get_bot_state("shop_featured_label")
    await callback.answer()
    await callback.message.edit_text(
        "⭐ <b>Витрина</b>\n\n"
        f"Сейчас: {html.escape(current) if current else 'пусто'}.\n"
        "Выберите товар, который будет первой кнопкой в магазине.",
        parse_mode="HTML",
        reply_markup=admin_vitrine_keyboard(),
    )


@router.callback_query(F.data.startswith("admin:vitrine:"))
async def admin_vitrine_set(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.data or not callback.message or not await _admin_callback(callback, db, settings):
        return
    key = callback.data.rsplit(":", 1)[1]
    from community_bot.shop_catalog import ITEM_LABELS, VITRINE_KEYS

    if key == "off":
        await db.set_bot_state("shop_featured", "")
        await db.set_bot_state("shop_featured_label", "")
        await db.set_bot_state("shop_featured_stock", "")
        await db.set_bot_state("shop_featured_until", "")
        await callback.answer("Витрина очищена.")
        current = await db.get_bot_state("shop_featured_label")
        await callback.message.edit_text(
            f"⭐ <b>Витрина</b>\n\nСейчас: {html.escape(current or 'пусто')}.",
            parse_mode="HTML",
            reply_markup=admin_vitrine_keyboard(),
        )
        return
    if key not in VITRINE_KEYS:
        await callback.answer("Нет такого товара.", show_alert=True)
        return
    await db.set_bot_state("shop_featured", key)
    await db.set_bot_state("shop_featured_label", str(ITEM_LABELS[key]))
    await db.set_bot_state("shop_featured_stock", "")
    await db.set_bot_state("shop_featured_until", "")
    await state.set_state(AdminFlow.user_value)
    await state.set_data({"admin_action": "vitrine_limits", "target_user_id": 0, "featured_key": key})
    await callback.answer()
    await callback.message.answer(
        "Тираж и часы двумя числами: <code>8 24</code>\n"
        "8 штук на 24 часа. <code>0 0</code> — без лимита.",
        parse_mode="HTML",
        reply_markup=flow_reply_keyboard(),
    )


@router.callback_query(F.data == "admin:rsvpstake")
async def admin_rsvpstake_begin(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    await state.set_state(AdminFlow.user_value)
    await state.set_data({"admin_action": "rsvpstake", "target_user_id": 0})
    await callback.answer()
    current = await db.get_bot_state("rsvp_stake") or "0"
    await callback.message.answer(
        f"Текущий залог RSVP: {html.escape(current)} 🍪.\nВведите целое число. 0 — бесплатно.",
        parse_mode="HTML",
        reply_markup=flow_reply_keyboard(),
    )


@router.callback_query(F.data == "admin:lottery")
async def admin_lottery_begin(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_POST):
        return
    await state.set_state(AdminFlow.user_value)
    await state.set_data({"admin_action": "lottery_fee", "target_user_id": 0})
    await callback.answer()
    await callback.message.answer(
        "Взнос розыгрыша в 🍪 (1–100). По умолчанию 5.",
        reply_markup=flow_reply_keyboard(),
    )


@router.callback_query(F.data == "admin:eventtitle")
async def admin_eventtitle_begin(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    await state.set_state(AdminFlow.user_value)
    await state.set_data({"admin_action": "eventtitle", "target_user_id": 0})
    await callback.answer()
    current = await db.get_bot_state("event_title")
    await callback.message.answer(
        f"Текущее название: {html.escape(current or 'не задано')}\nВведите новое (2–80 символов).",
        parse_mode="HTML",
        reply_markup=flow_reply_keyboard(),
    )


@router.callback_query(F.data == "admin:features")
async def admin_features(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_FEATURES):
        return
    flags = await db.list_feature_flags()
    await callback.answer()
    await callback.message.edit_text(
        features_panel_text(flags),
        parse_mode="HTML",
        reply_markup=feature_flags_keyboard(flags),
    )


@router.callback_query(F.data == "admin:features:reset")
async def admin_features_reset_ask(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_FEATURES):
        return
    await callback.answer()
    await callback.message.edit_text(
        "♻️ <b>Сброс функций</b>\n\n"
        "Вернуть все переключатели к заводским значениям?\n"
        "Игры, тамагочи, видео-профили и награды за активность — включены.\n"
        "Антифлуд, фильтры ссылок/медиа/стикеров, ночной и рейд-режим — выключены.",
        parse_mode="HTML",
        reply_markup=feature_reset_keyboard(),
    )


@router.callback_query(F.data == "admin:features:reset:yes")
async def admin_features_reset_yes(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_FEATURES):
        return
    await db.reset_feature_flags(callback.from_user.id)
    flags = await db.list_feature_flags()
    await callback.answer("Настройки сброшены.")
    await callback.message.edit_text(
        features_panel_text(flags),
        parse_mode="HTML",
        reply_markup=feature_flags_keyboard(flags),
    )


@router.callback_query(F.data.regexp(r"^admin:feature:[a-z_]+$"))
async def admin_toggle_feature(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message or not await _admin_callback(callback, db, settings, PERM_FEATURES):
        return
    key = callback.data.rsplit(":", 1)[1]
    enabled = await db.toggle_feature(key, callback.from_user.id)
    if enabled is None:
        await callback.answer("Неизвестная функция.", show_alert=True)
        return
    flags = await db.list_feature_flags()
    await callback.answer("Функция включена." if enabled else "Функция выключена.")
    await callback.message.edit_text(
        features_panel_text(flags),
        parse_mode="HTML",
        reply_markup=feature_flags_keyboard(flags),
    )


@router.callback_query(F.data == "admin:morning")
async def admin_morning(callback: CallbackQuery, db: Database, settings: Settings, bot: Bot) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_FEATURES):
        return
    if not await db.feature_enabled("morning_digest"):
        await callback.answer("Утренний пост выключен в функциях.", show_alert=True)
        return
    if not settings.community_chat_id:
        await callback.answer("Чат сообщества не задан.", show_alert=True)
        return
    await callback.answer("Собираю утреннюю сводку…")
    from community_bot.morning import publish_morning_digest

    try:
        pinned = await publish_morning_digest(bot, db, settings, force=True)
    except Exception:
        logger.exception("Не удалось отправить утренний пост вручную")
        await callback.message.answer("Сводку собрать не удалось. Повторю в 9:00.")
        return
    await callback.message.answer(
        "Утренний пост отправлен в чат и закреплён." if pinned else
        "Пост отправлен, но закрепить его не удалось. Проверьте право бота закреплять сообщения.",
    )


@router.callback_query(F.data == "admin:health")
async def admin_health(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    stats = await db.dashboard_stats()
    database_size = db.path.stat().st_size if db.path.exists() else 0
    enabled = sum(int(row["enabled"]) for row in await db.list_feature_flags())
    rows = await db.recent_admin_actions(8)
    minus = sum(1 for row in rows if str(row.get("action") or "") in {"mute", "warn", "kick", "ban"})
    await callback.answer()
    await callback.message.edit_text(
        "📊 <b>Сводка дня</b>\n\n"
        f"База: <b>{database_size / 1024 / 1024:.2f} МБ</b>\n"
        f"Людей: <b>{stats['users']}</b> · питомцев: <b>{stats['pets']}</b>\n"
        f"Очередь: анкет {stats['pending_applications']} · платежей {stats['pending_orders']} · "
        f"тикетов {stats.get('open_tickets', 0)}\n"
        f"Игры сейчас: <b>{stats['active_games']}</b> · функций включено: <b>{enabled}</b>\n"
        f"Последние модерации в журнале: <b>{minus}</b>\n\n"
        "Журнал и инактив — соседние кнопки. Размер базы — только ориентир.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад", callback_data="admin:system")]]
        ),
    )


@router.callback_query(F.data == "admin:audit")
async def admin_audit(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    rows = await db.recent_admin_actions(20)
    await callback.answer()
    await callback.message.edit_text(
        format_audit_log(rows),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="↩️ В панель", callback_data="admin:panel")]]
        ),
    )


@router.callback_query(F.data == "admin:inactive")
async def admin_inactive(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    rows = await db.inactive_users(days=7, limit=40)
    lines = ["💤 <b>Неактивны 7+ дней</b>", ""]
    for row in rows:
        name = row["profile_name"] or row["telegram_name"] or row["username"] or row["user_id"]
        last_seen = str(row["last_message_at"] or "нет сообщений")[:10]
        lines.append(f"• {user_link(int(row['user_id']), str(name))} · {row['message_count']} сообщений · {last_seen}")
    if not rows:
        lines.append("Все известные участники проявляли активность за последние 7 дней.")
    lines.append("\nБот ничего не удаляет автоматически — список только для проверки администратором.")
    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="↩️ В панель", callback_data="admin:panel")]]
        ),
    )


async def _start_application(message: Message, state: FSMContext, db: Database, user: User) -> bool:
    reason = await application_block_reason(db, user.id)
    if reason:
        await state.clear()
        await message.answer(reason)
        return False
    await register_telegram_user(db, user)
    await state.set_state(ApplicationForm.name)
    await state.set_data({"flow_kind": "application"})
    await message.answer(APPLICATION_INTRO, reply_markup=flow_reply_keyboard())
    return True


@router.message(command_or_alias("apply"))
@router.message(F.text == "📝 Заполнить анкету")
async def begin_application(message: Message, state: FSMContext, db: Database) -> None:
    if not message.from_user:
        return
    await _start_application(message, state, db, message.from_user)


@router.callback_query(F.data == "start:apply")
async def begin_application_button(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not callback.message or not callback.from_user:
        return
    await callback.answer()
    await _start_application(callback.message, state, db, callback.from_user)


async def _validate_text(message: Message, minimum: int = 1, maximum: int | None = None) -> str | None:
    text = (message.text or "").strip()
    if len(text) < minimum:
        await message.answer(f"Ответ должен содержать минимум {minimum} символов. Попробуй ещё раз.")
        return None
    if maximum is not None and len(text) > maximum:
        await message.answer(f"Ответ должен содержать не более {maximum} символов. Попробуй ещё раз.")
        return None
    return text


@router.message(ApplicationForm.name)
async def application_name(message: Message, state: FSMContext) -> None:
    if (text := await _validate_text(message, maximum=50)) is None:
        return
    await state.update_data(name=text)
    await state.set_state(ApplicationForm.age)
    await message.answer(APPLICATION_QUESTIONS["age"], reply_markup=flow_reply_keyboard())


@router.message(ApplicationForm.age)
async def application_age(message: Message, state: FSMContext) -> None:
    if (text := await _validate_text(message, maximum=50)) is None:
        return
    await state.update_data(age=text)
    await state.set_state(ApplicationForm.referral)
    await message.answer(APPLICATION_QUESTIONS["referral"], reply_markup=flow_reply_keyboard())


@router.message(ApplicationForm.referral)
async def application_referral(message: Message, state: FSMContext) -> None:
    if (text := await _validate_text(message, maximum=100)) is None:
        return
    await state.update_data(referral=text)
    await state.set_state(ApplicationForm.expectations)
    await message.answer(APPLICATION_QUESTIONS["expectations"], reply_markup=flow_reply_keyboard())


@router.message(ApplicationForm.expectations)
async def application_expectations(message: Message, state: FSMContext) -> None:
    if (text := await _validate_text(message)) is None:
        return
    await state.update_data(expectations=text)
    await state.set_state(ApplicationForm.bio)
    await message.answer(APPLICATION_QUESTIONS["bio"], reply_markup=flow_reply_keyboard())


@router.message(ApplicationForm.bio)
async def application_bio(message: Message, state: FSMContext) -> None:
    if (text := await _validate_text(message)) is None:
        return
    await state.update_data(bio=text)
    await state.set_state(ApplicationForm.interview)
    await message.answer(APPLICATION_QUESTIONS["interview"], reply_markup=YES_NO_KEYBOARD)


def _application_text(application_id: int, user_id: int, username: str | None, answers: dict[str, Any]) -> str:
    who = f"@{html.escape(username)}" if username else user_link(user_id, answers["name"])
    return (
        f"📝 <b>Новая анкета №{application_id}</b>\n"
        f"Пользователь: {who} (<code>{user_id}</code>)\n\n"
        f"<b>Имя:</b> {html.escape(answers['name'])}\n"
        f"<b>Возраст:</b> {html.escape(answers['age'])}\n"
        f"<b>Откуда узнал:</b> {html.escape(answers['referral'])}\n\n"
        f"<b>Ожидания:</b>\n{html.escape(answers['expectations'])}\n\n"
        f"<b>О себе:</b>\n{html.escape(answers['bio'])}\n\n"
        "<b>Онлайн-интервью:</b> да"
    )


@router.callback_query(ApplicationForm.interview, F.data.startswith("application:interview:"))
async def finish_application(
    callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings, bot: Bot
) -> None:
    if not callback.from_user or not callback.data or not callback.message:
        return
    await callback.answer()
    if callback.data.endswith(":no"):
        await state.clear()
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(APPLICATION_REJECTED_INTERVIEW)
        await restore_private_menu(callback.message, db, settings)
        return
    answers = await state.get_data()
    application_id = await db.create_application(callback.from_user.id, answers)
    if not application_id:
        await state.clear()
        reason = await application_block_reason(db, callback.from_user.id) or "Анкета уже есть."
        await callback.message.answer(reason)
        await restore_private_menu(callback.message, db, settings)
        return
    text = _application_text(application_id, callback.from_user.id, callback.from_user.username, answers)
    for reviewer_id in settings.reviewers:
        await safe_send(
            bot,
            reviewer_id,
            text,
            parse_mode="HTML",
            reply_markup=application_review_keyboard(application_id),
        )
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"✅ Анкета №{application_id} отправлена на проверку. Решение придёт сюда.",
    )
    await restore_private_menu(callback.message, db, settings)


async def _reviewer(callback: CallbackQuery, db: Database, settings: Settings) -> bool:
    if await has_permission(db, settings, callback.from_user.id, PERM_APPLICATIONS):
        return True
    await callback.answer("Недостаточно прав.", show_alert=True)
    return False


async def _notify_application_decision(
    bot: Bot,
    db: Database,
    settings: Settings,
    application_id: int,
    moderator_id: int,
    status: str,
    reason: str | None,
) -> None:
    application = await db.get_application(application_id)
    if not application:
        return
    approved = status == "approved"
    result = "✅ Заявка одобрена" if approved else "❌ Заявка отклонена"
    reason_text = f"\nПричина: {html.escape(reason)}" if reason else ""
    invite = ""
    if approved and settings.community_invite_url:
        invite = (
            "\n\nДобро пожаловать в НОРУ:\n"
            f'<a href="{html.escape(settings.community_invite_url, quote=True)}">'
            f"{html.escape(settings.community_invite_url)}</a>"
        )
    is_staff = await has_permission(db, settings, int(application["user_id"]), PERM_ADMIN_PANEL)
    await safe_send(
        bot,
        int(application["user_id"]),
        f"{result}.{reason_text}{invite}",
        parse_mode="HTML",
        reply_markup=main_private_keyboard(is_staff),
    )
    report = f"{result}: анкета №{application_id}, решение принял <code>{moderator_id}</code>.{reason_text}"
    for reviewer_id in settings.reviewers - {moderator_id, int(application["user_id"])}:
        await safe_send(bot, reviewer_id, report, parse_mode="HTML")


@router.callback_query(F.data.startswith("application:approve:"))
async def approve_application(callback: CallbackQuery, db: Database, settings: Settings, bot: Bot) -> None:
    if not callback.data or not await _reviewer(callback, db, settings):
        return
    application_id = int(callback.data.rsplit(":", 1)[1])
    if not await db.decide_application(application_id, callback.from_user.id, "approved", None):
        await callback.answer("Эта анкета уже рассмотрена.", show_alert=True)
        return
    await callback.answer("Анкета одобрена.")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
    application = await db.get_application(application_id)
    await db.log_admin_action(
        callback.from_user.id,
        "application_approved",
        str((application or {}).get("user_id") or ""),
        f"анкета №{application_id}",
        actor_name=callback.from_user.full_name,
        target_name=person_label(application, str((application or {}).get("user_id") or "")),
        reason="одобрение анкеты",
    )
    await _notify_application_decision(bot, db, settings, application_id, callback.from_user.id, "approved", None)


@router.callback_query(F.data.startswith("application:reject:"))
async def reject_application(callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    if not callback.data or not await _reviewer(callback, db, settings):
        return
    application_id = int(callback.data.rsplit(":", 1)[1])
    application = await db.get_application(application_id)
    if not application or application["status"] != "pending":
        await callback.answer("Эта анкета уже рассмотрена.", show_alert=True)
        return
    await state.set_state(ModeratorReply.rejection_reason)
    await state.set_data({"application_id": application_id})
    await callback.answer()
    if callback.message:
        await callback.message.answer("Напишите причину отказа одним сообщением.", reply_markup=flow_reply_keyboard())


@router.message(ModeratorReply.rejection_reason)
async def rejection_reason(message: Message, state: FSMContext, db: Database, settings: Settings, bot: Bot) -> None:
    if not message.from_user or not message.text:
        await message.answer("Нужна текстовая причина отказа.")
        return
    data = await state.get_data()
    application_id = int(data["application_id"])
    reason = message.text.strip()[:1000]
    if not await db.decide_application(application_id, message.from_user.id, "rejected", reason):
        await message.answer("Эта анкета уже рассмотрена.")
        await state.clear()
        return
    await state.clear()
    await message.answer("Анкета отклонена, пользователь уведомлён.")
    application = await db.get_application(application_id)
    await db.log_admin_action(
        message.from_user.id,
        "application_rejected",
        str((application or {}).get("user_id") or ""),
        f"анкета №{application_id}",
        actor_name=message.from_user.full_name,
        target_name=person_label(application, str((application or {}).get("user_id") or "")),
        reason=reason,
    )
    await _notify_application_decision(bot, db, settings, application_id, message.from_user.id, "rejected", reason)


async def _send_pending_applications(message: Message, db: Database) -> None:
    rows = await db.pending_applications()
    if not rows:
        await message.answer("Новых анкет нет.")
        return
    await message.answer(
        "Новые анкеты:\n"
        + "\n".join(
            f"№{row['id']} — @{row['username']}" if row["username"] else f"№{row['id']} — ID {row['user_id']}"
            for row in rows
        )
    )
    for row in rows:
        application = await db.get_application(int(row["id"]))
        assert application
        await message.answer(
            _application_text(
                int(application["id"]),
                int(application["user_id"]),
                application["username"],
                application["answers"],
            ),
            parse_mode="HTML",
            reply_markup=application_review_keyboard(int(application["id"])),
        )


@router.message(command_or_alias("applications"))
async def applications_list(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user or not await has_permission(db, settings, message.from_user.id, PERM_APPLICATIONS):
        return
    await _send_pending_applications(message, db)


@router.callback_query(F.data == "admin:applications")
async def admin_applications(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_APPLICATIONS):
        return
    await callback.answer()
    await _send_pending_applications(callback.message, db)


@router.callback_query(F.data == "admin:orders")
async def admin_cookie_orders(callback: CallbackQuery, db: Database, settings: Settings, bot: Bot) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_PAYMENTS):
        return
    orders = await db.pending_cookie_orders()
    await callback.answer()
    if not orders:
        await callback.message.answer("Новых платежей на проверке нет.")
        return
    await callback.message.answer(f"💳 Платежей на проверке: {len(orders)}.")
    for order in orders:
        name = order["profile_name"] or order["telegram_name"] or order["username"] or order["user_id"]
        caption = (
            f"💳 <b>Заказ печенек №{order['id']}</b>\n"
            f"Пользователь: {user_link(int(order['user_id']), str(name))}\n"
            f"Пакет: <b>{order['amount']} 🍪</b> · сумма <b>{order['rubles']} ₽</b>"
        )
        try:
            if order["receipt_media_type"] == "photo":
                await bot.send_photo(
                    callback.from_user.id,
                    order["receipt_file_id"],
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=cookie_order_review_keyboard(int(order["id"])),
                )
            else:
                await bot.send_document(
                    callback.from_user.id,
                    order["receipt_file_id"],
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=cookie_order_review_keyboard(int(order["id"])),
                )
        except TelegramBadRequest:
            await callback.message.answer(f"Не удалось открыть вложение заказа №{order['id']}.")


@router.callback_query(F.data == "admin:roles")
async def admin_roles(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    can_assign = await has_permission(db, settings, callback.from_user.id, PERM_ROLES_ASSIGN)
    can_edit = await has_permission(db, settings, callback.from_user.id, PERM_ROLES_EDIT)
    if not can_assign and not can_edit:
        await callback.answer("Недостаточно прав.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        "👥 <b>Права и роли</b>\n\nСоздавайте роли, включайте нужные права тумблерами и назначайте их людям.",
        parse_mode="HTML",
        reply_markup=roles_hub_keyboard(can_edit),
    )


@router.callback_query(F.data == "admin:roleusers")
async def admin_role_users(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_ROLES_ASSIGN):
        return
    users = await db.list_users()
    await callback.answer()
    await callback.message.edit_text(
        "👥 <b>Назначить роль человеку</b>\n\nВыберите пользователя:",
        parse_mode="HTML",
        reply_markup=role_users_keyboard(users),
    )


@router.callback_query(F.data == "admin:rolelist")
async def admin_role_list(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    roles = await db.list_staff_roles()
    await callback.answer()
    await callback.message.edit_text(
        "📜 <b>Роли</b>\n\nНажмите роль, чтобы править права и ранг.",
        parse_mode="HTML",
        reply_markup=staff_roles_keyboard(roles),
    )


@router.callback_query(F.data == "admin:rolenew")
async def admin_role_new(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_ROLES_EDIT):
        return
    await state.set_state(AdminFlow.role_name)
    await callback.answer()
    await callback.message.answer(
        "Напишите название новой роли (до 40 символов). Права потом включите тумблерами.",
        reply_markup=flow_reply_keyboard(),
    )


@router.message(AdminFlow.role_name)
async def admin_role_create_name(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not message.from_user or not await has_permission(db, settings, message.from_user.id, PERM_ROLES_EDIT):
        await state.clear()
        return
    name = (message.text or "").strip()
    if not 2 <= len(name) <= 40:
        await message.answer("Название — от 2 до 40 символов.")
        return
    slug = slugify_role(name)
    existing = await db.get_staff_role(slug)
    suffix = 2
    while existing:
        slug = f"{slugify_role(name)[:20]}_{suffix}"
        existing = await db.get_staff_role(slug)
        suffix += 1
    actor_rank = await rank_of_user(db, settings, message.from_user.id)
    rank = min(50, max(1, actor_rank - 1))
    if not await db.create_staff_role(slug, name, rank, []):
        await message.answer("Не удалось создать роль, попробуйте другое имя.")
        return
    await state.clear()
    await db.log_admin_action(message.from_user.id, "role_create", slug, name)
    role = await db.get_staff_role(slug)
    assert role
    await message.answer(
        f"✅ Роль <b>{html.escape(name)}</b> создана (ранг {rank}). Включите нужные права:",
        parse_mode="HTML",
        reply_markup=staff_role_view_keyboard(role, True),
    )


async def _show_role_view(callback: CallbackQuery, db: Database, settings: Settings, slug: str) -> None:
    role = await db.get_staff_role(slug)
    if not role or not callback.message:
        await callback.answer("Роль не найдена.", show_alert=True)
        return
    can_edit = await has_permission(db, settings, callback.from_user.id, PERM_ROLES_EDIT)
    perms = ", ".join(str(item) for item in role["permissions"]) or "нет"
    await callback.message.edit_text(
        f"💠 <b>{html.escape(str(role['name']))}</b>\n"
        f"Код: <code>{html.escape(slug)}</code>\n"
        f"Ранг: <b>{role['rank']}</b> · {'системная' if int(role['is_system']) else 'своя'}\n"
        f"Права: <code>{html.escape(perms)}</code>\n\n"
        "Нажимайте строки, чтобы включать и выключать права.",
        parse_mode="HTML",
        reply_markup=staff_role_view_keyboard(role, can_edit),
    )


@router.callback_query(F.data.startswith("admin:roleview:"))
async def admin_role_view(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not await _admin_callback(callback, db, settings):
        return
    await callback.answer()
    await _show_role_view(callback, db, settings, callback.data.rsplit(":", 1)[1])


@router.callback_query(F.data.startswith("admin:roletog:"))
async def admin_role_toggle(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not await _admin_callback(callback, db, settings, PERM_ROLES_EDIT):
        return
    _, _, slug, perm = callback.data.split(":", 3)
    role = await db.get_staff_role(slug)
    if not role or slug == "owner":
        await callback.answer("Эту роль нельзя менять.", show_alert=True)
        return
    perms = list(role["permissions"])
    if perm in perms:
        perms.remove(perm)
    else:
        perms.append(perm)
    await db.update_staff_role(slug, permissions=perms)
    await db.log_admin_action(callback.from_user.id, "role_perm", slug, perm)
    await callback.answer("Право обновлено.")
    await _show_role_view(callback, db, settings, slug)


@router.callback_query(F.data.startswith("admin:rolerank:"))
async def admin_role_rank(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not await _admin_callback(callback, db, settings, PERM_ROLES_EDIT):
        return
    _, _, slug, delta_raw = callback.data.split(":")
    role = await db.get_staff_role(slug)
    if not role or slug == "owner":
        await callback.answer("Ранг этой роли фиксирован.", show_alert=True)
        return
    delta = int(delta_raw)
    actor_rank = await rank_of_user(db, settings, callback.from_user.id)
    ceiling = 99 if settings.is_owner(callback.from_user.id) else actor_rank - 1
    new_rank = max(0, min(ceiling, int(role["rank"]) + delta))
    await db.update_staff_role(slug, rank=new_rank)
    await callback.answer(f"Ранг: {new_rank}")
    await _show_role_view(callback, db, settings, slug)


@router.callback_query(F.data.startswith("admin:roledel:"))
async def admin_role_delete(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not await _admin_callback(callback, db, settings, PERM_ROLES_EDIT):
        return
    slug = callback.data.rsplit(":", 1)[1]
    if not await db.delete_staff_role(slug):
        await callback.answer("Системную роль удалить нельзя.", show_alert=True)
        return
    await db.log_admin_action(callback.from_user.id, "role_delete", slug)
    await callback.answer("Роль удалена, людям назначен участник.")
    roles = await db.list_staff_roles()
    if callback.message:
        await callback.message.edit_text(
            "📜 <b>Роли</b>",
            parse_mode="HTML",
            reply_markup=staff_roles_keyboard(roles),
        )


@router.callback_query(F.data.startswith("admin:user:"))
async def admin_role_user(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    actor_role = await _admin_callback(callback, db, settings, PERM_ROLES_ASSIGN)
    if not callback.data or not callback.message or not actor_role:
        return
    user_id = int(callback.data.rsplit(":", 1)[1])
    user = await db.get_user(user_id)
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    name = user["profile_name"] or user["telegram_name"] or user["username"] or f"ID {user_id}"
    username = f"@{user['username']}" if user["username"] else "без юзернейма"
    title = await role_title(db, str(user["role"]))
    roles = await db.list_staff_roles()
    actor_rank = await rank_of_user(db, settings, callback.from_user.id)
    await callback.answer()
    await callback.message.edit_text(
        f"👤 <b>{html.escape(str(name))}</b>\n"
        f"{html.escape(username)} · <code>{user_id}</code>\n"
        f"Текущая роль: <b>{html.escape(title)}</b>\n\n"
        "Выберите новую роль:",
        parse_mode="HTML",
        reply_markup=role_selection_keyboard(
            user_id,
            roles,
            actor_rank,
            settings.is_owner(callback.from_user.id),
        ),
    )


@router.callback_query(F.data.startswith("admin:setrole:"))
async def admin_set_role(callback: CallbackQuery, db: Database, settings: Settings, bot: Bot) -> None:
    actor_role = await _admin_callback(callback, db, settings, PERM_ROLES_ASSIGN)
    if not callback.data or not callback.message or not actor_role:
        return
    _, _, user_id_raw, new_role = callback.data.split(":")
    user_id = int(user_id_raw)
    target = await db.get_user(user_id)
    role = await db.get_staff_role(new_role)
    if not target or not role or new_role == "owner":
        await callback.answer("Некорректный пользователь или роль.", show_alert=True)
        return
    if settings.is_owner(user_id) or user_id == callback.from_user.id:
        await callback.answer("Эту роль нельзя изменить здесь.", show_alert=True)
        return
    if not await can_manage_user(db, settings, callback.from_user.id, user_id):
        await callback.answer("Нельзя менять роль равного или выше.", show_alert=True)
        return
    actor_rank = await rank_of_user(db, settings, callback.from_user.id)
    if not settings.is_owner(callback.from_user.id) and int(role["rank"]) >= actor_rank:
        await callback.answer("Нельзя выдать роль не ниже своей.", show_alert=True)
        return
    await db.set_role(user_id, new_role)
    label = str(role["name"])
    await callback.answer(f"Новая роль: {label}.")
    roles = await db.list_staff_roles()
    await callback.message.edit_text(
        f"✅ Пользователю <code>{user_id}</code> назначена роль <b>{html.escape(label)}</b>.",
        parse_mode="HTML",
        reply_markup=role_selection_keyboard(
            user_id,
            roles,
            actor_rank,
            settings.is_owner(callback.from_user.id),
        ),
    )
    await safe_send(
        bot,
        user_id,
        f"Ваша роль изменена: <b>{html.escape(label)}</b>.",
        parse_mode="HTML",
        reply_markup=main_private_keyboard(),
    )


async def _can_admin_manage(actor_id: int, target_id: int, db: Database, settings: Settings) -> bool:
    return await can_manage_user(db, settings, actor_id, target_id)


@router.callback_query(F.data == "admin:users")
async def admin_users(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    if not (
        await has_permission(db, settings, callback.from_user.id, PERM_USERS_EDIT)
        or await has_permission(db, settings, callback.from_user.id, PERM_USERS_COOKIES)
    ):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return
    users = await db.list_users(limit=100)
    await callback.answer()
    await callback.message.edit_text(
        "👤 <b>Профили и балансы</b>\n\nВыберите пользователя:",
        parse_mode="HTML",
        reply_markup=admin_users_keyboard(users),
    )


@router.callback_query(F.data.startswith("admin:manage:"))
async def admin_manage_user(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    actor_role = await _admin_callback(callback, db, settings)
    if not callback.data or not callback.message or not actor_role:
        return
    user_id = int(callback.data.rsplit(":", 1)[1])
    user = await db.get_user(user_id)
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    if not await _can_admin_manage(callback.from_user.id, user_id, db, settings):
        await callback.answer("Нельзя редактировать пользователя с равной или более высокой ролью.", show_alert=True)
        return
    name = user["profile_name"] or user["telegram_name"] or user["username"] or f"ID {user_id}"
    note = str(user.get("moderator_note") or "").strip() or "нет"
    await callback.answer()
    await callback.message.edit_text(
        f"👤 <b>{html.escape(str(name))}</b> · <code>{user_id}</code>\n"
        f"Роль: {html.escape(await role_title(db, str(user['role'])))}\n"
        f"Репутация: <b>{user['reputation']}</b> · щиты {int(user.get('hate_shields') or 0)}\n"
        f"Титул: {html.escape(str(user.get('profile_title') or 'нет'))}\n"
        f"Возраст: {user['age'] or 'не указан'}\n"
        f"Баланс: <b>{user['cookies']} 🍪</b>\n"
        f"Предупреждения: <b>{user['warnings']}</b>\n"
        f"Заметка: {html.escape(note)}\n\n"
        "Что изменить?",
        parse_mode="HTML",
        reply_markup=admin_user_keyboard(user_id),
    )


@router.callback_query(F.data.startswith("admin:edit:"))
async def admin_begin_user_edit(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    actor_role = await _admin_callback(callback, db, settings)
    if not callback.data or not callback.message or not actor_role:
        return
    _, _, action, raw_user_id = callback.data.split(":")
    user_id = int(raw_user_id)
    if not await db.get_user(user_id) or not await _can_admin_manage(callback.from_user.id, user_id, db, settings):
        await callback.answer("Редактирование этого пользователя недоступно.", show_alert=True)
        return
    prompts = {
        "cookies": "Введите точный новый баланс от 0 до 1 000 000.",
        "add_cookies": "Сколько печенек начислить? От 1 до 1 000 000.",
        "name": "Введите новое имя (до 50 символов).",
        "age": "Введите новый возраст числом от 14 до 120.",
        "avatar": "Отправьте новую фотографию или видео профиля.",
        "warnings": "Введите точное количество предупреждений, 0 или больше.",
        "rep": "Введите новую репутацию числом от -20 до 100.",
        "note": "Введите заметку модератора (до 400 символов). «-» чтобы стереть.",
    }
    if action not in prompts:
        await callback.answer("Неизвестное действие.", show_alert=True)
        return
    await state.set_state(AdminFlow.user_value)
    await state.set_data({"admin_action": action, "target_user_id": user_id})
    await callback.answer()
    await callback.message.answer(prompts[action], reply_markup=flow_reply_keyboard())


@router.message(AdminFlow.user_value)
async def admin_save_user_edit(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    if not message.from_user:
        return
    actor_role = await _admin_role(message.from_user.id, db, settings)
    data = await state.get_data()
    user_id = int(data.get("target_user_id") or 0)
    action = str(data["admin_action"])
    if action == "search":
        if not actor_role:
            await state.clear()
            await message.answer("Недостаточно прав.")
            return
        query = (message.text or "").strip()
        if len(query) < 2 and not query.isdigit():
            await message.answer("Введите имя, @username или Telegram ID.")
            return
        users = await db.search_users(query)
        await state.clear()
        if not users:
            await message.answer("Никого не нашла.")
            return
        await message.answer(
            f"🔎 Найдено: {len(users)}",
            reply_markup=admin_users_keyboard(users),
        )
        return
    if action == "eventtitle":
        if not actor_role:
            await state.clear()
            await message.answer("Недостаточно прав.")
            return
        title = (message.text or "").strip()
        if not 2 <= len(title) <= 80:
            await message.answer("Название от 2 до 80 символов.")
            return
        await db.set_bot_state("event_title", title)
        await state.clear()
        await message.answer(f"✅ Мероприятие теперь: {html.escape(title)}", parse_mode="HTML")
        return
    if action == "stopword_add":
        if not actor_role or not await has_permission(db, settings, message.from_user.id, PERM_FEATURES):
            await state.clear()
            await message.answer("Недостаточно прав.")
            return
        word = (message.text or "").strip()
        if not await db.add_stop_word(word, message.from_user.id):
            await message.answer("Слово не принято (1–40 символов, без дублей).")
            return
        await state.clear()
        await message.answer(f"Стоп-слово «{html.escape(word)}» добавлено.", parse_mode="HTML")
        return
    if action == "vitrine_limits":
        if not actor_role:
            await state.clear()
            await message.answer("Недостаточно прав.")
            return
        parts = (message.text or "").split()
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            await message.answer("Два числа: тираж и часы. Пример: 8 24. 0 0 — без лимита.")
            return
        stock, hours = int(parts[0]), int(parts[1])
        await db.set_bot_state("shop_featured_stock", str(stock) if stock else "")
        if hours:
            until = (datetime.now(UTC) + timedelta(hours=hours)).isoformat()
            await db.set_bot_state("shop_featured_until", until)
        else:
            await db.set_bot_state("shop_featured_until", "")
        await state.clear()
        label = await db.get_bot_state("shop_featured_label")
        extra = []
        if stock:
            extra.append(f"тираж {stock}")
        if hours:
            extra.append(f"{hours} ч")
        suffix = f" ({', '.join(extra)})" if extra else " без лимита"
        await message.answer(f"⭐ Витрина: {html.escape(label or '')}{suffix}.", parse_mode="HTML")
        from community_bot.notify import fanout

        await fanout(
            message.bot,
            db,
            "shop",
            f"⭐ Новая витрина: {html.escape(label or '')}{suffix}.",
        )
        return
    if action == "rsvpstake":
        if not actor_role:
            await state.clear()
            await message.answer("Недостаточно прав.")
            return
        raw = (message.text or "").strip()
        if not raw.isdigit():
            await message.answer("Целое число 🍪. 0 — без залога.")
            return
        await db.set_bot_state("rsvp_stake", raw)
        await state.clear()
        await message.answer(f"Залог RSVP: {raw} 🍪.")
        return
    if action == "lottery_fee":
        if not actor_role or not await has_permission(db, settings, message.from_user.id, PERM_POST):
            await state.clear()
            await message.answer("Недостаточно прав.")
            return
        if not settings.community_chat_id:
            await state.clear()
            await message.answer("ID чата сообщества не настроен.")
            return
        raw = (message.text or "").strip()
        fee = int(raw) if raw.isdigit() else 5
        lottery_id, error = await db.create_lottery(settings.community_chat_id, message.from_user.id, fee)
        await state.clear()
        if not lottery_id:
            await message.answer(error)
            return
        from community_bot.ephemeral import keep_in_chat
        from community_bot.routers.life import lottery_markup

        with keep_in_chat():
            await bot.send_message(
                settings.community_chat_id,
                f"🎲 <b>Розыгрыш</b>\nВзнос {fee} 🍪. Кто в котле — жмёт кнопку. Итог: «розыгрыш итог».",
                parse_mode="HTML",
                reply_markup=lottery_markup(lottery_id),
            )
        await message.answer("Розыгрыш опубликован в чат.")
        return
    if not actor_role or not await _can_admin_manage(message.from_user.id, user_id, db, settings):
        await state.clear()
        await message.answer("Недостаточно прав для изменения этого пользователя.")
        return
    if action == "avatar":
        if not message.photo and not message.video:
            await message.answer("Нужно отправить фотографию или видео.")
            return
        if message.video:
            await db.update_profile(user_id, "avatar_file_id", message.video.file_id)
            await db.update_profile(user_id, "avatar_media_type", "video")
        else:
            await db.update_profile(user_id, "avatar_file_id", message.photo[-1].file_id)
            await db.update_profile(user_id, "avatar_media_type", "photo")
        result = "Аватар обновлён."
    elif action == "name":
        value = (message.text or "").strip()
        if not 1 <= len(value) <= 50:
            await message.answer("Имя должно содержать от 1 до 50 символов.")
            return
        await db.update_profile(user_id, "profile_name", value)
        result = "Имя обновлено."
    elif action == "age":
        if not message.text or not message.text.isdigit() or not 14 <= int(message.text) <= 120:
            await message.answer("Возраст должен быть числом от 14 до 120.")
            return
        await db.update_profile(user_id, "age", int(message.text))
        result = "Возраст обновлён."
    elif action == "warnings":
        if not message.text or not message.text.isdigit():
            await message.answer("Введите целое число 0 или больше.")
            return
        await db.set_warnings(user_id, int(message.text))
        result = f"Количество предупреждений установлено: {int(message.text)}."
    elif action == "rep":
        raw = (message.text or "").strip()
        if not raw.lstrip("-").isdigit():
            await message.answer("Репутация — целое число от -20 до 100.")
            return
        value = int(raw)
        if not -20 <= value <= 100:
            await message.answer("Репутация должна быть от -20 до 100.")
            return
        await db.execute(
            "UPDATE users SET reputation = ?, updated_at = ? WHERE user_id = ?",
            (value, utcnow(), user_id),
        )
        result = f"Репутация установлена: {value}."
    elif action == "note":
        value = (message.text or "").strip()
        if value == "-":
            value = ""
        if len(value) > 400:
            await message.answer("Заметка до 400 символов.")
            return
        await db.update_profile(user_id, "moderator_note", value)
        result = "Заметка обновлена."
    elif action == "cookies":
        if not message.text or not message.text.isdigit() or int(message.text) > 1_000_000:
            await message.answer("Баланс должен быть числом от 0 до 1 000 000.")
            return
        await db.set_cookies(user_id, int(message.text), message.from_user.id)
        result = f"Баланс установлен: {int(message.text)} 🍪."
    else:
        if not message.text or not message.text.isdigit() or not 1 <= int(message.text) <= 1_000_000:
            await message.answer("Количество должно быть числом от 1 до 1 000 000.")
            return
        amount = int(message.text)
        await db.add_cookies(user_id, amount, "admin", f"by:{message.from_user.id}")
        result = f"Начислено {amount} 🍪."
    await db.log_admin_action(message.from_user.id, f"user_{action}", str(user_id), result)
    await state.clear()
    await message.answer(f"✅ {result}")


def _open_chat_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_invite_users=True,
    )


@router.callback_query(F.data.startswith("admin:chat:"))
async def admin_toggle_chat(callback: CallbackQuery, db: Database, settings: Settings, bot: Bot) -> None:
    if not callback.data or not await _admin_callback(callback, db, settings, PERM_CHAT_LOCK):
        return
    if not settings.community_chat_id:
        await callback.answer("ID чата сообщества не настроен.", show_alert=True)
        return
    action = callback.data.rsplit(":", 1)[1]
    permissions = ChatPermissions(can_send_messages=False) if action == "mute" else _open_chat_permissions()
    try:
        await bot.set_chat_permissions(settings.community_chat_id, permissions)
    except TelegramBadRequest as error:
        await callback.answer(f"Telegram отклонил действие: {error.message}", show_alert=True)
        return
    await callback.answer("Чат закрыт для участников." if action == "mute" else "Чат снова открыт.", show_alert=True)
    await db.log_admin_action(callback.from_user.id, f"chat_{action}", str(settings.community_chat_id))
    await bot.send_message(
        settings.community_chat_id,
        "🔇 Администрация временно закрыла чат." if action == "mute" else "🔊 Администрация снова открыла чат.",
    )


@router.callback_query(F.data == "admin:broadcast")
async def admin_begin_broadcast(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_BROADCAST):
        return
    await state.set_state(AdminFlow.broadcast_private)
    await callback.answer()
    await callback.message.answer(
        "Отправьте сообщение или вложение для рассылки всем пользователям бота.",
        reply_markup=flow_reply_keyboard(),
    )


@router.message(AdminFlow.broadcast_private)
async def admin_send_broadcast(message: Message, state: FSMContext, db: Database, settings: Settings, bot: Bot) -> None:
    if not message.from_user or not await _admin_role(message.from_user.id, db, settings):
        await state.clear()
        return
    delivered = 0
    failed = 0
    for user in await db.list_all_users():
        try:
            await bot.copy_message(int(user["user_id"]), message.chat.id, message.message_id)
            delivered += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
        await asyncio.sleep(0.05)
    await state.clear()
    await db.log_admin_action(
        message.from_user.id,
        "broadcast_private",
        "all",
        f"delivered:{delivered}:failed:{failed}",
    )
    await message.answer(f"✅ Рассылка завершена. Доставлено: {delivered}, недоступно: {failed}.")


@router.callback_query(F.data == "admin:post")
async def admin_begin_community_post(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_POST):
        return
    from community_bot.posting import templates_keyboard

    await state.set_state(AdminFlow.post_pick)
    await state.set_data(
        {
            "post_template": "announce",
            "post_body": "",
            "post_media_type": None,
            "post_file_id": None,
            "post_buttons": [],
            "post_poll": None,
        }
    )
    await callback.answer()
    await callback.message.answer(
        "📢 <b>Студия поста в сообщество</b>\n\n"
        "Выберите шаблон. Жирный, курсив и ссылки из вашего сообщения сохранятся.\n"
        "После текста можно добавить медиа, кнопки-ссылки и голосование Telegram.",
        parse_mode="HTML",
        reply_markup=templates_keyboard(),
    )


@router.callback_query(F.data == "post:cancel")
async def admin_post_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Отменено")
    if callback.message:
        await callback.message.answer("Публикация отменена.")


@router.callback_query(F.data.startswith("post:tpl:"))
async def admin_post_pick_template(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_POST):
        return
    from community_bot.posting import TEMPLATES, skip_keyboard

    template_id = callback.data.rsplit(":", 1)[1]
    if template_id not in TEMPLATES:
        await callback.answer("Нет такого шаблона.", show_alert=True)
        return
    await state.set_state(AdminFlow.post_body)
    await state.update_data(post_template=template_id)
    meta = TEMPLATES[template_id]
    await callback.answer()
    await callback.message.answer(
        f"{meta['title']}\n{meta['hint']}\n\n"
        "Пришлите текст одним сообщением. Можно выделить жирным или курсивом в Telegram — теги сохранятся.",
        reply_markup=skip_keyboard("body") if template_id == "html" else flow_reply_keyboard(),
    )


@router.message(AdminFlow.post_body)
async def admin_post_body(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not message.from_user or not await _admin_role(message.from_user.id, db, settings):
        await state.clear()
        return
    from community_bot.posting import media_from_studio_message, skip_keyboard

    body = (message.html_text or message.text or message.caption or "").strip()
    media_type, file_id = media_from_studio_message(message)
    if not body and not media_type:
        await message.answer("Нужен текст или вложение.")
        return
    await state.update_data(post_body=body, post_media_type=media_type, post_file_id=file_id)
    if media_type:
        await state.set_state(AdminFlow.post_buttons)
        await message.answer(
            "Кнопки: каждая с новой строки\n"
            "<code>Текст | https://ссылка | green</code>\n"
            "Цвет: green, blue, red, gray. Или напишите «нет».",
            parse_mode="HTML",
            reply_markup=skip_keyboard("buttons"),
        )
        return
    await state.set_state(AdminFlow.post_media)
    await message.answer(
        "Прикрепите фото, видео, GIF или файл — или нажмите «Пропустить».",
        reply_markup=skip_keyboard("media"),
    )


@router.callback_query(F.data == "post:skip:body")
async def admin_post_skip_body(callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_POST):
        return
    from community_bot.posting import skip_keyboard

    await state.update_data(post_body="")
    await state.set_state(AdminFlow.post_media)
    await callback.answer()
    await callback.message.answer("Медиа или «Пропустить».", reply_markup=skip_keyboard("media"))


@router.message(AdminFlow.post_media)
async def admin_post_media(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not message.from_user or not await _admin_role(message.from_user.id, db, settings):
        await state.clear()
        return
    from community_bot.posting import is_skip_text, media_from_studio_message, skip_keyboard

    if is_skip_text(message.text):
        await state.update_data(post_media_type=None, post_file_id=None)
    else:
        media_type, file_id = media_from_studio_message(message)
        if not media_type:
            await message.answer("Пришлите медиа или «нет».")
            return
        await state.update_data(post_media_type=media_type, post_file_id=file_id)
    await state.set_state(AdminFlow.post_buttons)
    await message.answer(
        "Кнопки: <code>Текст | https://ссылка | green</code> — по одной в строке. Или «нет».",
        parse_mode="HTML",
        reply_markup=skip_keyboard("buttons"),
    )


@router.callback_query(F.data == "post:skip:media")
async def admin_post_skip_media(callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_POST):
        return
    from community_bot.posting import skip_keyboard

    await state.update_data(post_media_type=None, post_file_id=None)
    await state.set_state(AdminFlow.post_buttons)
    await callback.answer()
    await callback.message.answer(
        "Кнопки: <code>Текст | https://ссылка | green</code> — по одной в строке. Или «нет».",
        parse_mode="HTML",
        reply_markup=skip_keyboard("buttons"),
    )


async def _ask_post_poll(message: Message, state: FSMContext) -> None:
    from community_bot.posting import poll_ask_keyboard

    await state.set_state(AdminFlow.post_poll_ask)
    await message.answer(
        "📊 Добавить голосование Telegram к этому посту?\n"
        "Опрос уйдёт отдельным сообщением сразу после публикации (кнопки-ссылки на опрос не ставятся).",
        reply_markup=poll_ask_keyboard(),
    )


async def _show_post_preview(message: Message, data: dict[str, Any], bot: Bot) -> None:
    from community_bot.posting import (
        compose_post_markup,
        poll_preview_block,
        preview_keyboard,
        render_post,
        rsvp_preview_block,
        send_studio_post,
    )

    html_text = render_post(str(data.get("post_template") or "announce"), str(data.get("post_body") or ""))
    html_text = (
        html_text + poll_preview_block(data.get("post_poll")) + rsvp_preview_block(data.get("post_rsvp"))
    ).strip() or " "
    markup = compose_post_markup(list(data.get("post_buttons") or []), data.get("post_rsvp"))
    preview = preview_keyboard()
    if markup:
        try:
            await send_studio_post(
                bot,
                message.chat.id,
                html_text or " ",
                data.get("post_media_type"),
                data.get("post_file_id"),
                markup,
            )
        except TelegramBadRequest:
            await message.answer(html_text or "Предпросмотр без текста.", parse_mode="HTML", reply_markup=markup)
        await message.answer("Так пост увидит сообщество. Опубликовать?", reply_markup=preview)
        return
    try:
        await send_studio_post(
            bot,
            message.chat.id,
            html_text or " ",
            data.get("post_media_type"),
            data.get("post_file_id"),
            preview,
        )
    except TelegramBadRequest:
        await message.answer(html_text or "Предпросмотр без текста.", parse_mode="HTML", reply_markup=preview)


@router.message(AdminFlow.post_buttons)
async def admin_post_buttons(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not message.from_user or not await _admin_role(message.from_user.id, db, settings):
        await state.clear()
        return
    from community_bot.posting import is_skip_text, parse_button_lines

    if is_skip_text(message.text):
        await state.update_data(post_buttons=[])
    else:
        buttons, error = parse_button_lines(message.text or "")
        if error:
            await message.answer(error)
            return
        await state.update_data(post_buttons=buttons)
    await _ask_post_poll(message, state)


@router.callback_query(F.data == "post:skip:buttons")
async def admin_post_skip_buttons(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_POST):
        return
    await state.update_data(post_buttons=[])
    await callback.answer()
    await _ask_post_poll(callback.message, state)


@router.callback_query(F.data == "post:poll:no")
async def admin_post_poll_no(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_POST):
        return
    await state.update_data(post_poll=None)
    await callback.answer()
    await _ask_post_rsvp(callback.message, state)


@router.callback_query(F.data == "post:poll:yes")
async def admin_post_poll_yes(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_POST):
        return
    await state.set_state(AdminFlow.post_poll_question)
    await callback.answer()
    await callback.message.answer("Напишите вопрос голосования (до 300 символов).")


@router.message(AdminFlow.post_poll_question)
async def admin_post_poll_question(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not message.from_user or not await _admin_role(message.from_user.id, db, settings):
        await state.clear()
        return
    question = (message.text or "").strip()
    if not question or len(question) > 300:
        await message.answer("Вопрос — обычный текст до 300 символов.")
        return
    await state.update_data(post_poll_question=question)
    await state.set_state(AdminFlow.post_poll_options)
    await message.answer("Варианты — каждый с новой строки, от 2 до 10.")


@router.message(AdminFlow.post_poll_options)
async def admin_post_poll_options(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not message.from_user or not await _admin_role(message.from_user.id, db, settings):
        await state.clear()
        return
    from community_bot.posting import parse_poll_options, poll_anonymous_keyboard

    options, error = parse_poll_options(message.text or "")
    if error:
        await message.answer(error)
        return
    await state.update_data(post_poll_options=options)
    await message.answer("Голосование анонимное?", reply_markup=poll_anonymous_keyboard())


@router.callback_query(F.data.startswith("post:poll:anon:"))
async def admin_post_poll_anon(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    if not callback.data or not callback.message or not await _admin_callback(callback, db, settings, PERM_POST):
        return
    anonymous = callback.data.endswith(":1")
    data = await state.get_data()
    question = str(data.get("post_poll_question") or "").strip()
    options = list(data.get("post_poll_options") or [])
    if not question or len(options) < 2:
        await callback.answer("Сначала укажите вопрос и варианты.", show_alert=True)
        return
    await state.update_data(post_poll={"question": question, "options": options, "anonymous": anonymous})
    await callback.answer()
    await _ask_post_rsvp(callback.message, state)


@router.message(AdminFlow.post_poll_ask)
async def admin_post_poll_ask_text(message: Message) -> None:
    await message.answer("Нажмите кнопку: добавить голосование или опубликовать только пост.")


async def _ask_post_rsvp(message: Message, state: FSMContext) -> None:
    from community_bot.posting import rsvp_ask_keyboard

    await state.set_state(AdminFlow.post_rsvp_ask)
    await message.answer("Добавить кнопку «Я буду»?", reply_markup=rsvp_ask_keyboard())


@router.callback_query(F.data == "post:rsvp:no")
async def admin_post_rsvp_no(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_POST):
        return
    await state.update_data(post_rsvp=None)
    await state.set_state(AdminFlow.post_preview)
    await callback.answer()
    await _show_post_preview(callback.message, await state.get_data(), bot)


@router.callback_query(F.data == "post:rsvp:yes")
async def admin_post_rsvp_yes(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_POST):
        return
    event_id = f"e{int(datetime.now(UTC).timestamp())}"
    await state.update_data(post_rsvp=event_id)
    await state.set_state(AdminFlow.post_preview)
    await callback.answer()
    await _show_post_preview(callback.message, await state.get_data(), bot)


@router.message(AdminFlow.post_rsvp_ask)
async def admin_post_rsvp_ask_text(message: Message) -> None:
    await message.answer("Нажмите кнопку: «Я буду» или без RSVP.")


@router.message(AdminFlow.post_preview)
async def admin_post_preview_text(message: Message) -> None:
    await message.answer("Нажмите «Опубликовать» или «Отмена».")


@router.callback_query(F.data == "post:send")
async def admin_post_send(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_POST):
        return
    if not settings.community_chat_id:
        await callback.answer("ID чата сообщества не настроен.", show_alert=True)
        return
    from community_bot.posting import compose_post_markup, render_post, send_studio_poll, send_studio_post

    data = await state.get_data()
    html_text = render_post(str(data.get("post_template") or "announce"), str(data.get("post_body") or ""))
    markup = compose_post_markup(list(data.get("post_buttons") or []), data.get("post_rsvp"))
    poll = data.get("post_poll")
    sent = None
    try:
        if html_text.strip() or data.get("post_file_id"):
            sent = await send_studio_post(
                bot,
                settings.community_chat_id,
                html_text or " ",
                data.get("post_media_type"),
                data.get("post_file_id"),
                markup,
            )
        if poll:
            await send_studio_poll(bot, settings.community_chat_id, dict(poll))
    except TelegramBadRequest:
        await callback.answer("Telegram не принял это сообщение или опрос.", show_alert=True)
        return
    await db.log_admin_action(
        callback.from_user.id,
        "post_community",
        str(settings.community_chat_id),
        str(data.get("post_template") or ""),
        actor_name=callback.from_user.full_name,
        reason=str(data.get("post_template") or "пост"),
    )
    template = str(data.get("post_template") or "")
    event_id = str(data.get("post_rsvp") or "")
    await callback.answer("Опубликовано")
    from community_bot.notify import fanout

    preview = html_text.strip().replace("\n", " ")
    if len(preview) > 180:
        preview = preview[:177] + "…"
    await fanout(bot, db, "events", f"📣 Новый пост студии.\n{preview}" if preview else "📣 Новый пост студии.")
    if template == "event" and sent is not None:
        from community_bot.posting import pay_ask_keyboard

        if not event_id:
            event_id = f"e{int(datetime.now(UTC).timestamp())}"
        await state.set_state(AdminFlow.post_pay_ask)
        await state.set_data(
            {
                "pay_chat_id": int(sent.chat.id),
                "pay_message_id": int(sent.message_id),
                "pay_event_id": event_id,
                "pay_body": html_text,
                "pay_buttons": list(data.get("post_buttons") or []),
                "pay_rsvp": data.get("post_rsvp"),
                "flow_kind": "event_pay",
            }
        )
        await callback.message.answer(
            "✅ Пост ушёл в чат сообщества.\nДобавить под ним кнопку оплаты участия?",
            reply_markup=pay_ask_keyboard(),
        )
        return
    await state.clear()
    await callback.message.answer("✅ Пост ушёл в чат сообщества.")


@router.callback_query(F.data == "post:pay:no")
async def admin_post_pay_no(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.answer("Ок, пост без кнопки оплаты.")


@router.callback_query(F.data == "post:pay:yes")
async def admin_post_pay_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminFlow.post_pay_text)
    await callback.answer()
    if callback.message:
        await callback.message.answer("Введите текст кнопки, например «Купить билет».")


@router.message(AdminFlow.post_pay_ask)
async def admin_post_pay_ask_text(message: Message) -> None:
    await message.answer("Нажмите кнопку: добавить оплату или оставить пост как есть.")


@router.message(AdminFlow.post_pay_text)
async def admin_post_pay_text(message: Message, state: FSMContext, db: Database) -> None:
    text = (message.text or "").strip()
    if not 1 <= len(text) <= 64:
        await message.answer("Текст кнопки — от 1 до 64 символов.")
        return
    await state.update_data(pay_button_text=text)
    await state.set_state(AdminFlow.post_pay_price)
    stake = await db.get_bot_state("rsvp_stake")
    hint = f" Сейчас залог RSVP: {stake} 🍪." if (stake or "").isdigit() and int(stake) > 0 else ""
    await message.answer(f"Сколько печенек стоит участие? Целое число.{hint}")


@router.message(AdminFlow.post_pay_price)
async def admin_post_pay_price(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    if not message.from_user or not message.text or not message.text.isdigit():
        await message.answer("Введите цену целым числом печенек.")
        return
    price = int(message.text)
    if not 1 <= price <= 1_000_000:
        await message.answer("Цена — от 1 до 1 000 000 🍪.")
        return
    data = await state.get_data()
    event_id = str(data.get("pay_event_id") or "")
    chat_id = int(data.get("pay_chat_id") or 0)
    message_id = int(data.get("pay_message_id") or 0)
    button_text = str(data.get("pay_button_text") or "Оплатить участие")
    if not event_id or not chat_id or not message_id:
        await state.clear()
        await message.answer("Не удалось привязать кнопку к посту.")
        return
    from community_bot.posting import compose_post_markup

    await db.save_event_offer(
        event_id,
        chat_id,
        message_id,
        button_text,
        price,
        message.from_user.id,
        title="Мероприятие",
        body=str(data.get("pay_body") or ""),
    )
    markup = compose_post_markup(
        list(data.get("pay_buttons") or []),
        data.get("pay_rsvp"),
        pay=(button_text, event_id),
    )
    try:
        await bot.edit_message_reply_markup(chat_id, message_id, reply_markup=markup)
    except TelegramBadRequest:
        await state.clear()
        await message.answer("Пост опубликован, но кнопку под ним отредактировать не удалось.")
        return
    await state.clear()
    await message.answer(f"✅ Кнопка «{html.escape(button_text)}» добавлена. Участие стоит {price} 🍪.")


@router.callback_query(F.data == "admin:mention")
async def admin_begin_mention(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_MENTION):
        return
    await state.set_state(AdminFlow.mention_all)
    await callback.answer()
    await callback.message.answer(
        "Введите текст уведомления. После него бот упомянет всех известных участников.",
        reply_markup=flow_reply_keyboard(),
    )


@router.message(AdminFlow.mention_all)
async def admin_send_mention(message: Message, state: FSMContext, db: Database, settings: Settings, bot: Bot) -> None:
    if not message.from_user or not await _admin_role(message.from_user.id, db, settings):
        await state.clear()
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Нужен текст уведомления.")
        return
    if not settings.community_chat_id:
        await state.clear()
        await message.answer("ID чата сообщества не настроен.")
        return
    await bot.send_message(
        settings.community_chat_id,
        f"📣 <b>Общее уведомление</b>\n\n{html.escape(text)}",
        parse_mode="HTML",
    )
    users = await db.list_all_users()
    mentions = [
        user_link(
            int(user["user_id"]),
            str(user["profile_name"] or user["telegram_name"] or user["username"] or user["user_id"]),
        )
        for user in users
    ]
    for index in range(0, len(mentions), 25):
        await bot.send_message(settings.community_chat_id, " ".join(mentions[index : index + 25]), parse_mode="HTML")
        await asyncio.sleep(0.1)
    await state.clear()
    await message.answer(f"✅ Уведомление отправлено. Упомянуто записей: {len(mentions)}.")


@router.callback_query(F.data == "admin:auto:list")
async def admin_automessages(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings, PERM_AUTOMESSAGES):
        return
    rows = await db.list_scheduled_messages()
    await callback.answer()
    await callback.message.edit_text(
        "⏱ <b>Автосообщения</b>\n\n✅ — активно, ⏸ — приостановлено. Нажатие на строку меняет состояние.",
        parse_mode="HTML",
        reply_markup=automessages_keyboard(rows),
    )


@router.callback_query(F.data == "admin:auto:new")
async def admin_automessage_target(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    await callback.answer()
    await callback.message.edit_text("Куда регулярно отправлять сообщение?", reply_markup=automessage_target_keyboard())


@router.callback_query(F.data.startswith("admin:auto:new:"))
async def admin_begin_automessage(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.data or not callback.message or not await _admin_callback(callback, db, settings):
        return
    target = callback.data.rsplit(":", 1)[1]
    if target not in {"community", "private_all"}:
        await callback.answer("Некорректная цель.", show_alert=True)
        return
    await state.set_state(AdminFlow.automessage_content)
    await state.set_data({"automessage_target": target})
    await callback.answer()
    await callback.message.answer(
        "Отправьте содержимое автосообщения: текст или одно вложение с подписью.",
        reply_markup=flow_reply_keyboard(),
    )


@router.message(AdminFlow.automessage_content)
async def admin_automessage_content(message: Message, state: FSMContext) -> None:
    text = message.text or message.caption
    media_type, media_file_id = media_from_message(message)
    if not text and not media_file_id:
        await message.answer("Поддерживаются текст, фото, видео, аудио, голосовые и документы.")
        return
    await state.update_data(
        automessage_text=text,
        automessage_media_type=media_type,
        automessage_media_file_id=media_file_id,
    )
    await state.set_state(AdminFlow.automessage_interval)
    await message.answer(
        "Введите период отправки в минутах — от 5 до 10080 (7 суток).",
        reply_markup=flow_reply_keyboard(),
    )


@router.message(AdminFlow.automessage_interval)
async def admin_save_automessage(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not message.from_user or not await _admin_role(message.from_user.id, db, settings):
        await state.clear()
        return
    if not message.text or not message.text.isdigit() or not 5 <= int(message.text) <= 10_080:
        await message.answer("Введите целое число минут от 5 до 10080.")
        return
    data = await state.get_data()
    schedule_id = await db.create_scheduled_message(
        str(data["automessage_target"]),
        data.get("automessage_text"),
        data.get("automessage_media_type"),
        data.get("automessage_media_file_id"),
        int(message.text),
        message.from_user.id,
    )
    await state.clear()
    await message.answer(f"✅ Автосообщение №{schedule_id} создано и включено.")


@router.callback_query(F.data.startswith("admin:auto:toggle:"))
async def admin_toggle_automessage(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message or not await _admin_callback(callback, db, settings):
        return
    schedule_id = int(callback.data.rsplit(":", 1)[1])
    await db.toggle_scheduled_message(schedule_id)
    rows = await db.list_scheduled_messages()
    await callback.answer("Состояние изменено.")
    await callback.message.edit_reply_markup(reply_markup=automessages_keyboard(rows))


@router.callback_query(F.data.startswith("admin:auto:delete:"))
async def admin_delete_automessage(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message or not await _admin_callback(callback, db, settings):
        return
    schedule_id = int(callback.data.rsplit(":", 1)[1])
    await db.delete_scheduled_message(schedule_id)
    rows = await db.list_scheduled_messages()
    await callback.answer("Автосообщение удалено.")
    await callback.message.edit_reply_markup(reply_markup=automessages_keyboard(rows))


@router.message(command_or_alias("question"))
@router.message(F.text == "❓ Задать вопрос")
async def open_ticket(message: Message, state: FSMContext, db: Database, settings: Settings, bot: Bot) -> None:
    if not message.from_user:
        return
    await register_telegram_user(db, message.from_user)
    ticket_id, created = await db.get_or_create_ticket(message.from_user.id)
    await state.set_state(TicketForm.active)
    await state.set_data({"ticket_id": ticket_id})
    if created:
        for reviewer_id in settings.reviewers:
            await safe_send(
                bot,
                reviewer_id,
                f"🎫 Открыт тикет №{ticket_id} пользователем "
                f"{user_link(message.from_user.id, message.from_user.full_name)}.",
                parse_mode="HTML",
                reply_markup=ticket_keyboard(ticket_id),
            )
        body = (
            f"🎫 <b>Тикет №{ticket_id}</b>\n"
            "Открыт. Пишите сюда. Закроет стафф или /close."
        )
    else:
        body = (
            f"🎫 <b>Тикет №{ticket_id}</b>\n"
            "Уже открыт. Напишите сюда — дойдёт до стаффа. /close — закрыть."
        )
    await answer_block(
        message,
        "ticket",
        body,
        parse_mode="HTML",
        reply_markup=flow_reply_keyboard(),
    )


@router.message(command_or_alias("close"), TicketForm.active)
async def close_own_ticket(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    data = await state.get_data()
    ticket_id = int(data["ticket_id"])
    await db.close_ticket(ticket_id)
    await state.clear()
    await message.answer(f"Тикет №{ticket_id} закрыт.")
    await restore_private_menu(message, db, settings)


@router.message(TicketForm.active)
async def relay_ticket_message(message: Message, state: FSMContext, db: Database, settings: Settings, bot: Bot) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    ticket_id = int(data["ticket_id"])
    media_type, file_id = media_from_message(message)
    text = message.text or message.caption
    if not text and not file_id:
        await message.answer("Поддерживаются текст, фото, видео, аудио и документы.")
        return
    await db.add_ticket_message(ticket_id, message.from_user.id, "user", text, media_type, file_id)
    header = f"🎫 <b>Тикет №{ticket_id}</b> от {user_link(message.from_user.id, message.from_user.full_name)}"
    delivered = 0
    for reviewer_id in settings.reviewers:
        if await safe_send(
            bot,
            reviewer_id,
            header,
            parse_mode="HTML",
            reply_markup=ticket_keyboard(ticket_id),
        ):
            try:
                await bot.copy_message(reviewer_id, message.chat.id, message.message_id)
            except TelegramBadRequest:
                pass
            delivered += 1
    await message.answer("Сообщение передано модераторам." if delivered else "Сообщение сохранено в тикете.")


@router.callback_query(F.data.startswith("ticket:reply:"))
async def begin_ticket_reply(callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    if not callback.data or not await _reviewer(callback, db, settings):
        return
    ticket_id = int(callback.data.rsplit(":", 1)[1])
    ticket = await db.get_ticket(ticket_id)
    if not ticket or ticket["status"] != "open":
        await callback.answer("Тикет уже закрыт.", show_alert=True)
        return
    await state.set_state(ModeratorReply.ticket_message)
    await state.set_data({"ticket_id": ticket_id})
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"Отправьте ответ для тикета №{ticket_id}. Можно приложить файл.",
            reply_markup=flow_reply_keyboard(),
        )


@router.message(ModeratorReply.ticket_message)
async def send_ticket_reply(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    if not message.from_user:
        return
    data = await state.get_data()
    ticket_id = int(data["ticket_id"])
    ticket = await db.get_ticket(ticket_id)
    if not ticket or ticket["status"] != "open":
        await state.clear()
        await message.answer("Тикет уже закрыт.")
        return
    media_type, file_id = media_from_message(message)
    text = message.text or message.caption
    await db.add_ticket_message(ticket_id, message.from_user.id, "moderator", text, media_type, file_id)
    try:
        await bot.send_message(int(ticket["user_id"]), f"💬 Ответ модератора по тикету №{ticket_id}:")
        await bot.copy_message(int(ticket["user_id"]), message.chat.id, message.message_id)
    except (TelegramForbiddenError, TelegramBadRequest):
        await message.answer("Ответ сохранён, но пользователь заблокировал бота.")
        await state.clear()
        return
    await state.clear()
    await message.answer("Ответ отправлен пользователю.")


@router.callback_query(F.data.startswith("ticket:close:"))
async def moderator_close_ticket(callback: CallbackQuery, db: Database, settings: Settings, bot: Bot) -> None:
    if not callback.data or not await _reviewer(callback, db, settings):
        return
    ticket_id = int(callback.data.rsplit(":", 1)[1])
    ticket = await db.get_ticket(ticket_id)
    if not ticket or ticket["status"] != "open":
        await callback.answer("Тикет уже закрыт.", show_alert=True)
        return
    await db.close_ticket(ticket_id)
    await db.log_admin_action(
        callback.from_user.id,
        "ticket_close",
        str(ticket["user_id"]),
        f"тикет №{ticket_id}",
        actor_name=callback.from_user.full_name,
        reason="закрытие тикета",
    )
    await callback.answer("Тикет закрыт.")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
    await safe_send(bot, int(ticket["user_id"]), f"Тикет №{ticket_id} закрыт модератором.")
