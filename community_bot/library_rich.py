"""Open music collections from chat without publishing private audio to the group."""
from __future__ import annotations

from aiogram import F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.types import (
    CallbackQuery,
    InputRichBlockButtons,
    InputRichBlockParagraph,
    InputRichMessage,
    Message,
    RichMessageButton,
)

from community_bot.access import private_allowed
from community_bot.aliases import command_or_alias
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.ephemeral import keep_in_chat, reply_ttl
from community_bot.helpers import resolve_command_target
from community_bot.music_library import (
    LIBRARY_PREFIX,
    can_read_library,
    change_collection,
    get_collection,
    is_public,
    page_entries,
    set_public,
)
from community_bot.private_rich import standalone_rich_message
from community_bot.profile_track import audio_block
from community_bot.reply_rich import bot_publication


def button(text, action):
    return RichMessageButton(text=text, callback_data=LIBRARY_PREFIX + action)


async def library_card(db, viewer, owner, page=0, *, profile=False, shared=False):
    target = await db.get_user(owner)
    if shared and (target.get("profile_private") or not await is_public(db, owner)):
        return InputRichMessage(blocks=[
            InputRichBlockParagraph(text="🔒 Мои треки · приватная коллекция. Открой личку с Норой."),
            InputRichBlockButtons(buttons=[button("← Назад", f"back:{owner}")]),
        ], skip_entity_detection=True)
    entries, page, pages = page_entries(await get_collection(db, owner), page)
    mode = "p_" if profile else ""
    title = "🎧 Мои треки" if viewer == owner else "🎧 Треки · " + str(
        target.get("profile_name") or target.get("telegram_name") or "Участник"
    )
    blocks = [InputRichBlockParagraph(text=title)]
    if not entries:
        blocks.append(InputRichBlockParagraph(text="Пока нет сохранённых треков."))
    for key, track in entries:
        blocks.append(audio_block(track))
        if viewer == owner and not shared:
            blocks.append(InputRichBlockButtons(buttons=[button("−", f"{mode}del:{key[:32]}:{page}")]))
    nav = []
    if page:
        nav.append(button("‹", f"{mode}page:{owner}:{page - 1}"))
    if page + 1 < pages:
        nav.append(button("›", f"{mode}page:{owner}:{page + 1}"))
    blocks.append(InputRichBlockParagraph(text=f"Страница {page + 1} / {pages}"))
    if nav:
        blocks.append(InputRichBlockButtons(buttons=nav))
    if viewer == owner and not shared:
        public = await is_public(db, owner)
        blocks.append(InputRichBlockButtons(buttons=[
            button("🔓 Публичная" if public else "🔒 Только я", f"{mode}public:{int(not public)}:{page}"),
        ]))
    end = button("← Назад", f"back:{owner}") if profile else button("❌", "close")
    blocks.append(InputRichBlockButtons(buttons=[end]))
    return InputRichMessage(blocks=blocks, skip_entity_detection=True)


async def allowed_actor(db, settings, uid):
    actor = await db.get_user(uid)
    return bool(actor and actor.get("city") and await private_allowed(db, settings, uid))


async def deliver(bot, db, viewer, owner):
    # Even a public library is delivered to the requester, not broadcast.
    # A private library must never be sent into a shared chat.
    with standalone_rich_message(), bot_publication(), reply_ttl(None):
        await bot.send_rich_message(
            viewer, rich_message=await library_card(db, viewer, owner),
            protect_content=True,
        )


async def show_tracks(message: Message, db: Database, settings: Settings):
    if not message.from_user or message.sender_chat or (
        message.chat.type != "private" and message.chat.id != settings.community_chat_id
    ):
        return
    uid = message.from_user.id
    if not await allowed_actor(db, settings, uid):
        return
    person, args, explicit = await resolve_command_target(message, db)
    if args or (explicit and not person):
        await message.answer("Не нашла участника. Используй Нора треки @username.")
        return
    owner = int(person["user_id"]) if person else uid
    if not await can_read_library(db, settings, uid, owner):
        await message.answer("🔒 Коллекция закрыта или недоступна.")
        return
    try:
        await deliver(message.bot, db, uid, owner)
    except TelegramAPIError:
        await message.answer("Открой личный чат с Норой, нажми «Старт» и повтори команду.")
        return
    if message.chat.type != "private":
        await message.answer("🎧 Отправила треки тебе в личку.")


async def edit_profile_library(message, db, uid, page=0):
    shared = message.chat.type != "private"
    rich = await library_card(db, uid, uid, page, profile=True, shared=shared)
    with standalone_rich_message(), keep_in_chat(), bot_publication(), reply_ttl(None):
        await message.edit_text(rich_message=rich, parse_mode=None, reply_markup=None)


async def back_to_profile(message, db, settings, uid):
    user = await db.get_user(uid)
    if message.chat.type != "private":
        from community_bot.group_profile import restore_group_profile_card

        return await restore_group_profile_card(message, db, settings, user, uid)
    from community_bot.helpers import render_profile
    from community_bot.routers.profile import send_profile_card

    text = await render_profile(db, settings, user, compact=True)
    # Let the normal private navigation middleware rebuild the profile actions.
    await send_profile_card(message, user, settings, editable=True, text=text, replace=True, db=db)
    return True


async def library_callback(callback: CallbackQuery, db: Database, settings: Settings):
    message = callback.message
    uid = callback.from_user.id
    if not isinstance(message, Message) or not await allowed_actor(db, settings, uid):
        await callback.answer("Коллекция недоступна.", show_alert=True)
        return
    parts = (callback.data or "")[len(LIBRARY_PREFIX):].split(":")
    action = parts[0]
    try:
        if action == "open" and len(parts) == 2:
            owner = int(parts[1])
            if message.chat.type != "private" and message.chat.id != settings.community_chat_id:
                raise ValueError
            if not await can_read_library(db, settings, uid, owner):
                await callback.answer("🔒 Коллекция закрыта или недоступна.", show_alert=True)
                return
            if owner != uid:
                # Legacy public collection buttons remain readable in DMs.
                await deliver(callback.bot, db, uid, owner)
                await callback.answer("Отправила треки в личку")
                return
            shared = message.chat.type != "private"
            if shared and await db.get_ui_owner(message.chat.id, message.message_id) != uid:
                raise ValueError
            await edit_profile_library(message, db, uid)
            if shared:
                try:
                    await deliver(callback.bot, db, uid, uid)
                except TelegramAPIError:
                    await callback.answer("Открой личку с Норой для копии треков.", show_alert=True)
                    return
            await callback.answer("Треки открыты")
            return
        if action == "back" and len(parts) == 2:
            if int(parts[1]) != uid:
                raise ValueError
            if message.chat.type != "private" and (
                message.chat.id != settings.community_chat_id
                or await db.get_ui_owner(message.chat.id, message.message_id) != uid
            ):
                raise ValueError
            if not await back_to_profile(message, db, settings, uid):
                await callback.answer("Не удалось вернуть профиль.", show_alert=True)
                return
            await callback.answer()
            return
        if action == "p_page" and len(parts) == 3:
            if int(parts[1]) != uid:
                raise ValueError
            if message.chat.type != "private" and (
                message.chat.id != settings.community_chat_id
                or await db.get_ui_owner(message.chat.id, message.message_id) != uid
            ):
                raise ValueError
            await edit_profile_library(message, db, uid, int(parts[2]))
            await callback.answer()
            return
        if message.chat.type != "private" or message.chat.id != uid:
            raise ValueError
        profile = action.startswith("p_")
        if profile:
            action = action[2:]
            if action not in {"del", "public"}:
                raise ValueError
        if action == "close" and len(parts) == 1:
            await message.delete()
            await callback.answer()
            return
        if action == "page" and len(parts) == 3:
            owner, page = int(parts[1]), int(parts[2])
            if not await can_read_library(db, settings, uid, owner):
                await message.delete()
                await callback.answer("Коллекция теперь закрыта.", show_alert=True)
                return
        elif action == "del" and len(parts) == 3:
            owner, page = uid, int(parts[2])
            keys = [key for key in await get_collection(db, uid) if key[:32] == parts[1]]
            if len(keys) != 1:
                await callback.answer("Трек уже недоступен.")
                return
            await change_collection(db, uid, key=keys[0], saved=False)
        elif action == "public" and len(parts) == 3 and parts[1] in {"0", "1"}:
            owner, page = uid, int(parts[2])
            await set_public(db, uid, parts[1] == "1")
        else:
            raise ValueError
        with standalone_rich_message(), bot_publication(), reply_ttl(None):
            rich = await library_card(db, uid, owner, page, profile=profile)
            await message.edit_text(rich_message=rich, parse_mode=None)
        await callback.answer("Удалено" if action == "del" else None)
    except ValueError:
        await callback.answer("Карточка недоступна.", show_alert=True)
    except TelegramAPIError:
        await callback.answer("Не удалось открыть треки. Открой личный чат с Норой.", show_alert=True)


def register_library_handlers(router):
    router.message.register(show_tracks, command_or_alias("tracks"), StateFilter(None))
    router.callback_query.register(library_callback, F.data.startswith(LIBRARY_PREFIX))
