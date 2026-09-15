from __future__ import annotations

import html
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto, Message

from community_bot.aliases import command_or_alias
from community_bot.blocks import cover_file
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.keyboards import flow_reply_keyboard, pet_keyboard, shop_category_keyboard
from community_bot.pet_cosmetics import render_pet_image
from community_bot.pets_talk import SPECIES, aftercare_line, pet_pronouns, species_meta
from community_bot.shop_catalog import SHOP_CATEGORIES, shop_prices_for
from community_bot.states import PetFlow
from community_bot.ui_owner import bind_ui_owner

router = Router(name="pets")

ASSETS = Path(__file__).resolve().parent.parent.parent / "assets" / "pets"


def _bar(value: int) -> str:
    filled = max(0, min(10, round(value / 10)))
    return "█" * filled + "░" * (10 - filled)


def pet_photo(species: str, equipped: list[str] | tuple[str, ...] | set[str] = ()) -> FSInputFile | None:
    path = render_pet_image(species, equipped)
    if path and path.is_file():
        return FSInputFile(path)
    fallback = ASSETS / f"{species}.png"
    return FSInputFile(fallback) if fallback.is_file() else None


def pet_text(pet: dict[str, object], equipped: list[str] | None = None) -> str:
    emoji, species = species_meta(str(pet["species"]))
    words = pet_pronouns(str(pet["species"]))
    hunger = int(pet["hunger"])
    thirst = int(pet["thirst"])
    mood = int(pet["mood"])
    sleeping = bool(int(pet["sleeping"]))
    farm_milli = int(pet["farm_milli"])
    status = f"💤 {words['sleep_status']}" if sleeping else f"✨ {words['awake']}"
    from community_bot.pet_cosmetics import COSMETIC_ITEMS, cosmetic_bonus_milli

    worn = equipped or []
    bonus = cosmetic_bonus_milli(worn)
    cosmetic_line = ""
    if worn:
        labels = ", ".join(str(COSMETIC_ITEMS[item]["label"]) for item in worn if item in COSMETIC_ITEMS)
        cosmetic_line = f"🎨 На {words['him']}: {labels} · фарм +{bonus}/ч\n"
    return (
        f"{emoji} <b>{html.escape(str(pet['name']))}</b> · {species}\n"
        f"{status}\n\n"
        f"🍗 Сытость: <b>{hunger}/100</b>\n<code>{_bar(hunger)}</code>\n"
        f"💧 Жажда: <b>{thirst}/100</b>\n<code>{_bar(thirst)}</code>\n"
        f"😊 Настроение: <b>{mood}/100</b>\n<code>{_bar(mood)}</code>\n\n"
        f"🎒 Припасы: {pet['food_units']} еды · {pet['water_units']} воды\n"
        f"🍪 Крошки: <b>{farm_milli}/1000</b> до печеньки\n"
        f"{cosmetic_line}\n"
        f"{_expedition_line(pet, words)}"
        f"Покорми или напои — {species} живёт в чате, не в личке."
    )


def _expedition_line(pet: dict[str, object], words: dict[str, str]) -> str:
    until = str(pet.get("expedition_until") or "")
    if not until:
        return ""
    return f"🌲 Сейчас в экспедиции. {words['returned'].capitalize()} с добычей.\n\n"


async def _equipped(db: Database, user_id: int) -> list[str]:
    return await db.equipped_cosmetics(user_id)


async def send_pet_card(message: Message, pet: dict[str, object], db: Database | None = None) -> Message | None:
    equipped = await _equipped(db, int(pet["user_id"])) if db else []
    text = pet_text(pet, equipped)
    photo = pet_photo(str(pet["species"]), equipped)
    sent: Message | None = None
    if photo:
        try:
            sent = await message.answer_photo(photo, caption=text, parse_mode="HTML", reply_markup=pet_keyboard())
        except TelegramBadRequest:
            sent = None
    if sent is None:
        cover = cover_file("pet")
        if cover:
            try:
                sent = await message.answer_photo(cover, caption=text, parse_mode="HTML", reply_markup=pet_keyboard())
            except TelegramBadRequest:
                sent = None
    if sent is None:
        sent = await message.answer(text, parse_mode="HTML", reply_markup=pet_keyboard())
    if db and message.from_user:
        await bind_ui_owner(db, sent, message.from_user.id, "pet")
    return sent


async def refresh_pet_card(target: Message, pet: dict[str, object], db: Database | None = None) -> None:
    equipped = await _equipped(db, int(pet["user_id"])) if db else []
    text = pet_text(pet, equipped)
    photo = pet_photo(str(pet["species"]), equipped)
    if photo:
        try:
            await target.edit_media(
                InputMediaPhoto(media=photo, caption=text, parse_mode="HTML"),
                reply_markup=pet_keyboard(),
            )
            return
        except TelegramBadRequest:
            pass
    try:
        await target.edit_caption(caption=text, parse_mode="HTML", reply_markup=pet_keyboard())
        return
    except TelegramBadRequest:
        pass
    try:
        await target.edit_text(text, parse_mode="HTML", reply_markup=pet_keyboard())
    except TelegramBadRequest:
        await send_pet_card(target, pet, db)


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
        await refresh_pet_card(message, pet, db)
        return
    await send_pet_card(message, pet, db)


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
    emoji, label, _gender = SPECIES[species]
    words = pet_pronouns(species)
    markup = flow_reply_keyboard() if callback.message.chat.type == "private" else None
    await callback.message.answer(
        f"Вы выбрали {emoji} {label}. Как {words['name_how']} назвать? До 24 символов.\n"
        "Чтобы отменить, откройте меню.",
        reply_markup=markup,
    )


@router.message(PetFlow.name)
async def create_pet(message: Message, state: FSMContext, db: Database) -> None:
    if not message.from_user:
        return
    name = (message.text or "").strip()
    if not 1 <= len(name) <= 24:
        await message.answer("Имя должно содержать от 1 до 24 символов.")
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
    await send_pet_card(message, pet, db)


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
    await refresh_pet_card(callback.message, pet, db)
    await callback.message.answer(aftercare_line(pet, kind))


@router.callback_query(F.data == "pet:rename")
async def begin_rename(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not callback.message:
        return
    pet = await db.get_pet(callback.from_user.id, settle=False)
    await state.set_state(PetFlow.rename)
    await state.set_data({"flow_kind": "pet_rename"})
    await callback.answer()
    markup = flow_reply_keyboard() if callback.message.chat.type == "private" else None
    words = pet_pronouns(str((pet or {}).get("species") or ""))
    await callback.message.answer(
        f"Введите новое имя — до 24 символов. Сейчас зовут {words['pet_acc']}.",
        reply_markup=markup,
    )


@router.message(PetFlow.rename)
async def rename_pet(message: Message, state: FSMContext, db: Database) -> None:
    if not message.from_user:
        return
    name = (message.text or "").strip()
    if not 1 <= len(name) <= 24:
        await message.answer("Имя должно содержать от 1 до 24 символов.")
        return
    pet = await db.get_pet(message.from_user.id, settle=False)
    if not await db.rename_pet(message.from_user.id, name):
        await state.clear()
        await message.answer("Питомец не найден.")
        return
    await state.clear()
    words = pet_pronouns(str((pet or {}).get("species") or ""))
    await message.answer(
        f"✅ Теперь {words['pet_acc']} зовут {html.escape(name)}.",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "pet:expedition")
async def pet_expedition(callback: CallbackQuery, db: Database) -> None:
    if not callback.message:
        return
    pet = await db.get_pet(callback.from_user.id, settle=False)
    ok, error, _reward = await db.start_expedition(callback.from_user.id)
    if not ok:
        await callback.answer(error, show_alert=True)
        return
    from community_bot.life import unlock

    await unlock(db, callback.from_user.id, "expedition")
    words = pet_pronouns(str((pet or {}).get("species") or ""))
    await callback.answer(f"{words['went'].capitalize()} в лес на 4 часа.")
    pet = await db.get_pet(callback.from_user.id, settle=False)
    if pet:
        await refresh_pet_card(callback.message, pet, db)
    await callback.message.answer(
        f"🌲 {html.escape(str((pet or {}).get('name') or 'Питомец'))} {words['went']} в экспедицию на 4 часа. "
        f"{words['returned'].capitalize()} с 🍪 — пинг будет в чат."
    )


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
    sent = await callback.message.answer(
        f"{meta['title']}\nБаланс: {user['cookies']} 🍪\n\n{meta['intro']}",
        reply_markup=shop_category_keyboard("pets", prices),
    )
    await bind_ui_owner(db, sent, callback.from_user.id, "shop")


@router.callback_query(F.data == "pet:custom")
async def pet_custom(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not callback.from_user:
        await callback.answer()
        return
    user = await db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Сначала откройте /start.", show_alert=True)
        return
    prices = shop_prices_for(user, settings.restricted_reputation_threshold)
    owned, equipped = await db.pet_cosmetic_sets(callback.from_user.id)
    await callback.answer()
    meta = SHOP_CATEGORIES["cosmetics"]
    sent = await callback.message.answer(
        f"{meta['title']}\nБаланс: {user['cookies']} 🍪\n\n{meta['intro']}",
        reply_markup=shop_category_keyboard("cosmetics", prices, owned=owned, equipped=equipped),
    )
    await bind_ui_owner(db, sent, callback.from_user.id, "shop")
