from __future__ import annotations

import html
from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from community_bot.audit import person_label
from community_bot.config import Settings
from community_bot.contest import (
    DEFAULT_PRIZE,
    MAX_EXTRA,
    MAX_PRIZE,
    contest_home_keyboard,
    contest_home_text,
    contest_join_keyboard,
    contest_preview_keyboard,
    contest_preview_text,
    contest_prize_keyboard,
    contest_skip_media_keyboard,
    contest_skip_text_keyboard,
    contest_text,
    publish_contest_post,
)
from community_bot.database import Database
from community_bot.ephemeral import keep_in_chat
from community_bot.helpers import has_permission, media_from_message, register_telegram_user
from community_bot.permissions import PERM_CONTEST
from community_bot.states import AdminFlow

router = Router(name="contest")


async def _contest_admin(callback: CallbackQuery, db: Database, settings: Settings) -> bool:
    if not callback.from_user or not await has_permission(db, settings, callback.from_user.id, PERM_CONTEST):
        await callback.answer("Недостаточно прав. Конкурс сначала только у владельцев.", show_alert=True)
        return False
    return True


async def _show_contest_home(
    callback: CallbackQuery,
    db: Database,
    settings: Settings,
    state: FSMContext,
) -> None:
    await state.clear()
    if not callback.message:
        return
    opened = await db.open_cookie_contest(settings.community_chat_id)
    count = await db.cookie_contest_entry_count(int(opened["id"])) if opened else 0
    await callback.message.edit_text(
        contest_home_text(opened, count),
        parse_mode="HTML",
        reply_markup=contest_home_keyboard(has_open=bool(opened)),
    )


@router.callback_query(F.data.in_({"admin:contest", "admin:contest:home"}))
async def admin_contest_home(
    callback: CallbackQuery,
    db: Database,
    settings: Settings,
    state: FSMContext,
) -> None:
    if not callback.message or not await _contest_admin(callback, db, settings):
        return
    await callback.answer()
    await _show_contest_home(callback, db, settings, state)


@router.callback_query(F.data == "admin:contest:new")
async def admin_contest_new(
    callback: CallbackQuery,
    db: Database,
    settings: Settings,
    state: FSMContext,
) -> None:
    if not callback.message or not await _contest_admin(callback, db, settings):
        return
    if not settings.community_chat_id:
        await callback.answer("Не задан ID чата сообщества.", show_alert=True)
        return
    if await db.open_cookie_contest(settings.community_chat_id):
        await callback.answer("Сначала закройте текущий конкурс.", show_alert=True)
        return
    await state.set_state(AdminFlow.contest_text)
    await state.set_data(
        {
            "contest_extra": "",
            "contest_media_type": None,
            "contest_file_id": None,
            "contest_prize": DEFAULT_PRIZE,
        }
    )
    await callback.answer()
    await callback.message.edit_text(
        "📝 <b>Новый конкурс</b>\n\n"
        "Базовый шаблон уже готов: заголовок, приз и кнопка «Участвовать».\n\n"
        "Напишите дополнительный текст (условия, срок, что разыгрываем) "
        "или нажмите «Без доп. текста».",
        parse_mode="HTML",
        reply_markup=contest_skip_text_keyboard(),
    )


@router.message(AdminFlow.contest_text, F.chat.type == "private")
async def admin_contest_text(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not message.from_user or not await has_permission(db, settings, message.from_user.id, PERM_CONTEST):
        await state.clear()
        return
    extra = (message.html_text or message.text or "").strip()
    if len(extra) > MAX_EXTRA:
        await message.answer(f"Доп. текст — до {MAX_EXTRA} символов.")
        return
    await state.update_data(contest_extra=extra)
    await state.set_state(AdminFlow.contest_media)
    await message.answer(
        "Теперь пришлите фото, видео, гиф или документ — это станет обложкой поста.\n"
        "Или нажмите «Без медиа».",
        reply_markup=contest_skip_media_keyboard(),
    )


@router.callback_query(AdminFlow.contest_text, F.data == "admin:contest:text:skip")
async def admin_contest_text_skip(callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings) -> None:
    if not callback.message or not await _contest_admin(callback, db, settings):
        return
    await state.update_data(contest_extra="")
    await state.set_state(AdminFlow.contest_media)
    await callback.answer()
    await callback.message.edit_text(
        "Теперь пришлите фото, видео, гиф или документ — это станет обложкой поста.\n"
        "Или нажмите «Без медиа».",
        reply_markup=contest_skip_media_keyboard(),
    )


@router.message(AdminFlow.contest_media, F.chat.type == "private")
async def admin_contest_media(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not message.from_user or not await has_permission(db, settings, message.from_user.id, PERM_CONTEST):
        await state.clear()
        return
    media_type, file_id = media_from_message(message)
    if not media_type or not file_id:
        await message.answer("Пришлите вложение или нажмите «Без медиа».")
        return
    extra = (message.html_text or message.caption or "").strip()
    data = await state.get_data()
    if extra and not data.get("contest_extra"):
        await state.update_data(contest_extra=extra[:MAX_EXTRA])
    await state.update_data(contest_media_type=media_type, contest_file_id=file_id)
    await state.set_state(AdminFlow.contest_prize)
    await message.answer(
        f"Сколько 🍪 получит победитель? Число от 1 до {MAX_PRIZE}.\n"
        f"Или оставьте стандартные {DEFAULT_PRIZE}.",
        reply_markup=contest_prize_keyboard(),
    )


@router.callback_query(AdminFlow.contest_media, F.data == "admin:contest:media:skip")
async def admin_contest_skip_media(
    callback: CallbackQuery, state: FSMContext, db: Database, settings: Settings
) -> None:
    if not callback.message or not await _contest_admin(callback, db, settings):
        return
    await state.update_data(contest_media_type=None, contest_file_id=None)
    await state.set_state(AdminFlow.contest_prize)
    await callback.answer()
    await callback.message.edit_text(
        f"Сколько 🍪 получит победитель? Число от 1 до {MAX_PRIZE}.\n"
        f"Или оставьте стандартные {DEFAULT_PRIZE}.",
        reply_markup=contest_prize_keyboard(),
    )


@router.message(AdminFlow.contest_prize, F.chat.type == "private")
async def admin_contest_prize(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not message.from_user or not await has_permission(db, settings, message.from_user.id, PERM_CONTEST):
        await state.clear()
        return
    raw = (message.text or "").strip().replace("🍪", "").strip()
    if not raw.isdigit() or not 1 <= int(raw) <= MAX_PRIZE:
        await message.answer(f"Нужно число от 1 до {MAX_PRIZE}.")
        return
    await state.update_data(contest_prize=int(raw))
    await _show_preview(message, state)


@router.callback_query(AdminFlow.contest_prize, F.data == "admin:contest:prize:default")
async def admin_contest_prize_default(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.message or not await _contest_admin(callback, db, settings):
        return
    await state.update_data(contest_prize=DEFAULT_PRIZE)
    await callback.answer()
    await _show_preview(callback.message, state, edit=True)


async def _show_preview(target: Message, state: FSMContext, *, edit: bool = False) -> None:
    data = await state.get_data()
    prize = int(data.get("contest_prize") or DEFAULT_PRIZE)
    extra = str(data.get("contest_extra") or "")
    has_media = bool(data.get("contest_file_id"))
    text = contest_preview_text(prize, extra, has_media)
    if edit:
        await target.edit_text(text, parse_mode="HTML", reply_markup=contest_preview_keyboard())
        return
    await target.answer(text, parse_mode="HTML", reply_markup=contest_preview_keyboard())


@router.callback_query(F.data == "admin:contest:publish")
async def admin_contest_publish(
    callback: CallbackQuery,
    bot: Bot,
    db: Database,
    settings: Settings,
    state: FSMContext,
) -> None:
    if not callback.message or not await _contest_admin(callback, db, settings):
        return
    if not settings.community_chat_id:
        await callback.answer("Не задан ID чата сообщества.", show_alert=True)
        return
    data = await state.get_data()
    prize = int(data.get("contest_prize") or DEFAULT_PRIZE)
    extra = str(data.get("contest_extra") or "")
    body = contest_text(prize, extra)
    contest_id, error = await db.create_cookie_contest(
        settings.community_chat_id,
        callback.from_user.id,
        prize,
        body,
        extra,
        data.get("contest_media_type"),
        data.get("contest_file_id"),
    )
    if not contest_id:
        await callback.answer(error, show_alert=True)
        return
    sent = await publish_contest_post(
        bot,
        settings.community_chat_id,
        contest_id,
        body,
        data.get("contest_media_type"),
        data.get("contest_file_id"),
    )
    if not sent:
        await db.cancel_cookie_contest(contest_id)
        await callback.answer("Не удалось отправить пост в чат. Проверьте права бота.", show_alert=True)
        return
    await db.set_cookie_contest_message(contest_id, sent.message_id)
    await db.log_admin_action(
        callback.from_user.id,
        "contest_publish",
        str(contest_id),
        f"prize:{prize}",
        reason="конкурс на печеньки",
        actor_name=callback.from_user.full_name,
    )
    await state.clear()
    await callback.answer("Опубликовано")
    await callback.message.edit_text(
        f"✅ Конкурс №{contest_id} ушёл в чат.\nКнопка «Участвовать» считает людей. "
        "Когда пора — вернитесь сюда и нажмите «Подвести итог».",
        reply_markup=contest_home_keyboard(has_open=True),
    )


@router.callback_query(F.data == "admin:contest:list")
async def admin_contest_list(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message or not await _contest_admin(callback, db, settings):
        return
    opened = await db.open_cookie_contest(settings.community_chat_id)
    if not opened:
        await callback.answer("Открытого конкурса нет.", show_alert=True)
        return
    rows = await db.list_cookie_contest_entries(int(opened["id"]))
    lines = [f"👥 <b>Участники конкурса №{opened['id']}</b> · {len(rows)} чел.", ""]
    if not rows:
        lines.append("Пока никто не нажал кнопку.")
    for row in rows:
        lines.append(f"• {html.escape(person_label(row, str(row['user_id'])))} (<code>{row['user_id']}</code>)")
    await callback.answer()
    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=contest_home_keyboard(has_open=True),
    )


async def _drop_contest_button(bot: Bot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    with keep_in_chat():
        with suppress(TelegramBadRequest):
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=int(message_id), reply_markup=None)


@router.callback_query(F.data == "admin:contest:draw")
async def admin_contest_draw(
    callback: CallbackQuery,
    bot: Bot,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.message or not await _contest_admin(callback, db, settings):
        return
    opened = await db.open_cookie_contest(settings.community_chat_id)
    if not opened:
        await callback.answer("Открытого конкурса нет.", show_alert=True)
        return
    ok, error, result = await db.draw_cookie_contest(int(opened["id"]))
    if not ok or not result:
        await callback.answer(error, show_alert=True)
        return
    winner = await db.get_user(int(result["winner_id"]))
    name = person_label(winner, str(result["winner_id"]))
    chat_id = int(opened["chat_id"])
    await _drop_contest_button(bot, chat_id, opened.get("message_id"))
    with keep_in_chat():
        with suppress(TelegramBadRequest):
            await bot.send_message(
                chat_id,
                (
                    f"🏆 <b>Итог конкурса на печеньки</b>\n\n"
                    f"Победитель: {html.escape(name)}\n"
                    f"Приз: <b>{result['prize']}</b> 🍪 · участников: {result['players']}."
                ),
                parse_mode="HTML",
            )
    await db.log_admin_action(
        callback.from_user.id,
        "contest_draw",
        str(result["winner_id"]),
        f"prize:{result['prize']}:players:{result['players']}",
        reason="итог конкурса",
        actor_name=callback.from_user.full_name,
        target_name=name,
    )
    await callback.answer("Победитель выбран")
    await callback.message.edit_text(
        f"🏆 Победитель: {html.escape(name)} · {result['prize']} 🍪 · участников {result['players']}.",
        parse_mode="HTML",
        reply_markup=contest_home_keyboard(has_open=False),
    )


@router.callback_query(F.data == "admin:contest:cancel")
async def admin_contest_cancel(
    callback: CallbackQuery,
    bot: Bot,
    db: Database,
    settings: Settings,
) -> None:
    if not callback.message or not await _contest_admin(callback, db, settings):
        return
    opened = await db.open_cookie_contest(settings.community_chat_id)
    if not opened:
        await callback.answer("Открытого конкурса нет.", show_alert=True)
        return
    await db.cancel_cookie_contest(int(opened["id"]))
    await _drop_contest_button(bot, int(opened["chat_id"]), opened.get("message_id"))
    await db.log_admin_action(
        callback.from_user.id,
        "contest_cancel",
        str(opened["id"]),
        reason="конкурс снят",
        actor_name=callback.from_user.full_name,
    )
    await callback.answer("Снято")
    await callback.message.edit_text(
        "Конкурс снят. Победителя нет, печеньки не начислялись.",
        reply_markup=contest_home_keyboard(has_open=False),
    )


@router.callback_query(F.data.startswith("contest:join:"))
async def contest_join(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.from_user:
        return
    contest_id = int(callback.data.rsplit(":", 1)[1])
    await register_telegram_user(db, callback.from_user)
    ok, error, count = await db.join_cookie_contest(contest_id, callback.from_user.id)
    if callback.message and count:
        with keep_in_chat():
            with suppress(TelegramBadRequest):
                await callback.message.edit_reply_markup(reply_markup=contest_join_keyboard(contest_id, count))
    if not ok:
        await callback.answer(error)
        return
    await callback.answer(f"Вы участвуете. Всего: {count}")


@router.callback_query(F.data.startswith('admin:season:'))
async def admin_seasonal(callback: CallbackQuery, db: Database, settings: Settings):
    from community_bot.keyboards import back_btn, ibtn
    from community_bot.seasonal import ITEM, TITLE, can_manage, draw, prepare_draw, snapshot

    if not callback.message or not await can_manage(db, settings, callback.from_user.id):
        await callback.answer('Недостаточно прав', show_alert=True)
        return
    uid = callback.from_user.id
    action = (callback.data or '').removeprefix('admin:season:')
    buttons = []
    try:
        if action == 'prepare':
            quote = await prepare_draw(db, settings, uid)
            text = (f'<b>Выбрать победителя?</b>\n\nУчастников: {quote["count"]}. '
                    'Выбор случайный, один победитель. Запись закроется, повторить выбор будет невозможно.')
            buttons.append([ibtn('Завершить и выбрать победителя', 'admin:season:draw:'+quote['token'])])
        elif action.startswith('draw:'):
            await draw(db, settings, uid, action.removeprefix('draw:'))
            result = await snapshot(db, settings, uid)
            text = f'<b>Итог сохранён</b>\n\n{TITLE}\nПобедитель: {html.escape(result["winner"] or "Участник")}'
        elif action.startswith('list:'):
            raw = action.removeprefix('list:')
            if not raw.isdigit() or len(raw)>6:
                raise ValueError('Некорректная страница')
            offset = int(raw)
            rows = await db.fetchall('SELECT u.profile_name,u.telegram_name,u.username,e.joined_at '
                                     'FROM seasonal_entries e JOIN users u ON u.user_id=e.user_id '
                                     'WHERE e.raffle_id=? ORDER BY e.joined_at,u.user_id LIMIT 11 OFFSET ?',
                                     (ITEM, offset))
            text = '<b>Участники · Багровый Страж Норы</b>\n\n' + ('\n'.join(
                f'{offset+i+1}. {html.escape(row["profile_name"] or row["telegram_name"])}'
                + (f' · @{html.escape(row["username"])}' if row['username'] else '')
                for i, row in enumerate(rows[:10])) or 'Пока нет заявок')
            if offset:
                buttons.append([ibtn('← Назад', f'admin:season:list:{max(0,offset-10)}')])
            if len(rows)>10:
                buttons.append([ibtn('Далее →', f'admin:season:list:{offset+10}')])
        else:
            result = await snapshot(db, settings, uid)
            text = (f'<b>{TITLE}</b>\nСезон 1 · бесплатный розыгрыш физической игрушки\n\n'
                    f'Участников: {result["count"]}\n'
                    + ('Идёт запись.' if result['status']=='open' else
                       f'Победитель: {html.escape(result["winner"] or "итог сохранён")}'))
            buttons.append([ibtn('Участники', 'admin:season:list:0')])
            if result['status']=='open':
                buttons.append([ibtn('Подвести итоги…', 'admin:season:prepare')])
    except ValueError as error:
        await callback.answer(str(error), show_alert=True)
        return
    await callback.answer()
    buttons.append([back_btn('admin:contest:home' if action=='home' else 'admin:season:home')])
    from aiogram.types import InlineKeyboardMarkup

    await callback.message.edit_text(
        text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
