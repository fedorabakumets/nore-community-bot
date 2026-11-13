import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
    SendPhoto,
    SendPoll,
)
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from community_bot.database import Database
from community_bot.ephemeral import GroupCallbackEphemeralMiddleware, patch_bot_ephemeral
from community_bot.navigation import CabinetNavigationMiddleware
from community_bot.routers import life, private
from community_bot.states import AdminFlow
from community_bot.ui_owner import UiOwnerMiddleware


class TelegramSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.message_id = 100
        self.fail = None

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 - aiogram session interface
        self.calls.append(method)
        if self.fail and self.fail(method):
            raise TelegramBadRequest(method=method, message="simulated Telegram failure")
        if isinstance(method, AnswerCallbackQuery):
            return True
        self.message_id += 1
        return Message(
            message_id=getattr(method, "message_id", None) or self.message_id,
            date=datetime.now(UTC),
            chat=Chat(id=method.chat_id, type="private" if method.chat_id > 0 else "supergroup"),
            from_user=User(id=123456, is_bot=True, first_name="Нора"),
            text=getattr(method, "text", None),
            reply_markup=getattr(method, "reply_markup", None),
        )


@pytest.fixture
async def app(tmp_path, monkeypatch):
    db = Database(tmp_path / "events.db")
    await db.initialize()
    await db.ensure_user(1, telegram_name="Админ")
    settings = SimpleNamespace(
        owner_ids=frozenset({1}), is_owner=lambda uid: uid == 1, moderator_ids=frozenset(),
        community_chat_id=-100123, timezone="Europe/Moscow", reviewers=frozenset(),
    )
    dispatcher = Dispatcher()
    dispatcher.callback_query.outer_middleware(UiOwnerMiddleware())
    dispatcher.callback_query.outer_middleware(CabinetNavigationMiddleware())
    dispatcher.callback_query.outer_middleware(GroupCallbackEphemeralMiddleware())
    # Use the actual registered filters and handlers without reparenting global routers.
    for source in (life.router, private.router):
        isolated = Router()
        isolated.callback_query.handlers.extend(source.callback_query.handlers)
        isolated.callback_query._handler.filters.extend(source.callback_query._handler.filters)
        isolated.message.handlers.extend(source.message.handlers)
        isolated.message._handler.filters.extend(source.message._handler.filters)
        dispatcher.include_router(isolated)
    session = TelegramSession()
    bot = Bot("123456:test", session=session)
    monkeypatch.setattr("community_bot.ephemeral.delete_later", AsyncMock())
    patch_bot_ephemeral(bot)
    yield SimpleNamespace(db=db, settings=settings, dp=dispatcher, bot=bot, session=session)
    await dispatcher.storage.close()
    await bot.session.close()


def callback(data, user_id=1, chat_id=1, message_id=10, markup=None):
    return CallbackQuery(
        id=f"test-{data}-{user_id}", chat_instance="test",
        from_user=User(id=user_id, is_bot=False, first_name=f"Участник {user_id}"), data=data,
        message=Message(
            message_id=message_id, date=datetime.now(UTC), chat=Chat(
                id=chat_id, type="private" if chat_id > 0 else "supergroup",
            ), from_user=User(id=123456, is_bot=True, first_name="Нора"),
            text="Встреча в субботу", reply_markup=markup,
        ),
    )


async def click(app, data, **kwargs):
    await app.dp.feed_update(
        app.bot, Update(update_id=len(app.session.calls) + 1, callback_query=callback(data, **kwargs)),
        db=app.db, settings=app.settings,
    )


@pytest.mark.parametrize("with_rsvp", [True, False])
@pytest.mark.parametrize("with_poll", [True, False])
async def test_both_rsvp_choices_reach_preview_through_dispatcher(app, with_rsvp, with_poll):
    state = app.dp.fsm.get_context(bot=app.bot, chat_id=1, user_id=1)
    await state.set_state(AdminFlow.post_rsvp_ask)
    await state.set_data({
        "post_template": "event", "post_body": "Встреча в субботу", "post_buttons": [],
        "post_poll": {"question": "Пойдём?", "options": ["Да", "Нет"], "anonymous": True} if with_poll else None,
    })
    await click(app, "post:rsvp:yes" if with_rsvp else "post:rsvp:no")
    assert await state.get_state() == AdminFlow.post_preview.state
    data = [b.callback_data for call in app.session.calls if getattr(call, "reply_markup", None)
            for row in call.reply_markup.inline_keyboard for b in row]
    assert "post:send" in data
    assert not any(isinstance(call, SendPoll) for call in app.session.calls)


async def event(app, event_id="e-test", *, stake=0, message_id=50, paid=False):
    from community_bot.posting import compose_post_markup

    buttons = [{"text": "Место встречи", "url": "https://example.com", "style": ""}]
    await app.db.save_studio_event(event_id, app.settings.community_chat_id, message_id, "Встреча", buttons, stake, 1)
    if paid:
        await app.db.save_event_offer(event_id, app.settings.community_chat_id, message_id, "Билет", 30, 1)
    return compose_post_markup(buttons, event_id, pay=("Билет", event_id) if paid else None)


async def attend(app, event_id="e-test", user_id=2, message_id=50, markup=None):
    await click(app, f"rsvp:{event_id}", user_id=user_id, chat_id=app.settings.community_chat_id,
                message_id=message_id, markup=markup)


def counter(app):
    edits = [c for c in app.session.calls if isinstance(c, EditMessageReplyMarkup)]
    return next(b.text for row in edits[-1].reply_markup.inline_keyboard for b in row
                if (b.callback_data or "").startswith("rsvp:"))


async def test_new_people_can_join_and_counter_preserves_other_buttons(app):
    markup = await event(app, paid=True)
    await asyncio.gather(attend(app, user_id=2, markup=markup), attend(app, user_id=3, markup=markup))
    assert await app.db.event_participant_count("e-test") == 2
    assert counter(app) == "Я буду (2)"
    edited = [c for c in app.session.calls if isinstance(c, EditMessageReplyMarkup)][-1]
    buttons = [b for row in edited.reply_markup.inline_keyboard for b in row]
    assert buttons[0].url == "https://example.com"
    assert buttons[-1].callback_data == "evpay:e-test"
    assert await app.db.get_user(2)
    assert await app.db.get_user(3)


async def test_duplicate_attendance_does_not_cancel_and_explicit_cancellation_is_idempotent(app):
    await event(app)
    await asyncio.gather(attend(app), attend(app))
    assert await app.db.event_participant_count("e-test") == 1
    await attend(app)
    assert any(isinstance(c, SendMessage) and "Отменить участие?" in c.text for c in app.session.calls)
    await click(app, "rsvpc:e-test:2", user_id=3, chat_id=app.settings.community_chat_id)
    assert await app.db.event_participant_count("e-test") == 1
    await click(app, "rsvpc:e-test:2", user_id=2, chat_id=app.settings.community_chat_id)
    await click(app, "rsvpc:e-test:2", user_id=2, chat_id=app.settings.community_chat_id)
    assert await app.db.event_participant_count("e-test") == 0
    assert counter(app) == "Я буду (0)"


async def test_deposit_needs_confirmation_and_refunds_once_after_restart(app):
    await event(app, stake=10)
    await app.db.ensure_user(2, telegram_name="Гость")
    await app.db.add_cookies(2, 50, "test")
    await attend(app)
    assert not await app.db.has_event_rsvp("e-test", 2)
    assert (await app.db.get_user(2))["cookies"] == 50
    await asyncio.gather(*(click(app, "rsvpj:e-test:2", user_id=2, chat_id=app.settings.community_chat_id)
                           for _ in range(2)))
    assert (await app.db.get_user(2))["cookies"] == 40
    restarted = Database(app.db.path)
    results = await asyncio.gather(*(restarted.cancel_event_rsvp("e-test", 2) for _ in range(2)))
    assert sum(ok for ok, _ in results) == 1
    assert (await app.db.get_user(2))["cookies"] == 50
    assert len([t for t in await app.db.list_transactions(2) if t["kind"] == "rsvp_refund"]) == 1


async def test_ticket_payment_credits_deposit_once_and_paid_ticket_cannot_be_cancelled(app):
    await event(app, stake=10, paid=True)
    await app.db.ensure_user(2)
    await app.db.add_cookies(2, 100, "test")
    assert (await app.db.add_rsvp("e-test", 2, 10, kind="rsvp"))[0]
    await click(app, "evpaygo:e-test", user_id=2, chat_id=app.settings.community_chat_id)
    confirmation = [c for c in app.session.calls if isinstance(c, SendMessage)][-1]
    assert "Спишется: 20" in confirmation.text
    data = confirmation.reply_markup.inline_keyboard[0][0].callback_data
    await asyncio.gather(*(click(app, data, user_id=2, chat_id=app.settings.community_chat_id) for _ in range(2)))
    assert (await app.db.get_user(2))["cookies"] == 70
    assert await app.db.event_participant_count("e-test") == 1
    assert await app.db.has_event_payment("e-test", 2)
    assert not (await app.db.cancel_event_rsvp("e-test", 2))[0]
    assert (await app.db.get_user(2))["cookies"] == 70
    assert counter(app) == "Я буду (1)"


async def test_changed_price_and_insufficient_balance_do_not_charge_or_register(app):
    await event(app, paid=True)
    await app.db.ensure_user(2)
    await app.db.add_cookies(2, 20, "test")
    assert not (await app.db.pay_event_offer("e-test", 2, 10))[0]
    assert not (await app.db.pay_event_offer("e-test", 2, 30))[0]
    assert not await app.db.has_event_rsvp("e-test", 2)
    assert (await app.db.get_user(2))["cookies"] == 20


async def test_deposit_larger_than_ticket_refunds_only_the_excess_once(app):
    await event(app, stake=50, paid=True)
    await app.db.ensure_user(2)
    await app.db.add_cookies(2, 100, "test")
    await app.db.add_rsvp("e-test", 2, 50, kind="rsvp")
    results = await asyncio.gather(*(Database(app.db.path).pay_event_offer("e-test", 2, 30) for _ in range(2)))
    assert sum(result[0] for result in results) == 1
    assert (await app.db.get_user(2))["cookies"] == 70
    assert (await app.db.get_event_rsvp("e-test", 2))["stake"] == 30
    assert len([t for t in await app.db.list_transactions(2) if t["kind"] == "rsvp_refund"]) == 1


async def test_counter_retries_after_telegram_failure_and_database_restart(app):
    from community_bot.rsvp import sync_event_counters

    await event(app)
    app.session.fail = lambda method: isinstance(method, EditMessageReplyMarkup)
    await attend(app)
    assert await app.db.has_event_rsvp("e-test", 2)
    assert (await app.db.get_studio_event("e-test"))["markup_dirty"] == 1
    app.session.fail = None
    await sync_event_counters(app.bot, Database(app.db.path))
    assert counter(app) == "Я буду (1)"
    assert (await app.db.get_studio_event("e-test"))["markup_dirty"] == 0


async def test_counter_edit_never_schedules_deletion_of_the_original_event_post(app, monkeypatch):
    import community_bot.ephemeral as ephemeral

    scheduled = []

    def track(result, ttl):
        if isinstance(result, Message):
            scheduled.append(result.message_id)

    monkeypatch.setattr(ephemeral, "schedule_group_reply", track)
    await event(app)
    await attend(app)
    assert counter(app) == "Я буду (1)"
    assert 50 not in scheduled
    await attend(app)
    assert scheduled  # The separate, short-lived cancellation prompt still expires normally.
    assert 50 not in scheduled


async def test_preview_and_wrong_post_cannot_register_or_charge(app):
    await event(app, stake=10)
    await click(app, "post:rsvp:preview")
    await click(app, "rsvp:e-test", user_id=2, chat_id=2)
    await attend(app, message_id=99)
    assert await app.db.event_participant_count("e-test") == 0
    assert await app.db.get_user(2) is None


async def test_admin_participant_pages_are_private_and_require_post_permission(app):
    await event(app)
    for uid in range(2, 14):
        await app.db.ensure_user(uid, username=f"guest{uid}", telegram_name=f"Гость {uid}")
        await app.db.add_rsvp("e-test", uid, 0, kind="rsvp")
    await click(app, "admin:events:0", user_id=2, chat_id=2)
    assert not any(isinstance(c, EditMessageText) for c in app.session.calls)
    await click(app, "admin:events:0")
    assert "Встреча (12)" in str(app.session.calls[-1].reply_markup)
    await click(app, "admin:attendees:e-test:0")
    first = app.session.calls[-1]
    assert "@guest2" in first.text and "@guest12" not in first.text
    assert "tg://user?id=2" in first.text
    await click(app, "admin:attendees:e-test:1")
    assert "@guest12" in app.session.calls[-1].text
    app.session.calls.clear()
    await click(app, "admin:attendees:e-test:0", user_id=1, chat_id=app.settings.community_chat_id)
    assert not any(isinstance(c, EditMessageText) for c in app.session.calls)


@pytest.mark.parametrize("with_rsvp", [False, True])
@pytest.mark.parametrize("media", [False, True])
async def test_publish_preserves_poll_media_and_rsvp_without_duplicate_posts(app, with_rsvp, media):
    state = app.dp.fsm.get_context(bot=app.bot, chat_id=1, user_id=1)
    await state.set_state(AdminFlow.post_rsvp_ask)
    await state.set_data({
        "post_template": "event", "post_body": "Встреча в субботу", "post_buttons": [],
        "post_poll": {"question": "Пойдём?", "options": ["Да", "Нет"], "anonymous": False},
        "post_media_type": "photo" if media else None, "post_file_id": "photo-id" if media else None,
    })
    await click(app, "post:rsvp:yes" if with_rsvp else "post:rsvp:no")
    app.session.calls.clear()
    await asyncio.gather(click(app, "post:send"), click(app, "post:send"))
    posted = [c for c in app.session.calls if isinstance(c, (SendPhoto, SendMessage))
              and c.chat_id == app.settings.community_chat_id]
    assert len(posted) == 1
    assert isinstance(posted[0], SendPhoto if media else SendMessage)
    polls = [c for c in app.session.calls if isinstance(c, SendPoll)]
    assert len(polls) == 1 and polls[0].is_anonymous is False
    events = await app.db.list_studio_events()
    assert len(events) == 1
    stored = await app.db.get_studio_event(events[0]["event_id"])
    assert bool(stored["rsvp_enabled"]) == with_rsvp
    assert bool(posted[0].reply_markup) == with_rsvp
    assert await state.get_state() == AdminFlow.post_pay_ask.state


async def test_poll_failure_retry_does_not_republish_the_post(app):
    state = app.dp.fsm.get_context(bot=app.bot, chat_id=1, user_id=1)
    await state.set_state(AdminFlow.post_preview)
    await state.set_data({
        "post_template": "announce", "post_body": "Пост", "post_buttons": [],
        "post_poll": {"question": "Вопрос", "options": ["Да", "Нет"]},
    })
    app.session.fail = lambda method: isinstance(method, SendPoll)
    await click(app, "post:send")
    assert await state.get_state() == AdminFlow.post_preview.state
    app.session.fail = None
    await click(app, "post:send")
    posts = [c for c in app.session.calls if isinstance(c, SendMessage) and c.chat_id == app.settings.community_chat_id]
    assert len(posts) == 1
    assert await state.get_state() is None


async def test_legacy_post_is_bound_on_first_click_and_old_attendees_are_visible(app):
    from community_bot.posting import compose_post_markup

    await app.db.ensure_user(4, telegram_name="Архивный участник")
    await app.db.add_rsvp("e-old", 4, 0)
    assert any(row["event_id"] == "e-old" for row in await app.db.list_studio_events())
    await attend(app, event_id="e-old", markup=compose_post_markup([], "e-old"))
    assert (await app.db.get_studio_event("e-old"))["message_id"] == 50
    assert counter(app) == "Я буду (2)"


async def test_adding_payment_button_preserves_existing_rsvp_count(app):
    await event(app)
    await attend(app)
    state = app.dp.fsm.get_context(bot=app.bot, chat_id=1, user_id=1)
    await state.set_state(AdminFlow.post_pay_price)
    await state.set_data({
        "pay_event_id": "e-test", "pay_chat_id": app.settings.community_chat_id, "pay_message_id": 50,
        "pay_button_text": "Купить билет", "pay_body": "Встреча",
    })
    message = Message(
        message_id=90, date=datetime.now(UTC), chat=Chat(id=1, type="private"),
        from_user=User(id=1, is_bot=False, first_name="Админ"), text="30",
    )
    await app.dp.feed_update(app.bot, Update(update_id=900, message=message), db=app.db, settings=app.settings)
    assert counter(app) == "Я буду (1)"
    assert (await app.db.get_event_offer("e-test"))["price"] == 30


async def test_old_schema_upgrade_keeps_registrations_balances_and_ledger(app):
    await app.db.ensure_user(2, telegram_name="До обновления")
    await app.db.add_cookies(2, 50, "test")
    await app.db.add_rsvp("e-old-paid", 2, 10)
    ledger = await app.db.list_transactions(2)
    async with app.db.connect() as connection:
        await connection.executescript("""
            ALTER TABLE event_rsvps RENAME TO event_rsvps_new;
            CREATE TABLE event_rsvps (
                event_id TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(user_id),
                stake INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, PRIMARY KEY(event_id, user_id)
            );
            INSERT INTO event_rsvps SELECT event_id, user_id, stake, created_at FROM event_rsvps_new;
            DROP TABLE event_rsvps_new;
            DROP TABLE studio_events;
        """)
    await app.db.initialize()
    assert (await app.db.get_user(2))["cookies"] == 40
    assert await app.db.list_transactions(2) == ledger
    row = await app.db.get_event_rsvp("e-old-paid", 2)
    assert row["stake"] == 10 and row["kind"] == "legacy"
    assert not (await app.db.cancel_event_rsvp("e-old-paid", 2))[0]
    assert await app.db.get_studio_event("e-old-paid") is None


async def test_plain_poll_text_is_escaped_in_preview():
    from community_bot.posting import poll_preview_block

    preview = poll_preview_block({"question": "<встреча> & кино?", "options": ["<да>", "нет & нет"]})
    assert "&lt;встреча&gt; &amp; кино?" in preview
    assert "&lt;да&gt;" in preview


async def test_empty_post_cannot_silently_drop_rsvp_button(app):
    state = app.dp.fsm.get_context(bot=app.bot, chat_id=1, user_id=1)
    await state.set_state(AdminFlow.post_preview)
    await state.set_data({"post_template": "html", "post_body": "", "post_rsvp": "e-empty"})
    await click(app, "post:send")
    assert not any(isinstance(c, SendMessage) and c.chat_id < 0 for c in app.session.calls)
    assert await state.get_state() == AdminFlow.post_preview.state


async def test_event_ids_are_unique_and_stale_choice_cannot_change_current_step(app):
    state = app.dp.fsm.get_context(bot=app.bot, chat_id=1, user_id=1)
    await state.set_state(AdminFlow.post_rsvp_ask)
    await state.set_data({"post_body": "Встреча"})
    await click(app, "post:rsvp:yes")
    first = (await state.get_data())["post_rsvp"]
    await click(app, "post:rsvp:no")
    assert (await state.get_data())["post_rsvp"] == first
    await state.set_state(AdminFlow.post_rsvp_ask)
    await click(app, "post:rsvp:yes")
    assert (await state.get_data())["post_rsvp"] != first
