import asyncio
import json
import zlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError, TelegramNotFound
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from community_bot import profile_access_rollout as rollout
from community_bot import widget_inbox
from community_bot import widget_notifications as notices
from community_bot.cabinet_api import notices as list_notices
from community_bot.cabinet_api import notices_update, widget_notice
from community_bot.database import Database
from community_bot.message_widgets import WidgetUpdateMiddleware
from community_bot.miniapp import protection
from community_bot.private_rich import PrivateRichMiddleware
from tests.test_miniapp import Request, signed


class WidgetSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.failures = {}

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109
        self.calls.append(method)
        name = method.__api_method__
        if name in self.failures:
            raise self.failures[name](method, "fake API error")
        if name == "getMe":
            return User(id=bot.id, is_bot=True, first_name="Нора", username="nora_test_bot")
        if name in {"sendWidget", "sendMessage"}:
            number = sum(call.__api_method__ == name for call in self.calls)
            return Message(message_id=455 + number, chat=Chat(id=method.chat_id, type="private"),
                           date=datetime.now(UTC), widget={"id": "fixture"})
        return True


@pytest.fixture
async def runtime(tmp_path, monkeypatch):
    db = Database(tmp_path / "widgets.db")
    await db.initialize()
    for user_id in (7, 8):
        await db.ensure_user(user_id)
        await db.set_role(user_id, "moderator")
    await db.set_bot_state("private_rich_panel:7", '{"message_id":123,"screen":"home"}')
    clock = SimpleNamespace(now=1_792_000_000)
    monkeypatch.setattr(notices, "time", lambda: clock.now)
    monkeypatch.setattr(widget_inbox, "time", lambda: clock.now)
    session = WidgetSession()
    bot = Bot("123456:isolated-widget-test", session=session)
    bot.community_db = db
    session.middleware.register(PrivateRichMiddleware())
    yield bot, db, session, clock
    await session.close()


async def emit(bot, db, event="rep:100", recipient=7):
    return await notices.send_notification(
        bot, db, recipient, notices.Sender("member", "@member", 8), "Изменение репутации",
        "Участник поддержал тебя.", "Полные подробности", "reputation",
        category="widget_reputation", event_key=event, context="В сообществе",
    )


def api_calls(session):
    return [method for method in session.calls if method.__api_method__ != "getMe"]


async def test_opt_in_concurrent_delivery_and_caption(runtime):
    bot, db, session, _ = runtime
    assert await emit(bot, db) == "suppressed"
    assert not api_calls(session)
    request = Request(db, body={"channel": "widget_reputation", "enabled": True, "digest": False})
    assert (await notices_update(request)).status == 200
    request.body["digest"] = True
    with pytest.raises(ValueError):
        await notices_update(request)

    outcomes = await asyncio.gather(emit(bot, db), emit(bot, db), emit(bot, db))
    assert sorted(outcomes) == ["sent", "suppressed", "suppressed"]
    assert await emit(bot, db, "rep:101") == "sent"
    assert await emit(bot, db) == "suppressed"
    sent, second = api_calls(session)
    assert sent.__api_method__ == "sendWidget" and sent.chat_id == 7
    assert sent.disable_notification is False and sent.allow_queries is True
    assert sent.reply_markup is None and sent.height is None and sent.width is None
    assert sent.parse_mode == "HTML"
    assert "У вас 1 уведомление!" in sent.caption and "репутации" not in sent.caption
    assert json.loads(sent.chat_data)["p"]["sender"] == "@member"
    assert second.__api_method__ == "sendWidget"
    assert json.loads(second.chat_data)["n"] == 1
    assert json.loads(second.chat_data)["p"]["id"] != json.loads(sent.chat_data)["p"]["id"]
    row = await db.fetchone("SELECT * FROM widget_notifications WHERE message_id=456")
    assert row["sender_id"] == 8 and row["details"] == "Полные подробности"
    assert f"https://t.me/nora_test_bot?startapp=nora_notice_{row['id']}" in sent.caption
    assert await db.get_bot_state("private_rich_panel:7") == '{"message_id":123,"screen":"home"}'


def widget_query(**changes):
    return {
        "id": "fixture-query", "from": {"id": 7}, "chat": {"type": "private", "id": 7},
        "message_id": 456, "type": {"type": "data"}, "data": notices.READ_REQUEST,
        **changes,
    }


async def test_query_authorization_and_restart_with_failed_edit(runtime):
    bot, db, session, clock = runtime
    assert await notices.send_admin_test(bot, db, 7, "admin-action") == "sent"
    await db.execute("UPDATE widget_notifications SET delivery='sent' WHERE message_id=456")
    dispatcher = Dispatcher()
    dispatcher.update.outer_middleware(WidgetUpdateMiddleware())
    for index, query in enumerate((
        widget_query(message_id=123),
        widget_query(**{"from": {"id": 8}}),
        widget_query(chat={"type": "group", "id": 7}),
        widget_query(type={"type": "sign_data"}),
        widget_query(inline_message_id="unrelated"),
        widget_query(),
        widget_query(),
    )):
        await dispatcher.feed_update(bot, Update(update_id=index, widget_query=query), db=db)
        assert json.loads(session.calls[-1].data) == {"read": index >= 5}
    initial = clock.now
    row = await db.fetchone("SELECT * FROM widget_notifications")
    assert row["read_at"] == row["next_action_at"] == initial

    # Reopening SQLite simulates losing all in-memory tasks after the query was saved.
    db = Database(db.path)
    session.failures["editMessageWidgetData"] = TelegramNetworkError
    await notices.settle_read_notifications(bot, db)
    row = await db.fetchone("SELECT * FROM widget_notifications")
    assert row["read_at"] == initial and row["next_action_at"] == initial + 60
    del session.failures["editMessageWidgetData"]
    clock.now += 60
    await notices.settle_read_notifications(bot, db)
    method = session.calls[-1]
    assert method.__api_method__ == "editMessageWidgetData"
    assert (method.chat_id, method.message_id, method.chat_data) == (7, 456, '{"read":true}')
    clock.now += notices.DELETE_DELAY - 1
    await notices.settle_read_notifications(bot, db)
    assert session.calls[-1] == method
    clock.now += 1
    await notices.settle_read_notifications(bot, db)
    method = session.calls[-1]
    assert method.__api_method__ == "deleteMessage"
    assert (method.chat_id, method.message_id) == (7, 456)
    await notices.handle_widget_query(bot, db, widget_query())
    await notices.settle_read_notifications(bot, db)
    assert (await db.fetchone("SELECT next_action_at FROM widget_notifications"))["next_action_at"] is None
    assert [m.__api_method__ for m in api_calls(session)].count("deleteMessage") == 1
    assert await db.get_bot_state("private_rich_panel:7") == '{"message_id":123,"screen":"home"}'


@pytest.mark.parametrize("failure,status", [(TelegramNetworkError, "unconfirmed"), (TelegramForbiddenError, "blocked")])
async def test_send_failure_does_not_duplicate_or_spam(runtime, failure, status):
    bot, db, session, clock = runtime
    await db.notify_toggle_enabled(7, "widget_reputation")
    session.failures["sendWidget"] = failure
    assert await emit(bot, db) == status
    clock.now += notices.SEND_INTERVAL + 1
    assert await emit(bot, Database(db.path)) == "suppressed"
    if status == "blocked":
        assert await emit(bot, db, "rep:101") == "blocked"
    assert [m.__api_method__ for m in api_calls(session)] == ["sendWidget"]
    row = await db.fetchone("SELECT delivery,message_id FROM widget_notifications WHERE event_key='rep:100'")
    expected = "notice_paused" if status == "blocked" else "notice_unconfirmed"
    assert row == {"delivery": expected, "message_id": None}


async def test_widget_detail_requires_current_miniapp_access_and_owner(runtime):
    bot, db, _, _ = runtime
    application_id = await db.create_application(7, {})
    await db.decide_application(application_id, 99, 'approved', None)
    await notices.send_admin_test(bot, db, 7, "test-details")
    row = await db.fetchone("SELECT id FROM widget_notifications")
    request = Request(db)
    request.match_info = {"notice_id": row["id"]}
    request.path = "/api/notices/widget/" + row["id"]
    request.headers = {}
    assert (await protection(request, widget_notice)).status == 401
    now = int(datetime.now(UTC).timestamp())
    request.headers["Authorization"] = "tma " + signed(uid=8, date=now)
    assert (await protection(request, widget_notice)).status == 404
    request.headers["Authorization"] = "tma " + signed(uid=7, date=now)
    response = await protection(request, widget_notice)
    assert response.status == 200 and response.headers["Cache-Control"] == "no-store"
    content = json.loads(response.body)
    assert content["target"] == "notices" and content["details"].startswith("Открой Нору")
    assert "recipient_id" not in content and "message_id" not in content
    await db.set_role(7, "member")
    assert (await protection(request, widget_notice)).status == 200
    request.headers["Authorization"] = "tma " + signed(uid=999, date=now)
    assert (await protection(request, widget_notice)).status == 403


def test_widget_uses_text_nodes_and_stays_within_telegram_limits():
    evil = '</script><img src="https://example.com/injected">'
    wide = "".join(chr(0x1F300 + n) for n in range(240))
    source = widget_inbox.widget_html()
    assert evil not in source and ".textContent = p.details" in source
    data = {"r": 1, "i": 0, "n": 1, "p": {
        "title": wide[:52], "sender": wide[:28], "context": wide[:35], "details": wide[:148],
        "url": "https://t.me/nora_test_bot?startapp=nora_notice_" + "a" * 32,
    }}
    assert len(widget_inbox.pack(data).encode()) <= 1024
    raw = source.encode()
    assert len(raw) <= 32768 and len(zlib.compress(raw, 9)) <= 4096
    assert len(("nwi:read:" + "a" * 32).encode()) <= 64


async def test_read_and_close_only_affect_their_own_widget(runtime):
    bot, db, session, clock = runtime
    await db.notify_toggle_enabled(7, "widget_reputation")
    assert await emit(bot, db) == "sent"
    assert await emit(bot, db, "rep:101") == "sent"
    first, second = [json.loads(call.chat_data) for call in api_calls(session)]

    async def query(data, **changes):
        assert await widget_inbox.handle_query(bot, db, widget_query(data=data, **changes))
        return json.loads(next(call.data for call in reversed(session.calls)
                               if call.__api_method__ == "answerWidgetQuery"))

    assert await query(f"nwi:close:{first['r']}", message_id=457) == {}
    assert await query(f"nwi:read:{second['p']['id']}") == {}
    assert await query(f"nwi:close:{first['r']}", **{"from": {"id": 8}}) == {}
    assert await query(f"nwi:read:{first['p']['id']}") == {"closed": True}
    session.failures["deleteMessage"] = TelegramNetworkError
    clock.now += notices.DELETE_DELAY
    await widget_inbox.settle_due(bot, db)
    assert await emit(bot, db, "rep:102") == "sent"
    del session.failures["deleteMessage"]
    clock.now += 60
    await widget_inbox.settle_due(bot, Database(db.path))
    assert await query(f"nwi:close:{second['r']}", message_id=457) == {"closed": True}
    rows = await db.fetchall("SELECT message_id,delivery FROM widget_notifications ORDER BY rowid")
    assert rows == [{"message_id": 456, "delivery": "notice_closed"},
                    {"message_id": 457, "delivery": "notice_closed"},
                    {"message_id": 458, "delivery": "notice_sent"}]
    assert await db.get_bot_state("private_rich_panel:7") == '{"message_id":123,"screen":"home"}'


async def test_widget_rejection_sends_separate_text_and_can_be_read(runtime):
    bot, db, session, _ = runtime
    session.failures["sendWidget"] = TelegramNotFound
    assert await notices.send_admin_test(bot, db, 7, "fallback") == "sent"
    attempt, fallback = api_calls(session)
    assert attempt.__api_method__ == "sendWidget"
    assert fallback.__api_method__ == "sendMessage" and fallback.disable_notification is False
    assert "Проверка уведомлений" in fallback.text
    row = await db.fetchone("SELECT id,delivery FROM widget_notifications")
    assert row["delivery"] == "notice_text"
    callback = CallbackQuery(
        id="fixture", from_user=User(id=7, is_bot=False, first_name="Участник"), chat_instance="private",
        message=Message(message_id=456, date=datetime.now(UTC), chat=Chat(id=7, type="private")),
        data=f"nwn:{row['id']}",
    )
    dispatcher = Dispatcher()
    dispatcher.update.outer_middleware(WidgetUpdateMiddleware())
    await dispatcher.feed_update(bot, Update(update_id=1, callback_query=callback), db=db)
    assert session.calls[-1].__api_method__ == "deleteMessage"
    assert session.calls[-1].message_id == 456
    assert (await db.fetchone("SELECT delivery FROM widget_notifications"))["delivery"] == "notice_closed"
    assert await db.get_bot_state("private_rich_panel:7") == '{"message_id":123,"screen":"home"}'


async def test_closing_old_inbox_keeps_new_notice(runtime):
    bot, db, session, _ = runtime
    await db.notify_toggle_enabled(7, "widget_reputation")
    assert await emit(bot, db) == "sent"
    old = json.loads(api_calls(session)[0].chat_data)
    await db.execute("UPDATE widget_notifications SET delivery='inbox_open' WHERE message_id=456")
    assert await emit(bot, db, "rep:101") == "sent"
    assert await widget_inbox.handle_query(bot, db, widget_query(data=f"nwi:close:{old['r']}"))
    rows = await db.fetchall("SELECT message_id,delivery FROM widget_notifications ORDER BY rowid")
    assert rows == [{"message_id": 456, "delivery": "inbox_closed"}, {"message_id": 457, "delivery": "notice_sent"}]


async def queue_profile_invite(db, clock, monkeypatch):
    monkeypatch.setattr(rollout, "time", lambda: clock.now)
    await db.notify_inbox_add(7, rollout.REQUEST, rollout.NOTICE)
    await rollout.queue_notices(db)
    return await db.fetchone("SELECT id FROM widget_notifications WHERE event_key=?", (rollout.REQUEST,))


@pytest.mark.parametrize("with_other_notice", [False, True])
async def test_profile_completion_removes_only_its_invite(runtime, monkeypatch, with_other_notice):
    bot, db, session, clock = runtime
    # The reminder must still disappear for a profile that already earned its bonus before the reset.
    await db.execute("INSERT INTO profile_completion_rewards(user_id,awarded_at) VALUES(7,'previous')")
    await db.execute(
        "UPDATE users SET profile_name='Имя',profile_bio='Описание',hobbies='Кино',"
        "avatar_file_id='photo' WHERE user_id=7"
    )
    row = await queue_profile_invite(db, clock, monkeypatch)
    await widget_inbox.settle_due(bot, db)
    sent = api_calls(session)[0]
    assert sent.__api_method__ == "sendWidget"
    assert "Прочитать и закрыть" in sent.html
    assert json.loads(sent.chat_data)["p"]["id"] == row["id"]
    if with_other_notice:
        await db.notify_toggle_enabled(7, "widget_reputation")
        assert await emit(bot, db) == "sent"

    await db.update_profile(7, "birth_date", "2000-01-01")
    # Scheduled cleanup survives a restart.
    db = Database(db.path)
    await widget_inbox.settle_due(bot, db)
    request = Request(db)
    request.match_info = {"notice_id": row["id"]}
    assert (await widget_notice(request)).status == 404
    assert json.loads((await list_notices(request)).body)["items"] == []
    assert (await db.get_user(7))["cookies"] == 0
    assert api_calls(session)[-1].__api_method__ == "deleteMessage"
    assert api_calls(session)[-1].message_id == 456
    if with_other_notice:
        other = await db.fetchone("SELECT delivery,message_id FROM widget_notifications WHERE event_key='rep:100'")
        assert other == {"delivery": "notice_sent", "message_id": 457}



@pytest.mark.parametrize("surface", ["miniapp", "widget"])
async def test_profile_invite_can_be_closed_manually(runtime, monkeypatch, surface):
    bot, db, session, clock = runtime
    row = await queue_profile_invite(db, clock, monkeypatch)
    await widget_inbox.settle_due(bot, db)
    if surface == "miniapp":
        request = Request(db, body={"action": "dismiss_profile_invite"})
        assert json.loads((await list_notices(request)).body)["items"][0]["profile_invite"]
        assert (await notices_update(request)).status == 200
        await widget_inbox.settle_due(bot, db)
    else:
        state = json.loads(api_calls(session)[0].chat_data)
        assert await widget_inbox.handle_query(bot, db, widget_query(data=f"nwi:close:{state['r']}"))
    assert not await db.fetchone("SELECT id FROM notify_inbox WHERE channel=?", (rollout.REQUEST,))
    assert (await db.fetchone("SELECT delivery FROM widget_notifications WHERE id=?", (row["id"],))) == {
        "delivery": "notice_closed",
    }
    assert api_calls(session)[-1].__api_method__ == "deleteMessage"


async def test_profile_invite_closed_before_delivery_is_never_sent(runtime, monkeypatch):
    bot, db, session, clock = runtime
    row = await queue_profile_invite(db, clock, monkeypatch)
    request = Request(db, body={"action": "dismiss_profile_invite"})
    assert (await notices_update(request)).status == 200
    await rollout.queue_notices(db)
    await widget_inbox.settle_due(bot, db)
    assert not api_calls(session)
    assert (await db.fetchone("SELECT delivery FROM widget_notifications WHERE id=?", (row["id"],))) == {
        "delivery": "notice_read",
    }
