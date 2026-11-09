from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from community_bot.routers import profile


@pytest.mark.parametrize('editable', [True, False])
@pytest.mark.parametrize('chat_type', ['group', 'supergroup'])
async def test_group_profile_has_only_red_close_button(monkeypatch, editable, chat_type):
    monkeypatch.setattr(profile, 'cover_file', lambda _: None)
    message = SimpleNamespace(chat=SimpleNamespace(type=chat_type), from_user=SimpleNamespace(id=1))
    message.answer = AsyncMock(return_value=object())
    await profile.send_profile_card(message, {'user_id': 1 if editable else 2}, None, editable=editable, text='Профиль')
    button_rows = message.answer.await_args.kwargs['reply_markup'].inline_keyboard
    assert len(button_rows) == 1 and len(button_rows[0]) == 1
    assert button_rows[0][0].callback_data == 'ui:close'
    assert button_rows[0][0].style == 'danger'


@pytest.mark.parametrize('ornate', [0, 1])
async def test_group_profile_request_uses_compact_format(monkeypatch, ornate):
    user = {'user_id': 1, 'profile_ornate': ornate}
    message = SimpleNamespace(chat=SimpleNamespace(type='group'), from_user=SimpleNamespace(id=1))
    monkeypatch.setattr(profile, 'register_telegram_user', AsyncMock(return_value=user))
    monkeypatch.setattr(profile, 'resolve_reply_target', AsyncMock(return_value=None))
    monkeypatch.setattr(profile, 'can_view_profile', AsyncMock(return_value=True))
    render = AsyncMock(return_value='compact')
    monkeypatch.setattr(profile, 'render_profile', render)
    send = AsyncMock()
    monkeypatch.setattr(profile, 'send_profile_card', send)
    await profile.show_profile(message, object(), object())
    assert render.await_args.kwargs['compact'] is True
    assert send.await_args.kwargs['text'] == 'compact'
