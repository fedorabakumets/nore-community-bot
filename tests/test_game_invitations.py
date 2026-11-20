import asyncio
import json
import secrets
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import SendRichMessage
from aiogram.types import Message, RichMessage

from community_bot import barricade_api, durak_api, durak_rooms, mafia_api, sea_api
from community_bot.database import Database
from community_bot.game_invitations import (
    close_game_invitation,
    deliver_game_invitation,
    open_invitation,
    quick_preview,
)
from community_bot.miniapp import protection
from tests.test_miniapp import Request as MiniAppRequest
from tests.test_miniapp import signed


class Request(MiniAppRequest):
    def __init__(self, db, uid, body, bot=None):
        super().__init__(db, uid, body)
        self["actor"]["username"] = f"player_{uid}"
        self.app.update(bot=bot, durak_updates=durak_api.Updates())
        self.app["settings"].community_chat_id = -100123
        self.app["settings"].owner_ids = {99}
        self.content_length = None
        self.path = "/api/games/invite"
        self.headers = {"Authorization": "tma " + signed(uid=uid, date=int(time.time()))}


@pytest.fixture
async def db(tmp_path):
    db = Database(tmp_path / "invites.sqlite")
    await db.initialize()
    for uid in (1, 2, 3):
        await db.ensure_user(uid, username=f"player_{uid}", telegram_name=f"Игрок {uid}")
        await db.execute(
            "UPDATE users SET profile_name=?,birth_date='2000-01-01',hobbies='Карты',"
            "profile_bio='Играю',avatar_file_id='test-avatar',role='moderator' WHERE user_id=?",
            (f"Игрок {uid}", uid),
        )
        await db.add_cookies(uid, 100, "fixture")
    await db.execute("INSERT INTO mini_friendships VALUES(1,2,1,'accepted','test','now','now',0,0)")
    return db


@pytest.mark.parametrize(("game", "title"), [("durak", "Дурака"), ("mafia", "Мафию"), ("sea", "Морской бой")])
async def test_rich_invite_delivers_both_copies_and_opens_the_invited_lobby(db, game, title):
    bot = SimpleNamespace(
        me=AsyncMock(return_value=SimpleNamespace(username="test_nora")), send_rich_message=AsyncMock(),
    )
    request = Request(db, 1, {}, bot)
    if game == "durak":
        rid, _ = await durak_rooms.command(db, 1, {
            "action": "create", "config": {"private": True, "stake": 25}, "nonce": secrets.token_hex(16),
        })
        request.body = {"action": "invite", "room": rid, "friend": 2, "nonce": secrets.token_hex(16)}
        handler = durak_api.action
    else:
        api = mafia_api if game == "mafia" else sea_api
        created = {"action": "create", "public": False, "request_id": secrets.token_hex(16)}
        rid, _, _ = await api.apply_action(db, request.app["settings"], 1, created)
        room = (await api.read_status(db, 1, room_id=rid))["room"]
        request.body = {"action": "invite", "room_id": rid, "user_id": 2,
                        "phase_token": room.get("phase_token"), "request_id": secrets.token_hex(16)}
        handler = api.action

    response = await handler(request)
    assert response.status == 200
    assert (await handler(request)).status == (409 if game == "sea" else 200)
    sent = {entry.args[0]: entry.kwargs["rich_message"] for entry in bot.send_rich_message.call_args_list}
    assert bot.send_rich_message.await_count == 2 and sent.keys() == {2, -100123}
    assert sent[2].blocks[0].text[0].text == "@player_1"
    assert sent[2].blocks[0].text[1] == f" приглашает сыграть в «{title}»!"
    assert sent[-100123].blocks[0].text[0].text == "@player_2"
    for card in sent.values():
        red, green = card.blocks[1].buttons
        assert (red.text, red.style, green.text, green.style) == ("❌", "danger", "✅", "success")
        assert green.url == f"https://t.me/test_nora?startapp=nora_inv_{game}_2_{rid}"
    assert (await db.fetchone("SELECT delivered FROM notify_inbox WHERE user_id=2"))["delivered"] == 1

    body = {"game": game, "room_id": rid, "recipient": 2}
    assert (await protection(Request(db, 3, body), open_invitation)).status == 403
    impostor = await protection(Request(db, 3, {**body, "recipient": 3}), open_invitation)
    assert impostor.status in {400, 409}

    opened = await asyncio.gather(*(protection(Request(db, 2, body), open_invitation) for _ in range(2)))
    assert all(response.status == 200 and json.loads(response.body) == {"room_id": rid} for response in opened)
    if game == "durak":
        assert (await durak_api.menu(db, 2))["invites"][0]["id"] == rid
        assert not (await durak_api.menu(db, 2))["active"]
        assert (await db.get_user(2))["cookies"] == 100
        current = await durak_api.snapshot(db, rid, 1)
        await durak_rooms.command(db, 1, {
            "action": "cancel", "room": rid, "rev": current["rev"], "nonce": secrets.token_hex(16),
        })
        assert (await protection(Request(db, 2, body), open_invitation)).status == 400
    else:
        assert (await api.read_status(db, 2))["room"]["id"] == rid


@pytest.mark.parametrize("chat_id", [2, -100123])
async def test_only_the_recipient_can_delete_the_card_with_its_own_button(chat_id, monkeypatch):
    dismiss = "game-invite:close:2:15"
    markup = RichMessage.model_validate({"blocks": [{"type": "buttons", "buttons": [
        {"text": "❌", "style": "danger", "callback_data": dismiss}
    ]}]})
    message = Message.model_validate({
        "message_id": 15, "date": 1000, "chat": {"id": chat_id, "type": "private" if chat_id > 0 else "supergroup"},
        "rich_message": markup,
    })
    delete = AsyncMock()
    monkeypatch.setattr(Message, "delete", delete)
    callback = SimpleNamespace(message=message, from_user=SimpleNamespace(id=3), data=dismiss, answer=AsyncMock())
    settings = SimpleNamespace(community_chat_id=-100123)
    await close_game_invitation(callback, settings)
    delete.assert_not_awaited()
    callback.from_user.id = 2
    callback.data = "game-invite:close:2:16"
    await close_game_invitation(callback, settings)
    delete.assert_not_awaited()
    callback.data = dismiss
    await close_game_invitation(callback, settings)
    delete.assert_awaited_once()


async def test_group_delivery_survives_closed_dm_and_rich_api_rejection(db):
    settings = SimpleNamespace(community_chat_id=-100123)
    method = SendRichMessage(chat_id=2, rich_message={"html": "Test"})
    bot = SimpleNamespace(
        me=AsyncMock(return_value=SimpleNamespace(username="test_nora")),
        send_rich_message=AsyncMock(side_effect=[
            TelegramForbiddenError(method=method, message="Private chat blocked"),
            TelegramBadRequest(method=method, message="Rich messages unsupported"),
        ]),
        send_message=AsyncMock(),
    )
    await deliver_game_invitation(bot, db, settings, "mafia", "a" * 22, 1, 2, 5)
    assert bot.send_message.call_args.args[0] == -100123
    red, green = bot.send_message.call_args.kwargs["reply_markup"].inline_keyboard[0]
    assert red.callback_data == "game-invite:close:2:5"
    assert green.url.endswith("nora_inv_mafia_2_" + "a" * 22)

@pytest.mark.parametrize(("game", "title", "handler"), [
    ("durak", "🃏 Дурак", durak_api.action), ("barricade", "🪵 Баррикада", barricade_api.action),
])
async def test_quick_lobby_announces_only_new_waiting_rooms_and_opens_specific_room(db, game, title, handler):
    bot = SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(username="test_nora")),
                          send_rich_message=AsyncMock())
    request = Request(db, 1, {"action": "quick", "config": {"stake": 100}, "nonce": secrets.token_hex(16)}, bot)
    first, retry = await handler(request), await handler(request)
    rid = json.loads(first.body)["id"]
    assert retry.body == first.body
    bot.send_rich_message.assert_awaited_once()
    args, kwargs = bot.send_rich_message.call_args
    assert args == (-100123,)
    heading, host, stake, actions = kwargs["rich_message"].blocks
    assert heading.text == title and host.text[0].text == "@player_1"
    assert stake.text[1].text == "100 🍪"
    assert actions.buttons[0].text == "Присоединиться"
    assert actions.buttons[0].url == f"https://t.me/test_nora?startapp=nora_q_{game}_{rid}"

    click = Request(db, 2, {})
    click.path = f"/api/games/quick/{game}/{rid}"
    click.match_info = {"game": game, "rid": rid}
    assert (await protection(click, quick_preview)).status == 200
    assert (await db.get_user(2))["cookies"] == 100
    click.body = {"action": "join-quick", "room": rid, "nonce": secrets.token_hex(16)}
    click.app["bot"] = bot
    assert json.loads((await handler(click)).body)["id"] == rid
    assert (await db.get_user(2))["cookies"] == 0
    assert (await protection(click, quick_preview)).status == 400
    assert bot.send_rich_message.await_count == 1


@pytest.mark.parametrize(("game", "handler"), [("durak", durak_api.action), ("barricade", barricade_api.action)])
async def test_quick_match_reuses_lobby_at_exact_stake_with_no_second_announcement(db, game, handler):
    bot = SimpleNamespace(me=AsyncMock(return_value=SimpleNamespace(username="test_nora")),
                          send_rich_message=AsyncMock())
    async def search(uid, stake):
        response = await handler(Request(db, uid, {
            "action": "quick", "config": {"stake": stake}, "nonce": secrets.token_hex(16),
        }, bot))
        return json.loads(response.body)["id"]

    original = await search(1, 100)
    assert await search(2, 10) != original
    assert await search(3, 100) == original
    assert bot.send_rich_message.await_count == 2
    assert (await db.get_user(1))["cookies"] == 0
    assert (await db.get_user(3))["cookies"] == 0
    assert (await db.get_user(2))["cookies"] == (90 if game == "durak" else 100)
