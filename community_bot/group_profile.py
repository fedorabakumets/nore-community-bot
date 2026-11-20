"""Compact, actionable profile cards shared in Telegram groups."""

from __future__ import annotations

from asyncio import Lock
from html import escape
from typing import Any
from weakref import WeakValueDictionary

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramNotFound
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    InputRichBlockButtons,
    InputRichBlockDetails,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichBlockTable,
    InputRichBlockVideo,
    InputRichMessage,
    Message,
    RichBlockTableCell,
    RichMessageButton,
    RichTextBold,
    RichTextButton,
)

from community_bot import friends_api, social_likes
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.domain import reputation_tier
from community_bot.ephemeral import keep_in_chat
from community_bot.helpers import role_title
from community_bot.keyboards import ibtn
from community_bot.media_cache import profile_photo_input
from community_bot.private_rich import _reusable
from community_bot.profile_fields import profile_age
from community_bot.profile_track import audio_block, get_track
from community_bot.reply_rich import bot_publication
from community_bot.ui_owner import bind_ui_owner

FRIEND_PREFIX = "gprofile:friend:"
LIKE_PREFIX = "gprofile:like:"
_EDIT_LOCKS: WeakValueDictionary[tuple[int, int], Lock] = WeakValueDictionary()


def _stats(user, settings):
    reputation = int(user["reputation"])
    tier = reputation_tier(reputation, settings.restricted_reputation_threshold)
    balance = f'{int(user["cookies"]):,}'.replace(",", "\u202f")
    return balance, f"{reputation}/100 · {tier.label}"


def _table(user, settings):
    rows = (("🍪 Печеньки", "Репутация"), _stats(user, settings))
    return InputRichBlockTable(
        cells=[
            [RichBlockTableCell(text=value, align="center", valign="middle", is_header=(index == 0))
             for value in row]
            for index, row in enumerate(rows)
        ],
        is_bordered=True,
        is_compact=True,
    )


async def _friend_icon(db, requester_id, target_id):
    return "🫂" if await friends_api.accepted(db, requester_id, target_id) else "👤"


async def _avatar(db, user):
    if not (file_id := user.get("avatar_file_id")):
        return None
    if user.get("avatar_media_type") == "video":
        return InputRichBlockVideo(video=InputMediaVideo(media=file_id))
    if photo := await profile_photo_input(db, file_id):
        return InputRichBlockPhoto(photo=InputMediaPhoto(media=photo))
    return None


async def send_group_profile(
    message: Message,
    db: Database,
    settings: Settings,
    user: dict[str, Any],
    requester_id: int,
    *,
    show_username: bool = True,
) -> Message:
    uid = int(user["user_id"])
    name = str(user.get("profile_name") or user.get("telegram_name") or "")
    name = (" ".join(name.split()) or f"Участник {uid}")[:100]
    role = await role_title(db, user["role"])
    age = profile_age(user)
    handle = f"@{user['username']}" if show_username and user.get("username") else ""
    subtitle = " · ".join(filter(None, (role, handle, f"Возраст: {age}" if age else "")))

    commands = [ibtn("❌", "ui:close", "danger")]
    bot = message.bot
    try:
        username = (await bot.me()).username
    except TelegramAPIError:
        username = None
    if username:
        commands.append(InlineKeyboardButton(
            text="📱", url=f"https://t.me/{username}?startapp=nora_profile_{uid}", style="primary",
        ))
    commands.append(ibtn(await _friend_icon(db, requester_id, uid), f"{FRIEND_PREFIX}{uid}", "success"))
    votes = [ibtn("👍", f"profile_action:rep_up:{uid}"), ibtn("👎", f"profile_action:rep_down:{uid}")]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[votes, commands])
    like = f"❤️ {await social_likes.count(db, uid)}"
    reputation, actions = [
        InputRichBlockButtons(align="center", buttons=[
            RichMessageButton(**button.model_dump(exclude_none=True)) for button in row
        ]) for row in keyboard.inline_keyboard
    ]
    details = [
        InputRichBlockDetails(summary=label, blocks=[InputRichBlockParagraph(text=value)])
        for label, field in (("О себе", "profile_bio"), ("Увлечения", "hobbies"))
        if (value := str(user.get(field) or "").strip())
    ]
    track = await get_track(db, uid) if not user.get("profile_private") else None
    body = [
        reputation,
        InputRichBlockParagraph(text=[
            RichTextBold(text=name), "  ",
            RichTextButton(button=RichMessageButton(text=like, style="link", callback_data=f"{LIKE_PREFIX}{uid}")),
        ]),
        InputRichBlockParagraph(text=subtitle),
        *details,
        _table(user, settings),
        actions,
    ]
    avatar = await _avatar(db, user)
    thread = message.message_thread_id if message.is_topic_message else None
    sent = None
    profile_blocks = [*body[:3], audio_block(track), *body[3:]] if track else body
    attempts = [[avatar, *profile_blocks], profile_blocks] if avatar else [profile_blocks]
    if track:
        attempts.extend([[avatar, *body], body] if avatar else [body])
    audio_inline = bool(track)
    for blocks in attempts:
        audio_inline = bool(track and any(block.type == "audio" for block in blocks))
        try:
            sent = await bot.send_rich_message(
                message.chat.id, message_thread_id=thread,
                rich_message=InputRichMessage(blocks=blocks, skip_entity_detection=True),
            )
            break
        except (TelegramBadRequest, TelegramNotFound):
            continue
    if sent is None:
        audio_inline = False
        balance, score = _stats(user, settings)
        text = f"<b>{escape(name)}</b>\n{escape(subtitle)}"
        for detail in details:
            content = escape(detail.blocks[0].text)
            text += f"\n<blockquote expandable>{detail.summary}\n{content}</blockquote>"
        text += f"\n🍪 {balance} · Репутация {escape(score)}"
        with bot_publication():
            sent = await bot.send_message(
                message.chat.id, text, message_thread_id=thread, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [ibtn(like, f"{LIKE_PREFIX}{uid}")], votes, commands,
                ]),
            )
    if track and not audio_inline:
        try:
            await sent.reply_audio(track["file_id"], title=track["title"], performer=track["artist"] or None)
        except TelegramAPIError:
            pass
    await bind_ui_owner(db, sent, requester_id, "profile")
    return sent


async def refresh_group_profile(message: Message, db: Database, settings: Settings, target_id: int) -> None:
    rich = message.rich_message
    blocks = _reusable(rich.model_dump(exclude_none=True)["blocks"]) if rich else []
    friend = next((
        button for block in blocks if block["type"] == "buttons" for button in block["buttons"]
        if button.get("callback_data") == f"{FRIEND_PREFIX}{target_id}"
    ), None)
    like_data = f"{LIKE_PREFIX}{target_id}"
    like = next((
        part["button"] for block in blocks if block["type"] == "paragraph" and isinstance(block["text"], list)
        for part in block["text"] if isinstance(part, dict) and part.get("type") == "button"
        and part["button"].get("callback_data") == like_data
    ), None)
    if friend is None and (rich or not message.reply_markup):
        return
    lock = _EDIT_LOCKS.setdefault((message.chat.id, message.message_id), Lock())
    async with lock:
        owner = await db.get_ui_owner(message.chat.id, message.message_id)
        user = await db.get_user(target_id)
        if owner is None or not user or user.get("profile_private"):
            return
        try:
            with keep_in_chat(), bot_publication():
                if friend is not None:
                    friend["text"] = await _friend_icon(db, owner, target_id)
                    if like is not None:
                        like["text"] = f"❤️ {await social_likes.count(db, target_id)}"
                    blocks = [_table(user, settings) if block["type"] == "table" else block for block in blocks]
                    await message.edit_text(
                        parse_mode=None, rich_message=InputRichMessage(blocks=blocks, skip_entity_detection=True),
                    )
                else:
                    markup = message.reply_markup.model_copy(deep=True)
                    for row in markup.inline_keyboard:
                        for button in row:
                            if button.callback_data == like_data:
                                button.text = f"❤️ {await social_likes.count(db, target_id)}"
                                await message.edit_reply_markup(reply_markup=markup)
                                return
        except TelegramAPIError:
            # The action already succeeded, even if this card has since expired.
            pass
