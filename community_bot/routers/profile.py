from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest, TelegramNotFound
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, InlineKeyboardMarkup, InputRichBlockButtons, InputRichBlockParagraph,
    InputRichMessage, Message, RichMessageButton, RichTextBold,
)

from community_bot.aliases import command_or_alias
from community_bot.blocks import cover_file, replace_block
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.group_friendship import DECISION_PREFIX, group_friend_decision, group_profile_friend
from community_bot.group_profile import FRIEND_PREFIX, _avatar, restore_group_profile_card, send_group_profile
from community_bot.helpers import (
    can_view_profile,
    format_warn_entry,
    register_telegram_user,
    render_profile,
    resolve_command_target,
)
from community_bot.domain import reputation_tier
from community_bot.ephemeral import keep_in_chat
from community_bot.reply_rich import bot_publication
from community_bot.shop_catalog import gift_price, shop_prices_for
from community_bot.keyboards import (
    close_btn,
    compact_profile_keyboard,
    flow_reply_keyboard,
    ibtn,
    profile_keyboard,
    public_profile_keyboard,
)
from community_bot.media_cache import profile_photo_input
from community_bot.private_rich import text_blocks
from community_bot.profile_fields import normalize_tg_channel_url, parse_birth_date
from community_bot.profile_track import audio_block, get_track
from community_bot.routers.flows import restore_private_menu
from community_bot.states import ProfileEdit
from community_bot.ui_owner import bind_ui_owner

router = Router(name="profile")

TGK_CALLBACK = "gprofile:tgk:"
TGK_PROMPT = "🔗 ТГК:"


async def _send_tgk_prompt(message: Message, db: Database, owner_id: int) -> None:
    expiry = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
    with keep_in_chat(), bot_publication():
        sent = await message.reply(
            f"{TGK_PROMPT} настройка канала для владельца профиля.\n"
            "Ответь на это сообщение одной ссылкой t.me/название или t.me/+приглашение.\n"
            "Чтобы удалить ТГК, ответь словом «удалить». Запрос действует 24 часа."
        )
    await db.execute(
        "DELETE FROM profile_tgk_prompts WHERE expires_at <= ?", (datetime.now(UTC).isoformat(),),
    )
    await db.execute(
        "INSERT OR REPLACE INTO profile_tgk_prompts(chat_id,message_id,user_id,expires_at) "
        "VALUES (?,?,?,?)",
        (sent.chat.id, sent.message_id, owner_id, expiry),
    )


@router.callback_query(F.data.startswith(TGK_CALLBACK))
async def request_tgk(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer("Карточка недоступна.", show_alert=True)
        return
    raw_id = callback.data[len(TGK_CALLBACK):]
    if not raw_id.isdecimal() or int(raw_id) != callback.from_user.id:
        await callback.answer("Установить ТГК может только владелец профиля.", show_alert=True)
        return
    if not await db.get_user(callback.from_user.id):
        await callback.answer("Профиль не найден.", show_alert=True)
        return
    await _send_tgk_prompt(callback.message, db, callback.from_user.id)
    await callback.answer("Ответь на сообщение ссылкой на свой ТГК.")


@router.message(Command("tgk"))
async def change_own_tgk(message: Message, db: Database) -> None:
    if not message.from_user:
        return
    await register_telegram_user(db, message.from_user)
    await _send_tgk_prompt(message, db, message.from_user.id)


@router.message(F.text, F.reply_to_message.text.startswith(TGK_PROMPT))
async def save_tgk_reply(message: Message, db: Database) -> None:
    if not message.from_user or not message.reply_to_message:
        return
    prompt = await db.fetchone(
        "SELECT user_id,expires_at FROM profile_tgk_prompts WHERE chat_id=? AND message_id=?",
        (message.chat.id, message.reply_to_message.message_id),
    )
    if not prompt:
        return
    if int(prompt["user_id"]) != message.from_user.id:
        await message.reply("Изменить ТГК может только владелец профиля.")
        return
    if str(prompt["expires_at"]) <= datetime.now(UTC).isoformat():
        await db.execute(
            "DELETE FROM profile_tgk_prompts WHERE chat_id=? AND message_id=?",
            (message.chat.id, message.reply_to_message.message_id),
        )
        await message.reply("Запрос устарел. Открой профиль и нажми «ТГК» ещё раз.")
        return
    try:
        url = normalize_tg_channel_url(message.text or "")
        await db.update_profile(message.from_user.id, "tg_channel_url", url)
    except ValueError as error:
        await message.reply(str(error) + ". Ответь на то же сообщение правильной ссылкой.")
        return
    await db.execute(
        "DELETE FROM profile_tgk_prompts WHERE chat_id=? AND message_id=?",
        (message.chat.id, message.reply_to_message.message_id),
    )
    with keep_in_chat(), bot_publication():
        await message.reply(
            f"✅ ТГК привязан: {url}\nОткрой профиль заново, чтобы ссылка появилась у имени."
            if url else "✅ ТГК удалён из профиля."
        )


async def send_profile_card(
    message: Message,
    user: dict[str, object],
    settings: Settings,
    *,
    editable: bool,
    text: str,
    replace: bool = False,
    db: Database | None = None,
) -> Message | None:
    user_id = int(user["user_id"])
    markup = (
        InlineKeyboardMarkup(inline_keyboard=[[close_btn()]])
        if message.chat.type in {"group", "supergroup"}
        else (
            profile_keyboard(user_id, bool(user.get("profile_private")), back_to_menu=message.chat.type == "private")
            if editable
            else public_profile_keyboard(user_id)
        )
    )
    sent: Message | None = None
    if db and message.chat.type == "private" and (editable or not user.get("profile_private")):
        track = await get_track(db, user_id)
        if track:
            name, closing_tag, details = text.partition("</b>")
            if not closing_tag:
                name, details = "", text
            lines = details.split("\n", 2)
            avatar = await _avatar(db, user)
            blocks = [
                *([avatar] if avatar else []), *text_blocks(name + closing_tag + "\n".join(lines[:2]), "HTML"),
                audio_block(track), *(text_blocks(lines[2], "HTML") if len(lines) > 2 else []),
            ]
            rich = InputRichMessage(blocks=blocks)
            try:
                if replace:
                    sent = await message.edit_text(rich_message=rich, reply_markup=markup)
                else:
                    sent = await message.answer(rich_message=rich, reply_markup=markup)
            except (TelegramBadRequest, TelegramNotFound):
                pass
            else:
                if message.from_user:
                    await bind_ui_owner(db, sent, user_id if editable else message.from_user.id, "profile")
                return sent
    if replace:
        sent = await replace_block(message, "profile", text, parse_mode="HTML", reply_markup=markup)
        if db and message.from_user:
            await bind_ui_owner(db, sent or message, user_id if editable else message.from_user.id, "profile")
        return sent
    if user.get("avatar_file_id"):
        try:
            if user.get("avatar_media_type") == "video":
                sent = await message.answer_video(
                    str(user["avatar_file_id"]),
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            else:
                file_id = str(user["avatar_file_id"])
                photo = await profile_photo_input(db, file_id) if db is not None else file_id
                if photo is not None:
                    sent = await message.answer_photo(photo, caption=text, parse_mode="HTML", reply_markup=markup)
        except TelegramBadRequest:
            sent = None
    if sent is None:
        cover = cover_file("profile") if message.chat.type != "private" else None
        if cover:
            try:
                sent = await message.answer_photo(cover, caption=text, parse_mode="HTML", reply_markup=markup)
            except TelegramBadRequest:
                sent = None
    if sent is None:
        sent = await message.answer(text, parse_mode="HTML", reply_markup=markup)
    if db and message.from_user:
        await bind_ui_owner(db, sent, user_id if editable else message.from_user.id, "profile")
    return sent


@router.message(command_or_alias("profile"))
@router.message(F.chat.type == "private", F.text == "👤 Мой профиль")
async def show_profile(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    actor = await register_telegram_user(db, message.from_user)
    target = actor
    if message.chat.type in {"group", "supergroup"}:
        person, args, explicit = await resolve_command_target(message, db)
        if args or (explicit and not person):
            await message.answer("Не нашла профиль этого участника. Попробуй ответить на его сообщение.")
            return
        if person:
            target = person
        if target.get("profile_private"):
            await message.answer("🔒 Этот профиль скрыт.")
            return
        await send_group_profile(message, db, settings, target, message.from_user.id)
        return
    editable = int(target["user_id"]) == message.from_user.id
    if not await can_view_profile(db, settings, message.from_user.id, target):
        await message.answer("🔒 Этот профиль скрыт.")
        return
    text = await render_profile(db, settings, target, compact=True)
    await send_profile_card(message, target, settings, editable=editable, text=text, db=db)


router.callback_query.register(
    group_profile_friend, F.data.startswith(FRIEND_PREFIX), F.message.chat.type.in_({"group", "supergroup"}),
)
router.callback_query.register(
    group_friend_decision, F.data.startswith(DECISION_PREFIX), F.message.chat.type.in_({"group", "supergroup"}),
)

LIMITS_CALLBACK = "gprofile:limits:"


async def _limits_price(db: Database, settings: Settings, payer: dict, *, gift: bool = False) -> int | None:
    item = await db.get_shop_item("reset_limits")
    category = await db.get_shop_category(item["category_slug"]) if item else None
    if (not item or not item.get("enabled") or not item.get("price")
            or not category or not category.get("enabled")):
        return None
    if gift:
        return gift_price(item["price"])
    prices = shop_prices_for(
        payer, settings.restricted_reputation_threshold, await db.priced_shop_map(),
    )
    return prices.get("reset_limits")


def _limits_confirmation(
    payer: dict, recipient: dict, price: int, token: str, *, gift: bool,
) -> InputRichMessage:
    uid = int(recipient["user_id"])
    balance = int(payer["cookies"])
    title = "🎁 Подарить восстановление лимитов" if gift else "♻️ Восстановление лимитов"
    if gift:
        name = str(recipient.get("profile_name") or recipient.get("telegram_name")
                   or recipient.get("username") or f"Участник {uid}")
        description = f"Восстановить дневные лимиты пользователю {name[:80]}?\n"
    else:
        description = "Все твои дневные лимиты будут сброшены.\n"
    return InputRichMessage(blocks=[
        InputRichBlockParagraph(text=[RichTextBold(text=title)]),
        InputRichBlockParagraph(
            text=f"{description}Цена: {price} 🍪 · Твой баланс: {balance} 🍪\n"
                 "Таймер 60 секунд между треками останется."
        ),
        InputRichBlockButtons(align="center", buttons=[
            RichMessageButton(text=f"Подтвердить · {price} 🍪", style="success",
                              callback_data=f"{LIMITS_CALLBACK}pay:{uid}:{token}"),
        ]),
        InputRichBlockButtons(align="center", buttons=[
            RichMessageButton(text="←", style="link",
                              callback_data=f"{LIMITS_CALLBACK}back:{uid}:{token}"),
        ]),
    ], skip_entity_detection=True)


@router.callback_query(
    F.data.startswith(LIMITS_CALLBACK), F.message.chat.type.in_({"group", "supergroup"}),
)
async def group_profile_limits(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    """Edit the shared card in place; only the clicking buyer owns the payment intent."""
    message = callback.message
    if not isinstance(message, Message) or not callback.data:
        await callback.answer("Карточка профиля больше недоступна.", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) not in (4, 5) or parts[:2] != ["gprofile", "limits"]:
        await callback.answer("Неверная кнопка.", show_alert=True)
        return
    _, _, action, raw_uid, *rest = parts
    if (not raw_uid.isdecimal() or action not in {"restore", "gift", "back", "pay"}
            or (action in {"restore", "gift"} and rest)
            or (action in {"back", "pay"} and len(rest) != 1)):
        await callback.answer("Некорректная операция.", show_alert=True)
        return

    uid = int(raw_uid)
    payer_id = callback.from_user.id
    if action == "restore" and payer_id != uid:
        await callback.answer("Восстановить свои лимиты можно только в своём профиле.", show_alert=True)
        return
    if action == "gift" and payer_id == uid:
        await callback.answer("Себе подарок отправить нельзя. Используй ♻️.", show_alert=True)
        return

    recipient = await db.get_user(uid)
    if not recipient or recipient.get("profile_private"):
        await callback.answer("Этот профиль недоступен.", show_alert=True)
        return
    payer = await db.get_user(payer_id)
    if not payer:
        payer = await register_telegram_user(db, callback.from_user)

    if action in {"restore", "gift"}:
        gift = action == "gift"
        price = await _limits_price(db, settings, payer, gift=gift)
        if price is None:
            await callback.answer("Сброс лимитов сейчас не продаётся в магазине.", show_alert=True)
            return
        token = await db.create_wallet_intent(
            payer_id, "reset_limits", price, target_id=uid,
            payload={"shop_quote": True, "gift": gift,
                     "restricted_threshold": settings.restricted_reputation_threshold},
        )
        try:
            with keep_in_chat(), bot_publication():
                await message.edit_text(
                    parse_mode=None,
                    rich_message=_limits_confirmation(payer, recipient, price, token, gift=gift),
                )
        except (TelegramBadRequest, TelegramNotFound):
            await db.cancel_wallet_intent(payer_id, token)
            await callback.answer("Не удалось открыть подтверждение покупки.", show_alert=True)
            return
        await callback.answer()
        return

    token = rest[0]
    intent = await db.get_wallet_intent(payer_id, token)
    gift = payer_id != uid
    if (not intent or intent["item"] != "reset_limits"
            or int(intent["target_id"]) != uid
            or bool(intent["payload"].get("gift")) != gift):
        await callback.answer("Подтверждение устарело или принадлежит другому участнику.", show_alert=True)
        return

    requester = await db.get_ui_owner(message.chat.id, message.message_id) or uid
    if action == "back":
        await db.cancel_wallet_intent(payer_id, token)
        restored = await restore_group_profile_card(message, db, settings, recipient, requester)
        await callback.answer("" if restored else "Не удалось вернуть карточку.", show_alert=not restored)
        return

    price = await _limits_price(db, settings, payer, gift=gift)
    if price is None or int(intent["price"]) != price:
        await callback.answer("Цена изменилась. Открой покупку заново.", show_alert=True)
        return

    ok, error = await db.buy_item(
        payer_id, "reset_limits", price, target_id=uid, intent_id=token,
    )
    if not ok:
        await callback.answer(error, show_alert=True)
        return

    from community_bot.life import unlock
    from community_bot.notify import vitrine_consumed

    await unlock(db, payer_id, "shop_first")
    await vitrine_consumed(message.bot, db, "reset_limits")
    fresh = await db.get_user(uid) or recipient
    edited = await restore_group_profile_card(message, db, settings, fresh, requester)
    result = "Подарок отправлен ✓" if gift else "Лимиты восстановлены ✓"
    await callback.answer(result if edited else f"{result} Открой профиль заново.")



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
        await db.set_profile_privacy(user_id, False)
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
        "age": (ProfileEdit.birth_date, "Введите дату рождения в формате ДД.ММ.ГГГГ."),
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


@router.message(ProfileEdit.birth_date)
async def edit_profile_birth_date(message: Message, state: FSMContext, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    try:
        await db.update_profile(message.from_user.id, "birth_date", parse_birth_date(message.text or ""))
    except ValueError as error:
        await message.answer(str(error))
        return
    await state.clear()
    await message.answer("Дата рождения сохранена.")
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
    text = await render_profile(db, settings, user, compact=callback.message.chat.type == "private")
    await callback.answer()
    await send_profile_card(callback.message, user, settings, editable=True, text=text, replace=True, db=db)


@router.callback_query(F.data == "p:rules")
async def profile_rules(callback: CallbackQuery, db: Database) -> None:
    if not callback.message:
        return
    user = await register_telegram_user(db, callback.from_user)
    await callback.answer()
    await replace_block(
        callback.message,
        "profile",
        "Пять блоков профиля: имя, дата рождения, увлечения, описание и фото.\n"
        "Без 100% репутация не выше бронзы. Подробности — /commands.",
        parse_mode="HTML",
        reply_markup=compact_profile_keyboard(user),
    )


@router.callback_query(F.data == "p:warns")
async def profile_warns(callback: CallbackQuery, db: Database) -> None:
    if not callback.message:
        return
    user = await register_telegram_user(db, callback.from_user)
    rows = await db.list_user_warns(callback.from_user.id)
    active = max(0, int(user.get("warnings") or 0))
    rows = rows[:active]
    await callback.answer()
    if not rows:
        body = "⚠️ <b>Варны</b>\n\nПока пусто — предупреждений нет."
    else:
        parts = [format_warn_entry(row, index) for index, row in enumerate(rows, start=1)]
        body = "⚠️ <b>Варны</b>\n\n" + "\n\n".join(parts)
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("↩️ К профилю", "menu:profile"), close_btn("ui:close")],
        ]
    )
    await replace_block(callback.message, "profile", body, parse_mode="HTML", reply_markup=markup)
