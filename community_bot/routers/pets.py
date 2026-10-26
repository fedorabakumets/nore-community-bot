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
from community_bot.expedition import (
    ExpeditionLoot,
    announce_expedition_result,
    parse_loot,
    remaining_label,
)
from community_bot.keyboards import flow_reply_keyboard, pet_keyboard, shop_category_keyboard
from community_bot.menu_art import menu_cover
from community_bot.pets_talk import SPECIES, aftercare_line, pet_pronouns, species_meta
from community_bot.shop_catalog import shop_header_lines, shop_prices_for
from community_bot.states import PetFlow
from community_bot.ui_owner import bind_ui_owner

router = Router(name="pets")

ASSETS = Path(__file__).resolve().parent.parent.parent / "assets" / "pets"


def _bar(value: int) -> str:
    filled = max(0, min(10, round(value / 10)))
    return "█" * filled + "░" * (10 - filled)


def pet_photo(species: str) -> FSInputFile | None:
    modern = menu_cover(f"pet_{species}")
    if modern:
        return FSInputFile(modern)
    fallback = ASSETS / f"{species}.png"
    return FSInputFile(fallback) if fallback.is_file() else None


def pet_text(pet: dict[str, object], timezone: str = "Europe/Moscow") -> str:
    emoji, species = species_meta(str(pet["species"]))
    words = pet_pronouns(str(pet["species"]))
    hunger = int(pet["hunger"])
    thirst = int(pet["thirst"])
    mood = int(pet["mood"])
    sleeping = bool(int(pet["sleeping"]))
    status = f"💤 {words['sleep_status']}" if sleeping else f"✨ {words['awake']}"
    return (
        f"{emoji} <b>{html.escape(str(pet['name']))}</b> · {species}\n"
        f"{status}\n\n"
        "Тамагочи — ваш талисман, который сыщет для вас самые редкие вещи!\n"
        "Через него в сообществе появляются сезонные находки, титулы, коллекционные награды "
        "и особые призы с мероприятий.\n\n"
        f"🍗 Сытость: <b>{hunger}/100</b>\n<code>{_bar(hunger)}</code>\n"
        f"💧 Жажда: <b>{thirst}/100</b>\n<code>{_bar(thirst)}</code>\n"
        f"😊 Настроение: <b>{mood}/100</b>\n<code>{_bar(mood)}</code>\n\n"
        f"🎒 Припасы: {pet['food_units']} еды · {pet['water_units']} воды\n\n"
        f"{_expedition_line(pet, words, timezone)}"
        "Печеньки талисман приносит только из экспедиции — сам по себе он их не фармит."
    )


def _expedition_line(pet: dict[str, object], words: dict[str, str], timezone: str) -> str:
    until = str(pet.get("expedition_until") or "")
    if until:
        left = remaining_label(until, timezone)
        return (
            f"🗺 Сейчас в экспедиции ({left}). {words['returned'].capitalize()} с находкой — "
            "одно сообщение в чат и в личку.\n\n"
        )
    return "🗺 Можно отправить в экспедицию раз в 24 часа. Находка: 1–10 🍪, крупные награды очень редки.\n\n"


async def _maybe_announce(message: Message, db: Database, settings: Settings, pet: dict[str, object]) -> None:
    sent = pet.get("expedition_notice_sent")
    if sent is None:
        sent = 1
    if not pet.get("expedition_done") and int(sent):
        return
    raw_loot = pet.get("expedition_loot")
    loot = ExpeditionLoot.from_mapping(raw_loot) if isinstance(raw_loot, dict) else parse_loot(str(raw_loot or ""))
    if loot is None:
        await db.claim_expedition_notice(int(pet["user_id"]))
        return
    await announce_expedition_result(message.bot, db, settings, int(pet["user_id"]), pet, loot)


async def send_pet_card(
    message: Message,
    pet: dict[str, object],
    db: Database | None = None,
    settings: Settings | None = None,
) -> Message | None:
    timezone = settings.timezone if settings else "Europe/Moscow"
    text = pet_text(pet, timezone)
    photo = pet_photo(str(pet["species"]))
    sent: Message | None = None
    markup = pet_keyboard(pet, timezone)
    if photo:
        try:
            sent = await message.answer_photo(photo, caption=text, parse_mode="HTML", reply_markup=markup)
        except TelegramBadRequest:
            sent = None
    if sent is None:
        cover = cover_file("pet")
        if cover:
            try:
                sent = await message.answer_photo(cover, caption=text, parse_mode="HTML", reply_markup=markup)
            except TelegramBadRequest:
                sent = None
    if sent is None:
        sent = await message.answer(text, parse_mode="HTML", reply_markup=markup)
    if db and message.from_user:
        await bind_ui_owner(db, sent, message.from_user.id, "pet")
    return sent


async def refresh_pet_card(
    target: Message,
    pet: dict[str, object],
    db: Database | None = None,
    settings: Settings | None = None,
) -> None:
    timezone = settings.timezone if settings else "Europe/Moscow"
    text = pet_text(pet, timezone)
    photo = pet_photo(str(pet["species"]))
    markup = pet_keyboard(pet, timezone)
    if photo:
        try:
            await target.edit_media(
                InputMediaPhoto(media=photo, caption=text, parse_mode="HTML"),
                reply_markup=markup,
            )
            return
        except TelegramBadRequest:
            pass
    try:
        await target.edit_caption(caption=text, parse_mode="HTML", reply_markup=markup)
        return
    except TelegramBadRequest:
        pass
    try:
        await target.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except TelegramBadRequest:
        await send_pet_card(target, pet, db, settings)


async def _show_pet(
    message: Message,
    db: Database,
    user_id: int,
    settings: Settings,
    *,
    replace: bool = False,
) -> None:
    pet = await db.get_pet(user_id)
    if not pet:
        text = "У вас пока нет тамагочи. Откройте магазин снизу."
        if replace:
            from community_bot.blocks import replace_block

            await replace_block(message, "pet", text, parse_mode="HTML")
            return
        await message.answer(text)
        return
    await _maybe_announce(message, db, settings, pet)
    if replace:
        await refresh_pet_card(message, pet, db, settings)
        return
    await send_pet_card(message, pet, db, settings)


@router.message(command_or_alias("pet"))
@router.message(F.text == "🐾 Тамагочи")
async def show_pet(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    await _show_pet(message, db, message.from_user.id, settings)


@router.callback_query(F.data.startswith("pet:species:"))
async def choose_species(callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message:
        return
    if not await db.feature_enabled("tamagotchi"):
        await callback.answer("Тамагочи временно выключены администрацией.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Откройте покупку питомца заново.", show_alert=True)
        return
    _, _, species, token = parts
    if species not in SPECIES:
        await callback.answer("Неизвестный питомец.", show_alert=True)
        return
    intent = await db.get_wallet_intent(callback.from_user.id, token)
    if not intent or intent["item"] != "tamagotchi" or intent["target_id"] != callback.from_user.id:
        await callback.answer("Покупка устарела или уже выполнена. Откройте магазин заново.", show_alert=True)
        return
    price = int(intent["price"])
    await state.set_state(PetFlow.name)
    await state.set_data({
        "pet_species": species, "pet_price": price, "purchase_intent": token, "flow_kind": "pet_name",
    })
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
async def create_pet(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    name = (message.text or "").strip()
    if not 1 <= len(name) <= 24:
        await message.answer("Имя должно содержать от 1 до 24 символов.")
        return
    data = await state.get_data()
    if not data.get("purchase_intent"):
        await message.answer("Покупка устарела. Откройте магазин заново.")
        return
    species = str(data["pet_species"])
    price = int(data["pet_price"])
    ok, error = await db.purchase_pet(
        message.from_user.id, species, name, price, intent_id=str(data["purchase_intent"]),
    )
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
    await send_pet_card(message, pet, db, settings)


@router.callback_query(F.data.startswith("pet:custom"))
@router.callback_query(F.data.startswith("pet:look"))
async def stale_pet_custom(callback: CallbackQuery) -> None:
    await callback.answer("Кастомизация тамагочи больше недоступна. Теперь это талисман экспедиций.", show_alert=True)


@router.callback_query(F.data.startswith("pet:use:"))
async def use_supply(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message:
        return
    kind = callback.data.rsplit(":", 1)[1]
    ok, error, pet = await db.use_pet_supply(callback.from_user.id, kind)
    if not ok or not pet:
        await callback.answer(error, show_alert=True)
        return
    await callback.answer("Готово!")
    await refresh_pet_card(callback.message, pet, db, settings)
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
async def pet_expedition(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message:
        return
    pet = await db.get_pet(callback.from_user.id)
    until = str((pet or {}).get("expedition_until") or "")
    if until:
        left = remaining_label(until, settings.timezone)
        await callback.answer(f"Талисман ещё в экспедиции ({left}).", show_alert=True)
        return
    ok, error, _reward = await db.start_expedition(callback.from_user.id, timezone=settings.timezone)
    if not ok:
        await callback.answer(error, show_alert=True)
        return
    from community_bot.life import unlock

    await unlock(db, callback.from_user.id, "expedition")
    await callback.answer("Талисман ушёл искать редкие вещи на 24 часа.")
    pet = await db.get_pet(callback.from_user.id, settle=False)
    if pet:
        await refresh_pet_card(callback.message, pet, db, settings)


@router.callback_query(F.data == "pet:shop")
async def pet_shop(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not callback.from_user:
        await callback.answer()
        return
    user = await db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Сначала откройте /start.", show_alert=True)
        return
    category = await db.get_shop_category("pets")
    items = await db.list_shop_items("pets", enabled_only=True, priced_only=True)
    prices = shop_prices_for(user, settings.restricted_reputation_threshold, await db.priced_shop_map())
    await callback.answer()
    header = shop_header_lines(await db.shop_header())
    title = str((category or {}).get("title") or "🐾 Тамагочи")
    intro = str((category or {}).get("description") or "")
    sent = await callback.message.answer(
        f"{header}{title}\nБаланс: {user['cookies']} 🍪\n\n{intro}",
        parse_mode="HTML",
        reply_markup=shop_category_keyboard("pets", prices, items=items),
    )
    await bind_ui_owner(db, sent, callback.from_user.id, "shop")
