from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from community_bot.config import Settings
from community_bot.database import Database
from community_bot.helpers import has_permission, render_profile
from community_bot.keyboards import (
    BTN_MENU,
    BTN_PROFILE,
    BTN_WALLET,
    flow_reply_keyboard,
    main_private_keyboard,
    private_menu_keyboard,
    profile_keyboard,
)
from community_bot.permissions import PERM_ADMIN_PANEL
from community_bot.states import ApplicationForm
from community_bot.texts import APPLICATION_INTRO

router = Router(name="flows")


class InFlow(Filter):
    async def __call__(self, event: Message | CallbackQuery, state: FSMContext) -> bool:
        return await state.get_state() is not None


async def restore_private_menu(message: Message, db: Database, settings: Settings) -> None:
    del db, settings
    if message.chat.type != "private":
        await message.answer("Действие отменено.", reply_markup=ReplyKeyboardRemove())
        return
    await message.answer(
        "Снизу всегда зелёный «Профиль», синий «Кошелёк» и синее «Меню».",
        reply_markup=main_private_keyboard(),
    )


async def restart_application(message: Message, state: FSMContext) -> None:
    await state.set_state(ApplicationForm.name)
    await state.set_data({"flow_kind": "application"})
    await message.answer(APPLICATION_INTRO, reply_markup=flow_reply_keyboard())


async def cancel_current_flow(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    await state.clear()
    if ticket_id:
        await db.close_ticket(int(ticket_id))
        await message.answer(f"Тикет №{ticket_id} закрыт.")
    else:
        await message.answer("Ок, закрываю это действие.")
    if message.chat.type == "private":
        await restore_private_menu(message, db, settings)


async def _show_own_profile(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    user = await db.ensure_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    text = await render_profile(db, settings, user)
    markup = profile_keyboard(message.from_user.id, bool(user.get("profile_private")))
    if user["avatar_file_id"]:
        try:
            if user.get("avatar_media_type") == "video":
                await message.answer_video(user["avatar_file_id"], caption=text, parse_mode="HTML", reply_markup=markup)
                return
            await message.answer_photo(user["avatar_file_id"], caption=text, parse_mode="HTML", reply_markup=markup)
            return
        except Exception:
            pass
    await message.answer(text, parse_mode="HTML", reply_markup=markup)


async def _show_inline_menu(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    show_admin = await has_permission(db, settings, message.from_user.id, PERM_ADMIN_PANEL)
    await message.answer(
        "📋 <b>Меню НОРЫ</b>\n\n"
        "Анкета, вопрос модераторам, магазин и тамагочи.\n"
        "Снизу всегда зелёный «Профиль», синий «Кошелёк» и синее «Меню».",
        parse_mode="HTML",
        reply_markup=private_menu_keyboard(show_admin),
    )


@router.message(F.chat.type == "private", F.text.in_({BTN_PROFILE, BTN_MENU, BTN_WALLET}))
async def persistent_nav(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    data = await state.get_data()
    ticket_id = data.get("ticket_id")
    await state.clear()
    if ticket_id:
        await db.close_ticket(int(ticket_id))
        await message.answer(f"Тикет №{ticket_id} закрыт, чтобы открыть это меню.")
    if message.text == BTN_PROFILE:
        await _show_own_profile(message, db, settings)
        return
    if message.text == BTN_WALLET:
        from community_bot.routers.wallet import send_wallet

        await send_wallet(message, db, settings)
        return
    await _show_inline_menu(message, db, settings)


@router.callback_query(InFlow(), F.data.in_({"flow:cancel", "flow:restart"}))
async def flow_callback_control(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.message:
        await callback.answer()
        return
    current = await state.get_state()
    await callback.answer()
    if callback.data == "flow:restart" and current and current.startswith("ApplicationForm:"):
        await restart_application(callback.message, state)
        return
    if callback.data == "flow:restart":
        await callback.message.answer("Здесь можно только отменить.")
        return
    await cancel_current_flow(callback.message, state, db, settings)


@router.callback_query(F.data == "flow:cancel")
async def flow_cancel_idle(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Закрыто")
    if callback.message:
        with_context = getattr(callback.message, "edit_reply_markup", None)
        if with_context:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass


@router.callback_query(F.data == "g:hide")
async def game_hide(callback: CallbackQuery) -> None:
    await callback.answer("Скрыто")
    if not callback.message:
        return
    try:
        await callback.message.delete()
    except (TelegramBadRequest, TelegramForbiddenError):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except (TelegramBadRequest, TelegramForbiddenError, AttributeError):
            pass


@router.callback_query(F.data == "ui:close")
async def ui_close(callback: CallbackQuery) -> None:
    await callback.answer("Закрыто")
    if not callback.message:
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass


@router.callback_query(F.data == "shop:close")
async def shop_close(callback: CallbackQuery) -> None:
    await callback.answer("Магазин закрыт")
    if not callback.message:
        return
    try:
        await callback.message.edit_text("🛒 Магазин закрыт.")
    except Exception:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


def with_flow_prompt(text: str) -> str:
    return f"{text}\n\nСнизу — зелёный «Профиль», синий «Кошелёк» и синее «Меню», они всегда работают."
