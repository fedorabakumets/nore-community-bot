import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import PinChatMessage

from community_bot.database import Database
from community_bot.lobby_widget import LobbyWidget, document, lifecycle
from community_bot.message_widgets import EditSharedWidgetData, ForwardWidget, SendWidget


class Bot:
    def __init__(self):
        self.calls = []
        self.get_chat_member_count = AsyncMock(return_value=125)
        self.get_me = AsyncMock(return_value=SimpleNamespace(username='nora_test_bot'))
        self.pin_chat_message = AsyncMock(return_value=True)

    async def __call__(self, method):
        self.calls.append(method)
        if isinstance(method, SendWidget):
            return SimpleNamespace(message_id=41, widget={'id': '123456789123456789'})
        return True


@pytest.fixture
async def env(tmp_path):
    db = Database(tmp_path / 'widget.db')
    await db.initialize()
    return {'db': db, 'bot': Bot(), 'settings': SimpleNamespace(community_chat_id=-100123), 'nora_lobby': {}}


async def test_publish_once_concurrent_admins_and_restart(env):
    service = LobbyWidget(env)
    await asyncio.gather(service.publish(), service.publish())
    sent = [c for c in env['bot'].calls if isinstance(c, SendWidget)]
    assert len(sent) == 1
    assert sent[0].is_shared and not sent[0].allow_queries
    assert json.loads(sent[0].public_data)['members'] == 125
    assert 'startapp=nora_lobby&mode=fullscreen' in sent[0].html
    await LobbyWidget(env).publish()
    assert sum(isinstance(c, SendWidget) for c in env['bot'].calls) == 1
    env['bot'].pin_chat_message.assert_called_with(-100123, 41, disable_notification=True)


async def test_presence_ttl_counts_all_players_and_no_personal_data(env):
    now = time.monotonic()
    env['nora_lobby'] = {uid: (now, 'session', {'nickname': 'PrivateName'}) for uid in range(30)}
    env['nora_lobby'][999] = (now - 9, 'expired', {})
    service = LobbyWidget(env)
    state = json.loads(await service.snapshot())
    assert state['online'] == 30  # Not the nearest-20 rendering limit.
    assert state['members'] == 125
    assert set(state) == {'online', 'members', 'updated', 'revision'}
    env['nora_lobby'].clear()
    next_state = json.loads(await service.snapshot())
    assert next_state['online'] == 0
    assert next_state['revision'] > state['revision']
    assert env['bot'].get_chat_member_count.await_count == 1


async def test_membership_failure_does_not_publish_a_fake_zero(env):
    env['bot'].get_chat_member_count.side_effect = RuntimeError('unavailable')
    with pytest.raises(RuntimeError):
        await LobbyWidget(env).publish()
    assert not env['bot'].calls


async def test_pin_failure_keeps_message_for_retry(env):
    env['bot'].pin_chat_message.side_effect = TelegramBadRequest(
        method=PinChatMessage(chat_id=-100123, message_id=41), message='not enough rights',
    )
    service = LobbyWidget(env)
    assert 'not enough rights' in await service.publish()
    env['bot'].pin_chat_message.side_effect = None
    await LobbyWidget(env).publish()
    assert sum(isinstance(c, SendWidget) for c in env['bot'].calls) == 1


async def test_deleted_message_can_be_explicitly_republished(env):
    service = LobbyWidget(env)
    await service.publish()
    env['bot'].pin_chat_message.side_effect = TelegramBadRequest(
        method=PinChatMessage(chat_id=-100123, message_id=41), message='message to pin not found',
    )
    assert 'удалено' in await service.publish()
    assert not service.saved
    assert not await env['db'].get_bot_state(service.key)
    env['bot'].pin_chat_message.side_effect = None
    await service.publish()
    assert sum(isinstance(c, SendWidget) for c in env['bot'].calls) == 2


async def test_lifecycle_never_publishes_and_cleans_up(env):
    ctx = lifecycle(env)
    await anext(ctx)
    await asyncio.sleep(0)
    assert not env['bot'].calls
    await ctx.aclose()
    assert not hasattr(env['bot'], '_nora_lobby_widget')


async def test_runtime_restores_saved_widget_and_respects_retry_after(env, monkeypatch):
    service = LobbyWidget(env)
    await service.publish()
    restored = LobbyWidget(env)
    restored.update = AsyncMock(side_effect=TelegramRetryAfter(
        method=EditSharedWidgetData(widget_id='1', public_data='{}'), message='flood', retry_after=77,
    ))
    delays = []

    async def stop(delay):
        delays.append(delay)
        raise asyncio.CancelledError

    monkeypatch.setattr('community_bot.lobby_widget.asyncio.sleep', stop)
    with pytest.raises(asyncio.CancelledError):
        await restored.run()
    assert restored.saved['message_id'] == 41
    assert delays == [77]


def test_html_limits_and_link_validation():
    html = document('https://t.me/nora_test_bot?startapp=nora_lobby&mode=fullscreen')
    assert '/*LOGO*/' not in html and 'data:image/png;base64,' in html
    assert 'watchPublicData' in html
    with pytest.raises(ValueError):
        document('https://evil.example/</script>')


async def test_private_relay_survives_forward_failure_and_restart(env):
    class RestrictedBot(Bot):
        fail_forward = True

        async def __call__(self, method):
            self.calls.append(method)
            if isinstance(method, SendWidget):
                if method.chat_id < 0:
                    raise TelegramBadRequest(method=method, message='INPUT_MEDIA_WIDGET_NOT_ALLOWED')
                return SimpleNamespace(message_id=50, widget={'id': 'shared-id'})
            if isinstance(method, ForwardWidget):
                if self.fail_forward:
                    raise TelegramBadRequest(method=method, message='not enough rights')
                return SimpleNamespace(message_id=60)
            return True

    env['bot'] = RestrictedBot()
    service = LobbyWidget(env)
    with pytest.raises(TelegramBadRequest):
        await service.publish(7)
    saved = json.loads(await env['db'].get_bot_state(service.key))
    assert saved['source_chat_id'] == 7 and saved['source_message_id'] == 50
    env['bot'].fail_forward = False
    restored = LobbyWidget(env)
    await restored.publish(8)
    assert len([c for c in env['bot'].calls if isinstance(c, SendWidget)]) == 2
    forward = next(c for c in env['bot'].calls if isinstance(c, ForwardWidget))
    assert forward.from_chat_id == 7 and forward.chat_id == -100123
    env['bot'].pin_chat_message.assert_awaited_with(-100123, 60, disable_notification=True)
    assert restored.saved['widget_id'] == 'shared-id'


async def test_update_failure_does_not_prevent_pinning(env):
    service = LobbyWidget(env)
    service.update = AsyncMock(side_effect=TelegramBadRequest(
        method=EditSharedWidgetData(widget_id='1', public_data='{}'), message='method not supported',
    ))
    result = await service.publish(7)
    assert 'закреплён' in result and 'method not supported' in result
    env['bot'].pin_chat_message.assert_awaited_once()


def test_delivery_error_has_stage_and_redacts_secrets():
    from community_bot.lobby_widget import delivery_error

    error = TelegramBadRequest(method=SendWidget(chat_id=1, html='', caption=''),
                               message='BAD https://example/secret 123456:secret_key <invalid>')
    result = delivery_error(error)
    assert 'отправка виджета' in result and 'BAD' in result
    assert 'example' not in result and 'secret' not in result
