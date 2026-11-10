import asyncio
import json
import zlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError
from aiogram.types import Chat, Message, Update, User

from community_bot import widget_inbox
from community_bot import widget_notifications as notices
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
        if name == "sendWidget":
            number = sum(call.__api_method__ == "sendWidget" for call in self.calls)
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
    assert await emit(bot, db, "rep:101") == "updated"
    assert await emit(bot, db) == "suppressed"
    sent, updated, edited = api_calls(session)
    assert sent.__api_method__ == "sendWidget" and sent.chat_id == 7
    assert sent.disable_notification is False and sent.allow_queries is True
    assert sent.reply_markup is None and sent.height is None and sent.width is None
    assert sent.parse_mode == "HTML"
    assert "У вас 1 уведомление!" in sent.caption and "репутации" not in sent.caption
    assert json.loads(sent.chat_data)["p"]["sender"] == "@member"
    assert (updated.__api_method__, updated.message_id, json.loads(updated.chat_data)["n"]) == (
        "editMessageWidgetData", 456, 2,
    )
    assert edited.__api_method__ == "editMessageCaption" and "У вас 2 уведомления!" in edited.caption
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
    expected = "inbox_paused" if status == "blocked" else "inbox_unconfirmed"
    assert row == {"delivery": expected, "message_id": None}


async def test_widget_detail_requires_current_miniapp_access_and_owner(runtime):
    bot, db, _, _ = runtime
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


async def test_pages_and_close_are_owner_bound_and_do_not_drop_new_events(runtime):
    bot, db, session, clock = runtime
    await db.notify_toggle_enabled(7, "widget_reputation")
    assert await emit(bot, db) == "sent"
    assert await emit(bot, db, "rep:101") == "updated"
    dispatcher = Dispatcher()
    dispatcher.update.outer_middleware(WidgetUpdateMiddleware())

    async def query(data, **changes):
        await dispatcher.feed_update(bot, Update(update_id=1, widget_query=widget_query(data=data, **changes)), db=db)
        return json.loads(next(call.data for call in reversed(session.calls)
                               if call.__api_method__ == "answerWidgetQuery"))

    assert await query("nwi:page:0", message_id=123) == {}
    assert await query("nwi:page:0", **{"from": {"id": 8}}) == {}
    first, second = await query("nwi:page:0"), await query("nwi:page:1")
    assert (first["n"], first["i"], second["i"]) == (2, 0, 1)
    assert first["p"]["id"] != second["p"]["id"]
    await emit(bot, db, "rep:102")
    stale = await query(f"nwi:close:{first['r']}")
    assert stale["changed"] is True and stale["n"] == 3
    remaining = await query(f"nwi:read:{second['p']['id']}")
    assert remaining["n"] == 2
    assert not any(call.__api_method__ == "deleteMessage" for call in session.calls)

    session.failures["deleteMessage"] = TelegramNetworkError
    assert (await query(f"nwi:close:{remaining['r']}"))["closed"]
    closed = await db.fetchall("SELECT read_at FROM widget_notifications ORDER BY rowid")
    assert all(row["read_at"] is not None for row in closed)
    assert await emit(bot, db, "rep:103") == "queued"
    del session.failures["deleteMessage"]
    clock.now += 60
    await widget_inbox.settle_due(bot, Database(db.path))
    deleted = [call for call in session.calls if call.__api_method__ == "deleteMessage"]
    assert [(call.chat_id, call.message_id) for call in deleted] == [(7, 456), (7, 456)]
    last = session.calls[-1]
    assert last.__api_method__ == "sendWidget" and json.loads(last.chat_data)["n"] == 1
    assert await db.get_bot_state("private_rich_panel:7") == '{"message_id":123,"screen":"home"}'
