from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from community_bot.config import Settings
from community_bot.database import Database
from community_bot.helpers import (
    can_view_profile,
    register_telegram_user,
    render_profile,
    resolve_reply_target,
)
from community_bot.keyboards import flow_reply_keyboard, profile_keyboard, public_profile_keyboard
from community_bot.routers.flows import restore_private_menu
from community_bot.states import ProfileEdit

router = Router(name="profile")


async def send_profile_card(
    message: Message,
    user: dict[str, object],
    settings: Settings,
    *,
    editable: bool,
    text: str,
) -> Message:
    user_id = int(user["user_id"])
    markup = (
        profile_keyboard(user_id, bool(user.get("profile_private")))
        if editable
        else public_profile_keyboard(user_id)
    )
    if user.get("avatar_file_id"):
        try:
            if user.get("avatar_media_type") == "video":
                return await message.answer_video(
                    str(user["avatar_file_id"]),
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            return await message.answer_photo(
                str(user["avatar_file_id"]),
                caption=text,
                parse_mode="HTML",
                reply_markup=markup,
            )
        except TelegramBadRequest:
            pass
    return await message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.message(Command("profile"))
@router.message(F.text == "👤 Мой профиль")
async def show_profile(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    actor = await register_telegram_user(db, message.from_user)
    target = actor
    if message.chat.type in {"group", "supergroup"}:
        replied = await resolve_reply_target(message, db)
        if replied:
            target = replied
    editable = int(target["user_id"]) == message.from_user.id
    if not await can_view_profile(db, settings, message.from_user.id, target):
        await message.answer("🔒 Этот профиль скрыт.")
        return
    text = await render_profile(db, settings, target)
    await send_profile_card(message, target, settings, editable=editable, text=text)


@router.callback_query(F.data.startswith("profile:"))
async def edit_profile(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, field, raw_user_id = parts
    user_id = int(raw_user_id)
    if callback.from_user.id != user_id:
        await callback.answer("Можно редактировать только свой профиль.", show_alert=True)
        return
    if field == "public":
        await db.update_profile(user_id, "profile_private", 0)
        await callback.answer("Профиль снова открыт.")
        user = await db.get_user(user_id)
        if user and callback.message:
            try:
                await callback.message.edit_reply_markup(reply_markup=profile_keyboard(user_id, False))
            except TelegramBadRequest:
                pass
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
    markup = flow_reply_keyboard() if callback.message.chat.type == "private" else None
    await callback.message.answer(prompt, reply_markup=markup)


@router.message(ProfileEdit.name)
async def edit_profile_name(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    text = (message.text or "").strip()
    if not message.from_user or not 1 <= len(text) <= 50:
        await message.answer("Имя должно содержать от 1 до 50 символов.")
        return
    await db.update_profile(message.from_user.id, "profile_name", text)
    await state.clear()
    await message.answer("Имя обновлено.")
    if message.chat.type == "private":
        await restore_private_menu(message, db, settings)


@router.message(ProfileEdit.age)
async def edit_profile_age(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
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
    if message.chat.type == "private":
        await restore_private_menu(message, db, settings)


@router.message(ProfileEdit.hobbies)
async def edit_profile_hobbies(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    text = (message.text or "").strip()
    if not message.from_user or not 1 <= len(text) <= 500:
        await message.answer("Увлечения — от 1 до 500 символов.")
        return
    await db.update_profile(message.from_user.id, "hobbies", text)
    await state.clear()
    await message.answer("Увлечения обновлены.")
    if message.chat.type == "private":
        await restore_private_menu(message, db, settings)


@router.message(ProfileEdit.avatar)
async def edit_profile_avatar(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not message.from_user or not message.photo:
        await message.answer("Нужно отправить фотографию.")
        return
    await db.update_profile(message.from_user.id, "avatar_file_id", message.photo[-1].file_id)
    await db.update_profile(message.from_user.id, "avatar_media_type", "photo")
    await state.clear()
    await message.answer("Аватар обновлён.")
    if message.chat.type == "private":
        await restore_private_menu(message, db, settings)
