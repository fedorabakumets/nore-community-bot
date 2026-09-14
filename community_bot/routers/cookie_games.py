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
from community_bot.cookie_logic import (
    DOOR_LABELS,
    RANKS,
    ROLE_LABELS,
    SUITS,
    TRAP_DOORS,
    TRAP_MAX_ROUNDS,
    apply_trap_round,
    deal_trap_doors,
    hand_value,
    settle_blackjack_pot,
    split_pot,
    trap_wait,
)
from community_bot.database import Database
from community_bot.ephemeral import expire_game_result, keep_in_chat
from community_bot.game_anim import decorate, edit_lobby_now, start_lobby_anim, stop_lobby_anim
from community_bot.game_notify import mention_fragment, send_game_finale
from community_bot.helpers import has_permission, register_telegram_user, user_link
from community_bot.keyboards import (
    COOKIE_STAKE_CHOICES,
    blackjack_turn_keyboard,
    cookie_lobby_keyboard,
    cookie_stake_keyboard,
    crash_keyboard,
    games_menu_keyboard,
    trap_keyboard,
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
    "trap": ("🪤", "Капкан", 2, 4),
}
COVER_BY_GAME = {"bj": "blackjack", "dice": "dice", "crash": "crash", "trap": "games"}
TURN_REMIND_AFTER = 45.0
_CRASH_JOBS: dict[int, asyncio.Task[None]] = {}
_TURN_JOBS: dict[int, asyncio.Task[None]] = {}
_TRAP_JOBS: dict[int, asyncio.Task[None]] = {}


def _hand_value(cards: list[str]) -> int:
    return hand_value(cards)


def _player_name(player: dict[str, object]) -> str:
    return str(player.get("profile_name") or player.get("telegram_name") or player.get("username") or player["user_id"])


def _card() -> str:
    return f"{secrets.choice(RANKS)}{secrets.choice(SUITS)}"


def _cards_text(cards: list[str]) -> str:
    return " ".join(cards)


def _cover(game_type: str) -> str:
    return COVER_BY_GAME.get(game_type, "games")


async def _emit_game(bot: Bot, db: Database, players: list[dict[str, object]], text: str) -> None:
    from community_bot.notify import emit_many

    await emit_many(bot, db, [int(player["user_id"]) for player in players], "games", text)


def _lobby_text(game: dict[str, object], players: list[dict[str, object]]) -> str:
    emoji, title, minimum, maximum = COOKIE_GAMES[str(game["game_type"])]
    stake = int((game.get("state") or {}).get("stake") or 0)
    names = "\n".join(f"• {user_link(int(player['user_id']), _player_name(player))}" for player in players)
    extra = ""
    if str(game["game_type"]) == "dice":
        extra = "Один кубик, большее число забирает весь банк.\n"
    elif str(game["game_type"]) == "crash":
        extra = "Множитель растёт. «Забрать» фиксирует выигрыш до срыва.\n"
    elif str(game["game_type"]) == "bj":
        extra = "Дилер Норы выбивает слабые руки. Сильнейший, кто обыграл дилера, забирает весь банк.\n"
    elif str(game["game_type"]) == "trap":
        extra = (
            "Три двери: капкан, проход и кладовая. 5 секунд на выбор. "
            "Последний живой забирает банк.\n"
        )
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


def _cancel_turn_job(game_id: int) -> None:
    task = _TURN_JOBS.pop(game_id, None)
    if task and not task.done():
        task.cancel()


def _cancel_trap_job(game_id: int) -> None:
    task = _TRAP_JOBS.pop(game_id, None)
    current = asyncio.current_task()
    if task and not task.done() and task is not current:
        task.cancel()


def _cancel_game_jobs(game_id: int) -> None:
    _cancel_crash_job(game_id)
    _cancel_turn_job(game_id)
    _cancel_trap_job(game_id)
    stop_lobby_anim(game_id)


async def _schedule_turn_reminder(
    bot: Bot,
    db: Database,
    chat_id: int,
    game_id: int,
    player: dict[str, object],
) -> None:
    user_id = int(player["user_id"])
    _cancel_turn_job(game_id)

    async def _wait() -> None:
        current = asyncio.current_task()
        try:
            await asyncio.sleep(TURN_REMIND_AFTER)
            game = await db.get_party_game(game_id)
            if not game or game["status"] != "active" or str(game["game_type"]) != "bj":
                return
            state = dict(game["state"])
            order = [int(item) for item in state["order"]]
            turn = int(state["turn"])
            if turn >= len(order) or order[turn] != user_id:
                return
            with keep_in_chat():
                with suppress(TelegramBadRequest):
                    await bot.send_message(
                        chat_id,
                        f"⏳ {mention_fragment(player)}, партия ждёт ваш ход в блэкджеке.\n"
                        "Возьмите карту или остановитесь на столе.",
                        parse_mode="HTML",
                    )
        except asyncio.CancelledError:
            raise
        finally:
            if _TURN_JOBS.get(game_id) is current:
                _TURN_JOBS.pop(game_id, None)

    _TURN_JOBS[game_id] = asyncio.create_task(_wait())


async def _render_cookie_lobby(db: Database, game_id: int, frame: int) -> str:
    game = await db.get_party_game(game_id)
    if not game:
        return "Лобби закрыто."
    players = await db.list_game_players(game_id)
    return decorate(_lobby_text(game, players), frame)


async def _publish_lobby(
    target: Message,
    game: dict[str, object],
    players: list[dict[str, object]],
    *,
    new: bool,
    db: Database | None = None,
) -> None:
    text = decorate(_lobby_text(game, players), 0)
    markup = _lobby_markup(game)
    if new:
        with keep_in_chat():
            sent = await answer_block(
                target,
                _cover(str(game["game_type"])),
                text,
                parse_mode="HTML",
                reply_markup=markup,
            )
        if db is not None:
            start_lobby_anim(
                sent,
                int(game["id"]),
                lambda frame, gid=int(game["id"]): _render_cookie_lobby(db, gid, frame),
                lambda g=game: _lobby_markup(g),
            )
        return
    await edit_lobby_now(target, int(game["id"]), text, markup)
    if db is not None:
        start_lobby_anim(
            target,
            int(game["id"]),
            lambda frame, gid=int(game["id"]): _render_cookie_lobby(db, gid, frame),
            lambda g=game: cookie_lobby_keyboard(int(g["id"]), int((g.get("state") or {}).get("stake") or 10)),
        )


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
    mapping = {"blackjack": "bj", "dice": "dice", "crash": "crash", "trap": "trap"}
    return mapping.get(raw)


@router.message(command_or_alias("cgames", "blackjack", "dice", "crash", "trap"))
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
        await message.answer("Ставка — целое число от 1 до 500 🍪. Пример: /blackjack 10 или «капкан 25»")
        return
    await register_telegram_user(db, message.from_user)
    game_id, status = await db.create_staked_game(message.chat.id, game_type, message.from_user.id, stake)
    if status != "ok" or game_id is None:
        await message.answer(status if game_id is None else f"{status} Уже идёт партия №{game_id}.")
        return
    game = await db.get_party_game(game_id)
    players = await db.list_game_players(game_id)
    assert game is not None
    await _publish_lobby(message, game, players, new=True, db=db)


@router.message(command_or_alias("gamecancel"))
async def cancel_active_game(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    game = await db.active_party_game(message.chat.id)
    if not game:
        await message.answer("Сейчас нет открытой партии на печеньки.")
        return
    is_admin = await _admin_cancel(db, settings, message.from_user.id)
    if not await db.cancel_party_game(int(game["id"]), message.from_user.id, is_admin):
        await message.answer("Отменить может создатель или администратор игр.")
        return
    _cancel_game_jobs(int(game["id"]))
    from community_bot.routers.social_games import cancel_social_jobs

    cancel_social_jobs(int(game["id"]))
    stake = int((game.get("state") or {}).get("stake") or 0)
    extra = ", 🍪 вернулись игрокам" if stake else ""
    await send_game_finale(message, f"❌ Игра №{game['id']} отменена{extra}.")


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
    await _publish_lobby(callback.message, game, players, new=True, db=db)


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
    await _publish_lobby(callback.message, game, players, new=False, db=db)


@router.callback_query(F.data.startswith("cg:stake:"))
async def cookie_change_stake(callback: CallbackQuery, db: Database) -> None:
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
    await _publish_lobby(callback.message, game, players, new=False, db=db)


@router.callback_query(F.data.startswith("cg:cancel:"))
async def cookie_cancel(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    is_admin = await _admin_cancel(db, settings, callback.from_user.id)
    if not await db.cancel_party_game(game_id, callback.from_user.id, is_admin):
        await callback.answer("Отменить может создатель или администратор игр.", show_alert=True)
        return
    _cancel_game_jobs(game_id)
    await callback.answer("Ставки возвращены.")
    await callback.message.edit_reply_markup(reply_markup=None)
    await send_game_finale(callback.message, f"❌ Игра №{game_id} отменена, 🍪 вернулись игрокам.")
    expire_game_result(callback.message)


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
    _cancel_game_jobs(game_id)
    kind = str(game["game_type"])
    if kind == "dice":
        await _start_dice(callback, db, game, players)
        return
    if kind == "crash":
        await _start_crash(callback, db, game, players)
        return
    if kind == "trap":
        await _start_trap(callback, db, game, players)
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
        lines.append("\nНичья — ставки вернулись.")
    else:
        winner = winners[0]
        payouts[int(winner["user_id"])] = pot
        lines.append(
            f"\n🏆 Банк <b>{pot} 🍪</b> забирает {user_link(int(winner['user_id']), _player_name(winner))}."
        )
    await db.save_party_state(int(game["id"]), {**game["state"], "phase": "done", "rolls": [item[0] for item in rolls]})
    await db.payout_staked_game(int(game["id"]), payouts)
    await callback.answer("Кубик брошен!")
    await callback.message.edit_reply_markup(reply_markup=None)
    await send_game_finale(callback.message, "\n".join(lines))
    expire_game_result(callback.message)
    await _emit_game(callback.message.bot, db, players, "🎲 Кубик · партия окончена.")


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
            lines.append(f"• {name}: забрал ×{float(info['mult']):.2f} → <b>{int(info['net'])} 🍪</b>")
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
        + ("Кто успел — забрал выигрыш. Кто нет — ставка сгорела."),
    )
    expire_game_result(message)
    await _emit_game(message.bot, db, players, "🚀 Рейс · партия окончена.")


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
    await _emit_game(callback.message.bot, db, players, "🚀 Рейс начался.")


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
    await _schedule_turn_reminder(callback.message.bot, db, callback.message.chat.id, int(game["id"]), current)
    await _emit_game(callback.message.bot, db, players, "🃏 Блэкджек начался.")
    from community_bot.notify import emit

    await emit(
        callback.message.bot,
        db,
        int(current["user_id"]),
        "games",
        "🃏 Блэкджек · ваш ход.",
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
    db: Database,
    chat_id: int,
    state: dict[str, object],
    players: list[dict[str, object]],
    game_id: int,
) -> None:
    order = [int(item) for item in state["order"]]
    turn = int(state["turn"])
    if turn >= len(order):
        _cancel_turn_job(game_id)
        return
    current = next((player for player in players if int(player["user_id"]) == order[turn]), None)
    if not current:
        _cancel_turn_job(game_id)
        return
    await _schedule_turn_reminder(bot, db, chat_id, game_id, current)
    from community_bot.notify import emit

    await emit(bot, db, int(current["user_id"]), "games", "🃏 Блэкджек · ваш ход.")


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
    order = [int(user_id) for user_id in state["order"]]
    hands = {uid: list(state["hands"][str(uid)]) for uid in order}
    payouts, tags, champs = settle_blackjack_pot(stake, order, hands, dealer)
    results: list[str] = []
    by_id = {int(player["user_id"]): player for player in players}
    for uid in order:
        value = _hand_value(hands[uid])
        name = user_link(uid, _player_name(by_id[uid]))
        tag = tags[uid]
        if tag == "champ":
            got = int(payouts.get(uid, 0))
            if len(champs) > 1:
                results.append(f"• {name}: {value} — делят банк, <b>{got} 🍪</b>")
            else:
                results.append(f"• {name}: {value} — сильнейшая рука, банк <b>{got} 🍪</b>")
        elif tag == "qualify":
            results.append(f"• {name}: {value} — обыграл дилера, но банк ушёл к более сильной руке")
        elif tag == "push":
            results.append(f"• {name}: {value} — ничья с дилером, ставка вернулась")
        elif tag == "bust":
            results.append(f"• {name}: перебор ({value}) — ставка в банке")
        else:
            results.append(f"• {name}: {value} — ниже дилера, ставка в банке")
    if not champs:
        results.append("\nНикто не обыграл дилера — банк без победителя, ставки вернулись.")
    elif len(champs) == 1:
        winner = by_id[champs[0]]
        results.append(
            f"\n🏆 {user_link(champs[0], _player_name(winner))} забирает банк "
            f"<b>{int(payouts[champs[0]])} 🍪</b>."
        )
    state["phase"] = "done"
    await db.save_party_state(game_id, state)
    await db.payout_staked_game(game_id, payouts)
    _cancel_turn_job(game_id)
    dealer_text = f"{_cards_text(dealer)} · <b>{dealer_value}</b>" + (" — перебор" if dealer_bust else "")
    with suppress(TelegramBadRequest):
        await message.edit_reply_markup(reply_markup=None)
    await send_game_finale(
        message,
        "🃏 <b>Итог блэкджека</b>\n"
        f"Дилер: {dealer_text}\n\n" + "\n".join(results),
    )
    expire_game_result(message)
    await _emit_game(message.bot, db, players, "🃏 Блэкджек · партия окончена.")


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
        await _notify_blackjack_turn(
            callback.message.bot, db, callback.message.chat.id, state, players, game_id
        )
    else:
        await db.save_party_state(game_id, state)
        await callback.answer("Ещё карта.")
        await _notify_blackjack_turn(
            callback.message.bot, db, callback.message.chat.id, state, players, game_id
        )
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
    await _notify_blackjack_turn(callback.message.bot, db, callback.message.chat.id, state, players, game_id)


def _trap_name(players: list[dict[str, object]], user_id: int) -> str:
    player = next((item for item in players if int(item["user_id"]) == user_id), None)
    if not player:
        return str(user_id)
    return user_link(user_id, _player_name(player))


def _arm_trap_round(
    state: dict[str, object],
    alive: list[int],
    shields: dict[int, int],
    *,
    bump: bool,
    log: str = "",
) -> dict[str, object]:
    round_no = int(state.get("round") or 0)
    if bump:
        round_no += 1
    round_no = max(1, round_no)
    return {
        **state,
        "phase": "pick",
        "round": round_no,
        "alive": alive,
        "shields": {str(uid): count for uid, count in shields.items() if count > 0},
        "picks": {},
        "doors": deal_trap_doors(),
        "wait": trap_wait(round_no),
        "log": log,
    }


def _trap_board(state: dict[str, object], players: list[dict[str, object]]) -> str:
    stake = int(state.get("stake") or 0)
    order = [int(item) for item in state.get("order") or []]
    pot = stake * len(order)
    alive = [int(item) for item in state.get("alive") or []]
    shields = {int(key): int(value) for key, value in dict(state.get("shields") or {}).items()}
    picks = dict(state.get("picks") or {})
    wait = float(state.get("wait") or 5)
    round_no = int(state.get("round") or 1)
    chosen = [uid for uid in alive if str(uid) in picks]
    pending = [uid for uid in alive if str(uid) not in picks]
    lines = [
        f"🪤 <b>Капкан · раунд {round_no}/{TRAP_MAX_ROUNDS}</b>",
        f"Банк: <b>{pot} 🍪</b> · {wait:g} сек на выбор",
        "",
    ]
    log = str(state.get("log") or "").strip()
    if log:
        lines.append(log)
        lines.append("")
    lines.append("В живых: " + ", ".join(_trap_name(players, uid) for uid in alive))
    if shields:
        held = [f"{_trap_name(players, uid)} ×{count}" for uid, count in shields.items() if uid in alive]
        if held:
            lines.append("Щит: " + ", ".join(held))
    if chosen:
        lines.append("Уже выбрали: " + ", ".join(_trap_name(players, uid) for uid in chosen))
    if pending:
        lines.append("Думают: " + ", ".join(_trap_name(players, uid) for uid in pending))
    lines.append("")
    lines.append("Три двери. Одна — капкан, одна — проход, одна — кладовая.")
    lines.append("Кладовая в одиночку даёт щит. Если вломятся двое — обвал, оба вылетают.")
    lines.append("Последний живой забирает весь банк.")
    return "\n".join(lines)


def _trap_round_log(
    doors: dict[str, str],
    picks: dict[str, str],
    result: dict[str, object],
    players: list[dict[str, object]],
) -> str:
    door_line = " · ".join(
        f"{DOOR_LABELS[door]} {ROLE_LABELS[doors[door]]}" for door in TRAP_DOORS if door in doors
    )
    bits: list[str] = [f"Прошлый раунд: {door_line}."]
    deaths = dict(result.get("deaths") or {})
    for uid, reason in deaths.items():
        name = _trap_name(players, int(uid))
        if reason == "greed":
            bits.append(f"{name} — обвал кладовой.")
        elif reason == "timeout":
            bits.append(f"{name} не успел.")
        else:
            door = picks.get(str(uid), "?")
            bits.append(f"{name} — капкан ({DOOR_LABELS.get(door, door)}).")
    for uid in list(result.get("saved") or []):
        bits.append(f"{_trap_name(players, int(uid))} спас щит.")
    stash_winner = result.get("stash_winner")
    if stash_winner:
        bits.append(f"{_trap_name(players, int(stash_winner))} забрал кладовую и щит.")
    if result.get("wipe"):
        bits.append("Все угодили в капкан — Нора даёт переигровку.")
    return " ".join(bits)


async def _finish_trap(
    message: Message,
    db: Database,
    game_id: int,
    state: dict[str, object],
    payouts: dict[int, int],
    finale: str,
) -> None:
    state = {**state, "phase": "done"}
    await db.save_party_state(game_id, state)
    await db.payout_staked_game(game_id, payouts)
    _cancel_trap_job(game_id)
    with suppress(TelegramBadRequest):
        await message.edit_reply_markup(reply_markup=None)
    await send_game_finale(message, finale)
    expire_game_result(message)
    players = await db.list_game_players(game_id)
    await _emit_game(message.bot, db, players, "🪤 Капкан · партия окончена.")


async def _resolve_trap_round(message: Message, db: Database, game_id: int) -> bool:
    snapshot = await db.trap_begin_resolve(game_id)
    if snapshot is None:
        return False
    state = dict(snapshot)
    alive = [int(item) for item in state.get("alive") or []]
    doors = dict(state.get("doors") or {})
    picks = dict(state.get("picks") or {})
    shields = dict(state.get("shields") or {})
    result = apply_trap_round(alive, picks, doors, shields)
    players = await db.list_game_players(game_id)
    stake = int(state.get("stake") or 0)
    order = [int(item) for item in state.get("order") or []]
    pot = stake * len(order)
    log = _trap_round_log(doors, picks, result, players)

    if result["wipe"]:
        shields_next = {int(key): int(value) for key, value in dict(result["shields"]).items()}
        round_no = int(state.get("round") or 1)
        if round_no >= TRAP_MAX_ROUNDS:
            payouts = split_pot(pot, alive)
            names = ", ".join(_trap_name(players, uid) for uid in alive)
            finale = (
                f"🪤 <b>Капкан</b>\n{log}\n\n"
                f"Двери так и не выбрали живого. {names} делят банк <b>{pot} 🍪</b>."
            )
            await _finish_trap(message, db, game_id, state, payouts, finale)
            return False
        next_state = _arm_trap_round(state, alive, shields_next, bump=True, log=log)
        await db.save_party_state(game_id, next_state)
        with suppress(TelegramBadRequest):
            await edit_block(
                message,
                _trap_board(next_state, players),
                parse_mode="HTML",
                reply_markup=trap_keyboard(game_id),
            )
        return True

    survivors = [int(item) for item in list(result["survivors"])]
    if len(survivors) == 1:
        winner = survivors[0]
        finale = (
            f"🪤 <b>Капкан</b>\n{log}\n\n"
            f"🏆 {_trap_name(players, winner)} остаётся последним и забирает банк <b>{pot} 🍪</b>."
        )
        await _finish_trap(message, db, game_id, state, {winner: pot}, finale)
        return False

    round_no = int(state.get("round") or 1)
    if round_no >= TRAP_MAX_ROUNDS or not survivors:
        payouts = split_pot(pot, survivors or alive)
        names = ", ".join(_trap_name(players, uid) for uid in (survivors or alive))
        finale = (
            f"🪤 <b>Капкан</b>\n{log}\n\n"
            f"Раунды кончились. {names} делят банк <b>{pot} 🍪</b>."
        )
        await _finish_trap(message, db, game_id, state, payouts, finale)
        return False

    next_state = _arm_trap_round(
        state,
        survivors,
        {int(key): int(value) for key, value in dict(result["shields"]).items()},
        bump=True,
        log=log,
    )
    await db.save_party_state(game_id, next_state)
    with suppress(TelegramBadRequest):
        await edit_block(
            message,
            _trap_board(next_state, players),
            parse_mode="HTML",
            reply_markup=trap_keyboard(game_id),
        )
    return True


async def _trap_loop(message: Message, db: Database, game_id: int) -> None:
    current = asyncio.current_task()
    try:
        while True:
            game = await db.get_party_game(game_id)
            if not game or game["status"] != "active" or str(game["game_type"]) != "trap":
                return
            state = dict(game["state"])
            if str(state.get("phase") or "") != "pick":
                return
            await asyncio.sleep(float(state.get("wait") or 5))
            keep_going = await _resolve_trap_round(message, db, game_id)
            if not keep_going:
                return
    except asyncio.CancelledError:
        raise
    finally:
        if _TRAP_JOBS.get(game_id) is current:
            _TRAP_JOBS.pop(game_id, None)


def _start_trap_loop(message: Message, db: Database, game_id: int) -> None:
    _cancel_trap_job(game_id)
    _TRAP_JOBS[game_id] = asyncio.create_task(_trap_loop(message, db, game_id))


async def _start_trap(
    callback: CallbackQuery,
    db: Database,
    game: dict[str, object],
    players: list[dict[str, object]],
) -> None:
    assert callback.message
    order = [int(player["user_id"]) for player in players]
    state = _arm_trap_round(
        {
            **game["state"],
            "order": order,
            "round": 0,
            "shields": {},
        },
        order,
        {},
        bump=True,
    )
    secrets_by_user = {user_id: {"stake": int(game["state"]["stake"])} for user_id in order}
    if not await db.start_party_game(int(game["id"]), int(game["creator_id"]), state, secrets_by_user):
        await callback.answer("Не удалось начать.", show_alert=True)
        return
    await callback.answer("Двери закрываются!")
    await edit_block(
        callback.message,
        _trap_board(state, players),
        parse_mode="HTML",
        reply_markup=trap_keyboard(int(game["id"])),
    )
    _start_trap_loop(callback.message, db, int(game["id"]))
    await _emit_game(callback.message.bot, db, players, "🪤 Капкан начался.")


@router.callback_query(F.data.startswith("cg:door:"))
async def trap_pick_door(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Нет такой двери.", show_alert=True)
        return
    game_id = int(parts[2])
    door = parts[3]
    ok, text = await db.trap_pick(game_id, callback.from_user.id, door)
    if not ok:
        await callback.answer(text, show_alert=True)
        return
    label = DOOR_LABELS.get(door, door)
    await callback.answer(f"Дверь {label}.")
    game = await db.get_party_game(game_id)
    if not game:
        return
    players = await db.list_game_players(game_id)
    state = dict(game["state"])
    alive = [int(item) for item in state.get("alive") or []]
    picks = dict(state.get("picks") or {})
    with suppress(TelegramBadRequest):
        await edit_block(
            callback.message,
            _trap_board(state, players),
            parse_mode="HTML",
            reply_markup=trap_keyboard(game_id),
        )
    if alive and all(str(uid) in picks for uid in alive):
        _cancel_trap_job(game_id)
        keep_going = await _resolve_trap_round(callback.message, db, game_id)
        if keep_going:
            _start_trap_loop(callback.message, db, game_id)

