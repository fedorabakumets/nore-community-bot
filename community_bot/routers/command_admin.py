from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from community_bot.command_registry import (
    OPTION_LABELS,
    CommandView,
    alias_taken,
    clean_aliases,
    default_reply_ttl,
    get_command,
    list_commands,
    load_registry,
    set_default_reply_ttl,
    slug_for_alias,
)
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.helpers import has_permission
from community_bot.keyboards import STYLE_CLOSE, STYLE_FUN, STYLE_GO, back_btn, ibtn
from community_bot.permissions import PERM_COMMANDS
from community_bot.states import CommandStudio

router = Router(name="command_admin")

_PAGE = 6
_SCOPES = ("both", "group", "private")
_SCOPE_LABEL = {"both": "везде", "group": "только чат", "private": "только личка"}


async def _allowed(callback: CallbackQuery, db: Database, settings: Settings) -> bool:
    if not callback.from_user or not await has_permission(db, settings, callback.from_user.id, PERM_COMMANDS):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return False
    return True


def _list_keyboard(page: int) -> InlineKeyboardMarkup:
    items = list_commands()
    pages = max(1, (len(items) + _PAGE - 1) // _PAGE)
    page = max(0, min(page, pages - 1))
    rows = []
    ttl = int(default_reply_ttl())
    if page == 0:
        rows.append([ibtn(f"⏱ Ответы по умолчанию: {ttl} с", "admin:cmds:edit:ttl:_ttl")])
        rows.append([ibtn("➕ Создать команду", "admin:cmds:new", STYLE_GO)])
    for view in items[page * _PAGE : (page + 1) * _PAGE]:
        mark = "" if view.enabled else " · выкл"
        rows.append([ibtn(f"{view.title}{mark}"[:40], f"admin:cmds:open:{view.slug}")])
    nav = []
    if page > 0:
        nav.append(ibtn("←", f"admin:cmds:page:{page - 1}"))
    if page + 1 < pages:
        nav.append(ibtn("→", f"admin:cmds:page:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([back_btn("admin:system")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _card_text(view: CommandView) -> str:
    ttl = "как у остальных" if view.ttl is None else ("не стирать" if view.ttl <= 0 else f"{int(view.ttl)} с")
    aliases = ", ".join(view.aliases) or "—"
    lines = [
        f"⌨️ <b>{html.escape(view.title)}</b>",
        f"<code>{html.escape(view.slug)}</code>",
        "",
        f"Состояние: {'включена' if view.enabled else 'выключена'}",
        f"Где работает: {_SCOPE_LABEL.get(view.scope, view.scope)}",
        f"Стирать ответ через: {ttl}",
        f"Слова вызова: {html.escape(aliases)}",
        "",
        html.escape(view.description or "Без описания."),
    ]
    if view.kind == "custom":
        preview = view.reply_text.strip() or "—"
        lines.extend(["", "<b>Ответ</b>", html.escape(preview[:500])])
    else:
        lines.extend(["", "Действие команды остаётся в боте. Здесь меняются вызов, описание, место и тайм-аут."])
    if view.options:
        lines.append("")
        for key, value in view.options.items():
            lines.append(f"{html.escape(OPTION_LABELS.get(key, key))}: {html.escape(value)}")
    return "\n".join(lines)


def _card_keyboard(view: CommandView) -> InlineKeyboardMarkup:
    rows = [
        [ibtn("Выключить" if view.enabled else "Включить", f"admin:cmds:toggle:{view.slug}", STYLE_FUN)],
        [ibtn("Где работает", f"admin:cmds:scope:{view.slug}")],
        [ibtn("Тайм-аут", f"admin:cmds:edit:ttl:{view.slug}")],
        [ibtn("Слова вызова", f"admin:cmds:edit:alias:{view.slug}")],
        [ibtn("Описание", f"admin:cmds:edit:desc:{view.slug}")],
    ]
    if view.kind == "custom":
        rows.append([ibtn("Текст ответа", f"admin:cmds:edit:reply:{view.slug}", STYLE_GO)])
        rows.append([ibtn("Удалить", f"admin:cmds:drop:{view.slug}", STYLE_CLOSE)])
    else:
        rows.append([ibtn("Сброс", f"admin:cmds:reset:{view.slug}")])
    for key in view.options:
        rows.append([ibtn(OPTION_LABELS.get(key, key), f"admin:cmds:edit:opt:{view.slug}:{key}")])
    rows.append([back_btn("admin:cmds")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _store(db: Database, view: CommandView) -> None:
    await db.save_command_override(
        view.slug,
        kind=view.kind,
        enabled=view.enabled,
        title=view.title,
        description=view.description,
        aliases=list(view.aliases),
        ttl_seconds=None if view.ttl is None else int(view.ttl),
        scope=view.scope,
        reply_text=view.reply_text,
        options=dict(view.options),
    )
    await load_registry(db)


async def _show_list(callback: CallbackQuery, page: int) -> None:
    if callback.message is None:
        return
    await callback.message.edit_text(
        "⌨️ <b>Команды</b>\n\nВызов, описание, где команда работает и через сколько стирается ответ.",
        parse_mode="HTML",
        reply_markup=_list_keyboard(page),
    )


async def _show_card(callback: CallbackQuery, slug: str) -> None:
    view = get_command(slug)
    if view is None or callback.message is None:
        await callback.answer("Команда не найдена.", show_alert=True)
        return
    await callback.message.edit_text(_card_text(view), parse_mode="HTML", reply_markup=_card_keyboard(view))


@router.callback_query(F.data == "admin:cmds")
async def open_commands(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not await _allowed(callback, db, settings):
        return
    await load_registry(db)
    await callback.answer()
    await _show_list(callback, 0)


@router.callback_query(F.data.startswith("admin:cmds:page:"))
async def page_commands(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not await _allowed(callback, db, settings):
        return
    await callback.answer()
    await _show_list(callback, int(callback.data.rsplit(":", 1)[-1] or 0))


@router.callback_query(F.data.startswith("admin:cmds:open:"))
async def open_command(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not await _allowed(callback, db, settings):
        return
    await callback.answer()
    await _show_card(callback, callback.data.split(":", 3)[-1])


@router.callback_query(F.data.startswith("admin:cmds:toggle:"))
async def toggle_command(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not await _allowed(callback, db, settings):
        return
    slug = callback.data.split(":", 3)[-1]
    view = get_command(slug)
    if view is None:
        await callback.answer("Команда не найдена.", show_alert=True)
        return
    view.enabled = not view.enabled
    await _store(db, view)
    await callback.answer("Сохранено")
    await _show_card(callback, slug)


@router.callback_query(F.data.startswith("admin:cmds:scope:"))
async def cycle_scope(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not await _allowed(callback, db, settings):
        return
    slug = callback.data.split(":", 3)[-1]
    view = get_command(slug)
    if view is None:
        await callback.answer("Команда не найдена.", show_alert=True)
        return
    index = _SCOPES.index(view.scope) if view.scope in _SCOPES else 0
    view.scope = _SCOPES[(index + 1) % len(_SCOPES)]
    await _store(db, view)
    await callback.answer(_SCOPE_LABEL[view.scope])
    await _show_card(callback, slug)


@router.callback_query(F.data.startswith("admin:cmds:reset:"))
async def reset_command(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not await _allowed(callback, db, settings):
        return
    slug = callback.data.split(":", 3)[-1]
    view = get_command(slug)
    if view is None or view.kind != "builtin":
        await callback.answer("Сброс только у встроенных команд.", show_alert=True)
        return
    await db.delete_command_override(slug)
    await load_registry(db)
    await callback.answer("Сброшено")
    await _show_card(callback, slug)


@router.callback_query(F.data.startswith("admin:cmds:drop:"))
async def ask_drop(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message or not await _allowed(callback, db, settings):
        return
    slug = callback.data.split(":", 3)[-1]
    await callback.answer()
    await callback.message.edit_text(
        "Удалить эту команду?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [ibtn("Да, удалить", f"admin:cmds:dropyes:{slug}", STYLE_CLOSE)],
                [ibtn("Не надо", f"admin:cmds:open:{slug}")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("admin:cmds:dropyes:"))
async def drop_command(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not await _allowed(callback, db, settings):
        return
    slug = callback.data.split(":", 3)[-1]
    view = get_command(slug)
    if view is None or view.kind != "custom":
        await callback.answer("Удаляются только созданные команды.", show_alert=True)
        return
    await db.delete_command_override(slug)
    await load_registry(db)
    await callback.answer("Удалено")
    await _show_list(callback, 0)


@router.callback_query(F.data == "admin:cmds:new")
async def begin_create(callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    if not callback.message or not await _allowed(callback, db, settings):
        return
    await state.set_state(CommandStudio.value)
    await state.set_data({"field": "new_alias"})
    await callback.answer()
    await callback.message.answer("Каким словом вызывать новую команду? Одним словом или короткой фразой.")


@router.callback_query(F.data.startswith("admin:cmds:edit:"))
async def begin_edit(callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message or not await _allowed(callback, db, settings):
        return
    parts = callback.data.split(":")
    field = parts[3]
    slug = parts[4]
    option = parts[5] if len(parts) > 5 else ""
    prompts = {
        "ttl": "Через сколько секунд стирать ответ? 0 — не стирать. «-» — как было.",
        "alias": "Слова вызова через запятую.",
        "desc": "Новое описание, до 400 знаков.",
        "reply": "Текст ответа. До 1000 знаков. Это и есть действие команды.",
        "opt": f"Новое значение: {OPTION_LABELS.get(option, option)}.",
    }
    if field == "ttl" and slug == "_ttl":
        prompt = "Общий тайм-аут ответов в секундах, от 5 до 600."
    else:
        prompt = prompts.get(field, "")
    if not prompt:
        await callback.answer("Нечего менять.", show_alert=True)
        return
    await state.set_state(CommandStudio.value)
    await state.set_data({"field": field, "slug": slug, "option": option})
    await callback.answer()
    await callback.message.answer(prompt)


@router.message(CommandStudio.value, F.chat.type == "private")
async def save_value(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not message.from_user or not await has_permission(db, settings, message.from_user.id, PERM_COMMANDS):
        await state.clear()
        await message.answer("Недостаточно прав.")
        return
    data = await state.get_data()
    field = str(data.get("field") or "")
    raw = (message.text or "").strip()
    if raw.casefold() in {"отмена", "назад"}:
        await state.clear()
        await message.answer("Оставила как было.")
        return
    if field == "new_alias":
        aliases, error = clean_aliases(raw, slug="c_new")
        if error or not aliases:
            await message.answer(error or "Нужно слово вызова.")
            return
        if any(alias_taken(alias) for alias in aliases):
            await message.answer("Такое слово уже занимает другая команда.")
            return
        await state.update_data(aliases=aliases, slug=slug_for_alias(aliases[0]), field="new_reply")
        await message.answer("Теперь текст ответа. До 1000 знаков.")
        return
    if field == "new_reply":
        if not 1 <= len(raw) <= 1000:
            await message.answer("Текст — от 1 до 1000 знаков.")
            return
        aliases = list(data.get("aliases") or [])
        slug = str(data.get("slug") or slug_for_alias(aliases[0] if aliases else "cmd"))
        view = CommandView(
            slug=slug,
            title=aliases[0] if aliases else slug,
            description=raw[:120],
            aliases=tuple(aliases),
            ttl=None,
            reply_text=html.escape(raw),
            kind="custom",
        )
        await _store(db, view)
        await state.clear()
        await message.answer(f"Команда «{aliases[0]}» включена.")
        return
    slug = str(data.get("slug") or "")
    if field == "ttl" and slug == "_ttl":
        if not raw.isdigit() or not 5 <= int(raw) <= 600:
            await message.answer("Нужно число от 5 до 600.")
            return
        set_default_reply_ttl(int(raw))
        await db.set_bot_state("reply_ttl_default", raw)
        await load_registry(db)
        await state.clear()
        await message.answer(f"Ответы по умолчанию стираются через {raw} с.")
        return
    view = get_command(slug)
    if view is None:
        await state.clear()
        await message.answer("Команда не найдена.")
        return
    if field == "ttl":
        if raw == "-":
            await db.delete_command_override(slug)
            await load_registry(db)
            await state.clear()
            await message.answer("Тайм-аут вернулся к исходному. Остальные правки этой команды тоже сброшены.")
            return
        if not raw.isdigit() or int(raw) > 3600:
            await message.answer("Нужно число секунд от 0 до 3600 или «-».")
            return
        view.ttl = float(int(raw))
    elif field == "alias":
        aliases, error = clean_aliases(raw, slug=slug)
        if error or aliases is None:
            await message.answer(error or "Не разобрала слова.")
            return
        if any(alias_taken(alias, ignore=slug) for alias in aliases):
            await message.answer("Такое слово уже занимает другая команда.")
            return
        view.aliases = tuple(aliases)
    elif field == "desc":
        if not 1 <= len(raw) <= 400:
            await message.answer("Описание — от 1 до 400 знаков.")
            return
        view.description = raw
    elif field == "reply":
        if view.kind != "custom":
            await state.clear()
            await message.answer("Текст ответа меняется у созданных команд.")
            return
        if not 1 <= len(raw) <= 1000:
            await message.answer("Текст — от 1 до 1000 знаков.")
            return
        view.reply_text = html.escape(raw)
    elif field == "opt":
        option = str(data.get("option") or "")
        if option not in view.options and option not in OPTION_LABELS:
            await state.clear()
            await message.answer("Такой опции нет.")
            return
        if not raw.isdigit() or not 1 <= int(raw) <= 10:
            await message.answer("Нужно число от 1 до 10.")
            return
        view.options[option] = raw
    else:
        await state.clear()
        return
    await _store(db, view)
    await state.clear()
    await message.answer("Сохранено.")
