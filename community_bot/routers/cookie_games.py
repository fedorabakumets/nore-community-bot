from __future__ import annotations

import asyncio
import secrets
from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.command import CommandObject
from aiogram.types import CallbackQuery, Message

from community_bot.aliases import command_or_alias, parse_trigger
from community_bot.blocks import answer_block, edit_block
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.domain import win_after_commission
from community_bot.ephemeral import expire_game_result, keep_in_chat
from community_bot.game_notify import notify_game_event, send_game_finale
from community_bot.helpers import has_permission, register_telegram_user, user_link
from community_bot.keyboards import (
    COOKIE_STAKE_CHOICES,
    blackjack_turn_keyboard,
    cookie_lobby_keyboard,
    cookie_stake_keyboard,
    crash_keyboard,
    games_menu_keyboard,
)
from community_bot.permissions import PERM_GAMES
from community_bot.texts import GAMES_HELP_TEXT

router = Router(name="cookie_games")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))
router.callback_query.filter(F.message.chat.type.in_({"group", "supergroup"}))

COOKIE_GAMES = {
    "bj": ("🃏", "Блэкджек", 2, 4),
    "dice": ("🎲", "Кубик", 2, 2),
    "crash": ("🚀", "Рейс", 2, 4),
}
COVER_BY_GAME = {"bj": "blackjack", "dice": "dice", "crash": "crash"}
RANKS = "A23456789TJQK"
SUITS = "♠♥♦♣"
_CRASH_JOBS: dict[int, asyncio.Task[None]] = {}


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


def _cover(game_type: str) -> str:
    return COVER_BY_GAME.get(game_type, "games")


def _lobby_text(game: dict[str, object], players: list[dict[str, object]]) -> str:
    emoji, title, minimum, maximum = COOKIE_GAMES[str(game["game_type"])]
    stake = int((game.get("state") or {}).get("stake") or 0)
    names = "\n".join(f"• {user_link(int(player['user_id']), _player_name(player))}" for player in players)
    extra = ""
    if str(game["game_type"]) == "dice":
        extra = "Один кубик, большее число забирает банк минус комиссия победителя.\n"
    elif str(game["game_type"]) == "crash":
        extra = "Множитель растёт. «Забрать» фиксирует выигрыш до срыва.\n"
    elif str(game["game_type"]) == "bj":
        extra = "Против дилера Норы. Выигрыш после комиссии репутации.\n"
    return (
        f"{emoji} <b>{title} на 🍪 · лобби №{game['id']}</b>\n"
        f"{extra}"
        f"Ставка: <b>{stake} 🍪</b> с каждого (списывается при входе).\n"
        f"Игроков: <b>{len(players)}/{maximum}</b> · нужно {minimum}–{maximum}\n{names}\n\n"
        "Создатель жмёт «Начать», когда компания в сборе."
    )


def _lobby_markup(game: dict[str, object]) -> object:
    return cookie_lobby_keyboard(int(game["id"]), int((game.get("state") or {}).get("stake") or 10))


async def _admin_cancel(db: Database, settings: Settings, user_id: int) -> bool:
    return await has_permission(db, settings, user_id, PERM_GAMES)


async def _alert(bot: Bot, chat_id: int, players: list[dict[str, object]], group_text: str, dm_text: str) -> None:
    await notify_game_event(bot, chat_id, players, group_text, dm_text)


async def _publish_lobby(
    target: Message,
    game: dict[str, object],
    players: list[dict[str, object]],
    *,
    new: bool,
) -> None:
    text = _lobby_text(game, players)
    markup = _lobby_markup(game)
    if new:
        with keep_in_chat():
            await answer_block(
                target,
                _cover(str(game["game_type"])),
                text,
                parse_mode="HTML",
                reply_markup=markup,
            )
        return
    await edit_block(target, text, parse_mode="HTML", reply_markup=markup)


def _cancel_crash_job(game_id: int) -> None:
    task = _CRASH_JOBS.pop(game_id, None)
    if task and not task.done():
        task.cancel()


def _crash_point() -> float:
    if secrets.randbelow(100) < 4:
        return 1.00
    roll = secrets.randbelow(10_000) / 10_000
    point = 0.96 / max(0.02, 1 - roll)
    return min(20.0, max(1.05, round(point, 2)))


def _game_type_from_command(raw: str) -> str | None:
    mapping = {"blackjack": "bj", "dice": "dice", "crash": "crash"}
    return mapping.get(raw)


@router.message(command_or_alias("cgames", "blackjack", "dice", "crash"))
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
            await answer_block(
                message,
                "games",
                GAMES_HELP_TEXT,
                parse_mode="HTML",
                reply_markup=games_menu_keyboard(),
            )
        return
    game_type = _game_type_from_command(raw)
    if game_type is None:
        return
    try:
        stake = int((args or "10").split()[0])
    except ValueError:
        stake = 0
    if not 1 <= stake <= 500:
        await message.answer("Ставка — целое число от 1 до 500 🍪. Пример: /blackjack 10 или «рейс 25»")
        return
    await register_telegram_user(db, message.from_user)
    game_id, status = await db.create_staked_game(message.chat.id, game_type, message.from_user.id, stake)
    if status != "ok" or game_id is None:
        await message.answer(status if game_id is None else f"{status} Уже идёт партия №{game_id}.")
        return
    game = await db.get_party_game(game_id)
    players = await db.list_game_players(game_id)
    assert game is not None
    await _publish_lobby(message, game, players, new=True)
    await _alert(
        message.bot,
        message.chat.id,
        players,
        f"🍪 Лобби №{game_id} открыто. Ставка {int(game['state']['stake'])} 🍪.",
        f"🍪 Вас ждут в лобби №{game_id}. Ставка {int(game['state']['stake'])} 🍪 уже списана.",
    )


@router.message(command_or_alias("gamecancel"))
async def cancel_active_game(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    game = await db.active_party_game(message.chat.id)
    if not game:
        await message.answer("Сейчас нет открытой партии на печеньки.")
        return
    players = await db.list_game_players(int(game["id"]))
    is_admin = await _admin_cancel(db, settings, message.from_user.id)
    if not await db.cancel_party_game(int(game["id"]), message.from_user.id, is_admin):
        await message.answer("Отменить может создатель или администратор игр.")
        return
    _cancel_crash_job(int(game["id"]))
    await send_game_finale(message, f"❌ Игра №{game['id']} отменена, 🍪 вернулись игрокам.")
    await _alert(
        message.bot,
        message.chat.id,
        players,
        f"❌ Игра №{game['id']} отменена, ставки возвращены.",
        f"❌ Лобби №{game['id']} отменено. Ваша ставка возвращена.",
    )


@router.callback_query(F.data == "cg:home")
async def cookie_games_home(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await answer_block(
            callback.message,
            "games",
            GAMES_HELP_TEXT,
            parse_mode="HTML",
            reply_markup=games_menu_keyboard(),
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
    emoji, title, minimum, maximum = COOKIE_GAMES[game_type]
    await answer_block(
        callback.message,
        _cover(game_type),
        f"{emoji} <b>{title}</b>\n"
        f"Игроков: {minimum}–{maximum}. Выберите ставку — она спишется при входе в лобби.",
        parse_mode="HTML",
        reply_markup=cookie_stake_keyboard(game_type),
    )


@router.callback_query(F.data.startswith("cg:new:"))
async def cookie_new_game(callback: CallbackQuery, db: Database, bot: Bot) -> None:
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
    await _publish_lobby(callback.message, game, players, new=True)
    await _alert(
        bot,
        callback.message.chat.id,
        players,
        f"🍪 Лобби №{game_id} открыто. Ставка {stake} 🍪.",
        f"🍪 Вас ждут в лобби №{game_id}. Ставка {stake} 🍪 уже списана.",
    )


@router.callback_query(F.data.startswith("cg:join:"))
async def cookie_join(callback: CallbackQuery, db: Database, bot: Bot) -> None:
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
    await _publish_lobby(callback.message, game, players, new=False)
    joiner = _player_name(next(player for player in players if int(player["user_id"]) == callback.from_user.id))
    await _alert(
        bot,
        callback.message.chat.id,
        players,
        f"🍪 {joiner} вошёл в лобби №{game_id}.",
        f"🍪 {joiner} присоединился к лобби №{game_id}. Ставка списана.",
    )


@router.callback_query(F.data.startswith("cg:stake:"))
async def cookie_change_stake(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    if not callback.data or not callback.message:
        return
    _, _, raw_game_id, raw_stake = callback.data.split(":")
    game_id = int(raw_game_id)
    stake = int(raw_stake)
    if stake not in COOKIE_STAKE_CHOICES:
        await callback.answer("Такой ставки нет.", show_alert=True)
        return
    ok, text = await db.update_staked_game_stake(game_id, callback.from_user.id, stake)
    if not ok:
        await callback.answer(text, show_alert=True)
        return
    game = await db.get_party_game(game_id)
    players = await db.list_game_players(game_id)
    assert game is not None
    await callback.answer(f"Ставка теперь {stake} 🍪.")
    await _publish_lobby(callback.message, game, players, new=False)
    await _alert(
        bot,
        callback.message.chat.id,
        players,
        f"🍪 Ставка в лобби №{game_id} теперь {stake} 🍪. Печеньки пересчитаны.",
        f"🍪 Ставка в лобби №{game_id} изменена на {stake} 🍪. Баланс пересчитан.",
    )


@router.callback_query(F.data.startswith("cg:cancel:"))
async def cookie_cancel(callback: CallbackQuery, db: Database, settings: Settings, bot: Bot) -> None:
    if not callback.data or not callback.message:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    players = await db.list_game_players(game_id)
    is_admin = await _admin_cancel(db, settings, callback.from_user.id)
    if not await db.cancel_party_game(game_id, callback.from_user.id, is_admin):
        await callback.answer("Отменить может создатель или администратор игр.", show_alert=True)
        return
    _cancel_crash_job(game_id)
    await callback.answer("Ставки возвращены.")
    await callback.message.edit_reply_markup(reply_markup=None)
    await send_game_finale(callback.message, f"❌ Игра №{game_id} отменена, 🍪 вернулись игрокам.")
    expire_game_result(callback.message)
    await _alert(
        bot,
        callback.message.chat.id,
        players,
        f"❌ Игра №{game_id} отменена, ставки возвращены.",
        f"❌ Лобби №{game_id} отменено. Ваша ставка возвращена.",
    )


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
    kind = str(game["game_type"])
    if kind == "dice":
        await _start_dice(callback, db, game, players)
        return
    if kind == "crash":
        await _start_crash(callback, db, game, players)
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
    rolls: list[tuple[int, dict[str, object]]] = []
    lines = ["🎲 <b>Кубик</b> — каждый бросает 1d6.\n"]
    for player in players:
        roll = secrets.randbelow(6) + 1
        rolls.append((roll, player))
        lines.append(f"• {user_link(int(player['user_id']), _player_name(player))}: <b>{roll}</b>")
    best = max(item[0] for item in rolls)
    winners = [item[1] for item in rolls if item[0] == best]
    pot = stake * len(players)
    payouts: dict[int, int] = {}
    if len(winners) > 1:
        payouts = {int(player["user_id"]): stake for player in players}
        lines.append("\nНичья — ставки вернулись без комиссии.")
    else:
        winner = winners[0]
        stored = await db.get_user(int(winner["user_id"]))
        net, percent = win_after_commission(pot, int(stored["reputation"]) if stored else 0)
        payouts[int(winner["user_id"])] = net
        lines.append(
            f"\n🏆 Банк <b>{pot} 🍪</b> забирает {user_link(int(winner['user_id']), _player_name(winner))} "
            f"— <b>{net} 🍪</b> после комиссии {percent}%."
        )
    await db.save_party_state(int(game["id"]), {**game["state"], "phase": "done", "rolls": [item[0] for item in rolls]})
    await db.payout_staked_game(int(game["id"]), payouts)
    await callback.answer("Кубик брошен!")
    await callback.message.edit_reply_markup(reply_markup=None)
    await send_game_finale(callback.message, "\n".join(lines))
    expire_game_result(callback.message)
    await _alert(
        callback.message.bot,
        callback.message.chat.id,
        players,
        f"🎲 Кубик №{game['id']} сыгран.",
        f"🎲 Итог кубика №{game['id']}. Смотрите чат.",
    )


async def _crash_board(state: dict[str, object], players: list[dict[str, object]], crashed: bool = False) -> str:
    multiplier = float(state.get("multiplier") or 1)
    stake = int(state.get("stake") or 0)
    cashed = dict(state.get("cashed") or {})
    lines = [
        "🚀 <b>Рейс</b>",
        f"{'💥 Срыв' if crashed else 'В полёте'}: <b>×{multiplier:.2f}</b>",
        f"Ставка: {stake} 🍪",
        "",
    ]
    flying: list[str] = []
    for player in players:
        uid = int(player["user_id"])
        info = cashed.get(str(uid))
        name = user_link(uid, _player_name(player))
        if info:
            lines.append(
                f"• {name}: забрал ×{float(info['mult']):.2f} → <b>{int(info['net'])} 🍪</b> (−{int(info['percent'])}%)"
            )
        else:
            flying.append(name)
    if flying and not crashed:
        lines.append("Ещё в кабине: " + ", ".join(flying))
        lines.append("\nЖмите «Забрать», пока рейс не сорвался.")
    elif flying and crashed:
        lines.append("Не успели: " + ", ".join(flying))
    return "\n".join(lines)


async def _finish_crash(message: Message, db: Database, game_id: int, crash_at: float) -> None:
    game = await db.get_party_game(game_id)
    if not game or str(game["game_type"]) != "crash":
        return
    state = dict(game["state"])
    if state.get("phase") != "flight":
        return
    state["phase"] = "done"
    state["multiplier"] = crash_at
    state["crash_at"] = crash_at
    players = await db.list_game_players(game_id)
    cashed = dict(state.get("cashed") or {})
    payouts = {int(uid): int(info["net"]) for uid, info in cashed.items()}
    await db.save_party_state(game_id, state)
    await db.payout_staked_game(game_id, payouts)
    with suppress(TelegramBadRequest):
        await edit_block(
            message,
            await _crash_board(state, players, crashed=True),
            parse_mode="HTML",
            reply_markup=None,
        )
    await send_game_finale(
        message,
        f"💥 <b>Рейс сорвался на ×{crash_at:.2f}</b>\n"
        + ("Кто успел — забрал после комиссии. Кто нет — ставка сгорела."),
    )
    expire_game_result(message)
    await _alert(
        message.bot,
        message.chat.id,
        players,
        f"🚀 Рейс №{game_id} сорвался на ×{crash_at:.2f}.",
        f"🚀 Итог рейса №{game_id}. Смотрите выплату в чате.",
    )


async def _crash_loop(message: Message, db: Database, game_id: int, crash_at: float) -> None:
    try:
        multiplier = 1.00
        if crash_at <= 1.00:
            await asyncio.sleep(0.45)
            await _finish_crash(message, db, game_id, 1.00)
            return
        while True:
            await asyncio.sleep(0.75)
            game = await db.get_party_game(game_id)
            if not game or game["status"] != "active":
                return
            state = dict(game["state"])
            if state.get("phase") != "flight":
                return
            nxt = round(multiplier * 1.12, 2)
            if nxt >= crash_at:
                await _finish_crash(message, db, game_id, crash_at)
                return
            multiplier = nxt
            state["multiplier"] = multiplier
            await db.save_party_state(game_id, state)
            players = await db.list_game_players(game_id)
            with suppress(TelegramBadRequest):
                await edit_block(
                    message,
                    await _crash_board(state, players),
                    parse_mode="HTML",
                    reply_markup=crash_keyboard(game_id),
                )
    except asyncio.CancelledError:
        raise
    finally:
        _CRASH_JOBS.pop(game_id, None)


async def _start_crash(
    callback: CallbackQuery,
    db: Database,
    game: dict[str, object],
    players: list[dict[str, object]],
) -> None:
    assert callback.message
    crash_at = _crash_point()
    order = [int(player["user_id"]) for player in players]
    state = {
        **game["state"],
        "phase": "flight",
        "multiplier": 1.00,
        "crash_at": crash_at,
        "cashed": {},
        "order": order,
    }
    secrets_by_user = {user_id: {"stake": int(game["state"]["stake"])} for user_id in order}
    if not await db.start_party_game(int(game["id"]), int(game["creator_id"]), state, secrets_by_user):
        await callback.answer("Не удалось начать.", show_alert=True)
        return
    await callback.answer("Поехали!")
    await edit_block(
        callback.message,
        await _crash_board(state, players),
        parse_mode="HTML",
        reply_markup=crash_keyboard(int(game["id"])),
    )
    task = asyncio.create_task(_crash_loop(callback.message, db, int(game["id"]), crash_at))
    _CRASH_JOBS[int(game["id"])] = task
    await _alert(
        callback.message.bot,
        callback.message.chat.id,
        players,
        f"🚀 Рейс №{game['id']} взлетел. Забирайте, пока не сорвался.",
        f"🚀 Рейс №{game['id']} в воздухе. Жмите «Забрать» в чате.",
    )


@router.callback_query(F.data.startswith("cg:cash:"))
async def crash_cash(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    ok, text, info = await db.crash_cashout(game_id, callback.from_user.id)
    if not ok or not info:
        await callback.answer(text, show_alert=True)
        return
    await callback.answer(f"Забрали ×{float(info['mult']):.2f} → {int(info['net'])} 🍪")
    game = await db.get_party_game(game_id)
    players = await db.list_game_players(game_id)
    if not game:
        return
    with suppress(TelegramBadRequest):
        await edit_block(
            callback.message,
            await _crash_board(dict(game["state"]), players),
            parse_mode="HTML",
            reply_markup=crash_keyboard(game_id),
        )


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
    await edit_block(
        callback.message,
        _blackjack_board(state, players, hide_dealer=True),
        parse_mode="HTML",
        reply_markup=blackjack_turn_keyboard(int(game["id"])),
    )
    current = next(player for player in players if int(player["user_id"]) == order[0])
    await _alert(
        callback.message.bot,
        callback.message.chat.id,
        players,
        f"🃏 Блэкджек №{game['id']} начался. Первый ход: {_player_name(current)}.",
        f"🃏 Блэкджек №{game['id']} начался. Карты на столе в чате.",
    )
    await notify_game_event(
        callback.message.bot,
        callback.message.chat.id,
        [current],
        f"👉 {_player_name(current)}, ваш ход в блэкджеке.",
        "👉 Сейчас ваш ход в блэкджеке: взять карту или остановиться.",
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


async def _notify_blackjack_turn(
    bot: Bot,
    chat_id: int,
    state: dict[str, object],
    players: list[dict[str, object]],
    game_id: int,
) -> None:
    order = [int(item) for item in state["order"]]
    turn = int(state["turn"])
    if turn >= len(order):
        return
    current = next((player for player in players if int(player["user_id"]) == order[turn]), None)
    if not current:
        return
    await notify_game_event(
        bot,
        chat_id,
        [current],
        f"👉 {_player_name(current)}, ваш ход в блэкджеке №{game_id}.",
        "👉 Сейчас ваш ход в блэкджеке: взять карту или остановиться.",
    )


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
            gross = share + (remainder if index == 0 else 0)
            stored = await db.get_user(uid)
            net, percent = win_after_commission(gross, int(stored["reputation"]) if stored else 0)
            payouts[uid] = payouts.get(uid, 0) + net
            results.append(f"  ↳ выплата {net} 🍪 после комиссии {percent}%")
    elif not pushes:
        payouts = {int(user_id): stake for user_id in state["order"]}
        results.append("\nВсе проиграли дилеру — ставки возвращены, печеньки не сжигаем.")
    state["phase"] = "done"
    await db.save_party_state(game_id, state)
    await db.payout_staked_game(game_id, payouts)
    dealer_text = f"{_cards_text(dealer)} · <b>{dealer_value}</b>" + (" — перебор" if dealer_bust else "")
    with suppress(TelegramBadRequest):
        await message.edit_reply_markup(reply_markup=None)
    await send_game_finale(
        message,
        "🃏 <b>Итог блэкджека</b>\n"
        f"Дилер: {dealer_text}\n\n" + "\n".join(results),
    )
    expire_game_result(message)
    await _alert(
        message.bot,
        message.chat.id,
        players,
        f"🃏 Блэкджек №{game_id} завершён. Смотрите итог в чате.",
        f"🃏 Итог блэкджека №{game_id} готов. Загляните в чат за выплатой.",
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
        await _notify_blackjack_turn(callback.message.bot, callback.message.chat.id, state, players, game_id)
    else:
        await db.save_party_state(game_id, state)
        await callback.answer("Ещё карта.")
    await edit_block(
        callback.message,
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
    await edit_block(
        callback.message,
        _blackjack_board(state, players, hide_dealer=True),
        parse_mode="HTML",
        reply_markup=blackjack_turn_keyboard(game_id),
    )
    await _notify_blackjack_turn(callback.message.bot, callback.message.chat.id, state, players, game_id)
