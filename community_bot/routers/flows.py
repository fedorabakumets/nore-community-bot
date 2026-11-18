from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, User

from community_bot.config import Settings
from community_bot.database import Database
from community_bot.helpers import has_permission, render_profile
from community_bot.keyboards import (
    BTN_MENU,
    BTN_SHOP,
    BTN_TICKET,
    BTN_WALLET,
    private_menu_keyboard,
    profile_keyboard,
)
from community_bot.permissions import PERM_ADMIN_PANEL

router = Router(name="flows")


class InFlow(Filter):
    async def __call__(self, event: Message | CallbackQuery, state: FSMContext) -> bool:
        return await state.get_state() is not None


async def restore_private_menu(message: Message, db: Database, settings: Settings) -> None:
    if message.chat.type != "private":
        await message.answer("Действие отменено.", reply_markup=ReplyKeyboardRemove())
        return
    from community_bot.access import private_allowed
    from community_bot.routers.private import private_menu_content

    uid = message.chat.id
    if await private_allowed(db, settings, uid):
        await message.answer(
            "Выбери раздел.",
            reply_markup=private_menu_keyboard(await has_permission(db, settings, uid, PERM_ADMIN_PANEL),
                                               unread=await db.notify_unread_count(uid)),
        )
        return
    text, markup = await private_menu_content(db, settings, uid)
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


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
    text = await render_profile(db, settings, user, compact=message.chat.type == "private")
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
    actor: User | None = None,
) -> None:
    actor = actor or message.from_user
    if not actor or actor.is_bot:
        return
    from community_bot.blocks import answer_block, replace_block
    from community_bot.cabinet import cabinet_text
    from community_bot.helpers import register_telegram_user

    user = await register_telegram_user(db, actor)
    show_admin = await has_permission(db, settings, actor.id, PERM_ADMIN_PANEL)
    unread = await db.notify_unread_count(actor.id)
    markup = private_menu_keyboard(show_admin, unread=unread)
    text = cabinet_text(
        user, await db.get_pet(actor.id, settle=False), unread=unread,
        restricted_threshold=settings.restricted_reputation_threshold,
    )
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
    await _show_inline_menu(callback.message, db, settings, replace=True, actor=callback.from_user)


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
            await _shop_home_text(db, user, settings),
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
        from community_bot.routers.private import _start_application

        await _start_application(callback.message, state, db, callback.from_user)
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
    from community_bot.updates import latest_update, update_keyboard, update_page

    item = latest_update()
    user_id = callback.from_user.id
    try:
        cover = cover_path_for(item)
        if cover:
            await bot.send_photo(
                user_id,
                FSInputFile(cover),
                caption=update_page(item, 0),
                parse_mode="HTML",
                reply_markup=update_keyboard(item, 0),
            )
        else:
            await bot.send_message(
                user_id, update_page(item, 0), parse_mode="HTML", reply_markup=update_keyboard(item, 0),
            )
    except (TelegramBadRequest, TelegramForbiddenError):
        await callback.answer("Напишите боту /start в личке, затем нажмите снова.", show_alert=True)
        return
    await callback.answer("Обновление отправлено в личный диалог с ботом")


@router.callback_query(F.data.startswith("updates:page:"))
async def switch_update_page(callback: CallbackQuery) -> None:
    from community_bot.updates import UPDATES, update_keyboard, update_page

    message = callback.message
    if not message or message.chat.type != "private" or message.chat.id != callback.from_user.id:
        await callback.answer()
        return
    try:
        _, _, number, raw_page = (callback.data or "").split(":")
        item = next(item for item in UPDATES if item.number == int(number))
        page = int(raw_page)
        text = update_page(item, page)
    except (ValueError, StopIteration):
        await callback.answer("Страница недоступна", show_alert=True)
        return
    try:
        if message.photo:
            await message.edit_caption(caption=text, parse_mode="HTML", reply_markup=update_keyboard(item, page))
        else:
            await message.edit_text(text, parse_mode="HTML", reply_markup=update_keyboard(item, page))
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error).lower():
            raise
    await callback.answer()


@router.callback_query(F.data == "g:hide")
async def game_hide(callback: CallbackQuery) -> None:
    await callback.answer("Закрыто")
    await _delete_callback_message(callback)


async def _delete_callback_message(callback: CallbackQuery) -> None:
    if not callback.message:
        return
    if callback.message.chat.type == "private":
        await callback.message.answer("Раздел закрыт. Выбери следующий раздел кнопками ниже.")
        return
    try:
        await callback.message.delete()
        return
    except (TelegramBadRequest, TelegramForbiddenError, AttributeError):
        pass
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except (TelegramBadRequest, TelegramForbiddenError, AttributeError):
        pass


@router.callback_query(F.data == "ui:close")
async def ui_close(callback: CallbackQuery) -> None:
    await callback.answer("Закрыто")
    await _delete_callback_message(callback)


@router.callback_query(F.data == "shop:close")
async def shop_close(callback: CallbackQuery) -> None:
    await callback.answer("Закрыто")
    await _delete_callback_message(callback)


def with_flow_prompt(text: str) -> str:
    return text
