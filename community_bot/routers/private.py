from __future__ import annotations

import asyncio
import contextlib
import html
from datetime import UTC, datetime
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
)

from community_bot.city import is_weather_text, weather_report
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.domain import ROLE_LABELS, ROLE_LEVELS
from community_bot.helpers import (
    effective_role,
    media_from_message,
    profile_text,
    register_telegram_user,
    safe_send,
    user_link,
)
from community_bot.keyboards import (
    MAIN_PRIVATE_KEYBOARD,
    YES_NO_KEYBOARD,
    admin_panel_keyboard,
    admin_user_keyboard,
    admin_users_keyboard,
    application_review_keyboard,
    automessage_target_keyboard,
    automessages_keyboard,
    cookie_order_review_keyboard,
    feature_flags_keyboard,
    main_private_keyboard,
    profile_keyboard,
    role_selection_keyboard,
    role_users_keyboard,
    ticket_keyboard,
)
from community_bot.states import AdminFlow, ApplicationForm, ModeratorReply, ProfileEdit, TicketForm
from community_bot.texts import (
    APPLICATION_INTRO,
    APPLICATION_QUESTIONS,
    APPLICATION_REJECTED_INTERVIEW,
    GROUP_COMMANDS_TEXT,
    WELCOME_TEXT,
)

router = Router(name="private")
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

EMERGENCY_STOP_COMMAND = "nore_stop_9x4q"
EMERGENCY_STOP_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="⛔ Да, отключить бота", callback_data="emergency:stop:confirm")],
        [InlineKeyboardButton(text="Отмена", callback_data="emergency:stop:cancel")],
    ]
)


async def _private_keyboard(user_id: int, db: Database, settings: Settings):
    role = await effective_role(db, settings, user_id)
    return main_private_keyboard(ROLE_LEVELS.get(role, 0) >= ROLE_LEVELS["admin"])


async def _send_welcome(message: Message, settings: Settings, reply_markup) -> None:
    cover = settings.welcome_cover
    if not cover:
        await message.answer(WELCOME_TEXT, reply_markup=reply_markup)
        return
    source: str | FSInputFile = cover
    if await asyncio.to_thread(Path(cover).is_file):
        source = FSInputFile(cover)
    try:
        await message.answer_photo(source, caption=WELCOME_TEXT, reply_markup=reply_markup)
    except (TelegramBadRequest, OSError):
        await message.answer(WELCOME_TEXT, reply_markup=reply_markup)


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
async def start(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    await register_telegram_user(db, message.from_user)
    await state.clear()
    await _send_welcome(message, settings, await _private_keyboard(message.from_user.id, db, settings))


@router.message(Command("help"))
async def help_command(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    await message.answer(
        GROUP_COMMANDS_TEXT,
        parse_mode="HTML",
        reply_markup=await _private_keyboard(message.from_user.id, db, settings),
    )


async def _admin_role(user_id: int, db: Database, settings: Settings) -> str | None:
    role = await effective_role(db, settings, user_id)
    return role if ROLE_LEVELS.get(role, 0) >= ROLE_LEVELS["admin"] else None


async def _admin_callback(callback: CallbackQuery, db: Database, settings: Settings) -> str | None:
    role = await _admin_role(callback.from_user.id, db, settings)
    if not role:
        await callback.answer("Недостаточно прав.", show_alert=True)
    return role


async def _admin_panel_text(db: Database) -> str:
    stats = await db.dashboard_stats()
    return (
        "🛡 <b>Админ-панель</b>\n\n"
        f"Пользователей: <b>{stats['users']}</b> · питомцев: <b>{stats['pets']}</b>\n"
        f"Анкет на проверке: <b>{stats['pending_applications']}</b>\n"
        f"Платежей на проверке: <b>{stats['pending_orders']}</b>\n"
        f"Активных игр: <b>{stats['active_games']}</b>"
    )


@router.message(Command("admin"))
@router.message(F.text == "🛡 Админ-панель")
async def admin_panel(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user or not await _admin_role(message.from_user.id, db, settings):
        return
    await message.answer(
        await _admin_panel_text(db),
        parse_mode="HTML",
        reply_markup=admin_panel_keyboard(),
    )


@router.callback_query(F.data == "admin:panel")
async def admin_panel_callback(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    await callback.answer()
    await callback.message.edit_text(
        await _admin_panel_text(db),
        parse_mode="HTML",
        reply_markup=admin_panel_keyboard(),
    )


@router.callback_query(F.data == "admin:features")
async def admin_features(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    flags = await db.list_feature_flags()
    await callback.answer()
    await callback.message.edit_text(
        "⚙️ <b>Функции и защита</b>\n\n🟢 — включено, ⚪ — выключено. Изменения применяются сразу.",
        parse_mode="HTML",
        reply_markup=feature_flags_keyboard(flags),
    )


@router.callback_query(F.data.startswith("admin:feature:"))
async def admin_toggle_feature(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message or not await _admin_callback(callback, db, settings):
        return
    key = callback.data.rsplit(":", 1)[1]
    enabled = await db.toggle_feature(key, callback.from_user.id)
    if enabled is None:
        await callback.answer("Неизвестная функция.", show_alert=True)
        return
    await callback.answer("Функция включена." if enabled else "Функция выключена.")
    await callback.message.edit_reply_markup(reply_markup=feature_flags_keyboard(await db.list_feature_flags()))


@router.callback_query(F.data == "admin:health")
async def admin_health(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    stats = await db.dashboard_stats()
    database_size = db.path.stat().st_size if db.path.exists() else 0
    enabled = sum(int(row["enabled"]) for row in await db.list_feature_flags())
    await callback.answer()
    await callback.message.edit_text(
        "📊 <b>Состояние системы</b>\n\n"
        f"База: <b>{database_size / 1024 / 1024:.2f} МБ</b>\n"
        f"Пользователей: <b>{stats['users']}</b>\n"
        f"Питомцев: <b>{stats['pets']}</b>\n"
        f"Активных игр: <b>{stats['active_games']}</b>\n"
        f"Включённых функций: <b>{enabled}</b>\n\n"
        "SQLite WAL включён · игровые состояния сохраняются после перезапуска.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="↩️ В панель", callback_data="admin:panel")]]
        ),
    )


@router.callback_query(F.data == "admin:audit")
async def admin_audit(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    rows = await db.recent_admin_actions(20)
    lines = ["🧾 <b>Последние действия</b>", ""]
    for row in rows:
        lines.append(
            f"#{row['id']} · <code>{row['actor_id']}</code> · {html.escape(str(row['action']))} · "
            f"{html.escape(str(row['target'] or '—'))}"
        )
    if not rows:
        lines.append("Журнал пока пуст.")
    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines),
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
        lines.append(
            f"• {user_link(int(row['user_id']), str(name))} · {row['message_count']} сообщений · {last_seen}"
        )
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


@router.message(Command("apply"))
@router.message(F.text == "📝 Заполнить анкету")
async def begin_application(message: Message, state: FSMContext, db: Database) -> None:
    if not message.from_user:
        return
    await register_telegram_user(db, message.from_user)
    await state.set_state(ApplicationForm.name)
    await state.set_data({})
    await message.answer(APPLICATION_INTRO)


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
    await message.answer(APPLICATION_QUESTIONS["age"])


@router.message(ApplicationForm.age)
async def application_age(message: Message, state: FSMContext) -> None:
    if (text := await _validate_text(message, maximum=50)) is None:
        return
    await state.update_data(age=text)
    await state.set_state(ApplicationForm.referral)
    await message.answer(APPLICATION_QUESTIONS["referral"])


@router.message(ApplicationForm.referral)
async def application_referral(message: Message, state: FSMContext) -> None:
    if (text := await _validate_text(message, maximum=100)) is None:
        return
    await state.update_data(referral=text)
    await state.set_state(ApplicationForm.expectations)
    await message.answer(APPLICATION_QUESTIONS["expectations"])


@router.message(ApplicationForm.expectations)
async def application_expectations(message: Message, state: FSMContext) -> None:
    if (text := await _validate_text(message)) is None:
        return
    await state.update_data(expectations=text)
    await state.set_state(ApplicationForm.bio)
    await message.answer(APPLICATION_QUESTIONS["bio"])


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
        await callback.message.answer(APPLICATION_REJECTED_INTERVIEW, reply_markup=MAIN_PRIVATE_KEYBOARD)
        return
    answers = await state.get_data()
    application_id = await db.create_application(callback.from_user.id, answers)
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
        reply_markup=MAIN_PRIVATE_KEYBOARD,
    )


async def _reviewer(callback: CallbackQuery, db: Database, settings: Settings) -> bool:
    role = await effective_role(db, settings, callback.from_user.id)
    if ROLE_LEVELS.get(role, 0) < ROLE_LEVELS["moderator"]:
        await callback.answer("Недостаточно прав.", show_alert=True)
        return False
    return True


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
    await safe_send(
        bot,
        int(application["user_id"]),
        f"{result}.{reason_text}",
        parse_mode="HTML",
        reply_markup=MAIN_PRIVATE_KEYBOARD,
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
        await callback.message.answer("Напишите причину отказа одним сообщением.")


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


@router.message(Command("applications"))
async def applications_list(message: Message, db: Database, settings: Settings) -> None:
    if (
        not message.from_user
        or ROLE_LEVELS.get(await effective_role(db, settings, message.from_user.id), 0) < ROLE_LEVELS["moderator"]
    ):
        return
    await _send_pending_applications(message, db)


@router.callback_query(F.data == "admin:applications")
async def admin_applications(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    await callback.answer()
    await _send_pending_applications(callback.message, db)


@router.callback_query(F.data == "admin:orders")
async def admin_cookie_orders(callback: CallbackQuery, db: Database, settings: Settings, bot: Bot) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
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
    users = await db.list_users()
    await callback.answer()
    await callback.message.edit_text(
        "👥 <b>Права пользователей</b>\n\nВыберите пользователя:",
        parse_mode="HTML",
        reply_markup=role_users_keyboard(users),
    )


@router.callback_query(F.data.startswith("admin:user:"))
async def admin_role_user(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    actor_role = await _admin_callback(callback, db, settings)
    if not callback.data or not callback.message or not actor_role:
        return
    user_id = int(callback.data.rsplit(":", 1)[1])
    user = await db.get_user(user_id)
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    name = user["profile_name"] or user["telegram_name"] or user["username"] or f"ID {user_id}"
    username = f"@{user['username']}" if user["username"] else "без юзернейма"
    await callback.answer()
    await callback.message.edit_text(
        f"👤 <b>{html.escape(str(name))}</b>\n"
        f"{html.escape(username)} · <code>{user_id}</code>\n"
        f"Текущая роль: <b>{ROLE_LABELS.get(str(user['role']), 'участник')}</b>\n\n"
        "Выберите новую роль:",
        parse_mode="HTML",
        reply_markup=role_selection_keyboard(user_id, actor_role == "owner"),
    )


@router.callback_query(F.data.startswith("admin:setrole:"))
async def admin_set_role(callback: CallbackQuery, db: Database, settings: Settings, bot: Bot) -> None:
    actor_role = await _admin_callback(callback, db, settings)
    if not callback.data or not callback.message or not actor_role:
        return
    _, _, user_id_raw, new_role = callback.data.split(":")
    user_id = int(user_id_raw)
    target = await db.get_user(user_id)
    if not target or new_role not in {"member", "moderator", "admin"}:
        await callback.answer("Некорректный пользователь или роль.", show_alert=True)
        return
    if user_id == settings.owner_id or user_id == callback.from_user.id:
        await callback.answer("Эту роль нельзя изменить здесь.", show_alert=True)
        return
    target_role = await effective_role(db, settings, user_id)
    if actor_role != "owner" and (ROLE_LEVELS.get(target_role, 0) >= ROLE_LEVELS["admin"] or new_role == "admin"):
        await callback.answer("Только владелец может управлять администраторами.", show_alert=True)
        return
    await db.set_role(user_id, new_role)
    label = ROLE_LABELS[new_role]
    await callback.answer(f"Новая роль: {label}.")
    await callback.message.edit_text(
        f"✅ Пользователю <code>{user_id}</code> назначена роль <b>{label}</b>.",
        parse_mode="HTML",
        reply_markup=role_selection_keyboard(user_id, actor_role == "owner"),
    )
    await safe_send(
        bot,
        user_id,
        f"Ваша роль изменена: <b>{label}</b>.",
        parse_mode="HTML",
        reply_markup=main_private_keyboard(new_role == "admin"),
    )


async def _can_admin_manage(actor_role: str, target_id: int, db: Database, settings: Settings) -> bool:
    if actor_role == "owner":
        return True
    target_role = await effective_role(db, settings, target_id)
    return ROLE_LEVELS.get(actor_role, 0) > ROLE_LEVELS.get(target_role, 0)


@router.callback_query(F.data == "admin:users")
async def admin_users(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
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
    if not await _can_admin_manage(actor_role, user_id, db, settings):
        await callback.answer("Нельзя редактировать пользователя с равной или более высокой ролью.", show_alert=True)
        return
    name = user["profile_name"] or user["telegram_name"] or user["username"] or f"ID {user_id}"
    await callback.answer()
    await callback.message.edit_text(
        f"👤 <b>{html.escape(str(name))}</b> · <code>{user_id}</code>\n"
        f"Роль: {ROLE_LABELS.get(str(user['role']), 'участник')}\n"
        f"Возраст: {user['age'] or 'не указан'}\n"
        f"Баланс: <b>{user['cookies']} 🍪</b>\n"
        f"Предупреждения: <b>{user['warnings']}</b>\n\n"
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
    if not await db.get_user(user_id) or not await _can_admin_manage(actor_role, user_id, db, settings):
        await callback.answer("Редактирование этого пользователя недоступно.", show_alert=True)
        return
    prompts = {
        "cookies": "Введите точный новый баланс от 0 до 1 000 000.",
        "add_cookies": "Сколько печенек начислить? От 1 до 1 000 000.",
        "name": "Введите новое имя (до 50 символов).",
        "age": "Введите новый возраст числом от 14 до 120.",
        "avatar": "Отправьте новую фотографию или видео профиля.",
        "warnings": "Введите точное количество предупреждений, 0 или больше.",
    }
    if action not in prompts:
        await callback.answer("Неизвестное действие.", show_alert=True)
        return
    await state.set_state(AdminFlow.user_value)
    await state.set_data({"admin_action": action, "target_user_id": user_id})
    await callback.answer()
    await callback.message.answer(prompts[action])


@router.message(AdminFlow.user_value)
async def admin_save_user_edit(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    actor_role = await _admin_role(message.from_user.id, db, settings)
    data = await state.get_data()
    user_id = int(data["target_user_id"])
    action = str(data["admin_action"])
    if not actor_role or not await _can_admin_manage(actor_role, user_id, db, settings):
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
    if not callback.data or not await _admin_callback(callback, db, settings):
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
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    await state.set_state(AdminFlow.broadcast_private)
    await callback.answer()
    await callback.message.answer("Отправьте сообщение или вложение для рассылки всем пользователям бота.")


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
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    await state.set_state(AdminFlow.post_community)
    await callback.answer()
    await callback.message.answer("Отправьте сообщение или вложение, которое нужно опубликовать в сообществе.")


@router.message(AdminFlow.post_community)
async def admin_send_community_post(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    if not message.from_user or not await _admin_role(message.from_user.id, db, settings):
        await state.clear()
        return
    if not settings.community_chat_id:
        await state.clear()
        await message.answer("ID чата сообщества не настроен.")
        return
    try:
        await bot.copy_message(settings.community_chat_id, message.chat.id, message.message_id)
    except TelegramBadRequest:
        await message.answer("Telegram не смог отправить это сообщение в сообщество.")
        return
    await state.clear()
    await message.answer("✅ Сообщение опубликовано в чате сообщества.")


@router.callback_query(F.data == "admin:mention")
async def admin_begin_mention(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    await state.set_state(AdminFlow.mention_all)
    await callback.answer()
    await callback.message.answer("Введите текст уведомления. После него бот упомянет всех известных участников.")


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
    if not callback.message or not await _admin_callback(callback, db, settings):
        return
    rows = await db.list_scheduled_messages()
    await callback.answer()
    await callback.message.edit_text(
        "⏱ <b>Автосообщения</b>\n\n"
        "✅ — активно, ⏸ — приостановлено. Нажатие на строку меняет состояние.",
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
    await callback.message.answer("Отправьте содержимое автосообщения: текст или одно вложение с подписью.")


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
    await message.answer("Введите период отправки в минутах — от 5 до 10080 (7 суток).")


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


@router.message(Command("question"))
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
    await message.answer(
        f"🎫 Тикет №{ticket_id} открыт. Отправьте вопрос, фото или файл. "
        "Все следующие сообщения попадут модераторам. Для завершения — /close."
    )


@router.message(Command("close"), TicketForm.active)
async def close_own_ticket(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    ticket_id = int(data["ticket_id"])
    await db.close_ticket(ticket_id)
    await state.clear()
    await message.answer(f"Тикет №{ticket_id} закрыт.", reply_markup=MAIN_PRIVATE_KEYBOARD)


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
        await callback.message.answer(f"Отправьте ответ для тикета №{ticket_id}. Можно приложить файл.")


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
    await callback.answer("Тикет закрыт.")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
    await safe_send(bot, int(ticket["user_id"]), f"Тикет №{ticket_id} закрыт модератором.")


@router.message(Command("profile"))
@router.message(F.text == "👤 Мой профиль")
async def show_profile(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    user = await register_telegram_user(db, message.from_user)
    text = profile_text(user, settings)
    if user["avatar_file_id"]:
        try:
            if user.get("avatar_media_type") == "video":
                await message.answer_video(
                    user["avatar_file_id"],
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=profile_keyboard(message.from_user.id),
                )
            else:
                await message.answer_photo(
                    user["avatar_file_id"],
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=profile_keyboard(message.from_user.id),
                )
            return
        except TelegramBadRequest:
            pass
    await message.answer(text, parse_mode="HTML", reply_markup=profile_keyboard(message.from_user.id))


@router.callback_query(F.data.startswith("profile:"))
async def edit_profile(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or not callback.message:
        return
    _, field, user_id = callback.data.split(":")
    if callback.from_user.id != int(user_id):
        await callback.answer("Можно редактировать только свой профиль.", show_alert=True)
        return
    prompts = {
        "name": (ProfileEdit.name, "Введите имя (до 50 символов)."),
        "age": (ProfileEdit.age, "Введите возраст числом от 14 до 120."),
        "hobbies": (ProfileEdit.hobbies, "Расскажите об увлечениях (до 500 символов)."),
        "avatar": (ProfileEdit.avatar, "Отправьте фотографию для аватара."),
    }
    if field not in prompts:
        await callback.answer()
        return
    next_state, prompt = prompts[field]
    await state.set_state(next_state)
    await callback.answer()
    await callback.message.answer(prompt)


@router.message(ProfileEdit.name)
async def edit_profile_name(message: Message, state: FSMContext, db: Database) -> None:
    if not message.from_user or (text := await _validate_text(message, maximum=50)) is None:
        return
    await db.update_profile(message.from_user.id, "profile_name", text)
    await state.clear()
    await message.answer("Имя обновлено.")


@router.message(ProfileEdit.age)
async def edit_profile_age(message: Message, state: FSMContext, db: Database) -> None:
    if not message.from_user or not message.text or not message.text.isdigit():
        await message.answer("Введите возраст числом от 14 до 120.")
        return
    age = int(message.text)
    if not 14 <= age <= 120:
        await message.answer("Возраст должен быть от 14 до 120.")
        return
    await db.update_profile(message.from_user.id, "age", age)
    await state.clear()
    await message.answer("Возраст обновлён.")


@router.message(ProfileEdit.hobbies)
async def edit_profile_hobbies(message: Message, state: FSMContext, db: Database) -> None:
    if not message.from_user or (text := await _validate_text(message, maximum=500)) is None:
        return
    await db.update_profile(message.from_user.id, "hobbies", text)
    await state.clear()
    await message.answer("Увлечения обновлены.")


@router.message(ProfileEdit.avatar)
async def edit_profile_avatar(message: Message, state: FSMContext, db: Database) -> None:
    if not message.from_user or not message.photo:
        await message.answer("Нужно отправить фотографию.")
        return
    await db.update_profile(message.from_user.id, "avatar_file_id", message.photo[-1].file_id)
    await db.update_profile(message.from_user.id, "avatar_media_type", "photo")
    await state.clear()
    await message.answer("Аватар обновлён.")


@router.message(F.text.func(is_weather_text), F.chat.type == "private")
async def private_weather(message: Message, settings: Settings) -> None:
    now = datetime.now(ZoneInfo(settings.timezone))
    await message.answer(
        await weather_report(now),
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
