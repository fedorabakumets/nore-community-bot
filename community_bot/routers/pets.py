from __future__ import annotations

import html
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from community_bot.aliases import command_or_alias
from community_bot.blocks import cover_file
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.keyboards import flow_reply_keyboard, pet_keyboard, shop_category_keyboard
from community_bot.pets_talk import SPECIES, aftercare_line, species_meta
from community_bot.shop_catalog import SHOP_CATEGORIES, shop_prices_for
from community_bot.states import PetFlow

router = Router(name="pets")

ASSETS = Path(__file__).resolve().parent.parent.parent / "assets" / "pets"


def _bar(value: int) -> str:
    filled = max(0, min(10, round(value / 10)))
    return "█" * filled + "░" * (10 - filled)


def pet_photo(species: str) -> FSInputFile | None:
    path = ASSETS / f"{species}.png"
    return FSInputFile(path) if path.is_file() else None


def pet_text(pet: dict[str, object]) -> str:
    emoji, species = species_meta(str(pet["species"]))
    hunger = int(pet["hunger"])
    thirst = int(pet["thirst"])
    mood = int(pet["mood"])
    sleeping = bool(int(pet["sleeping"]))
    farm_milli = int(pet["farm_milli"])
    status = "💤 сладко спит от голода или жажды" if sleeping else "✨ бодрствует и светится"
    return (
        f"{emoji} <b>{html.escape(str(pet['name']))}</b> · {species}\n"
        f"{status}\n\n"
        f"🍗 Сытость: <b>{hunger}/100</b>\n<code>{_bar(hunger)}</code>\n"
        f"💧 Жажда: <b>{thirst}/100</b>\n<code>{_bar(thirst)}</code>\n"
        f"😊 Настроение: <b>{mood}/100</b>\n<code>{_bar(mood)}</code>\n\n"
        f"🎒 Припасы: {pet['food_units']} еды · {pet['water_units']} воды\n"
        f"🍪 Крошки: <b>{farm_milli}/1000</b> до печеньки\n\n"
        f"{_expedition_line(pet)}"
        "Покорми или напои — малыш живёт в чате, не в личке."
    )


def _expedition_line(pet: dict[str, object]) -> str:
    until = str(pet.get("expedition_until") or "")
    if not until:
        return ""
    return "🌲 Сейчас в экспедиции. Вернётся с добычей.\n\n"


async def send_pet_card(message: Message, pet: dict[str, object]) -> None:
    text = pet_text(pet)
    photo = pet_photo(str(pet["species"]))
    if photo:
        try:
            await message.answer_photo(photo, caption=text, parse_mode="HTML", reply_markup=pet_keyboard())
            return
        except TelegramBadRequest:
            pass
    cover = cover_file("pet")
    if cover:
        try:
            await message.answer_photo(cover, caption=text, parse_mode="HTML", reply_markup=pet_keyboard())
            return
        except TelegramBadRequest:
            pass
    await message.answer(text, parse_mode="HTML", reply_markup=pet_keyboard())


async def refresh_pet_card(target: Message, pet: dict[str, object]) -> None:
    text = pet_text(pet)
    try:
        await target.edit_caption(caption=text, parse_mode="HTML", reply_markup=pet_keyboard())
        return
    except TelegramBadRequest:
        pass
    try:
        await target.edit_text(text, parse_mode="HTML", reply_markup=pet_keyboard())
    except TelegramBadRequest:
        await send_pet_card(target, pet)


async def _show_pet(message: Message, db: Database, user_id: int, *, replace: bool = False) -> None:
    pet = await db.get_pet(user_id)
    if not pet:
        text = "У вас пока нет тамагочи. Откройте магазин снизу."
        if replace:
            from community_bot.blocks import replace_block

            await replace_block(message, "pet", text, parse_mode="HTML")
            return
        await message.answer(text)
        return
    if replace:
        await refresh_pet_card(message, pet)
        return
    await send_pet_card(message, pet)


@router.message(command_or_alias("pet"))
@router.message(F.text == "🐾 Тамагочи")
async def show_pet(message: Message, db: Database) -> None:
    if not message.from_user:
        return
    await _show_pet(message, db, message.from_user.id)


@router.callback_query(F.data.startswith("pet:species:"))
async def choose_species(callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message:
        return
    if not await db.feature_enabled("tamagotchi"):
        await callback.answer("Тамагочи временно выключены администрацией.", show_alert=True)
        return
    _, _, species, raw_price = callback.data.split(":")
    if species not in SPECIES:
        await callback.answer("Неизвестный питомец.", show_alert=True)
        return
    price = int(raw_price)
    await state.set_state(PetFlow.name)
    await state.set_data({"pet_species": species, "pet_price": price, "flow_kind": "pet_name"})
    await callback.answer()
    emoji, label = SPECIES[species]
    markup = flow_reply_keyboard() if callback.message.chat.type == "private" else None
    await callback.message.answer(
        f"Вы выбрали {emoji} {label}. Как его назвать? До 24 символов.\n"
        "Чтобы отменить, откройте меню.",
        reply_markup=markup,
    )


@router.message(PetFlow.name)
async def create_pet(message: Message, state: FSMContext, db: Database) -> None:
    if not message.from_user:
        return
    name = (message.text or "").strip()
    if not 1 <= len(name) <= 24:
        await message.answer("Имя питомца должно содержать от 1 до 24 символов.")
        return
    data = await state.get_data()
    species = str(data["pet_species"])
    price = int(data["pet_price"])
    ok, error = await db.purchase_pet(message.from_user.id, species, name, price)
    await state.clear()
    if not ok:
        await message.answer(error)
        return
    from community_bot.life import unlock

    await unlock(db, message.from_user.id, "first_pet")
    pet = await db.get_pet(message.from_user.id, settle=False)
    assert pet is not None
    await message.answer(
        f"✅ {SPECIES[species][0]} <b>{html.escape(name)}</b> теперь живёт у вас. Списано {price} 🍪.",
        parse_mode="HTML",
    )
    await send_pet_card(message, pet)


@router.callback_query(F.data.startswith("pet:use:"))
async def use_supply(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    kind = callback.data.rsplit(":", 1)[1]
    ok, error, pet = await db.use_pet_supply(callback.from_user.id, kind)
    if not ok or not pet:
        await callback.answer(error, show_alert=True)
        return
    await callback.answer("Готово!")
    await refresh_pet_card(callback.message, pet)
    await callback.message.answer(aftercare_line(pet, kind))


@router.callback_query(F.data == "pet:rename")
async def begin_rename(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        return
    await state.set_state(PetFlow.rename)
    await state.set_data({"flow_kind": "pet_rename"})
    await callback.answer()
    markup = flow_reply_keyboard() if callback.message.chat.type == "private" else None
    await callback.message.answer("Введите новое имя питомца — до 24 символов.", reply_markup=markup)


@router.message(PetFlow.rename)
async def rename_pet(message: Message, state: FSMContext, db: Database) -> None:
    if not message.from_user:
        return
    name = (message.text or "").strip()
    if not 1 <= len(name) <= 24:
        await message.answer("Имя питомца должно содержать от 1 до 24 символов.")
        return
    if not await db.rename_pet(message.from_user.id, name):
        await state.clear()
        await message.answer("Питомец не найден.")
        return
    await state.clear()
    await message.answer(f"✅ Теперь питомца зовут {html.escape(name)}.", parse_mode="HTML")


@router.callback_query(F.data == "pet:expedition")
async def pet_expedition(callback: CallbackQuery, db: Database) -> None:
    if not callback.message:
        return
    ok, error, _reward = await db.start_expedition(callback.from_user.id)
    if not ok:
        await callback.answer(error, show_alert=True)
        return
    from community_bot.life import unlock

    await unlock(db, callback.from_user.id, "expedition")
    await callback.answer("Ушёл в лес на 4 часа.")
    pet = await db.get_pet(callback.from_user.id, settle=False)
    if pet:
        await refresh_pet_card(callback.message, pet)
    await callback.message.answer("🌲 Питомец ушёл в экспедицию на 4 часа. Вернётся с 🍪 — пинг будет в чат.")


@router.callback_query(F.data == "pet:shop")
async def pet_shop(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not callback.from_user:
        await callback.answer()
        return
    user = await db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Сначала откройте /start.", show_alert=True)
        return
    prices = shop_prices_for(user, settings.restricted_reputation_threshold)
    await callback.answer()
    meta = SHOP_CATEGORIES["pets"]
    await callback.message.answer(
        f"{meta['title']}\nБаланс: {user['cookies']} 🍪\n\n{meta['intro']}",
        reply_markup=shop_category_keyboard("pets", prices),
    )
