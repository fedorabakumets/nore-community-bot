from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from community_bot.aliases import command_or_alias
from community_bot.blocks import cover_file, replace_block
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.helpers import (
    can_view_profile,
    register_telegram_user,
    render_profile,
    resolve_reply_target,
)
from community_bot.keyboards import (
    compact_profile_keyboard,
    flow_reply_keyboard,
    profile_keyboard,
    public_profile_keyboard,
)
from community_bot.profile_fill import cabinet_profile_text
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
    replace: bool = False,
) -> Message | None:
    user_id = int(user["user_id"])
    private_chat = getattr(message.chat, "type", None) == "private"
    if editable and private_chat:
        text = cabinet_profile_text(user)
        markup = compact_profile_keyboard(user)
        if replace:
            return await replace_block(message, "profile", text, parse_mode="HTML", reply_markup=markup)
        cover = cover_file("profile")
        if cover:
            try:
                return await message.answer_photo(cover, caption=text, parse_mode="HTML", reply_markup=markup)
            except TelegramBadRequest:
                pass
        return await message.answer(text, parse_mode="HTML", reply_markup=markup)
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
    cover = cover_file("profile")
    if cover:
        try:
            return await message.answer_photo(cover, caption=text, parse_mode="HTML", reply_markup=markup)
        except TelegramBadRequest:
            pass
    return await message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.message(command_or_alias("profile"))
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
        "bio": (ProfileEdit.bio, "Напишите описание профиля (до 280 символов). Это блок верификации."),
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


@router.message(ProfileEdit.bio)
async def edit_profile_bio(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    text = (message.text or "").strip()
    if not message.from_user or not 1 <= len(text) <= 280:
        await message.answer("Описание — от 1 до 280 символов.")
        return
    await db.update_profile(message.from_user.id, "profile_bio", text)
    await state.clear()
    await message.answer("Описание сохранено.")
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


@router.callback_query(F.data == "menu:verify")
async def menu_verify(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message:
        return
    user = await register_telegram_user(db, callback.from_user)
    await callback.answer()
    await send_profile_card(callback.message, user, settings, editable=True, text="", replace=True)


@router.callback_query(F.data == "p:rules")
async def profile_rules(callback: CallbackQuery, db: Database) -> None:
    if not callback.message:
        return
    user = await register_telegram_user(db, callback.from_user)
    await callback.answer()
    await replace_block(
        callback.message,
        "profile",
        "Пять блоков профиля: имя, возраст, увлечения, описание и фото.\n"
        "Без 100% репутация не выше серебра. Подробности — /commands.",
        parse_mode="HTML",
        reply_markup=compact_profile_keyboard(user),
    )


@router.callback_query(F.data == "p:warn")
async def profile_warn(callback: CallbackQuery, db: Database) -> None:
    if not callback.message:
        return
    user = await register_telegram_user(db, callback.from_user)
    await callback.answer()
    await replace_block(
        callback.message,
        "profile",
        "Предупреждение за пустое описание выдано всем при обновлении.\n"
        "Оно навсегда: заполнение описания шкалу поднимает, предупреждение не снимает.",
        parse_mode="HTML",
        reply_markup=compact_profile_keyboard(user),
    )
