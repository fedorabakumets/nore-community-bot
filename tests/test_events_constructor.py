import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import EditMessageText, SendMessage
from aiohttp import web

from community_bot import december_cabin, miniapp
from community_bot.database import Database
from community_bot.events_api import config, delete, editor, participants, public_events, publish, save, validate
from community_bot.rsvp import refresh_event_markup
from community_bot.shop_api import purchase, quote


@pytest.fixture
async def env(tmp_path, monkeypatch):
    db = Database(tmp_path / 'events.db')
    await db.initialize()
    for uid in (1, 2, 3):
        await db.ensure_user(uid, f'person{uid}', f'Друг {uid}')
        await db.execute("UPDATE users SET cookies=100,reputation=100,profile_name='Имя',birth_date='2000-01-01',"
                         "hobbies='Город',profile_bio='Описание',avatar_file_id='photo' WHERE user_id=?", (uid,))
    bot = SimpleNamespace(**{method: AsyncMock(return_value=SimpleNamespace(message_id=123)) for method in (
        'send_message', 'send_photo', 'send_video', 'send_poll', 'pin_chat_message', 'unpin_chat_message',
        'edit_message_text', 'edit_message_caption', 'edit_message_media', 'edit_message_reply_markup')})
    monkeypatch.setattr('community_bot.stickers.send_context_sticker', AsyncMock(return_value=True))
    settings = SimpleNamespace(is_owner=lambda uid: uid == 1, owner_ids={1}, moderator_ids=set(),
                               community_chat_id=-100123, timezone='Europe/Moscow', restricted_reputation_threshold=0)
    return SimpleNamespace(db=db, bot=bot, settings=settings)


class Request(dict):
    def __init__(self, env, body=None, uid=1):
        super().__init__(actor={'id': uid})
        self.app = vars(env)
        self.body = body or {}

    async def json(self):
        return self.body


def fields(**kwargs):
    return dict(id='e' + 'a' * 20, title='Вечер настолок', description='Встреча <друзей>', price=0,
                location='Питер', capacity=1, revision=0, starts_at='2026-11-10T18:00',
                links=[{'label': 'Как добраться', 'url': 'https://example.org/map'}], **kwargs)


async def create(env, body=None):
    b = fields() if body is None else body
    await save(Request(env, b))
    item = json.loads((await editor(Request(env))).body)['items'][0]
    return item


@pytest.mark.parametrize("stored_username", ["Alice230305", None])
async def test_december_event_publish_and_rsvp(env, monkeypatch, stored_username):
    env.settings.owner_id = 1
    await env.db.ensure_user(2, stored_username, "Алиса")
    await env.db.ensure_user(3, "another_alice", "Алиса")
    env.bot.me = AsyncMock(return_value=SimpleNamespace(id=1234, username="NoraBot"))
    env.bot.get_chat_administrators = AsyncMock(return_value=[])
    members = {
        1234: SimpleNamespace(status="administrator", can_pin_messages=True),
        2: SimpleNamespace(user=SimpleNamespace(id=2, username="Alice230305", is_bot=False)),
        3: SimpleNamespace(user=SimpleNamespace(id=3, username="another_alice", is_bot=False)),
    }
    env.bot.get_chat_member = AsyncMock(side_effect=lambda chat, uid: members[uid])
    env.bot.send_photo.return_value = SimpleNamespace(message_id=123, photo=[SimpleNamespace(file_id="cover")])
    backup = AsyncMock(return_value=True)
    monkeypatch.setattr(december_cabin, "verify_requested_release_backup", backup)
    await december_cabin.publish_meetup(env.db, env.settings, env.bot)
    await december_cabin.publish_meetup(env.db, env.settings, env.bot)
    backup.assert_awaited_once()
    env.bot.send_photo.assert_awaited_once()
    env.bot.pin_chat_message.assert_awaited_once_with(env.settings.community_chat_id, 123, disable_notification=False)
    eid = december_cabin.EVENT_ID
    url = f"https://t.me/NoraBot?startapp=nora_event_{eid}"
    published = env.bot.send_photo.await_args.kwargs
    assert "<b>Что Нас там ждёт?</b>\n<blockquote>• Треск" in published["caption"]
    assert "шашлыки.</blockquote>\nПоиграем" in published["caption"]
    keyboard = published["reply_markup"].inline_keyboard
    assert keyboard[0][0].url == url and keyboard[1][0].callback_data == f"rsvp:{eid}"
    event = (await public_events(env.db, 3))[0]
    assert event["organizer"]["id"] == 2 and event["has_media"] and event["registration_only"]
    assert [block["kind"] for block in event["description_blocks"]] == ["text", "bold", "quote", "text"]

    body = {"event_id": eid, "price": 0}
    monkeypatch.setattr(miniapp, "actor", AsyncMock(return_value={"user_id": 3}))
    assert (await miniapp.join_event(Request(env, body))).status == 200
    assert (await miniapp.join_event(Request(env, body))).status == 409
    env.bot.send_message.assert_awaited_once()
    assert env.bot.send_message.await_args.args[0] == 3
    assert env.bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard[0][0].url == url
    assert env.bot.edit_message_reply_markup.await_args.kwargs["reply_markup"].inline_keyboard[0][0].url == url

    monkeypatch.setattr(miniapp, "actor", AsyncMock(return_value={"user_id": 2}))
    env.bot.send_message.side_effect = TelegramForbiddenError(method=SendMessage(chat_id=2, text=""), message="blocked")
    response = await miniapp.join_event(Request(env, body))
    assert response.status == 200 and "Подробности здесь" in json.loads(response.body)["message"]
    assert await env.db.event_participant_count(eid) == 2


@pytest.mark.parametrize("replace_photo_post", [False, True])
async def test_rich_event_keeps_nora_and_attendance_and_grants_scoped_editor(env, monkeypatch, replace_photo_post):
    eid = december_cabin.EVENT_ID
    url = f"https://t.me/NoraBot?startapp=nora_event_{eid}"
    await env.db.save_studio_event(eid, env.settings.community_chat_id, 123, "Домик",
                                   [{"text": "Нора", "url": url}], 0, 1, media_type="photo")
    await env.db.set_bot_state(f"event_config:{eid}", json.dumps({
        "organizer_id": 2, "registration_only": True, "media_id": "cover", "pinned": True,
        "post_buttons": [{"text": "Нора", "url": url}],
    }))
    await env.db.add_rsvp(eid, 2, 0, kind="rsvp")
    monkeypatch.setattr(december_cabin, "verify_requested_release_backup", AsyncMock())
    env.bot.send_rich_message = AsyncMock(return_value=SimpleNamespace(message_id=456))
    if replace_photo_post:
        env.bot.edit_message_text.side_effect = [TelegramBadRequest(
            method=EditMessageText(message_id=123), message="there is no text in the message to edit"
        )]
    await december_cabin.upgrade_meetup(env.db, env.settings, env.bot)
    await december_cabin.upgrade_meetup(env.db, env.settings, env.bot)
    new_id = 456 if replace_photo_post else 123
    assert (await env.db.get_studio_event(eid))["message_id"] == new_id
    assert env.bot.send_rich_message.await_count == int(replace_photo_post)
    payload = (env.bot.send_rich_message if replace_photo_post else env.bot.edit_message_text).await_args.kwargs
    blocks = payload["rich_message"].blocks
    assert blocks[0].photo.media == "cover"
    assert blocks[-1].buttons[0].callback_data == f"rsvp:{eid}"
    assert blocks[-1].buttons[0].text == "Я буду (1)"
    assert payload["reply_markup"].inline_keyboard[0][0].url == url
    if replace_photo_post:
        env.bot.pin_chat_message.assert_awaited_once_with(env.settings.community_chat_id, new_id,
                                                        disable_notification=True)
        env.bot.unpin_chat_message.assert_awaited_once_with(env.settings.community_chat_id, 123)
        assert env.bot.edit_message_reply_markup.await_args.kwargs["reply_markup"].inline_keyboard[0][0].url == url

    env.bot.edit_message_text.side_effect = None
    await env.db.add_rsvp(eid, 3, 0, kind="rsvp")
    assert await refresh_event_markup(env.bot, env.db, eid)
    assert env.bot.edit_message_text.await_args.kwargs["rich_message"].blocks[-1].buttons[0].text == "Я буду (2)"
    request = Request(env, uid=2)
    request.match_info, request.query = {"event_id": eid}, {}
    await env.db.execute("UPDATE users SET profile_private=1 WHERE user_id=3")
    people = json.loads((await participants(request)).body)
    assert people == {
        "items": [{"id": 2, "name": "Имя"}, {"name": "Участник со скрытым профилем"}],
        "next_offset": None,
    }
    assert not json.loads((await editor(request)).body)["can_delete"]
    new = fields()
    await save(Request(env, new, uid=2))
    draft = {"id": new["id"], "revision": 1}
    env.bot.send_message.return_value = SimpleNamespace(message_id=789)
    with pytest.raises(web.HTTPForbidden):
        await publish(Request(env, {**draft, "notify": True}, uid=2))
    assert (await publish(Request(env, draft, uid=2))).status == 200
    with pytest.raises(web.HTTPForbidden):
        await delete(request)
    with pytest.raises(web.HTTPForbidden):
        await editor(Request(env, uid=3))


async def test_authorization_draft_validation_and_preview(env):
    with pytest.raises(web.HTTPForbidden):
        await save(Request(env, fields(), uid=2))
    with pytest.raises(ValueError):
        validate({**fields(), 'links': [{'label': 'Bad', 'url': 'javascript:alert(1)'}]})
    item = await create(env)
    assert not item['published'] and item['revision'] == 1
    assert not await public_events(env.db, 2)
    assert item['starts_at'].endswith('+00:00') and item['location'] == 'Питер'
    assert (await save(Request(env, fields()))).status == 409


async def test_publish_idempotent_pin_poll_mentions_named_links_and_multiple_events(env):
    item = await create(env, {**fields(), 'poll': {'question': 'Что берём?', 'options': ['Шахматы', 'Карты']}})
    for uid in (1, 2, 3):
        await env.db.record_activity(uid, -100123, False)
    body = {'id': item['id'], 'revision': item['revision'], 'notify': True}
    for _ in range(2):
        assert (await publish(Request(env, body))).status == 200
    assert env.bot.send_message.await_count == 2  # post and one emoji-mention batch
    env.bot.pin_chat_message.assert_awaited_once()
    env.bot.send_poll.assert_awaited_once()
    text = env.bot.send_message.await_args_list[0].args[1]
    assert '<b>Доп. информация</b>' in text and '>Как добраться</a>' in text and '&lt;друзей&gt;' in text
    assert 'tg://user?id=2' in env.bot.send_message.await_args_list[1].args[1]
    # A second event is a separate active item; the first remains joinable.
    await create(env, {**fields(), 'id': 'e' + 'b' * 20})
    second = await env.db.get_studio_event('e' + 'b' * 20)
    env.bot.send_message.return_value = SimpleNamespace(message_id=124)
    await publish(Request(env, {'id': second['event_id'], 'revision': second['revision']}))
    assert len(await public_events(env.db, 2)) == 2


async def test_capacity_atomic_free_and_paid_refunds_once_and_other_event_unaffected(env):
    item = await create(env)
    await publish(Request(env, {'id': item['id'], 'revision': item['revision']}))
    results = await asyncio.gather(*(env.db.add_rsvp(item['id'], uid, 0, kind='rsvp') for uid in (2, 3)))
    assert sum(ok for ok, _ in results) == 1
    await delete(Request(env, {'id': item['id'], 'revision': item['revision']}))
    assert not await public_events(env.db, 2)
    b = {**fields(), 'id': 'e' + 'c' * 20, 'price': 20}
    paid = await create(env, b)
    env.bot.send_message.return_value = SimpleNamespace(message_id=125)
    await publish(Request(env, {'id': paid['id'], 'revision': paid['revision']}))
    results = await asyncio.gather(*(env.db.pay_event_offer(paid['id'], uid, 20) for uid in (2, 3)))
    assert sum(ok for ok, _, _ in results) == 1
    await delete(Request(env, {'id': paid['id'], 'revision': paid['revision']}))
    with pytest.raises(ValueError):
        await delete(Request(env, {'id': paid['id'], 'revision': paid['revision']}))
    assert (await env.db.get_user(2))['cookies'] == 100 and (await env.db.get_user(3))['cookies'] == 100


async def test_gifts_use_base_plus_ten_percent_and_revalidate_catalog(env):
    await env.db.upsert_shop_item('rep_shield', price=11, enabled=1)
    user = await env.db.get_user(1)
    q = await quote(env.db, env.settings, user, {'sku': 'rep_shield', 'recipient': '2'})
    assert q['price'] == 13 and q['gift']
    assert (await purchase(env.db, env.settings, None, user, q['token']))[0]
    assert (await env.db.get_user(1))['cookies'] == 87
    assert (await env.db.get_user(2))['hate_shields'] == 1
    assert not (await purchase(env.db, env.settings, None, user, q['token']))[0]
    q = await quote(env.db, env.settings, user, {'sku': 'rep_shield', 'recipient': '3'})
    await env.db.upsert_shop_item('rep_shield', price=20, enabled=1)
    assert not (await purchase(env.db, env.settings, None, user, q['token']))[0]
    assert (await env.db.get_user(3))['hate_shields'] == 0


async def test_unknown_delivery_does_not_repeat_post(env):
    item = await create(env)
    env.bot.send_message.side_effect = TimeoutError('Unknown delivery')
    body = {'id': item['id'], 'revision': item['revision']}
    with pytest.raises(TimeoutError):
        await publish(Request(env, body))
    with pytest.raises(ValueError, match='не подтверждена'):
        await publish(Request(env, body))
    assert env.bot.send_message.await_count == 1
    assert (await config(env.db, item['id']))['post_sent'] == 'sending'


async def test_editing_preserves_existing_photo_imports_named_links_and_rechecks_upload_owner(env):
    await env.db.save_studio_event('legacy', -100123, 45, 'Старое событие',
                                   [{'text': 'Карта', 'url': 'https://example.org'}], 0, 1, media_type='photo')
    item = json.loads((await editor(Request(env))).body)['items'][0]
    assert item['has_media'] and item['links'][0]['label'] == 'Карта'
    await save(Request(env, {**fields(), 'id': 'legacy', 'revision': 0, 'title': 'Новое имя'}))
    env.bot.edit_message_caption.assert_awaited()
    assert 'Новое имя' in env.bot.edit_message_caption.await_args.kwargs['caption']
    assert (await env.db.get_studio_event('legacy'))['buttons_json'] == '[]'
    await env.db.set_bot_state('event_upload:mine', json.dumps({
        'owner': 2, 'media_id': 'untrusted-file', 'cover_id': 'untrusted-file', 'media_type': 'photo'}))
    with pytest.raises(ValueError, match='медиа'):
        await save(Request(env, {**fields(), 'media_token': 'mine'}))


async def test_price_capacity_and_poll_protect_existing_participants(env):
    item = await create(env)
    await publish(Request(env, {'id': item['id'], 'revision': item['revision']}))
    await env.db.add_rsvp(item['id'], 2, 0, kind='rsvp')
    with pytest.raises(ValueError, match='Цена'):
        await save(Request(env, {**fields(), 'revision': 1, 'price': 10}))
    # Opening a second unlimited event never consumes another event's seats.
    second = await create(env, {**fields(), 'id': 'e' + 'd' * 20, 'capacity': 0})
    env.bot.send_message.return_value = SimpleNamespace(message_id=124)
    await publish(Request(env, {'id': second['id'], 'revision': 1}))
    assert all(r[0] for r in await asyncio.gather(*(env.db.add_rsvp(second['id'], uid, 0) for uid in (2, 3))))
    with pytest.raises(ValueError, match='Лимит'):
        await save(Request(env, {**fields(), 'id': second['id'], 'revision': 1, 'capacity': 1}))


async def test_join_uses_requested_event_not_current_selection(env):
    from community_bot.miniapp import join_event

    await env.db.save_studio_event('first', -100123, 20, 'Первая', [], 0, 1)
    await env.db.save_studio_event('second', -100123, 21, 'Вторая', [], 0, 1)
    await env.db.set_bot_state('current_studio_event', 'second')
    request = Request(env, {'event_id': 'first', 'price': 0}, uid=2)
    assert (await join_event(request)).status == 200
    assert await env.db.has_event_rsvp('first', 2)
    assert not await env.db.has_event_rsvp('second', 2)
