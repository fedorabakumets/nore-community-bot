from __future__ import annotations

import html
import json
import re
import secrets
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from community_bot.blocks import answer_block
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.keyboards import STYLE_CLOSE, STYLE_FUN, STYLE_GO, back_btn, close_btn, flow_reply_keyboard, ibtn
from community_bot.permissions import PERM_FEATURES, PERM_USERS_EDIT, slugify_role
from community_bot.shop_catalog import (
    cookie_pack_label,
    cookie_rate_line,
    cookie_shop_member_text,
    parse_cookie_packs,
    shop_header_lines,
)
from community_bot.states import ShopAdminFlow

router = Router(name="shop_admin")


async def _allowed(callback: CallbackQuery, db: Database, settings: Settings) -> bool:
    from community_bot.helpers import has_permission

    user_id = callback.from_user.id
    if settings.is_owner(user_id):
        return True
    if await has_permission(db, settings, user_id, PERM_FEATURES):
        return True
    if await has_permission(db, settings, user_id, PERM_USERS_EDIT):
        return True
    await callback.answer("Недостаточно прав.", show_alert=True)
    return False


def _home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("📦 Товары", "ashop:items", STYLE_GO), ibtn("📁 Категории", "ashop:cats", STYLE_FUN)],
            [ibtn("➕ Создать товар", "ashop:newitem", STYLE_GO), ibtn("➕ Создать категорию", "ashop:newcat")],
            [ibtn("📝 Шапка магазина", "ashop:header", STYLE_FUN)],
            [ibtn("🍪 Покупка печенек", "ashop:cookies", STYLE_GO)],
            [ibtn("📋 Предпросмотр", "ashop:preview")],
            [back_btn("admin:panel"), close_btn("ui:close")],
        ]
    )


def _items_keyboard(items: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: list[list[Any]] = []
    for item in items:
        sku = str(item["sku"])
        price = item.get("price")
        mark = "👁" if int(item.get("enabled") or 0) else "🙈"
        price_label = "без цены" if price is None else f"{price} 🍪"
        rows.append([ibtn(f"{mark} {item['title']} · {price_label}"[:60], f"ashop:item:{sku}")])
    rows.append([ibtn("➕ Создать товар", "ashop:newitem", STYLE_GO)])
    rows.append([back_btn("ashop:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cats_keyboard(categories: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: list[list[Any]] = []
    for row in categories:
        slug = str(row["slug"])
        rows.append([ibtn(str(row["title"])[:40], f"ashop:cat:{slug}")])
    rows.append([ibtn("➕ Создать категорию", "ashop:newcat", STYLE_GO)])
    rows.append([back_btn("ashop:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _item_keyboard(item: dict[str, Any], categories: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    sku = str(item["sku"])
    enabled = int(item.get("enabled") or 0)
    rows = [
        [ibtn("✏️ Название", f"ashop:iedit:title:{sku}"), ibtn("📝 Описание", f"ashop:iedit:desc:{sku}")],
        [ibtn("💰 Цена", f"ashop:iedit:price:{sku}"), ibtn("🖼 Картинка", f"ashop:iedit:image:{sku}")],
        [ibtn("⚙️ Доп. параметры", f"ashop:iedit:extra:{sku}")],
        [
            ibtn("👁 Включить" if not enabled else "🙈 Выключить", f"ashop:itog:{sku}"),
        ],
        [ibtn("⬆️", f"ashop:imove:{sku}:-1"), ibtn("⬇️", f"ashop:imove:{sku}:1")],
    ]
    cat_row = []
    for cat in categories:
        mark = "• " if cat["slug"] == item["category_slug"] else ""
        cat_row.append(ibtn(f"{mark}{cat['title']}"[:24], f"ashop:icat:{sku}:{cat['slug']}"))
        if len(cat_row) == 2:
            rows.append(cat_row)
            cat_row = []
    if cat_row:
        rows.append(cat_row)
    rows.append([ibtn("🗑 Удалить", f"ashop:idel:{sku}", STYLE_CLOSE)])
    rows.append([back_btn("ashop:items")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cat_keyboard(category: dict[str, Any]) -> InlineKeyboardMarkup:
    slug = str(category["slug"])
    builtin = slug in {"pets", "reputation", "profile"}
    enabled = int(category.get("enabled") or 0)
    rows = [
        [ibtn("✏️ Название", f"ashop:cedit:title:{slug}"), ibtn("📝 Описание", f"ashop:cedit:desc:{slug}")],
        [ibtn("👁 Включить" if not enabled else "🙈 Выключить", f"ashop:ctog:{slug}")],
        [ibtn("⬆️", f"ashop:cmove:{slug}:-1"), ibtn("⬇️", f"ashop:cmove:{slug}:1")],
    ]
    if not builtin:
        rows.append([ibtn("🗑 Удалить категорию", f"ashop:cdel:{slug}", STYLE_CLOSE)])
    rows.append([back_btn("ashop:cats")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cookies_keyboard(shop: dict[str, Any]) -> InlineKeyboardMarkup:
    enabled = bool(shop.get("enabled"))
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("Выключить" if enabled else "Включить", "ashop:cktog", STYLE_GO if not enabled else STYLE_CLOSE)],
            [ibtn("💱 Курс", "ashop:ckedit:rate"), ibtn("📦 Пакеты", "ashop:ckedit:packs")],
            [ibtn("✏️ Заголовок", "ashop:ckedit:title"), ibtn("📝 Текст", "ashop:ckedit:intro")],
            [ibtn("🔘 Кнопка в магазине", "ashop:ckedit:button")],
            [ibtn("📋 Предпросмотр блока", "ashop:ckpreview")],
            [back_btn("ashop:home")],
        ]
    )


def _cookie_shop_preview(shop: dict[str, Any]) -> str:
    status = "включён" if shop.get("enabled") else "выключен"
    rate = int(shop.get("rate_rub") or 1)
    packs = [int(item) for item in shop.get("packs") or []]
    pack_lines = "\n".join(f"• {cookie_pack_label(amount, rate)}" for amount in packs) or "• пакетов нет"
    return (
        f"🍪 <b>Покупка печенек</b>\n"
        f"Сейчас: <b>{status}</b>.\n"
        f"{cookie_rate_line(rate)}\n\n"
        f"Кнопка: <b>{html.escape(str(shop.get('button') or ''))}</b>\n"
        f"Заголовок: {html.escape(str(shop.get('title') or ''))}\n"
        f"{html.escape(str(shop.get('intro') or '') or 'без текста')}\n\n"
        f"<b>Пакеты</b>\n{pack_lines}"
    )


def _header_keyboard(header: dict[str, Any]) -> InlineKeyboardMarkup:
    enabled = bool(header.get("enabled"))
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("Выключить" if enabled else "Включить", "ashop:htog", STYLE_GO if not enabled else STYLE_CLOSE)],
            [ibtn("✏️ Заголовок", "ashop:hedit:title"), ibtn("📝 Текст", "ashop:hedit:text")],
            [ibtn("📋 Предпросмотр шапки", "ashop:hpreview")],
            [back_btn("ashop:home")],
        ]
    )


def _item_preview(item: dict[str, Any]) -> str:
    price = item.get("price")
    price_line = "Цена не задана — товар скрыт у участников." if price is None else f"Цена: <b>{int(price)} 🍪</b>"
    status = "показан" if int(item.get("enabled") or 0) else "скрыт"
    image = "есть" if str(item.get("image") or "").strip() else "нет"
    description = str(item.get("description") or "").strip() or "без описания"
    extra = str(item.get("extra_json") or "").strip()
    extra_line = f"\nДоп. параметры: <code>{html.escape(extra[:200])}</code>" if extra and extra != "{}" else ""
    return (
        f"📦 <b>{html.escape(str(item['title']))}</b>\n"
        f"<code>{html.escape(str(item['sku']))}</code> · {html.escape(str(item['category_slug']))}\n"
        f"{price_line}\n"
        f"Статус: {status} · картинка: {image}\n\n"
        f"{html.escape(description)}{extra_line}\n\n"
        "Так товар видит участник, когда цена задана и товар включён."
    )


async def _show_home(message: Message) -> None:
    await edit_or_answer(
        message,
        "🛠 <b>Управление магазином</b>\n\n"
        "Товары, категории, цены, картинки, шапка и блок покупки печенек. "
        "Курс 🍪 и пакеты СБП правятся здесь же — изменения сразу видны участникам.\n\n"
        "📦 Товары · 📁 Категории · 🍪 печеньки · ➕ создание · ✏️ правка · 🗑 удаление · "
        "💰 цены · 🖼 картинки · 📝 описания · 🔄 порядок · 👁 активность · 📋 предпросмотр.",
        _home_keyboard(),
    )


async def edit_or_answer(message: Message, text: str, markup: InlineKeyboardMarkup) -> None:
    try:
        await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        return
    except TelegramBadRequest:
        pass
    await answer_block(message, "admin", text, parse_mode="HTML", reply_markup=markup)


@router.callback_query(F.data == "ashop:home")
async def shop_admin_home(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _allowed(callback, db, settings):
        return
    await callback.answer()
    await _show_home(callback.message)


@router.callback_query(F.data == "ashop:items")
async def shop_admin_items(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _allowed(callback, db, settings):
        return
    items = await db.list_shop_items()
    await callback.answer()
    await edit_or_answer(
        callback.message,
        "📦 <b>Товары</b>\nВыберите позицию, чтобы править название, цену, картинку, категорию и порядок.",
        _items_keyboard(items),
    )


@router.callback_query(F.data == "ashop:cats")
async def shop_admin_cats(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _allowed(callback, db, settings):
        return
    cats = await db.list_shop_categories()
    await callback.answer()
    await edit_or_answer(
        callback.message,
        "📁 <b>Категории</b>\nПапки магазина. Внутри каждой — товары. Можно создавать сколько угодно.",
        _cats_keyboard(cats),
    )


@router.callback_query(F.data.startswith("ashop:item:"))
async def shop_admin_item(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not callback.data or not await _allowed(callback, db, settings):
        return
    sku = callback.data.split(":", 2)[2]
    item = await db.get_shop_item(sku)
    if not item:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    await callback.answer()
    cats = await db.list_shop_categories()
    text = _item_preview(item)
    markup = _item_keyboard(item, cats)
    image = str(item.get("image") or "").strip()
    if image:
        try:
            await callback.message.answer_photo(image, caption=text, parse_mode="HTML", reply_markup=markup)
            return
        except TelegramBadRequest:
            pass
    await edit_or_answer(callback.message, text, markup)


@router.callback_query(F.data.startswith("ashop:cat:"))
async def shop_admin_cat(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not callback.data or not await _allowed(callback, db, settings):
        return
    slug = callback.data.split(":", 2)[2]
    category = await db.get_shop_category(slug)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    items = await db.list_shop_items(slug)
    await callback.answer()
    await edit_or_answer(
        callback.message,
        f"📁 <b>{html.escape(str(category['title']))}</b>\n"
        f"<code>{html.escape(slug)}</code>\n\n"
        f"{html.escape(str(category.get('description') or 'без описания'))}\n\n"
        f"Товаров: <b>{len(items)}</b>.",
        _cat_keyboard(category),
    )


@router.callback_query(F.data.startswith("ashop:itog:"))
async def shop_admin_toggle_item(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not await _allowed(callback, db, settings):
        return
    sku = callback.data.rsplit(":", 1)[1]
    item = await db.get_shop_item(sku)
    if not item:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    nxt = 0 if int(item.get("enabled") or 0) else 1
    await db.upsert_shop_item(sku, enabled=nxt)
    await callback.answer("Включён." if nxt else "Скрыт.")
    callback.data = f"ashop:item:{sku}"
    await shop_admin_item(callback, db, settings)


@router.callback_query(F.data.startswith("ashop:ctog:"))
async def shop_admin_toggle_cat(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not await _allowed(callback, db, settings):
        return
    slug = callback.data.rsplit(":", 1)[1]
    category = await db.get_shop_category(slug)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    nxt = 0 if int(category.get("enabled") or 0) else 1
    await db.upsert_shop_category(slug, str(category["title"]), str(category.get("description") or ""), enabled=nxt)
    await callback.answer("Полка включена." if nxt else "Полка скрыта.")
    callback.data = f"ashop:cat:{slug}"
    await shop_admin_cat(callback, db, settings)


@router.callback_query(F.data.startswith("ashop:imove:"))
async def shop_admin_move_item(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not await _allowed(callback, db, settings):
        return
    _, _, sku, raw_dir = callback.data.split(":", 3)
    await db.shift_shop_item(sku, int(raw_dir))
    await callback.answer("Порядок обновлён.")
    callback.data = f"ashop:item:{sku}"
    await shop_admin_item(callback, db, settings)


@router.callback_query(F.data.startswith("ashop:cmove:"))
async def shop_admin_move_cat(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not await _allowed(callback, db, settings):
        return
    _, _, slug, raw_dir = callback.data.split(":", 3)
    await db.shift_shop_category(slug, int(raw_dir))
    await callback.answer("Порядок обновлён.")
    callback.data = f"ashop:cat:{slug}"
    await shop_admin_cat(callback, db, settings)


@router.callback_query(F.data.startswith("ashop:icat:"))
async def shop_admin_move_item_cat(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not await _allowed(callback, db, settings):
        return
    _, _, sku, slug = callback.data.split(":", 3)
    await db.upsert_shop_item(sku, category_slug=slug)
    await callback.answer("Товар перенесён.")
    callback.data = f"ashop:item:{sku}"
    await shop_admin_item(callback, db, settings)


@router.callback_query(F.data.startswith("ashop:idel:"))
async def shop_admin_delete_item(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not callback.data or not await _allowed(callback, db, settings):
        return
    sku = callback.data.rsplit(":", 1)[1]
    if not await db.delete_shop_item(sku):
        await callback.answer("Не удалось удалить.", show_alert=True)
        return
    await callback.answer("Товар удалён.")
    items = await db.list_shop_items()
    await edit_or_answer(callback.message, "📦 <b>Товары</b>", _items_keyboard(items))


@router.callback_query(F.data.startswith("ashop:cdel:"))
async def shop_admin_delete_cat(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not callback.data or not await _allowed(callback, db, settings):
        return
    slug = callback.data.rsplit(":", 1)[1]
    if not await db.delete_shop_category(slug):
        await callback.answer("Базовые полки удалять нельзя.", show_alert=True)
        return
    await callback.answer("Категория удалена.")
    cats = await db.list_shop_categories()
    await edit_or_answer(callback.message, "📁 <b>Категории</b>", _cats_keyboard(cats))


@router.callback_query(F.data == "ashop:newcat")
async def shop_admin_new_cat(callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    if not callback.message or not await _allowed(callback, db, settings):
        return
    await state.set_state(ShopAdminFlow.category_title)
    await state.set_data({"flow_kind": "shop_admin"})
    await callback.answer()
    await callback.message.answer("Название новой категории (папки):", reply_markup=flow_reply_keyboard())


@router.message(ShopAdminFlow.category_title)
async def shop_admin_save_cat_title(message: Message, state: FSMContext, db: Database) -> None:
    title = (message.text or "").strip()
    if not 2 <= len(title) <= 40:
        await message.answer("Название от 2 до 40 символов.")
        return
    await state.set_state(ShopAdminFlow.category_intro)
    await state.update_data(cat_title=title)
    await message.answer("Короткое описание полки. «-» чтобы оставить пустым.")


@router.message(ShopAdminFlow.category_intro)
async def shop_admin_save_cat(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    title = str(data.get("cat_title") or "")
    intro = "" if (message.text or "").strip() == "-" else (message.text or "").strip()
    base = slugify_role(title) or f"cat_{secrets.token_hex(3)}"
    slug = base
    index = 2
    while await db.get_shop_category(slug):
        slug = f"{base}_{index}"[:24]
        index += 1
    await db.upsert_shop_category(slug, title, intro)
    await state.clear()
    await message.answer(f"✅ Категория «{html.escape(title)}» создана.", parse_mode="HTML")


@router.callback_query(F.data == "ashop:newitem")
async def shop_admin_new_item(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _allowed(callback, db, settings):
        return
    cats = await db.list_shop_categories()
    rows = [[ibtn(str(cat["title"])[:40], f"ashop:newitemcat:{cat['slug']}")] for cat in cats]
    rows.append([back_btn("ashop:home")])
    await callback.answer()
    await edit_or_answer(
        callback.message,
        "Выберите папку для нового товара:",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("ashop:newitemcat:"))
async def shop_admin_new_item_cat(
    callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings
) -> None:
    if not callback.message or not callback.data or not await _allowed(callback, db, settings):
        return
    slug = callback.data.rsplit(":", 1)[1]
    if not await db.get_shop_category(slug):
        await callback.answer("Нет такой категории.", show_alert=True)
        return
    await state.set_state(ShopAdminFlow.item_title)
    await state.set_data({"item_cat": slug, "flow_kind": "shop_admin"})
    await callback.answer()
    await callback.message.answer("Название товара:", reply_markup=flow_reply_keyboard())


@router.message(ShopAdminFlow.item_title)
async def shop_admin_item_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not 2 <= len(title) <= 60:
        await message.answer("Название от 2 до 60 символов.")
        return
    await state.update_data(item_title=title)
    await state.set_state(ShopAdminFlow.item_description)
    await message.answer("Описание, как его увидит участник. «-» чтобы пропустить.")


@router.message(ShopAdminFlow.item_description)
async def shop_admin_item_desc(message: Message, state: FSMContext) -> None:
    text = "" if (message.text or "").strip() == "-" else (message.text or "").strip()
    await state.update_data(item_desc=text)
    await state.set_state(ShopAdminFlow.item_price)
    await message.answer("Цена в печеньках (целое число). «-» чтобы оставить без цены — товар будет скрыт.")


@router.message(ShopAdminFlow.item_price)
async def shop_admin_item_price(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    price: int | None
    if raw == "-":
        price = None
    else:
        if not re.fullmatch(r"\d{1,7}", raw):
            await message.answer("Введите целое число или «-».")
            return
        price = int(raw)
    await state.update_data(item_price=price)
    await state.set_state(ShopAdminFlow.item_image)
    await message.answer("Пришлите картинку товара или «-», чтобы без фото.")


@router.message(ShopAdminFlow.item_image)
async def shop_admin_item_image(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    image = ""
    if message.photo:
        image = message.photo[-1].file_id
    elif (message.text or "").strip() not in {"-", "—"}:
        await message.answer("Нужно фото или «-».")
        return
    title = str(data["item_title"])
    sku_base = slugify_role(title) or f"item_{secrets.token_hex(3)}"
    sku = sku_base
    index = 2
    while await db.get_shop_item(sku):
        sku = f"{sku_base}_{index}"[:24]
        index += 1
    price = data.get("item_price")
    await db.upsert_shop_item(
        sku,
        category_slug=str(data["item_cat"]),
        title=title,
        description=str(data.get("item_desc") or ""),
        price=price,
        image=image,
    )
    await state.clear()
    item = await db.get_shop_item(sku)
    preview = item or {"sku": sku, "title": title, "category_slug": data["item_cat"]}
    await message.answer(_item_preview(preview), parse_mode="HTML")


@router.callback_query(F.data.startswith("ashop:iedit:"))
async def shop_admin_edit_item_begin(
    callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings
) -> None:
    if not callback.message or not callback.data or not await _allowed(callback, db, settings):
        return
    _, _, field, sku = callback.data.split(":", 3)
    if not await db.get_shop_item(sku):
        await callback.answer("Товар не найден.", show_alert=True)
        return
    prompts = {
        "title": "Новое название товара:",
        "desc": "Новое описание. «-» чтобы очистить.",
        "price": "Новая цена (число) или «-», чтобы убрать цену.",
        "image": "Пришлите новое фото или «-», чтобы убрать картинку.",
        "extra": "Дополнительные параметры JSON, например {\"kind\":\"title\"}. «-» чтобы очистить.",
    }
    await state.set_state(ShopAdminFlow.edit_value)
    await state.set_data({"edit_target": "item", "edit_field": field, "edit_sku": sku, "flow_kind": "shop_admin"})
    await callback.answer()
    await callback.message.answer(prompts[field], reply_markup=flow_reply_keyboard())


@router.callback_query(F.data.startswith("ashop:cedit:"))
async def shop_admin_edit_cat_begin(
    callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings
) -> None:
    if not callback.message or not callback.data or not await _allowed(callback, db, settings):
        return
    _, _, field, slug = callback.data.split(":", 3)
    if not await db.get_shop_category(slug):
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    await state.set_state(ShopAdminFlow.edit_value)
    await state.set_data({"edit_target": "cat", "edit_field": field, "edit_sku": slug, "flow_kind": "shop_admin"})
    await callback.answer()
    prompt = "Новое название категории:" if field == "title" else "Новое описание. «-» чтобы очистить."
    await callback.message.answer(prompt, reply_markup=flow_reply_keyboard())


@router.message(ShopAdminFlow.edit_value)
async def shop_admin_save_edit(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    target = str(data.get("edit_target"))
    field = str(data.get("edit_field"))
    sku = str(data.get("edit_sku"))
    if target == "item":
        item = await db.get_shop_item(sku)
        if not item:
            await state.clear()
            await message.answer("Товар уже удалён.")
            return
        if field == "title":
            title = (message.text or "").strip()
            if not 2 <= len(title) <= 60:
                await message.answer("Название от 2 до 60 символов.")
                return
            await db.upsert_shop_item(sku, title=title)
        elif field == "desc":
            text = "" if (message.text or "").strip() == "-" else (message.text or "").strip()
            await db.upsert_shop_item(sku, description=text)
        elif field == "price":
            raw = (message.text or "").strip()
            if raw == "-":
                await db.upsert_shop_item(sku, price=None)
            elif re.fullmatch(r"\d{1,7}", raw):
                await db.upsert_shop_item(sku, price=int(raw))
            else:
                await message.answer("Число или «-».")
                return
        elif field == "image":
            if message.photo:
                await db.upsert_shop_item(sku, image=message.photo[-1].file_id)
            elif (message.text or "").strip() in {"-", "—"}:
                await db.upsert_shop_item(sku, image="")
            else:
                await message.answer("Фото или «-».")
                return
        elif field == "extra":
            raw = "" if (message.text or "").strip() == "-" else (message.text or "").strip()
            if raw:
                try:
                    parsed = json.loads(raw)
                    if not isinstance(parsed, dict):
                        await message.answer("Нужен JSON-объект, например {\"kind\":\"merch\"}.")
                        return
                    raw = json.dumps(parsed, ensure_ascii=False)
                except json.JSONDecodeError:
                    await message.answer("Некорректный JSON.")
                    return
            await db.upsert_shop_item(sku, extra_json=raw or "{}")
        await state.clear()
        fresh = await db.get_shop_item(sku)
        await message.answer(_item_preview(fresh or item), parse_mode="HTML")
        return
    category = await db.get_shop_category(sku)
    if not category:
        await state.clear()
        await message.answer("Категория уже удалена.")
        return
    if field == "title":
        title = (message.text or "").strip()
        if not 2 <= len(title) <= 40:
            await message.answer("Название от 2 до 40 символов.")
            return
        await db.upsert_shop_category(sku, title, str(category.get("description") or ""))
    else:
        text = "" if (message.text or "").strip() == "-" else (message.text or "").strip()
        await db.upsert_shop_category(sku, str(category["title"]), text)
    await state.clear()
    await message.answer("Категория обновлена.")


@router.callback_query(F.data == "ashop:header")
async def shop_admin_header(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _allowed(callback, db, settings):
        return
    header = await db.shop_header()
    await callback.answer()
    status = "включена" if header.get("enabled") else "выключена"
    preview = shop_header_lines(header) or "Шапка пустая."
    await edit_or_answer(
        callback.message,
        f"📝 <b>Шапка магазина</b>\nСейчас: <b>{status}</b>.\n"
        "Она показывается во всех полках магазина.\n\n"
        f"{preview}",
        _header_keyboard(header),
    )


@router.callback_query(F.data == "ashop:htog")
async def shop_admin_header_toggle(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not await _allowed(callback, db, settings):
        return
    header = await db.shop_header()
    await db.set_shop_header(enabled=not bool(header.get("enabled")))
    await callback.answer("Готово.")
    await shop_admin_header(callback, db, settings)


@router.callback_query(F.data.startswith("ashop:hedit:"))
async def shop_admin_header_edit(callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    if not callback.message or not callback.data or not await _allowed(callback, db, settings):
        return
    field = callback.data.rsplit(":", 1)[1]
    await state.set_state(ShopAdminFlow.header_title if field == "title" else ShopAdminFlow.header_text)
    await state.set_data({"flow_kind": "shop_admin"})
    await callback.answer()
    if field == "title":
        prompt = "Заголовок шапки, например: Курс на 21.09.2026"
    else:
        prompt = "Текст шапки, например: 🍪 1 печенька = 1 ₽"
    await callback.message.answer(prompt, reply_markup=flow_reply_keyboard())


@router.message(ShopAdminFlow.header_title)
async def shop_admin_header_title(message: Message, state: FSMContext, db: Database) -> None:
    await db.set_shop_header(title=(message.text or "").strip()[:80])
    await state.clear()
    await message.answer("Заголовок шапки сохранён.")


@router.message(ShopAdminFlow.header_text)
async def shop_admin_header_text(message: Message, state: FSMContext, db: Database) -> None:
    await db.set_shop_header(text=(message.text or "").strip()[:500])
    await state.clear()
    await message.answer("Текст шапки сохранён.")


@router.callback_query(F.data == "ashop:hpreview")
async def shop_admin_header_preview(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not await _allowed(callback, db, settings):
        return
    header = await db.shop_header()
    preview = shop_header_lines({**header, "enabled": True}) or "Шапка пустая."
    await callback.answer()
    if callback.message:
        await callback.message.answer("📋 Предпросмотр шапки:\n\n" + preview, parse_mode="HTML")


@router.callback_query(F.data == "ashop:cookies")
async def shop_admin_cookies(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _allowed(callback, db, settings):
        return
    shop = await db.cookie_shop()
    await callback.answer()
    await edit_or_answer(callback.message, _cookie_shop_preview(shop), _cookies_keyboard(shop))


@router.callback_query(F.data == "ashop:cktog")
async def shop_admin_cookies_toggle(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not await _allowed(callback, db, settings):
        return
    shop = await db.cookie_shop()
    await db.set_cookie_shop(enabled=not bool(shop.get("enabled")))
    await callback.answer("Готово.")
    await shop_admin_cookies(callback, db, settings)


@router.callback_query(F.data.startswith("ashop:ckedit:"))
async def shop_admin_cookies_edit(
    callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings
) -> None:
    if not callback.message or not callback.data or not await _allowed(callback, db, settings):
        return
    field = callback.data.rsplit(":", 1)[1]
    prompts = {
        "rate": "Сколько рублей стоит 1 печенька? Целое число, например 1.",
        "title": "Заголовок блока покупки печенек:",
        "intro": "Текст под курсом. «-» чтобы очистить.",
        "button": "Подпись кнопки в магазине, например: 🍪 Купить печеньки",
        "packs": "Пакеты — целые числа печенек через запятую.\nНапример: 10, 50, 100\nРубли посчитаются по курсу.",
    }
    states = {
        "rate": ShopAdminFlow.cookie_rate,
        "title": ShopAdminFlow.cookie_title,
        "intro": ShopAdminFlow.cookie_intro,
        "button": ShopAdminFlow.cookie_button,
        "packs": ShopAdminFlow.cookie_packs,
    }
    if field not in states:
        await callback.answer("Неизвестное поле.", show_alert=True)
        return
    await state.set_state(states[field])
    await state.set_data({"flow_kind": "shop_admin"})
    await callback.answer()
    await callback.message.answer(prompts[field], reply_markup=flow_reply_keyboard())


@router.message(ShopAdminFlow.cookie_rate)
async def shop_admin_cookie_rate(message: Message, state: FSMContext, db: Database) -> None:
    raw = (message.text or "").strip()
    if not re.fullmatch(r"\d{1,5}", raw) or int(raw) < 1:
        await message.answer("Введите целое число от 1.")
        return
    await db.set_cookie_shop(rate_rub=int(raw))
    await state.clear()
    shop = await db.cookie_shop()
    await message.answer(f"Курс сохранён: {cookie_rate_line(int(shop['rate_rub']))}.")


@router.message(ShopAdminFlow.cookie_title)
async def shop_admin_cookie_title(message: Message, state: FSMContext, db: Database) -> None:
    title = (message.text or "").strip()
    if not 2 <= len(title) <= 60:
        await message.answer("Заголовок от 2 до 60 символов.")
        return
    await db.set_cookie_shop(title=title)
    await state.clear()
    await message.answer("Заголовок блока сохранён.")


@router.message(ShopAdminFlow.cookie_intro)
async def shop_admin_cookie_intro(message: Message, state: FSMContext, db: Database) -> None:
    text = "" if (message.text or "").strip() == "-" else (message.text or "").strip()
    await db.set_cookie_shop(intro=text[:500])
    await state.clear()
    await message.answer("Текст блока сохранён.")


@router.message(ShopAdminFlow.cookie_button)
async def shop_admin_cookie_button(message: Message, state: FSMContext, db: Database) -> None:
    button = (message.text or "").strip()
    if not 2 <= len(button) <= 40:
        await message.answer("Подпись кнопки от 2 до 40 символов.")
        return
    await db.set_cookie_shop(button=button)
    await state.clear()
    await message.answer("Кнопка магазина обновлена.")


@router.message(ShopAdminFlow.cookie_packs)
async def shop_admin_cookie_packs(message: Message, state: FSMContext, db: Database) -> None:
    packs = parse_cookie_packs(message.text or "")
    if not packs:
        await message.answer("Нужны целые числа через запятую, например: 10, 50, 100.")
        return
    await db.set_cookie_shop(packs=packs)
    await state.clear()
    shop = await db.cookie_shop()
    rate = int(shop["rate_rub"])
    labels = ", ".join(cookie_pack_label(int(amount), rate) for amount in shop["packs"])
    await message.answer(f"Пакеты сохранены: {labels}.")


@router.callback_query(F.data == "ashop:ckpreview")
async def shop_admin_cookies_preview(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not await _allowed(callback, db, settings):
        return
    from community_bot.keyboards import cookie_packages_keyboard

    shop = await db.cookie_shop()
    header = shop_header_lines(await db.shop_header())
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "📋 Предпросмотр блока:\n\n" + cookie_shop_member_text(shop, header),
            parse_mode="HTML",
            reply_markup=cookie_packages_keyboard(shop),
        )


@router.callback_query(F.data == "ashop:preview")
async def shop_admin_preview(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _allowed(callback, db, settings):
        return
    from community_bot.routers.group import _shop_home_markup, _shop_home_text

    user = await db.get_user(callback.from_user.id) or {
        "cookies": 0,
        "reputation": 70,
        "user_id": callback.from_user.id,
    }
    await callback.answer()
    await answer_block(
        callback.message,
        "shop",
        "📋 <b>Предпросмотр для участника</b>\n\n" + await _shop_home_text(db, user, settings),
        parse_mode="HTML",
        reply_markup=await _shop_home_markup(db),
    )
