from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from community_bot.config import Settings
from community_bot.database import Database
from community_bot.domain import ROLE_LEVELS
from community_bot.helpers import effective_role
from community_bot.keyboards import FLOW_CANCEL, FLOW_RESTART, flow_reply_keyboard, main_private_keyboard
from community_bot.states import ApplicationForm
from community_bot.texts import APPLICATION_INTRO

router = Router(name="flows")


class InFlow(Filter):
    async def __call__(self, event: Message | CallbackQuery, state: FSMContext) -> bool:
        return await state.get_state() is not None


async def restore_private_menu(message: Message, db: Database, settings: Settings) -> None:
    if message.chat.type != "private" or not message.from_user:
        await message.answer("Действие отменено.", reply_markup=ReplyKeyboardRemove())
        return
    role = await effective_role(db, settings, message.from_user.id)
    await message.answer(
        "Главное меню снова снизу.",
        reply_markup=main_private_keyboard(ROLE_LEVELS.get(role, 0) >= ROLE_LEVELS["admin"]),
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


@router.message(InFlow(), F.text.in_({FLOW_CANCEL, FLOW_RESTART}))
async def flow_text_control(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    current = await state.get_state()
    if message.text == FLOW_RESTART and current and current.startswith("ApplicationForm:"):
        await restart_application(message, state)
        return
    if message.text == FLOW_RESTART:
        await message.answer("Здесь можно только отменить. Нажмите ❌ Отмена.")
        return
    await cancel_current_flow(message, state, db, settings)


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
    return f"{text}\n\nСнизу — только «Начать заново» и «Отмена»."
