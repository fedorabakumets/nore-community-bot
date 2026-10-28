"""Own pet, wallet and notification controls, sharing the Telegram ledger and rules."""

from __future__ import annotations

from datetime import UTC, datetime

from aiohttp import web

from community_bot.domain import transfer_commission_percent
from community_bot.economy import (
    LOAN_DAYS,
    LOAN_PRINCIPAL,
    TRANSACTION_LABELS,
    loan_interest_percent,
    loan_repay_amount,
)
from community_bot.miniapp import actor
from community_bot.pets_talk import SPECIES
from community_bot.rsvp import event_lock
from community_bot.shop_api import recipient
from community_bot.shop_catalog import ITEM_LABELS
from community_bot.shop_text import plain_shop_text


def result(ok, message):
    return web.json_response({"ok": ok, "message": message}, status=200 if ok else 409)


async def wallet_data(db, settings, user):
    percent = loan_interest_percent(user["reputation"], settings.restricted_reputation_threshold)
    loan = await db.get_active_loan(user["user_id"])
    return {
        "active": {k: loan[k] for k in ("principal", "due_amount", "due_at")} if loan else None,
        "principal": LOAN_PRINCIPAL,
        "days": LOAN_DAYS,
        "interest_percent": percent,
        "repay_amount": loan_repay_amount(LOAN_PRINCIPAL, percent),
        "available": not loan and not user["cookie_debt"],
        "transfer_percent": transfer_commission_percent(user["reputation"], settings.restricted_reputation_threshold),
    }


async def pet_data(db, user):
    from community_bot.expedition import ExpeditionLoot, parse_loot

    pet = await db.get_pet(user["user_id"])
    if not pet:
        return None
    raw_loot = pet.get("expedition_loot")
    loot = ExpeditionLoot.from_mapping(raw_loot) if isinstance(raw_loot, dict) else parse_loot(raw_loot)
    value = {
        k: pet.get(k)
        for k in (
            "name",
            "species",
            "hunger",
            "thirst",
            "mood",
            "sleeping",
            "food_units",
            "water_units",
            "expedition_until",
            "created_at",
            "guard_used_on",
        )
    }
    value.update(
        emoji=SPECIES.get(pet["species"], ("🐾",))[0],
        species_label=SPECIES.get(pet["species"], ("", "питомец"))[1],
        last_find=loot.label() if loot and not pet["expedition_until"] else None,
        enabled=await db.feature_enabled("tamagotchi"),
    )
    return value


async def pet_prepare(request):
    user, db = await actor(request), request.app["db"]
    body = await request.json()
    action = body.get("action") if isinstance(body, dict) else None
    if action not in {"food", "water", "expedition", "rename"} or not await db.feature_enabled("tamagotchi"):
        raise ValueError("Это действие питомца сейчас недоступно")
    if not await db.get_pet(user["user_id"], settle=False):
        raise ValueError("Сначала заведи тамагочи в магазине")
    payload = {"action": action}
    if action == "rename":
        name = body.get("name")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 24:
            raise ValueError("Имя питомца: от 1 до 24 символов")
        payload["name"] = name.strip()
    token = await db.create_wallet_intent(user["user_id"], "pet_action", 1, payload=payload)
    return web.json_response({"token": token})


async def pet_action(request):
    user, db = await actor(request), request.app["db"]
    body = await request.json()
    token = body.get("token") if isinstance(body, dict) else None
    if not isinstance(token, str):
        raise ValueError("Открой действие питомца заново")
    async with event_lock(db, "cabinet:" + token):
        intent = await db.get_wallet_intent(user["user_id"], token)
        if not intent or intent["item"] != "pet_action":
            return result(False, "Действие уже выполнено или устарело")
        action = intent["payload"]["action"]
        if action == "expedition":
            ok, message, _ = await db.start_expedition(
                user["user_id"], request.app["settings"].timezone, intent_id=token
            )
            if ok:
                from community_bot.life import unlock

                await unlock(db, user["user_id"], "expedition")
            return result(ok, "Питомец отправился в поход на 24 часа!" if ok else message)
        if action in {"food", "water"}:
            ok, message, _ = await db.use_pet_supply(user["user_id"], action, intent_id=token)
            return result(ok, "Питомец доволен!" if ok else message)
        if action == "rename":
            async with db.connect() as connection:
                await connection.execute("BEGIN IMMEDIATE")
                error = await db._consume_wallet_intent(
                    connection, token, user["user_id"], "pet_action", 1, user["user_id"]
                )
                if error:
                    await connection.rollback()
                    return result(False, error)
                await connection.execute(
                    "UPDATE pets SET name=?,updated_at=? WHERE user_id=?",
                    (intent["payload"]["name"], datetime.now(UTC).isoformat(), user["user_id"]),
                )
                await connection.commit()
            return result(True, "Имя питомца обновлено в боте и миниапке")
    return result(False, "Неизвестное действие")


async def wallet_prepare(request):
    user, db, settings = await actor(request), request.app["db"], request.app["settings"]
    body = await request.json()
    action = body.get("action") if isinstance(body, dict) else None
    if action == "transfer":
        target, label = await recipient(db, user["user_id"], body.get("recipient"))
        amount = body.get("amount")
        if target == user["user_id"] or type(amount) is not int or not 1 <= amount <= 1_000_000:
            raise ValueError("Укажи другого участника и целую сумму от 1 до 1 000 000")
        percent = transfer_commission_percent(user["reputation"], settings.restricted_reputation_threshold)
        received = amount * (100 - percent) // 100
        if not received:
            raise ValueError("После комиссии получателю ничего не останется. Увеличь сумму")
        transfer_id = await db.create_transfer(user["user_id"], target, amount)
        token = await db.create_wallet_intent(
            user["user_id"],
            "transfer",
            amount,
            target_id=target,
            payload={"transfer_id": transfer_id, "percent": percent},
        )
        return web.json_response(
            {"token": token, "amount": amount, "received": received, "percent": percent, "recipient": label}
        )
    if action == "starter_pack":
        if await db.get_active_loan(user["user_id"]) or user["cookie_debt"]:
            raise ValueError("Сначала верни текущий стартер-пак или погаси долг")
        percent = loan_interest_percent(user["reputation"], settings.restricted_reputation_threshold)
        token = await db.create_wallet_intent(
            user["user_id"], "loan", LOAN_PRINCIPAL, payload={"interest_percent": percent}
        )
        return web.json_response(
            {
                "token": token,
                "amount": LOAN_PRINCIPAL,
                "days": LOAN_DAYS,
                "percent": percent,
                "due_amount": loan_repay_amount(LOAN_PRINCIPAL, percent),
            }
        )
    if action == "repay":
        debt = int(user["cookie_debt"])
        if debt:
            amount = min(user["cookies"], debt)
            item, payload = "debt_repay", {}
        else:
            loan = await db.get_active_loan(user["user_id"])
            if not loan:
                raise ValueError("Возвращать пока нечего")
            amount, item, payload = loan["due_amount"], "loan_repay", {"loan_id": loan["id"]}
        if amount <= 0 or amount > user["cookies"]:
            raise ValueError("Сначала пополни баланс для возврата")
        token = await db.create_wallet_intent(user["user_id"], item, amount, payload=payload)
        return web.json_response({"token": token, "amount": amount, "remaining_debt": max(0, debt - amount)})
    raise ValueError("Неизвестное действие кошелька")


async def repay_active(db, uid, intent):
    async with db.connect() as connection:
        await connection.execute("BEGIN IMMEDIATE")
        error = await db._consume_wallet_intent(connection, intent["token"], uid, "loan_repay", intent["price"], uid)
        if error:
            await connection.rollback()
            return False, error
        loan = await (
            await connection.execute(
                "SELECT * FROM cookie_loans WHERE id=? AND user_id=? AND status='active'",
                (intent["payload"]["loan_id"], uid),
            )
        ).fetchone()
        if not loan or loan["due_amount"] != intent["price"]:
            await connection.rollback()
            return False, "Стартер-пак уже возвращён или условия изменились"
        cursor = await connection.execute(
            "UPDATE users SET cookies=cookies-? WHERE user_id=? AND cookies>=?", (intent["price"], uid, intent["price"])
        )
        if cursor.rowcount != 1:
            await connection.rollback()
            return False, "Недостаточно печенек"
        now = datetime.now(UTC).isoformat()
        await connection.execute("UPDATE cookie_loans SET status='repaid',collected_at=? WHERE id=?", (now, loan["id"]))
        await connection.execute(
            "INSERT INTO transactions(user_id,amount,kind,details,created_at) VALUES(?,?,?,?,?)",
            (uid, -intent["price"], "loan_repay", f"loan:{loan['id']};early", now),
        )
        await connection.commit()
        return True, "Стартер-пак возвращён!"


async def wallet_confirm(request):
    user, db, settings = await actor(request), request.app["db"], request.app["settings"]
    body = await request.json()
    token = body.get("token") if isinstance(body, dict) else None
    if not isinstance(token, str):
        raise ValueError("Открой подтверждение заново")
    async with event_lock(db, "cabinet:" + token):
        intent = await db.get_wallet_intent(user["user_id"], token)
        if not intent:
            return result(False, "Подтверждение уже выполнено или устарело")
        item = intent["item"]
        if item == "transfer":
            ok, message, received = await db.complete_transfer(
                intent["payload"]["transfer_id"],
                user["user_id"],
                settings.restricted_reputation_threshold,
                intent_id=token,
            )
            if ok and request.app["bot"]:
                from community_bot.helpers import safe_send

                await safe_send(request.app["bot"], intent["target_id"], f"Тебе перевели {received} 🍪.")
            return result(ok, f"Перевод выполнен: получателю {received} 🍪" if ok else message)
        if item == "loan":
            ok, message, _ = await db.take_cookie_loan(
                user["user_id"], settings.restricted_reputation_threshold, intent_id=token
            )
            return result(ok, "НОРА — СТАРТЕР-ПАК: 100 🍪 на общем балансе. Помни о возврате." if ok else message)
        if item == "debt_repay":
            ok, message = await db.repay_cookie_debt(user["user_id"], intent["price"], intent_id=token)
            return result(ok, "Долг погашен на " + str(intent["price"]) + " 🍪" if ok else message)
        if item == "loan_repay":
            return result(*await repay_active(db, user["user_id"], intent))
    return result(False, "Это подтверждение не относится к кошельку")


async def wallet_history(request):
    user, db = await actor(request), request.app["db"]
    raw = request.query.get("offset", "0")
    if not raw.isdigit() or len(raw) > 8:
        raise ValueError("Некорректная страница истории")
    offset = min(int(raw), 1_000_000)
    rows = await db.list_transactions(user["user_id"], 21, offset=offset)
    items = []
    for row in rows[:20]:
        kind, details = row["kind"], row["details"]
        label = TRANSACTION_LABELS.get(kind, "Операция с печеньками")
        if kind in {"shop", "pet_shop"}:
            sku, _, target = details.partition("->")
            label = ITEM_LABELS.get(sku, label) + (" · подарок" if target else "")
        elif kind == "transfer":
            label = "Перевод отправлен" if row["amount"] < 0 else "Перевод получен"
        items.append(
            {"id": row["id"], "amount": row["amount"], "kind": kind, "label": label, "date": row["created_at"]}
        )
    return web.json_response({"items": items, "offset": offset, "has_more": len(rows) > 20})


async def notices(request):
    from community_bot.notify import CHANNELS

    user, db = await actor(request), request.app["db"]
    rows = await db.fetchall(
        "SELECT id,channel,text,created_at,read FROM notify_inbox WHERE user_id=? ORDER BY id DESC LIMIT 40",
        (user["user_id"],),
    )
    from community_bot.mafia_api import read_status

    invitations = {item["room_id"]: item for item in (await read_status(db, user["user_id"]))["invites"]}
    for row in rows:
        room_id = await db.get_bot_state(f"mafia_notice:{row['id']}")
        row["mafia_invite"] = invitations.get(room_id)
    prefs = await db.notify_prefs_map(user["user_id"])
    return web.json_response(
        {
            "items": [dict(row, text=plain_shop_text(row["text"])) for row in rows],
            "mafia_invites": [item for key, item in invitations.items()
                              if not any(row.get("mafia_invite") == item for row in rows)],
            "unread": await db.notify_unread_count(user["user_id"]),
            "channels": [
                {
                    "id": key,
                    "title": plain_shop_text(value[0]),
                    "description": value[1],
                    "enabled": bool(prefs.get(key, {}).get("enabled")),
                    "digest": bool(prefs.get(key, {}).get("digest")),
                }
                for key, value in CHANNELS.items()
            ],
        }
    )


async def notices_update(request):
    from community_bot.notify import CHANNELS

    user, db = await actor(request), request.app["db"]
    body = await request.json()
    if not isinstance(body, dict):
        raise ValueError("Проверь настройки уведомлений")
    if body.get("action") == "read":
        through = body.get("through_id")
        if type(through) is not int or through < 0:
            raise ValueError("Открой уведомления заново")
        await db.execute("UPDATE notify_inbox SET read=1 WHERE user_id=? AND id<=?", (user["user_id"], through))
    else:
        channel, enabled, digest = body.get("channel"), body.get("enabled"), body.get("digest")
        if channel not in CHANNELS or type(enabled) is not bool or type(digest) is not bool:
            raise ValueError("Проверь настройки канала")
        await db.execute(
            "INSERT INTO notify_prefs(user_id,channel,enabled,digest) VALUES(?,?,?,?) "
            "ON CONFLICT(user_id,channel) DO UPDATE SET enabled=excluded.enabled,digest=excluded.digest",
            (user["user_id"], channel, int(enabled), int(digest)),
        )
    return result(True, "Уведомления обновлены")
