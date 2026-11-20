"""Telegram game invitations and their recipient-bound Mini App entry point."""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramNotFound
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichBlockButtons,
    InputRichBlockParagraph,
    InputRichMessage,
    Message,
    RichBlockButtons,
    RichMessageButton,
    RichTextTextMention,
    User,
)
from aiohttp import web

from community_bot.access import miniapp_allowed
from community_bot.ephemeral import keep_in_chat
from community_bot.helpers import display_name, user_link
from community_bot.private_rich import standalone_rich_message
from community_bot.reply_rich import bot_publication

router = Router(name="game_invitations")
logger = logging.getLogger(__name__)
_GAME_NAMES = {"mafia": "«Мафию»", "sea": "«Морской бой»", "durak": "«Дурака»", "barricade": "«Баррикаду»"}
_DISMISS = "game-invite:close:"
_DELIVERY_ERRORS = (TelegramAPIError, OSError, TimeoutError)


def _mention(user):
    name = display_name(user, "Участник")
    label = f"@{user['username']}" if user.get("username") else name
    return RichTextTextMention(
        text=label, user=User(id=user["user_id"], first_name=name, is_bot=False),
    )


async def _send(bot, chat_id, sender, recipient, line, url, dismiss):
    text = [recipient, ", ", sender, line] if chat_id != recipient.user.id else [sender, line]
    buttons = [
        RichMessageButton(text="❌", style="danger", callback_data=dismiss),
        RichMessageButton(text="✅", style="success", url=url),
    ]
    with standalone_rich_message(), bot_publication(), keep_in_chat():
        try:
            await bot.send_rich_message(
                chat_id,
                rich_message=InputRichMessage(
                    blocks=[
                        InputRichBlockParagraph(text=text),
                        InputRichBlockButtons(align="center", buttons=buttons),
                    ],
                    skip_entity_detection=True,
                ),
            )
        except (TelegramBadRequest, TelegramNotFound):
            plain = "".join(part if isinstance(part, str) else user_link(part.user.id, part.text) for part in text)
            await bot.send_message(
                chat_id, plain, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(**button.model_dump(exclude_none=True)) for button in buttons
                ]]),
            )


async def deliver_game_invitation(bot, db, settings, game, room_id, sender_id, recipient_id, inbox_id):
    """Send each copy independently once the invitation and inbox entry are committed."""
    if bot is None:
        return
    try:
        username = (await bot.me()).username
    except _DELIVERY_ERRORS as error:
        logger.warning("Game invitation kept in Nora inbox: %s", type(error).__name__)
        return
    if not username:
        return
    sender = _mention(await db.get_user(sender_id))
    recipient = _mention(await db.get_user(recipient_id))
    url = f"https://t.me/{username}?startapp=nora_inv_{game}_{recipient_id}_{room_id}"
    dismiss = f"{_DISMISS}{recipient_id}:{inbox_id}"
    line = f" приглашает сыграть в {_GAME_NAMES[game]}!"

    async def deliver(chat_id):
        try:
            await _send(bot, chat_id, sender, recipient, line, url, dismiss)
        except _DELIVERY_ERRORS as error:
            logger.warning("Game invitation delivery failed: %s", type(error).__name__)
            return
        if chat_id == recipient_id:
            await db.notify_mark_delivered(inbox_id)

    if settings.community_chat_id:
        await asyncio.gather(deliver(recipient_id), deliver(settings.community_chat_id))
    else:
        await deliver(recipient_id)


@router.callback_query(F.data.startswith(_DISMISS))
async def close_game_invitation(callback: CallbackQuery, settings):
    message, data, uid = callback.message, callback.data, callback.from_user.id
    if not data.startswith(f"{_DISMISS}{uid}:"):
        await callback.answer("Приглашение адресовано другому игроку.", show_alert=True)
        return
    if not isinstance(message, Message) or message.chat.id not in {uid, settings.community_chat_id}:
        await callback.answer("Сообщение уже недоступно.", show_alert=True)
        return
    if message.rich_message:
        rows = [block.buttons for block in message.rich_message.blocks if isinstance(block, RichBlockButtons)]
    else:
        rows = message.reply_markup.inline_keyboard if message.reply_markup else []
    if not any(button.callback_data == data for row in rows for button in row):
        await callback.answer("Сообщение уже недоступно.", show_alert=True)
        return
    try:
        await message.delete()
    except TelegramAPIError:
        await callback.answer("Telegram не смог удалить сообщение.", show_alert=True)
        return
    await callback.answer()


async def open_invitation(request):
    from community_bot import durak_rooms as durak
    from community_bot import mafia_api, sea_api

    body = await request.json()
    if not isinstance(body, dict):
        raise ValueError("Ссылка на приглашение устарела")
    game, rid, recipient = body.get("game"), body.get("room_id"), body.get("recipient")
    uid, db, settings = request["actor"]["id"], request.app["db"], request.app["settings"]
    if type(recipient) is not int or uid != recipient:
        return web.json_response({"error": "Приглашение адресовано другому игроку"}, status=403)
    room_pattern = r"[a-f0-9]{16}" if game in ("durak", "barricade") else r"[A-Za-z0-9_-]{22}"
    if not isinstance(game, str) or game not in _GAME_NAMES or not isinstance(rid, str) or not re.fullmatch(
        room_pattern, rid,
    ):
        raise ValueError("Ссылка на приглашение устарела")
    if not await miniapp_allowed(db, settings, uid):
        return web.json_response({"error": "Миниапка доступна участникам Норы"}, status=403)

    if game in ("durak", "barricade"):
        async with db.connect() as conn:
            await conn.execute("BEGIN")
            room = await durak._room(conn, rid, game)
            own = await durak.one(conn, "SELECT 1 FROM durak_members WHERE room=? AND uid=? AND active=1", (rid, uid))
            if not own and (room["status"] != "waiting" or room["deadline"] <= time.time()
                            or not await durak._invited(conn, rid, uid)
                            or await durak._blocked(conn, rid, uid)):
                raise ValueError("Приглашение больше не действует")
    else:
        api = mafia_api if game == "mafia" else sea_api
        table = "mini_mafia_members" if game == "mafia" else "mini_sea_members"
        member_query = f"SELECT 1 FROM {table} WHERE room_id=? AND user_id=? AND active=1"
        if not await db.fetchone(member_query, (rid, uid)):
            try:
                await api.apply_action(db, settings, uid, {
                    "action": "respond", "room_id": rid, "accept": True, "request_id": secrets.token_hex(16),
                })
            except api.Conflict as error:
                # Both Telegram copies can be opened before either request finishes.
                if not await db.fetchone(member_query, (rid, uid)):
                    return web.json_response({"error": str(error)}, status=409)
    return web.json_response({"room_id": rid})
