import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest
from aiohttp import web

from community_bot.database import Database
from community_bot.seasonal import (
    ITEM,
    all_items,
    buy_confirm,
    buy_prepare,
    draw,
    join,
    manage,
    prepare_draw,
    save_item,
    snapshot,
    validate_metadata,
)


@pytest.fixture
async def env(tmp_path):
    db = Database(tmp_path / "season.db")
    await db.initialize()
    for uid in (7, 8, 9):
        await db.ensure_user(uid, f"user_{uid}", f"Друг {uid}")
        await db.execute(
            "UPDATE users SET age=25,profile_name=?,hobbies='Город',profile_bio='Люблю Нору',"
            "avatar_file_id='fake',cookies=100 WHERE user_id=?",
            (f"Друг {uid}", uid),
        )
    settings = SimpleNamespace(is_owner=lambda uid: uid == 7, owner_ids={7}, moderator_ids=set())
    return SimpleNamespace(db=db, settings=settings)


async def test_join_is_concurrent_once_and_does_not_charge_or_expose_roster(env):
    ledger = await env.db.fetchall("SELECT * FROM transactions ORDER BY id")
    await asyncio.gather(*[join(env.db, 8) for _ in range(12)])
    view = await snapshot(env.db, env.settings, 8)
    assert view["joined"] and view["count"] == 1 and not view["can_manage"]
    assert not (await snapshot(env.db, env.settings, 9))["joined"]
    assert (await env.db.get_user(8))["cookies"] == 100
    assert await env.db.fetchall("SELECT * FROM transactions ORDER BY id") == ledger
    assert set(view) == {
        "id",
        "title",
        "season",
        "status",
        "joined",
        "count",
        "image",
        "author",
        "author_url",
        "image_alt",
        "description",
        "links",
        "eligible",
        "can_manage",
        "winner",
        "won",
        "drawn_at",
    }
    entries = await env.db.fetchall("SELECT * FROM seasonal_entries ORDER BY user_id")
    assert entries[0]["raffle_id"] == "season1-crimson-guardian"
    await env.db.initialize()
    assert await env.db.fetchall("SELECT * FROM seasonal_entries ORDER BY user_id") == entries
    assert (await snapshot(env.db, env.settings, 8))["count"] == 1


async def test_full_profile_gate_and_foreign_admin_cannot_draw_or_read_members(env):
    await env.db.execute("UPDATE users SET hobbies='' WHERE user_id=8")
    with pytest.raises(ValueError, match="100%"):
        await join(env.db, 8)
    for fn in (prepare_draw,):
        with pytest.raises(web.HTTPForbidden):
            await fn(env.db, env.settings, 8)
    with pytest.raises(web.HTTPForbidden):
        await draw(env.db, env.settings, 8, "x" * 30)
    request = {"actor": {"id": 8, "first_name": "Друг"}}

    class Request(dict):
        pass

    r = Request(request)
    r.app = {"db": env.db, "settings": env.settings}
    with pytest.raises(web.HTTPForbidden):
        await manage(r)
    with pytest.raises(ValueError, match="нет участников"):
        await prepare_draw(env.db, env.settings, 7)


async def test_draw_freezes_winner_and_cannot_reroll_even_concurrently_or_after_restart(env):
    for uid in (8, 9):
        await join(env.db, uid)
    q1 = await prepare_draw(env.db, env.settings, 7)
    q2 = await prepare_draw(env.db, env.settings, 7)
    result = await asyncio.gather(
        draw(env.db, env.settings, 7, q1["token"]), draw(env.db, env.settings, 7, q2["token"]), return_exceptions=True
    )
    winners = [r for r in result if isinstance(r, int)]
    assert len(winners) == 1 and winners[0] in (8, 9)
    assert sum(isinstance(r, ValueError) for r in result) == 1
    row = await env.db.fetchone("SELECT * FROM seasonal_raffles WHERE id=?", (ITEM,))
    assert row["entry_count"] == 2 and len(row["entries_digest"]) == 64 and row["drawn_by"] == 7
    assert (await snapshot(env.db, env.settings, winners[0]))["won"]
    await env.db.initialize()
    with pytest.raises(ValueError, match="завершён"):
        await join(env.db, 7)
    with pytest.raises(ValueError, match="уже определён"):
        await draw(env.db, env.settings, 7, q1["token"])
    assert (await env.db.fetchone("SELECT COUNT(*) n FROM notify_inbox WHERE user_id=?", (winners[0],)))["n"] == 1
    assert "Розовый Хранитель" in json.dumps(await snapshot(env.db, env.settings, 8), ensure_ascii=False)


async def test_changed_participants_expiry_and_permissions_invalidate_confirmation(env, monkeypatch):
    await join(env.db, 8)
    q = await prepare_draw(env.db, env.settings, 7)
    await join(env.db, 9)
    with pytest.raises(ValueError, match="изменился"):
        await draw(env.db, env.settings, 7, q["token"])
    q = await prepare_draw(env.db, env.settings, 7)
    await env.db.execute("UPDATE seasonal_draw_tokens SET expires_at=0")
    with pytest.raises(ValueError, match="устарело"):
        await draw(env.db, env.settings, 7, q["token"])
    q = await prepare_draw(env.db, env.settings, 7)
    revoked = SimpleNamespace(is_owner=lambda uid: False, owner_ids=set(), moderator_ids=set())
    with pytest.raises(web.HTTPForbidden):
        await draw(env.db, revoked, 7, q["token"])
    assert (await snapshot(env.db, env.settings, 8))["status"] == "open"


async def test_metadata_changes_keep_existing_entries_and_reject_unsafe_links(env):
    await join(env.db, 8)
    metadata = {"title": "Новый приз", "description": "Описание", "author": "Автор",
                "author_url": "https://example.com", "image": "https://example.com/image.jpg",
                "links": [{"label": "Источник", "url": "https://example.com/source"}]}
    validated = validate_metadata(metadata)
    await env.db.set_bot_state("seasonal_item_metadata", json.dumps(validated))
    view = await snapshot(env.db, env.settings, 8)
    assert view["title"] == "Новый приз" and view["joined"] and view["count"] == 1
    metadata["links"][0]["url"] = "javascript:alert(1)"
    with pytest.raises(ValueError, match="HTTPS"):
        validate_metadata(metadata)


async def test_paid_item_atomic_confirmation_and_price_change(env):
    item = {"title": "Приз", "description": "Описание", "author": "Автор", "mode": "paid", "price": 30,
            "author_url": "https://example.com", "image": "https://example.com/a.jpg", "links": []}
    with pytest.raises(web.HTTPForbidden):
        await save_item(env.db, env.settings, 8, None, item)
    item_id = await save_item(env.db, env.settings, 7, None, item)
    assert len(await all_items(env.db, env.settings, 8)) == 2
    with pytest.raises(ValueError, match="не розыгрыш"):
        await prepare_draw(env.db, env.settings, 7, item_id)
    with pytest.raises(ValueError, match="недоступен"):
        await join(env.db, 8, item_id)
    q = await buy_prepare(env.db, env.settings, 8, item_id)
    item["price"] = 40
    await save_item(env.db, env.settings, 7, item_id, item)
    with pytest.raises(ValueError, match="изменились"):
        await buy_confirm(env.db, 8, q["token"])
    assert (await env.db.get_user(8))["cookies"] == 100
    q = await buy_prepare(env.db, env.settings, 8, item_id)
    q2 = await buy_prepare(env.db, env.settings, 8, item_id)
    with pytest.raises(ValueError, match="подтверждение|устарело"):
        await buy_confirm(env.db, 9, q["token"])
    results = await asyncio.gather(buy_confirm(env.db, 8, q["token"]), buy_confirm(env.db, 8, q2["token"]),
                                   return_exceptions=True)
    assert results.count(item_id) == 1
    assert sum(isinstance(x, ValueError) for x in results) == 1
    assert (await env.db.get_user(8))["cookies"] == 60
    assert (await snapshot(env.db, env.settings, 8, item_id))["joined"]
    item.update(mode="raffle", price=0)
    with pytest.raises(ValueError, match="Нельзя менять"):
        await save_item(env.db, env.settings, 7, item_id, item)


async def test_insufficient_funds_do_not_record_purchase(env):
    item = {"title": "Приз", "description": "Описание", "author": "Автор", "mode": "paid", "price": 101,
            "author_url": "https://example.com", "image": "https://example.com/a.jpg", "links": []}
    item_id = await save_item(env.db, env.settings, 7, None, item)
    q = await buy_prepare(env.db, env.settings, 8, item_id)
    with pytest.raises(ValueError, match="Недостаточно"):
        await buy_confirm(env.db, 8, q["token"])
    assert (await env.db.get_user(8))["cookies"] == 100
    assert not (await snapshot(env.db, env.settings, 8, item_id))["joined"]
    assert not await env.db.fetchall("SELECT * FROM transactions WHERE kind='seasonal_purchase'")


async def test_purchase_ledger_failure_rolls_back_debit_and_confirmation(env):
    item = {"title": "Приз", "description": "Описание", "author": "Автор", "mode": "paid", "price": 30,
            "author_url": "https://example.com", "image": "https://example.com/a.jpg", "links": []}
    item_id = await save_item(env.db, env.settings, 7, None, item)
    q = await buy_prepare(env.db, env.settings, 8, item_id)
    await env.db.execute("CREATE TRIGGER reject_purchase BEFORE INSERT ON transactions "
                         "WHEN NEW.kind='seasonal_purchase' BEGIN SELECT RAISE(ABORT, 'test'); END")
    with pytest.raises(sqlite3.IntegrityError, match="test"):
        await buy_confirm(env.db, 8, q["token"])
    assert (await env.db.get_user(8))["cookies"] == 100
    assert not (await snapshot(env.db, env.settings, 8, item_id))["joined"]
    await env.db.execute("DROP TRIGGER reject_purchase")
    assert await buy_confirm(env.db, 8, q["token"]) == item_id


async def test_hiding_item_stops_pending_purchases_but_admin_can_edit(env):
    item = {"title": "Приз", "description": "Описание", "author": "Автор", "mode": "paid", "price": 30,
            "author_url": "https://example.com", "image": "https://example.com/a.jpg", "links": []}
    item_id = await save_item(env.db, env.settings, 7, None, item)
    q = await buy_prepare(env.db, env.settings, 8, item_id)
    item["enabled"] = False
    await save_item(env.db, env.settings, 7, item_id, item)
    assert item_id not in [x["id"] for x in await all_items(env.db, env.settings, 8)]
    assert item_id in [x["id"] for x in await all_items(env.db, env.settings, 7)]
    with pytest.raises(ValueError, match="изменились"):
        await buy_confirm(env.db, 8, q["token"])
    assert (await env.db.get_user(8))["cookies"] == 100


async def test_new_raffle_draw_confirmation_bound_to_item(env):
    item = {"title": "Приз", "description": "Описание", "author": "Автор", "mode": "raffle", "price": 0,
            "author_url": "https://example.com", "image": "https://example.com/a.jpg", "links": []}
    item_id = await save_item(env.db, env.settings, 7, None, item)
    await join(env.db, 8, item_id)
    await join(env.db, 8)
    q = await prepare_draw(env.db, env.settings, 7, item_id)
    with pytest.raises(ValueError, match="изменился"):
        await draw(env.db, env.settings, 7, q["token"])
    assert await draw(env.db, env.settings, 7, q["token"], item_id) == 8


async def test_save_endpoint_requires_management_permission(env, monkeypatch):
    from community_bot import miniapp, seasonal

    class Request:
        app = {"db": env.db, "settings": env.settings}

        async def json(self):
            return {"id": None, "item": {}}

    async def actor(_):
        return {"user_id": 8}

    monkeypatch.setattr(miniapp, "actor", actor)
    with pytest.raises(web.HTTPForbidden):
        await seasonal.save_endpoint(Request())


async def test_seasonal_http_handlers_create_and_complete_purchase(env, monkeypatch):
    from community_bot import miniapp, seasonal

    class Request:
        app = {"db": env.db, "settings": env.settings}

        def __init__(self, uid, body):
            self.uid, self.body = uid, body

        async def json(self):
            return self.body

    async def actor(request):
        return {"user_id": request.uid}

    monkeypatch.setattr(miniapp, "actor", actor)
    item = {"title": "Приз", "description": "Описание", "author": "Автор", "mode": "paid", "price": 30,
            "author_url": "https://example.com", "image": "https://example.com/a.jpg", "links": []}
    response = await seasonal.save_endpoint(Request(7, {"id": None, "item": item}))
    items = json.loads(response.text)["items"]
    item_id = next(x["id"] for x in items if x["title"] == "Приз")
    response = await seasonal.buy_prepare_endpoint(Request(8, {"id": item_id}))
    token = json.loads(response.text)["token"]
    response = await seasonal.buy_confirm_endpoint(Request(8, {"token": token}))
    assert "администрация свяжется" in json.loads(response.text)["message"].lower()
    assert (await env.db.get_user(8))["cookies"] == 70

async def test_seasonal_image_upload_save_and_read(env):
    from io import BytesIO

    from PIL import Image

    from community_bot import seasonal

    buf = BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, "PNG")

    class FakeBot:
        async def send_photo(self, uid, photo, **kwargs):
            assert uid == 7
            return SimpleNamespace(photo=[SimpleNamespace(file_id="test-photo")])

        async def download(self, file_id, destination):
            assert file_id == "test-photo"
            destination.write(b"jpeg-data")

    class Request(dict):
        def __init__(self, uid, raw, content_type="image/png"):
            super().__init__(actor={"id": uid})
            self.app = {"db": env.db, "settings": env.settings, "bot": FakeBot()}
            self.raw = raw
            self.content_type = content_type

        async def read(self):
            return self.raw

    with pytest.raises(web.HTTPForbidden):
        await seasonal.upload_image(Request(8, buf.getvalue()))
    with pytest.raises(ValueError):
        await seasonal.upload_image(Request(7, b"not an image"))
    with pytest.raises(ValueError):
        await seasonal.upload_image(Request(7, buf.getvalue(), "image/gif"))
    response = await seasonal.upload_image(Request(7, buf.getvalue()))
    image_path = json.loads(response.text)["image"]
    item = {"title": "Приз", "description": "Описание", "author": "Автор", "mode": "raffle", "price": 0,
            "author_url": "https://example.com", "image": image_path, "links": []}
    item_id = await save_item(env.db, env.settings, 7, None, item)
    assert (await snapshot(env.db, env.settings, 8, item_id))["image"] == image_path
    request = Request(8, b"")
    request.match_info = {"token": image_path.rsplit("/", 1)[-1]}
    assert (await seasonal.image(request)).body == b"jpeg-data"
    item["image"] = "/seasonal/media/" + "0" * 48
    with pytest.raises(ValueError, match="не найдено"):
        await save_item(env.db, env.settings, 7, item_id, item)
