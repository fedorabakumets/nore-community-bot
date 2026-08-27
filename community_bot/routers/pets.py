from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from community_bot.config import Settings
from community_bot.database import Database
from community_bot.keyboards import pet_keyboard
from community_bot.states import PetFlow

router = Router(name="pets")

SPECIES = {
    "cat": ("🐈", "кот"),
    "dog": ("🐕", "пёс"),
    "raccoon": ("🦝", "енот"),
    "fox": ("🦊", "лиса"),
    "dragon": ("🐉", "дракончик"),
}


def _bar(value: int) -> str:
    filled = max(0, min(10, round(value / 10)))
    return "█" * filled + "░" * (10 - filled)


def pet_text(pet: dict[str, object]) -> str:
    emoji, species = SPECIES.get(str(pet["species"]), ("🐾", "питомец"))
    hunger = int(pet["hunger"])
    thirst = int(pet["thirst"])
    mood = int(pet["mood"])
    sleeping = bool(int(pet["sleeping"]))
    farm_milli = int(pet["farm_milli"])
    status = "💤 спит от голода или жажды" if sleeping else "✨ бодрствует"
    return (
        f"{emoji} <b>{html.escape(str(pet['name']))}</b> · {species}\n"
        f"Состояние: {status}\n\n"
        f"🍗 Сытость: <b>{hunger}/100</b>\n<code>{_bar(hunger)}</code>\n"
        f"💧 Жажда: <b>{thirst}/100</b>\n<code>{_bar(thirst)}</code>\n"
        f"😊 Настроение: <b>{mood}/100</b>\n<code>{_bar(mood)}</code>\n\n"
        f"🎒 Припасы: {pet['food_units']} еды · {pet['water_units']} воды\n"
        f"🍪 Найдено крошек: <b>{farm_milli}/1000</b> до следующей печеньки\n\n"
        "За каждые 50 сообщений в чате выдаётся еда и вода. "
        "Сытый питомец приносит 0,1–0,3 🍪 каждые 6 часов; целая печенька начисляется после накопления 1000 крошек."
    )


async def _send_pet(message: Message, db: Database) -> None:
    if not message.from_user:
        return
    pet = await db.get_pet(message.from_user.id)
    if not pet:
        await message.answer("У вас пока нет тамагочи. Его можно завести в /shop за 50 🍪 со скидкой уровня.")
        return
    await message.answer(pet_text(pet), parse_mode="HTML", reply_markup=pet_keyboard())


@router.message(Command("pet"), F.chat.type == "private")
async def show_pet_private(message: Message, db: Database) -> None:
    await _send_pet(message, db)


@router.message(Command("pet"), F.chat.type.in_({"group", "supergroup"}))
async def show_pet_group(message: Message, db: Database) -> None:
    if not message.from_user:
        return
    try:
        await message.bot.send_message(message.from_user.id, "🐾 Ваш тамагочи:")
        pet = await db.get_pet(message.from_user.id)
        if pet:
            await message.bot.send_message(
                message.from_user.id,
                pet_text(pet),
                parse_mode="HTML",
                reply_markup=pet_keyboard(),
            )
        else:
            await message.bot.send_message(
                message.from_user.id,
                "У вас пока нет тамагочи. Его можно завести в /shop за 50 🍪 со скидкой уровня.",
            )
    except Exception:
        await message.answer("Сначала откройте личный чат с ботом и нажмите Start.")


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
    await state.set_data({"pet_species": species, "pet_price": price})
    await callback.answer()
    await callback.message.answer(
        f"Вы выбрали {SPECIES[species][0]} {SPECIES[species][1]}. Как его назвать? До 24 символов."
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
    pet = await db.get_pet(message.from_user.id, settle=False)
    assert pet is not None
    await message.answer(
        f"✅ {SPECIES[species][0]} <b>{html.escape(name)}</b> теперь живёт у вас. Списано {price} 🍪.",
        parse_mode="HTML",
    )
    await message.answer(pet_text(pet), parse_mode="HTML", reply_markup=pet_keyboard())


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
    await callback.message.edit_text(pet_text(pet), parse_mode="HTML", reply_markup=pet_keyboard())


@router.callback_query(F.data == "pet:rename")
async def begin_rename(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        return
    await state.set_state(PetFlow.rename)
    await callback.answer()
    await callback.message.answer("Введите новое имя питомца — до 24 символов.")


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


@router.callback_query(F.data == "pet:shop")
async def pet_shop(callback: CallbackQuery) -> None:
    if callback.message:
        await callback.message.answer("Откройте /shop — корм и вода находятся в общем магазине.")
    await callback.answer()
