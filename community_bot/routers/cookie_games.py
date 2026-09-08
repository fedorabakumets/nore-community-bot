from __future__ import annotations

import secrets

from aiogram import F, Router
from aiogram.filters.command import CommandObject
from aiogram.types import CallbackQuery, Message

from community_bot.aliases import command_or_alias, parse_trigger
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.ephemeral import keep_in_chat
from community_bot.helpers import has_permission, register_telegram_user, user_link
from community_bot.keyboards import (
    blackjack_turn_keyboard,
    cookie_lobby_keyboard,
    cookie_stake_keyboard,
)
from community_bot.permissions import PERM_GAMES

router = Router(name="cookie_games")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))
router.callback_query.filter(F.message.chat.type.in_({"group", "supergroup"}))

COOKIE_GAMES = {
    "bj": ("🃏", "Блэкджек", 2, 4),
    "dice": ("🎲", "Кости", 2, 4),
}
RANKS = "A23456789TJQK"
SUITS = "♠♥♦♣"


def _player_name(player: dict[str, object]) -> str:
    return str(player.get("profile_name") or player.get("telegram_name") or player.get("username") or player["user_id"])


def _card() -> str:
    return f"{secrets.choice(RANKS)}{secrets.choice(SUITS)}"


def _hand_value(cards: list[str]) -> int:
    total = 0
    aces = 0
    for card in cards:
        rank = card[0]
        if rank == "A":
            total += 11
            aces += 1
        elif rank in {"T", "J", "Q", "K"}:
            total += 10
        else:
            total += int(rank)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def _cards_text(cards: list[str]) -> str:
    return " ".join(cards)


def _lobby_text(game: dict[str, object], players: list[dict[str, object]]) -> str:
    emoji, title, minimum, maximum = COOKIE_GAMES[str(game["game_type"])]
    stake = int((game.get("state") or {}).get("stake") or 0)
    names = "\n".join(f"• {user_link(int(player['user_id']), _player_name(player))}" for player in players)
    return (
        f"{emoji} <b>{title} на 🍪 · лобби №{game['id']}</b>\n"
        f"Ставка: <b>{stake} 🍪</b> с каждого (списывается при входе).\n"
        f"Игроков: <b>{len(players)}/{maximum}</b> · нужно {minimum}–{maximum}\n{names}\n\n"
        "Создатель жмёт «Начать», когда компания в сборе."
    )


async def _admin_cancel(db: Database, settings: Settings, user_id: int) -> bool:
    return await has_permission(db, settings, user_id, PERM_GAMES)


@router.message(command_or_alias("cgames", "blackjack", "dice"))
async def cookie_games_command(
    message: Message,
    command: CommandObject,
    db: Database,
    settings: Settings,
) -> None:
    del settings
    if not message.from_user:
        return
    if not await db.feature_enabled("games"):
        await message.answer("Мини-игры временно выключены администрацией.")
        return
    parsed = parse_trigger(message.text or "")
    if parsed:
        raw, args = parsed
    else:
        raw = (command.command or "cgames").casefold()
        args = command.args or ""
    if raw == "cgames":
        with keep_in_chat():
            await message.answer(
                "🍪 <b>Игры на печеньки</b>\n2–4 игрока, ставка списывается при входе.\n"
                "🃏 Блэкджек — против дилера Норы.\n🎲 Кости — 2d6, банк забирает лучший бросок.\n\n"
                "Команды: <code>/blackjack 10</code> · «блэкджек 10» · <code>/dice 25</code> · «кости 25»",
                parse_mode="HTML",
                reply_markup=cookie_stake_keyboard("bj"),
            )
        return
    game_type = "bj" if raw == "blackjack" else "dice"
    try:
        stake = int((args or "10").split()[0])
    except ValueError:
        stake = 0
    if not 1 <= stake <= 500:
        await message.answer("Ставка — целое число от 1 до 500 🍪. Пример: /blackjack 10 или «кости 25»")
        return
    await register_telegram_user(db, message.from_user)
    game_id, status = await db.create_staked_game(message.chat.id, game_type, message.from_user.id, stake)
    if status != "ok" or game_id is None:
        await message.answer(status if game_id is None else f"{status} Уже идёт партия №{game_id}.")
        return
    game = await db.get_party_game(game_id)
    players = await db.list_game_players(game_id)
    assert game is not None
    with keep_in_chat():
        await message.answer(_lobby_text(game, players), parse_mode="HTML", reply_markup=cookie_lobby_keyboard(game_id))


@router.callback_query(F.data == "cg:home")
async def cookie_games_home(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "🍪 Выберите игру, затем ставку. В партии 2–4 человека.",
            reply_markup=cookie_stake_keyboard("bj"),
        )


@router.callback_query(F.data.startswith("cg:pick:"))
async def cookie_pick_game(callback: CallbackQuery) -> None:
    if not callback.data or not callback.message:
        return
    game_type = callback.data.rsplit(":", 1)[1]
    if game_type not in COOKIE_GAMES:
        await callback.answer("Неизвестная игра.", show_alert=True)
        return
    await callback.answer()
    emoji, title, _, _ = COOKIE_GAMES[game_type]
    await callback.message.answer(
        f"{emoji} <b>{title}</b>\nВыберите ставку печенек. Она спишется при входе в лобби.",
        parse_mode="HTML",
        reply_markup=cookie_stake_keyboard(game_type),
    )


@router.callback_query(F.data.startswith("cg:new:"))
async def cookie_new_game(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    if not await db.feature_enabled("games"):
        await callback.answer("Игры выключены.", show_alert=True)
        return
    _, _, game_type, raw_stake = callback.data.split(":")
    if game_type not in COOKIE_GAMES:
        await callback.answer("Неизвестная игра.", show_alert=True)
        return
    stake = int(raw_stake)
    await register_telegram_user(db, callback.from_user)
    game_id, status = await db.create_staked_game(
        callback.message.chat.id,
        game_type,
        callback.from_user.id,
        stake,
    )
    if status != "ok" or game_id is None:
        await callback.answer(status if game_id is None else f"Уже идёт партия №{game_id}.", show_alert=True)
        return
    game = await db.get_party_game(game_id)
    players = await db.list_game_players(game_id)
    assert game is not None
    await callback.answer("Лобби создано, ставка списана.")
    await callback.message.answer(
        _lobby_text(game, players),
        parse_mode="HTML",
        reply_markup=cookie_lobby_keyboard(game_id),
    )


@router.callback_query(F.data.startswith("cg:join:"))
async def cookie_join(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    game = await db.get_party_game(game_id)
    if not game or game["game_type"] not in COOKIE_GAMES:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    await register_telegram_user(db, callback.from_user)
    maximum = COOKIE_GAMES[str(game["game_type"])][3]
    ok, text = await db.join_staked_game(game_id, callback.from_user.id, maximum)
    await callback.answer(text, show_alert=not ok)
    if not ok:
        return
    players = await db.list_game_players(game_id)
    game = await db.get_party_game(game_id)
    assert game is not None
    await callback.message.edit_text(
        _lobby_text(game, players),
        parse_mode="HTML",
        reply_markup=cookie_lobby_keyboard(game_id),
    )


@router.callback_query(F.data.startswith("cg:cancel:"))
async def cookie_cancel(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    is_admin = await _admin_cancel(db, settings, callback.from_user.id)
    if not await db.cancel_party_game(game_id, callback.from_user.id, is_admin):
        await callback.answer("Отменить может создатель или администратор игр.", show_alert=True)
        return
    await callback.answer("Ставки возвращены.")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"❌ Игра №{game_id} отменена, 🍪 вернулись игрокам.")


@router.callback_query(F.data.startswith("cg:start:"))
async def cookie_start(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    game = await db.get_party_game(game_id)
    if not game or game["status"] != "lobby" or game["game_type"] not in COOKIE_GAMES:
        await callback.answer("Лобби уже закрыто.", show_alert=True)
        return
    if callback.from_user.id != int(game["creator_id"]):
        await callback.answer("Начать может только создатель.", show_alert=True)
        return
    players = await db.list_game_players(game_id)
    minimum, maximum = COOKIE_GAMES[str(game["game_type"])][2], COOKIE_GAMES[str(game["game_type"])][3]
    if not minimum <= len(players) <= maximum:
        await callback.answer(f"Нужно от {minimum} до {maximum} игроков.", show_alert=True)
        return
    if str(game["game_type"]) == "dice":
        await _start_dice(callback, db, game, players)
        return
    await _start_blackjack(callback, db, game, players)


async def _start_dice(
    callback: CallbackQuery,
    db: Database,
    game: dict[str, object],
    players: list[dict[str, object]],
) -> None:
    assert callback.message
    stake = int(game["state"]["stake"])
    rolls: list[tuple[int, int, int, dict[str, object]]] = []
    lines = ["🎲 <b>Кости</b> — каждый бросает 2d6.\n"]
    for player in players:
        a, b = secrets.randbelow(6) + 1, secrets.randbelow(6) + 1
        rolls.append((a + b, a, b, player))
        lines.append(
            f"• {user_link(int(player['user_id']), _player_name(player))}: {a}+{b} = <b>{a + b}</b>"
        )
    best = max(item[0] for item in rolls)
    winners = [item[3] for item in rolls if item[0] == best]
    pot = stake * len(players)
    share, remainder = divmod(pot, len(winners))
    payouts = {int(player["user_id"]): share for player in winners}
    if remainder:
        payouts[int(winners[0]["user_id"])] += remainder
    await db.save_party_state(int(game["id"]), {**game["state"], "phase": "done", "rolls": best})
    await db.payout_staked_game(int(game["id"]), payouts)
    names = ", ".join(user_link(int(player["user_id"]), _player_name(player)) for player in winners)
    lines.append(f"\n🏆 Банк <b>{pot} 🍪</b> забирает: {names}.")
    await callback.answer("Кости брошены!")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("\n".join(lines), parse_mode="HTML")


async def _start_blackjack(
    callback: CallbackQuery,
    db: Database,
    game: dict[str, object],
    players: list[dict[str, object]],
) -> None:
    assert callback.message
    order = [int(player["user_id"]) for player in players]
    hands = {str(user_id): [_card(), _card()] for user_id in order}
    dealer = [_card(), _card()]
    state = {
        **game["state"],
        "phase": "play",
        "order": order,
        "turn": 0,
        "hands": hands,
        "dealer": dealer,
        "done": [],
    }
    secrets_by_user = {user_id: {"stake": int(game["state"]["stake"])} for user_id in order}
    if not await db.start_party_game(int(game["id"]), int(game["creator_id"]), state, secrets_by_user):
        await callback.answer("Не удалось начать.", show_alert=True)
        return
    await callback.answer("Раздача!")
    await callback.message.edit_text(
        _blackjack_board(state, players, hide_dealer=True),
        parse_mode="HTML",
        reply_markup=blackjack_turn_keyboard(int(game["id"])),
    )


def _blackjack_board(state: dict[str, object], players: list[dict[str, object]], hide_dealer: bool) -> str:
    by_id = {int(player["user_id"]): player for player in players}
    dealer = list(state["dealer"])
    if hide_dealer:
        dealer_line = f"{dealer[0]} 🂠"
    else:
        dealer_line = f"{_cards_text(dealer)} · {_hand_value(dealer)}"
    lines = [
        "🃏 <b>Блэкджек · Нора сдаёт</b>",
        f"Дилер: {dealer_line}",
        "",
    ]
    turn_id = int(state["order"][int(state["turn"])]) if int(state["turn"]) < len(list(state["order"])) else 0
    for user_id in state["order"]:
        cards = list(state["hands"][str(user_id)])
        marker = "👉 " if user_id == turn_id and hide_dealer else "• "
        player = by_id[int(user_id)]
        lines.append(
            f"{marker}{user_link(int(user_id), _player_name(player))}: "
            f"{_cards_text(cards)} · <b>{_hand_value(cards)}</b>"
        )
    if hide_dealer:
        current = by_id.get(turn_id)
        if current:
            lines.append(
                f"\nХод: {user_link(turn_id, _player_name(current))}. Взять карту или остановиться."
            )
    return "\n".join(lines)


async def _finish_blackjack(message: Message, db: Database, game_id: int) -> None:
    game = await db.get_party_game(game_id)
    if not game:
        return
    state = dict(game["state"])
    dealer = list(state["dealer"])
    while _hand_value(dealer) < 17:
        dealer.append(_card())
    state["dealer"] = dealer
    dealer_value = _hand_value(dealer)
    dealer_bust = dealer_value > 21
    players = await db.list_game_players(game_id)
    stake = int(state["stake"])
    results: list[str] = []
    winners: list[int] = []
    pushes: list[int] = []
    for user_id in state["order"]:
        uid = int(user_id)
        value = _hand_value(list(state["hands"][str(uid)]))
        player = next(item for item in players if int(item["user_id"]) == uid)
        name = user_link(uid, _player_name(player))
        if value > 21:
            results.append(f"• {name}: перебор ({value}) — ставка сгорает")
        elif dealer_bust or value > dealer_value:
            winners.append(uid)
            results.append(f"• {name}: {value} — победа")
        elif value == dealer_value:
            pushes.append(uid)
            results.append(f"• {name}: {value} — ничья, ставка вернётся")
        else:
            results.append(f"• {name}: {value} — дилер выше")
    pot = stake * len(list(state["order"]))
    returned = stake * len(pushes)
    prize_pool = pot - returned
    payouts: dict[int, int] = {uid: stake for uid in pushes}
    if winners:
        share, remainder = divmod(prize_pool, len(winners))
        for index, uid in enumerate(winners):
            payouts[uid] = payouts.get(uid, 0) + share + (remainder if index == 0 else 0)
    elif not pushes:
        payouts = {int(user_id): stake for user_id in state["order"]}
        results.append("\nВсе проиграли дилеру — ставки возвращены, печеньки не сжигаем.")
    state["phase"] = "done"
    await db.save_party_state(game_id, state)
    await db.payout_staked_game(game_id, payouts)
    dealer_text = f"{_cards_text(dealer)} · <b>{dealer_value}</b>" + (" — перебор" if dealer_bust else "")
    await message.edit_reply_markup(reply_markup=None)
    await message.answer(
        "🃏 <b>Итог блэкджека</b>\n"
        f"Дилер: {dealer_text}\n\n" + "\n".join(results),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("cg:hit:"))
async def blackjack_hit(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    game = await db.get_party_game(game_id)
    if not game or game["status"] != "active" or game["game_type"] != "bj":
        await callback.answer("Партия уже закончилась.", show_alert=True)
        return
    state = dict(game["state"])
    order = [int(item) for item in state["order"]]
    turn = int(state["turn"])
    if turn >= len(order) or callback.from_user.id != order[turn]:
        await callback.answer("Сейчас не ваш ход.", show_alert=True)
        return
    user_id = order[turn]
    hand = list(state["hands"][str(user_id)])
    hand.append(_card())
    state["hands"][str(user_id)] = hand
    players = await db.list_game_players(game_id)
    if _hand_value(hand) >= 21:
        state["turn"] = turn + 1
        await db.save_party_state(game_id, state)
        await callback.answer("Хватит с этой руки.")
        if int(state["turn"]) >= len(order):
            await _finish_blackjack(callback.message, db, game_id)
            return
    else:
        await db.save_party_state(game_id, state)
        await callback.answer("Ещё карта.")
    await callback.message.edit_text(
        _blackjack_board(state, players, hide_dealer=True),
        parse_mode="HTML",
        reply_markup=blackjack_turn_keyboard(game_id),
    )


@router.callback_query(F.data.startswith("cg:stand:"))
async def blackjack_stand(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    game = await db.get_party_game(game_id)
    if not game or game["status"] != "active" or game["game_type"] != "bj":
        await callback.answer("Партия уже закончилась.", show_alert=True)
        return
    state = dict(game["state"])
    order = [int(item) for item in state["order"]]
    turn = int(state["turn"])
    if turn >= len(order) or callback.from_user.id != order[turn]:
        await callback.answer("Сейчас не ваш ход.", show_alert=True)
        return
    state["turn"] = turn + 1
    await db.save_party_state(game_id, state)
    await callback.answer("Стойка.")
    if int(state["turn"]) >= len(order):
        await _finish_blackjack(callback.message, db, game_id)
        return
    players = await db.list_game_players(game_id)
    await callback.message.edit_text(
        _blackjack_board(state, players, hide_dealer=True),
        parse_mode="HTML",
        reply_markup=blackjack_turn_keyboard(game_id),
    )
