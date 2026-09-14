from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from community_bot.config import Settings
from community_bot.database import Database
from community_bot.helpers import application_block_reason, has_permission, render_profile
from community_bot.keyboards import (
    BTN_MENU,
    BTN_SHOP,
    BTN_TICKET,
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
        "Можно открыть профиль, магазин, кошелёк или написать тикет.",
        reply_markup=main_private_keyboard(),
    )


async def restart_application(message: Message, state: FSMContext, db: Database, user_id: int) -> None:
    reason = await application_block_reason(db, user_id)
    if reason:
        await state.clear()
        await message.answer(reason)
        return
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


async def _show_inline_menu(
    message: Message,
    db: Database,
    settings: Settings,
    *,
    replace: bool = False,
) -> None:
    if not message.from_user:
        return
    from community_bot.blocks import answer_block, replace_block

    show_admin = await has_permission(db, settings, message.from_user.id, PERM_ADMIN_PANEL)
    unread = await db.notify_unread_count(message.from_user.id)
    markup = private_menu_keyboard(show_admin, unread=unread)
    text = "📋 <b>Меню</b>\nПрофиль, питомец, уведомления. Снизу — магазин, кошелёк и тикет."
    if replace:
        await replace_block(message, "cabinet", text, parse_mode="HTML", reply_markup=markup)
        return
    await answer_block(
        message,
        "cabinet",
        text,
        parse_mode="HTML",
        reply_markup=markup,
    )


@router.callback_query(F.data == "menu:home")
async def menu_home(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message:
        await callback.answer()
        return
    await callback.answer()
    await _show_inline_menu(callback.message, db, settings, replace=True)


@router.message(F.chat.type == "private", F.text.in_({BTN_MENU, BTN_SHOP, BTN_WALLET, BTN_TICKET}))
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
    if message.text == BTN_WALLET:
        from community_bot.routers.wallet import send_wallet

        await send_wallet(message, db, settings)
        return
    if message.text == BTN_SHOP:
        from community_bot.blocks import answer_block
        from community_bot.helpers import register_telegram_user
        from community_bot.routers.group import _shop_home_markup, _shop_home_text

        user = await register_telegram_user(db, message.from_user)
        await answer_block(
            message,
            "shop",
            _shop_home_text(user, settings),
            parse_mode="HTML",
            reply_markup=await _shop_home_markup(db),
        )
        return
    if message.text == BTN_TICKET:
        from community_bot.routers.private import open_ticket

        await open_ticket(message, state, db, settings, message.bot)
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
        await restart_application(callback.message, state, db, callback.from_user.id)
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


@router.callback_query(F.data == "updates:dm")
async def send_update_to_dm(callback: CallbackQuery, bot: Bot) -> None:
    from aiogram.types import FSInputFile

    from community_bot.covers import cover_path_for
    from community_bot.telegraph import member_dm_text
    from community_bot.updates import community_announcement, latest_update

    item = latest_update()
    user_id = callback.from_user.id
    try:
        cover = cover_path_for(item)
        if cover:
            await bot.send_photo(
                user_id,
                FSInputFile(cover),
                caption=community_announcement(item),
                parse_mode="HTML",
            )
        await bot.send_message(user_id, member_dm_text(item), parse_mode="HTML")
    except (TelegramBadRequest, TelegramForbiddenError):
        await callback.answer("Напишите боту /start в личке, затем нажмите снова.", show_alert=True)
        return
    await callback.answer("Обновление отправлено в личный диалог с ботом")


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
    return text
