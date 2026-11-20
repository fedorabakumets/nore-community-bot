from collections import OrderedDict
from datetime import UTC, datetime, timedelta

from aiogram import BaseMiddleware, Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message, MessageReactionUpdated, ReactionTypeCustomEmoji, ReactionTypeEmoji, User

from community_bot.chat_memory import MAX_ARCHIVE_ROWS, MEMORY_TTL_HOURS
from community_bot.social_emoji import interaction_emoji


class ReactionAuthors(BaseMiddleware):
    """Index the author and topic only, including media with no searchable text."""

    def __init__(self):
        self.authors: OrderedDict[tuple[int, int], tuple[User, int | None, datetime]] = OrderedDict()
        self.custom_emoji: OrderedDict[str, str | None] = OrderedDict()
        self.updates: OrderedDict[int, None] = OrderedDict()

    async def __call__(self, handler, event: Message, data):
        settings = data.get("settings")
        if settings and event.chat.id == settings.community_chat_id:
            self._remember(event)
            if event.reply_to_message:
                self._remember(event.reply_to_message)
        return await handler(event, data)

    def _remember(self, message: Message) -> None:
        author = message.from_user
        if author is None or author.is_bot or message.sender_chat:
            return
        key = (message.chat.id, message.message_id)
        self.authors[key] = (author, message.message_thread_id if message.is_topic_message else None, datetime.now(UTC))
        self.authors.move_to_end(key)
        if len(self.authors) > MAX_ARCHIVE_ROWS:
            self.authors.popitem(last=False)

    async def target(self, db, chat_id: int, message_id: int):
        cutoff = datetime.now(UTC) - timedelta(hours=MEMORY_TTL_HOURS)
        author = self.authors.get((chat_id, message_id))
        if author and author[2] >= cutoff:
            user, thread, _ = author
            target = await db.get_user(user.id)
            if target is None:
                from community_bot.helpers import register_telegram_user

                target = await register_telegram_user(db, user)
            return target, thread
        row = await db.fetchone(
            "SELECT user_id, thread_id FROM community_messages WHERE chat_id=? AND message_id=? AND sent_at>=?",
            (chat_id, message_id, cutoff.isoformat()),
        )
        return (await db.get_user(row["user_id"]), row["thread_id"]) if row else (None, None)

    def claim_update(self, update_id: int) -> bool:
        if update_id in self.updates:
            return False
        self.updates[update_id] = None
        if len(self.updates) > MAX_ARCHIVE_ROWS:
            self.updates.popitem(last=False)
        return True

    async def added(self, event: MessageReactionUpdated, bot: Bot) -> set[str]:
        custom_ids = list(dict.fromkeys(
            r.custom_emoji_id for r in [*event.old_reaction, *event.new_reaction]
            if isinstance(r, ReactionTypeCustomEmoji) and r.custom_emoji_id not in self.custom_emoji
        ))
        if custom_ids:
            try:
                stickers = await bot.get_custom_emoji_stickers(custom_ids)
            except TelegramAPIError:
                pass
            else:
                matches = {sticker.custom_emoji_id: interaction_emoji(sticker.emoji or "") for sticker in stickers}
                for sticker_id in custom_ids:
                    self.custom_emoji[sticker_id] = matches.get(sticker_id)
                    if len(self.custom_emoji) > 1000:
                        self.custom_emoji.popitem(last=False)

        def kinds(reactions):
            result = set()
            for reaction in reactions:
                if isinstance(reaction, ReactionTypeEmoji):
                    kind = interaction_emoji(reaction.emoji)
                elif isinstance(reaction, ReactionTypeCustomEmoji):
                    kind = self.custom_emoji.get(reaction.custom_emoji_id)
                else:
                    continue
                if kind:
                    result.add(kind)
            return result

        return kinds(event.new_reaction) - kinds(event.old_reaction)
