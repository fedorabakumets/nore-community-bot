from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SetChatMemberTag

from community_bot import social_likes
from community_bot import telegram_like_tags as tags
from community_bot.database import Database

CHAT = -100123


def member(tag=None, *, status=ChatMemberStatus.MEMBER, is_bot=False, **kwargs):
    return SimpleNamespace(user=SimpleNamespace(is_bot=is_bot), status=status, tag=tag, **kwargs)


class FakeBot:
    id = 7

    def __init__(self):
        self.rights = False
        self.members = {}
        self.get_chat_member = AsyncMock(side_effect=self.read)
        self.set_chat_member_tag = AsyncMock(side_effect=self.write)
        self.set_chat_administrator_custom_title = AsyncMock(side_effect=self.write_title)

    async def read(self, chat, uid):
        assert chat == CHAT
        if uid == self.id:
            status = ChatMemberStatus.ADMINISTRATOR if self.rights else ChatMemberStatus.MEMBER
            return SimpleNamespace(status=status, can_manage_tags=self.rights)
        return self.members[uid]

    async def write(self, chat, uid, tag):
        assert chat == CHAT
        self.members[uid].tag = tag
        return True

    async def write_title(self, chat, uid, custom_title):
        assert chat == CHAT
        self.members[uid].custom_title = custom_title
        return True


@pytest.fixture
async def db(tmp_path):
    db = Database(tmp_path / 'tags.sqlite3')
    await db.initialize()
    for uid in range(1, 7):
        await db.ensure_user(uid, telegram_name='Участник')
    return db


async def test_backfills_updates_own_tag_and_respects_telegram_and_profile_privacy(db):
    bot = FakeBot()
    bot.members = {
        1: member(),
        2: member('Вручную'),
        3: member(status=ChatMemberStatus.CREATOR),
        4: member(),
        5: member(is_bot=True),
        6: member(status=ChatMemberStatus.RESTRICTED, is_member=False),
    }
    for uid in bot.members:
        await db.set_bot_state(f'{social_likes.COUNT_PREFIX}{uid}', '49')
    await db.update_profile(4, 'profile_private', 1)

    deferred = {}
    await tags.sync_like_tags(db, bot, CHAT, deferred)
    bot.get_chat_member.assert_awaited_once_with(CHAT, bot.id)
    bot.set_chat_member_tag.assert_not_awaited()
    bot.rights = True
    await tags.sync_like_tags(db, bot, CHAT, deferred)
    assert bot.members[1].tag == '♡ 49'
    assert bot.members[2].tag == 'Вручную ♡ 49'
    bot.set_chat_administrator_custom_title.assert_not_awaited()

    assert await social_likes.give(db, 2, 1) is None
    await tags.sync_like_tags(db, bot, CHAT, deferred)
    bot.set_chat_member_tag.assert_awaited_with(CHAT, 1, tag='♡ 50')
    bot.get_chat_member.reset_mock()
    await tags.sync_like_tags(db, bot, CHAT, deferred)
    bot.get_chat_member.assert_not_awaited()

    await db.update_profile(1, 'profile_private', 1)
    await tags.sync_like_tags(db, bot, CHAT, deferred)
    bot.set_chat_member_tag.assert_awaited_with(CHAT, 1, tag='')
    assert await social_likes.count(db, 1) == 50
    assert not await db.get_bot_state(f'{tags.TAG_STATE_PREFIX}{CHAT}:1')
    assert bot.members[2].tag == 'Вручную ♡ 49' and bot.set_chat_member_tag.await_count == 4


async def test_network_failure_after_telegram_applied_tag_can_be_reconciled(db):
    bot = FakeBot()
    bot.rights = True
    bot.members[1] = member('Свой тег')
    await db.set_bot_state(f'{social_likes.COUNT_PREFIX}1', '1')

    async def wrote_but_disconnected(chat, uid, tag):
        await bot.write(chat, uid, tag)
        raise TelegramNetworkError(SetChatMemberTag(chat_id=chat, user_id=uid, tag=tag), 'connection lost')

    bot.set_chat_member_tag.side_effect = wrote_but_disconnected
    with pytest.raises(TelegramNetworkError):
        await tags.sync_like_tags(db, bot, CHAT, {})
    key = f'{tags.TAG_STATE_PREFIX}{CHAT}:1'
    pending = tags.TagState.read(await db.get_bot_state(key))
    assert pending.base == 'Свой тег' and pending.pending == 'Свой тег ♡ 1'

    bot.set_chat_member_tag.side_effect = bot.write
    await tags.sync_like_tags(db, bot, CHAT, {})
    state = tags.TagState.read(await db.get_bot_state(key))
    assert state.base == 'Свой тег' and state.applied == 'Свой тег ♡ 1' and state.pending is None
    assert bot.set_chat_member_tag.await_count == 1

    bot.members[1].tag = 'Ручной тег'
    await db.update_profile(1, 'profile_private', 1)
    await tags.sync_like_tags(db, bot, CHAT, {})
    assert bot.members[1].tag == 'Ручной тег' and bot.set_chat_member_tag.await_count == 1


async def test_admin_title_suffix_updates_in_place_and_preserves_protected_titles(db, monkeypatch):
    bot = FakeBot()
    bot.rights = True
    bot.members = {
        1: member(status=ChatMemberStatus.ADMINISTRATOR, custom_title='Модер', can_be_edited=True),
        2: member(status=ChatMemberStatus.ADMINISTRATOR, custom_title='Главный', can_be_edited=False),
        3: member(status=ChatMemberStatus.CREATOR, custom_title='Владелец'),
        4: member(status=ChatMemberStatus.ADMINISTRATOR, custom_title=None, can_be_edited=True),
        5: member(status=ChatMemberStatus.ADMINISTRATOR, custom_title='Суперадмин чата', can_be_edited=True),
        6: member(status=ChatMemberStatus.ADMINISTRATOR, custom_title='Администратор', can_be_edited=True),
    }
    counts = (49, 50, 50, 4, 5, 6)
    for uid, count in enumerate(counts, start=1):
        await db.set_bot_state(f'{social_likes.COUNT_PREFIX}{uid}', str(count))
    monkeypatch.setattr(tags, 'monotonic', lambda: 10.0)
    checked = {}
    await tags.sync_like_tags(db, bot, CHAT, checked)
    assert [item.custom_title for item in bot.members.values()] == [
        'Модер ♡ 49', 'Главный', 'Владелец', 'Админ ♡ 4', 'Суперадмин чата', 'Администратор ♡6',
    ]
    assert [call.args[1] for call in bot.set_chat_administrator_custom_title.await_args_list] == [1, 4, 6]
    bot.set_chat_member_tag.assert_not_awaited()

    assert await social_likes.give(db, 3, 1) is None
    await tags.sync_like_tags(db, bot, CHAT, checked)
    assert bot.members[1].custom_title == 'Модер ♡ 50'

    bot.members[1].custom_title = 'Куратор ♡ 50'
    monkeypatch.setattr(tags, 'monotonic', lambda: 700.0)
    await tags.sync_like_tags(db, bot, CHAT, checked)
    assert bot.members[1].custom_title == 'Куратор ♡ 50'
    assert await social_likes.give(db, 2, 1) is None
    await tags.sync_like_tags(db, bot, CHAT, checked)
    assert bot.members[1].custom_title == 'Куратор ♡ 51'

    await db.update_profile(1, 'profile_private', 1)
    await db.update_profile(4, 'profile_private', 1)
    await tags.sync_like_tags(db, bot, CHAT, checked)
    assert bot.members[1].custom_title == 'Куратор'
    assert bot.members[4].custom_title == ''


@pytest.mark.parametrize('saved', ['♡ 49', '♡ 48\n♡ 49'])
async def test_existing_managed_tag_is_updated_without_duplicate_suffix(db, saved):
    bot = FakeBot()
    bot.rights = True
    bot.members[1] = member('♡ 49')
    await db.set_bot_state(f'{social_likes.COUNT_PREFIX}1', '50')
    await db.set_bot_state(f'{tags.TAG_STATE_PREFIX}{CHAT}:1', saved)
    await tags.sync_like_tags(db, bot, CHAT, {})
    bot.set_chat_member_tag.assert_awaited_once_with(CHAT, 1, tag='♡ 50')


async def test_new_role_inserted_before_a_count_has_one_separator(db):
    bot = FakeBot()
    bot.rights = True
    bot.members[1] = member('Тестер ♡ 49')
    await db.set_bot_state(f'{social_likes.COUNT_PREFIX}1', '50')
    await db.set_bot_state(f'{tags.TAG_STATE_PREFIX}{CHAT}:1', '♡ 49')
    await tags.sync_like_tags(db, bot, CHAT, {})
    bot.set_chat_member_tag.assert_awaited_once_with(CHAT, 1, tag='Тестер ♡ 50')
