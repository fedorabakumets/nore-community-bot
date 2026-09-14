from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters.command import CommandObject
from aiogram.types import CallbackQuery, Message
from aiogram.types.input_file import FSInputFile

from community_bot.aliases import command_or_alias
from community_bot.blocks import answer_block, cover_path, replace_block
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.ephemeral import expire_game_result, keep_in_chat
from community_bot.game_anim import decorate, start_lobby_anim, stop_lobby_anim
from community_bot.game_notify import mention_fragment, send_game_finale
from community_bot.helpers import has_permission, register_telegram_user, user_link
from community_bot.keyboards import (
    bunker_reveal_keyboard,
    mafia_target_keyboard,
    social_lobby_keyboard,
    social_vote_keyboard,
)
from community_bot.permissions import PERM_GAMES
from community_bot.social_data import (
    BUNKER_CAPACITY,
    BUNKER_MAX,
    BUNKER_MIN,
    MAFIA_MAX,
    MAFIA_MIN,
    REVEAL_LABELS,
    REVEAL_ORDER,
    ROLE_LABELS,
    deal_bunker_card,
    deal_mafia_roles,
    mafia_team,
    pick_catastrophe,
    pick_event,
)

router = Router(name="social_games")

SOCIAL = {
    "mafia": ("🕶", "Мафия", MAFIA_MIN, MAFIA_MAX, "mafia"),
    "bunker": ("🛡", "Бункер", BUNKER_MIN, BUNKER_MAX, "bunker"),
}
_PHASE_JOBS: dict[int, asyncio.Task[None]] = {}
NIGHT_SECONDS = 40.0
DAY_SECONDS = 35.0
VOTE_SECONDS = 35.0
REVEAL_SECONDS = 35.0


def _name(player: dict[str, object]) -> str:
    return str(player.get("profile_name") or player.get("telegram_name") or player.get("username") or player["user_id"])


def _link(player: dict[str, object]) -> str:
    return user_link(int(player["user_id"]), _name(player))


def _cancel_phase(game_id: int) -> None:
    task = _PHASE_JOBS.pop(game_id, None)
    current = asyncio.current_task()
    if task and not task.done() and task is not current:
        task.cancel()


def cancel_social_jobs(game_id: int) -> None:
    _cancel_phase(game_id)
    stop_lobby_anim(game_id)


def _lobby_body(game: dict[str, object], players: list[dict[str, object]]) -> str:
    kind = str(game["game_type"])
    emoji, title, minimum, maximum, _cover = SOCIAL[kind]
    names = "\n".join(f"• {_link(player)}" for player in players)
    extra = (
        "Роли придут в личку. В чате ночь, день и суд — картинками."
        if kind == "mafia"
        else "Катастрофа и досье — в личку. В чате погода, улица и собрания."
    )
    return (
        f"{emoji} <b>{title} · лобби №{game['id']}</b>\n"
        f"{extra}\n"
        f"Игроков: <b>{len(players)}/{maximum}</b> · нужно {minimum}–{maximum}\n{names}\n\n"
        "Создатель жмёт «Начать», когда все на месте."
    )


async def _publish_social_lobby(
    target: Message,
    db: Database,
    game: dict[str, object],
    players: list[dict[str, object]],
    *,
    new: bool,
) -> None:
    kind = str(game["game_type"])
    cover = SOCIAL[kind][4]
    text = decorate(_lobby_body(game, players), 0)
    markup = social_lobby_keyboard(int(game["id"]))
    if new:
        with keep_in_chat():
            sent = await answer_block(target, cover, text, parse_mode="HTML", reply_markup=markup)
        start_lobby_anim(
            sent,
            int(game["id"]),
            lambda frame, gid=int(game["id"]): _render_social(db, gid, frame),
            lambda gid=int(game["id"]): social_lobby_keyboard(gid),
        )
        return
    await replace_block(target, cover, text, parse_mode="HTML", reply_markup=markup)
    start_lobby_anim(
        target,
        int(game["id"]),
        lambda frame, gid=int(game["id"]): _render_social(db, gid, frame),
        lambda gid=int(game["id"]): social_lobby_keyboard(gid),
    )


async def _render_social(db: Database, game_id: int, frame: int) -> str:
    game = await db.get_party_game(game_id)
    if not game:
        return "Лобби закрыто."
    players = await db.list_game_players(game_id)
    return decorate(_lobby_body(game, players), frame)


async def _stage(
    message: Message,
    block: str,
    text: str,
    markup: object | None = None,
) -> Message:
    with keep_in_chat():
        sent = await answer_block(message, block, text, parse_mode="HTML", reply_markup=markup)
    return sent


async def _dm_role(bot: Bot, user_id: int, role: str, extra: str) -> bool:
    title, cover, hint = ROLE_LABELS[role]
    caption = f"🕶 <b>Ваша роль: {title}</b>\n{hint}\n{extra}"
    path = cover_path(cover)
    try:
        if path:
            await bot.send_photo(user_id, FSInputFile(path), caption=caption, parse_mode="HTML")
        else:
            await bot.send_message(user_id, caption, parse_mode="HTML")
        return True
    except (TelegramForbiddenError, TelegramBadRequest):
        return False


async def _dm_bunker(bot: Bot, user_id: int, card: dict[str, str], catastrophe: str) -> bool:
    lines = [
        f"🛡 <b>Досье бункера</b>\nКатастрофа: <b>{catastrophe}</b>",
        "",
        f"Профессия: {card['profession']}",
        f"Здоровье: {card['health']}",
        f"Хобби: {card['hobby']}",
        f"Багаж: {card['baggage']}",
        f"Факт: {card['fact']}",
        "",
        "Карты видите только вы. В чате будете открывать их по одной.",
    ]
    path = cover_path("bunker_card")
    try:
        if path:
            await bot.send_photo(user_id, FSInputFile(path), caption="\n".join(lines), parse_mode="HTML")
        else:
            await bot.send_message(user_id, "\n".join(lines), parse_mode="HTML")
        return True
    except (TelegramForbiddenError, TelegramBadRequest):
        return False


def _alive_players(players: list[dict[str, object]], alive: list[int]) -> list[dict[str, object]]:
    return [player for player in players if int(player["user_id"]) in alive]


@router.callback_query(F.data.startswith("sg:pick:"))
async def social_pick(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    kind = callback.data.rsplit(":", 1)[1]
    if kind not in SOCIAL:
        await callback.answer("Неизвестная игра.", show_alert=True)
        return
    if callback.message.chat.type not in {"group", "supergroup"}:
        await callback.answer("Мафия и бункер запускаются в чате сообщества.", show_alert=True)
        return
    if not await db.feature_enabled("games"):
        await callback.answer("Игры выключены.", show_alert=True)
        return
    await register_telegram_user(db, callback.from_user)
    game_id, created = await db.create_party_game(
        callback.message.chat.id,
        kind,
        callback.from_user.id,
        {"phase": "lobby"},
    )
    if not created:
        await callback.answer(f"Уже идёт партия №{game_id}.", show_alert=True)
        return
    game = await db.get_party_game(game_id)
    players = await db.list_game_players(game_id)
    assert game is not None
    await callback.answer("Лобби открыто.")
    await _publish_social_lobby(callback.message, db, game, players, new=True)


@router.message(command_or_alias("mafia", "bunker"))
async def social_command(message: Message, command: CommandObject, db: Database, settings: Settings) -> None:
    del settings
    if not message.from_user:
        return
    if not await db.feature_enabled("games"):
        await message.answer("Мини-игры временно выключены администрацией.")
        return
    kind = (command.command or "").casefold()
    if kind not in SOCIAL:
        return
    await register_telegram_user(db, message.from_user)
    game_id, created = await db.create_party_game(
        message.chat.id,
        kind,
        message.from_user.id,
        {"phase": "lobby"},
    )
    if not created:
        await message.answer(f"В чате уже идёт партия №{game_id}.")
        return
    game = await db.get_party_game(game_id)
    players = await db.list_game_players(game_id)
    assert game is not None
    await _publish_social_lobby(message, db, game, players, new=True)


@router.callback_query(F.data.startswith("sg:join:"))
async def social_join(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    game = await db.get_party_game(game_id)
    if not game or game["game_type"] not in SOCIAL:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    await register_telegram_user(db, callback.from_user)
    maximum = SOCIAL[str(game["game_type"])][3]
    ok, text = await db.join_party_game(game_id, callback.from_user.id, maximum)
    await callback.answer(text, show_alert=not ok)
    if not ok:
        return
    game = await db.get_party_game(game_id)
    players = await db.list_game_players(game_id)
    assert game is not None
    body = decorate(_lobby_body(game, players), 0)
    from community_bot.game_anim import edit_lobby_now

    await edit_lobby_now(callback.message, game_id, body, social_lobby_keyboard(game_id))


@router.callback_query(F.data.startswith("sg:cancel:"))
async def social_cancel(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    is_admin = await has_permission(db, settings, callback.from_user.id, PERM_GAMES)
    if not await db.cancel_party_game(game_id, callback.from_user.id, is_admin):
        await callback.answer("Отменить может создатель или администратор игр.", show_alert=True)
        return
    cancel_social_jobs(game_id)
    await callback.answer("Партия отменена.")
    await send_game_finale(callback.message, f"❌ Игра №{game_id} отменена.")
    expire_game_result(callback.message)


@router.callback_query(F.data.startswith("sg:start:"))
async def social_start(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    if not callback.data or not callback.message:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    game = await db.get_party_game(game_id)
    if not game or game["status"] != "lobby" or game["game_type"] not in SOCIAL:
        await callback.answer("Лобби уже закрыто.", show_alert=True)
        return
    if callback.from_user.id != int(game["creator_id"]):
        await callback.answer("Начать может только создатель.", show_alert=True)
        return
    players = await db.list_game_players(game_id)
    minimum, maximum = SOCIAL[str(game["game_type"])][2], SOCIAL[str(game["game_type"])][3]
    if not minimum <= len(players) <= maximum:
        await callback.answer(f"Нужно от {minimum} до {maximum} игроков.", show_alert=True)
        return
    kind = str(game["game_type"])
    stop_lobby_anim(game_id)
    if kind == "mafia":
        await _start_mafia(callback, db, bot, game, players)
        return
    await _start_bunker(callback, db, bot, game, players)


async def _ping_dm(
    message: Message,
    players: list[dict[str, object]],
    failed: list[int],
    what: str = "роль",
) -> None:
    mentions = ", ".join(mention_fragment(player) for player in players)
    extra = ""
    if failed:
        missing = ", ".join(
            mention_fragment(player) for player in players if int(player["user_id"]) in failed
        )
        extra = f"\nНе открылась личка: {missing}. Напишите боту /start и перезапустите партию."
    await message.answer(
        f"{mentions}\nПроверьте личные сообщения с ботом — туда ушла ваша {what}.{extra}",
        parse_mode="HTML",
    )


async def _start_mafia(
    callback: CallbackQuery,
    db: Database,
    bot: Bot,
    game: dict[str, object],
    players: list[dict[str, object]],
) -> None:
    assert callback.message
    order = [int(player["user_id"]) for player in players]
    roles = deal_mafia_roles(len(order))
    secrets_by_user = {uid: {"role": role} for uid, role in zip(order, roles, strict=True)}
    mafia_ids = [uid for uid, role in secrets_by_user.items() if mafia_team(str(role["role"]))]
    state = {
        "phase": "night",
        "round": 1,
        "alive": order,
        "roles": {str(uid): secrets_by_user[uid]["role"] for uid in order},
        "night": {},
        "grave": [],
    }
    if not await db.start_party_game(int(game["id"]), int(game["creator_id"]), state, secrets_by_user):
        await callback.answer("Не удалось начать.", show_alert=True)
        return
    await callback.answer("Город засыпает.")
    failed: list[int] = []
    mates = ", ".join(str(uid) for uid in mafia_ids)
    for player in players:
        uid = int(player["user_id"])
        role = secrets_by_user[uid]["role"]
        extra = ""
        if mafia_team(role) and len(mafia_ids) > 1:
            extra = f"Ваша команда: {len(mafia_ids)} чел. Код стола: {mates[-4:]}."
        if not await _dm_role(bot, uid, role, extra):
            failed.append(uid)
    await _ping_dm(callback.message, players, failed, "роль")
    await _mafia_night(callback.message, db, bot, int(game["id"]))


async def _mafia_night(message: Message, db: Database, bot: Bot, game_id: int) -> None:
    game = await db.get_party_game(game_id)
    if not game:
        return
    state = dict(game["state"])
    players = await db.list_game_players(game_id)
    alive = [int(item) for item in state["alive"]]
    state["phase"] = "night"
    state["night"] = {}
    await db.save_party_state(game_id, state)
    await _stage(
        message,
        "mafia_night",
        f"🌙 <b>Ночь {state['round']}</b>\nГород спит. Мафия, доктор и шериф действуют в личке.",
    )
    by_id = {int(player["user_id"]): player for player in players}
    living = _alive_players(players, alive)
    for uid in alive:
        role = str(state["roles"][str(uid)])
        if role in {"mafia", "don"}:
            targets = [player for player in living if int(player["user_id"]) != uid]
            with suppress(TelegramForbiddenError, TelegramBadRequest):
                await bot.send_message(
                    uid,
                    "Выберите жертву ночи.",
                    reply_markup=mafia_target_keyboard(game_id, "kill", targets),
                )
        elif role == "doctor":
            with suppress(TelegramForbiddenError, TelegramBadRequest):
                await bot.send_message(
                    uid,
                    "Кого лечить этой ночью?",
                    reply_markup=mafia_target_keyboard(game_id, "heal", living),
                )
        elif role == "sheriff":
            others = [player for player in living if int(player["user_id"]) != uid]
            with suppress(TelegramForbiddenError, TelegramBadRequest):
                await bot.send_message(
                    uid,
                    "Кого проверить?",
                    reply_markup=mafia_target_keyboard(game_id, "check", others),
                )
    del by_id
    _cancel_phase(game_id)
    _PHASE_JOBS[game_id] = asyncio.create_task(_wait_then(NIGHT_SECONDS, _mafia_dawn, message, db, bot, game_id))


async def _wait_then(delay: float, fn: Callable[..., Awaitable[None]], *args: object) -> None:
    game_id = int(args[-1])
    current = asyncio.current_task()
    try:
        await asyncio.sleep(delay)
        await fn(*args)
    except asyncio.CancelledError:
        raise
    finally:
        if _PHASE_JOBS.get(game_id) is current:
            _PHASE_JOBS.pop(game_id, None)


async def _mafia_dawn(message: Message, db: Database, bot: Bot, game_id: int) -> None:
    game = await db.get_party_game(game_id)
    if not game or str(game["game_type"]) != "mafia" or game["status"] != "active":
        return
    state = dict(game["state"])
    if str(state.get("phase")) != "night":
        return
    players = await db.list_game_players(game_id)
    by_id = {int(player["user_id"]): player for player in players}
    night = dict(state.get("night") or {})
    kill = int(night["kill"]) if night.get("kill") else 0
    heal = int(night["heal"]) if night.get("heal") else 0
    check = int(night["check"]) if night.get("check") else 0
    dead = 0
    if kill and kill != heal and kill in {int(item) for item in state["alive"]}:
        dead = kill
        state["alive"] = [int(item) for item in state["alive"] if int(item) != dead]
        grave = list(state.get("grave") or [])
        grave.append(dead)
        state["grave"] = grave
    if check:
        role = str(state["roles"].get(str(check)) or "civilian")
        team = "мафия" if mafia_team(role) else "мирный"
        sheriff_id = next(
            (int(uid) for uid, role_name in state["roles"].items() if role_name == "sheriff"),
            0,
        )
        if sheriff_id:
            with suppress(TelegramForbiddenError, TelegramBadRequest):
                name = _name(by_id[check]) if check in by_id else str(check)
                await bot.send_message(sheriff_id, f"Проверка: {name} — {team}.")
    state["phase"] = "day"
    await db.save_party_state(game_id, state)
    if dead:
        victim = by_id.get(dead)
        text = f"☀️ <b>Утро</b>\nНочь забрала { _link(victim) if victim else dead }."
    else:
        text = "☀️ <b>Утро</b>\nВсе дожили до рассвета."
    await _stage(message, "mafia_day", text)
    if _mafia_over(message, db, state, players):
        await _finish_mafia(message, db, game_id, state, players)
        return
    living = ", ".join(_link(player) for player in _alive_players(players, [int(i) for i in state["alive"]]))
    await message.answer(f"Город обсуждает. Живы: {living}", parse_mode="HTML")
    _PHASE_JOBS[game_id] = asyncio.create_task(_wait_then(DAY_SECONDS, _mafia_court, message, db, bot, game_id))


def _mafia_over(_message: Message, _db: Database, state: dict[str, object], _players: list[dict[str, object]]) -> bool:
    alive = [int(item) for item in list(state["alive"])]
    roles = dict(state["roles"])
    mafia_left = sum(1 for uid in alive if mafia_team(str(roles.get(str(uid)))))
    town_left = len(alive) - mafia_left
    return mafia_left == 0 or mafia_left >= town_left


async def _mafia_court(message: Message, db: Database, bot: Bot, game_id: int) -> None:
    del bot
    game = await db.get_party_game(game_id)
    if not game or game["status"] != "active":
        return
    state = dict(game["state"])
    if str(state.get("phase")) != "day":
        return
    players = await db.list_game_players(game_id)
    alive = [int(item) for item in state["alive"]]
    living = _alive_players(players, alive)
    state["phase"] = "vote"
    state["votes"] = {}
    await db.save_party_state(game_id, state)
    await _stage(
        message,
        "mafia_court",
        "⚖️ <b>Суд</b>\nГолосуйте, кого изгнать. Молчание — голос против казни.",
        social_vote_keyboard(game_id, living),
    )
    _PHASE_JOBS[game_id] = asyncio.create_task(_wait_then(VOTE_SECONDS, _mafia_lynch, message, db, game_id))


async def _mafia_lynch(message: Message, db: Database, game_id: int) -> None:
    game = await db.get_party_game(game_id)
    if not game or game["status"] != "active":
        return
    state = dict(game["state"])
    if str(state.get("phase")) != "vote":
        return
    players = await db.list_game_players(game_id)
    by_id = {int(player["user_id"]): player for player in players}
    votes = dict(state.get("votes") or {})
    counts: dict[int, int] = {}
    for target in votes.values():
        tid = int(target)
        counts[tid] = counts.get(tid, 0) + 1
    lynched = 0
    if counts:
        best = max(counts.values())
        champs = [uid for uid, count in counts.items() if count == best]
        if len(champs) == 1 and best > 0:
            lynched = champs[0]
    if lynched and lynched in {int(item) for item in state["alive"]}:
        state["alive"] = [int(item) for item in state["alive"] if int(item) != lynched]
        grave = list(state.get("grave") or [])
        grave.append(lynched)
        state["grave"] = grave
        victim = by_id.get(lynched)
        role = ROLE_LABELS.get(str(state["roles"].get(str(lynched))), ("?", "", ""))[0]
        await message.answer(
            f"⚖️ Казнён { _link(victim) if victim else lynched } · роль: <b>{role}</b>.",
            parse_mode="HTML",
        )
    else:
        await message.answer("⚖️ Город не сошёлся. Никого не казнили.")
    state["round"] = int(state.get("round") or 1) + 1
    await db.save_party_state(game_id, state)
    if _mafia_over(message, db, state, players):
        await _finish_mafia(message, db, game_id, state, players)
        return
    await _mafia_night(message, db, message.bot, game_id)


async def _finish_mafia(
    message: Message,
    db: Database,
    game_id: int,
    state: dict[str, object],
    players: list[dict[str, object]],
) -> None:
    _cancel_phase(game_id)
    alive = [int(item) for item in list(state["alive"])]
    roles = dict(state["roles"])
    mafia_left = sum(1 for uid in alive if mafia_team(str(roles.get(str(uid)))))
    winner = "мафия" if mafia_left else "мирные"
    lines = [f"🕶 <b>Мафия окончена</b> — победили {winner}."]
    for player in players:
        uid = int(player["user_id"])
        label = ROLE_LABELS.get(str(roles.get(str(uid))), ("?", "", ""))[0]
        mark = "✓" if uid in alive else "✕"
        lines.append(f"{mark} {_link(player)} — {label}")
    state["phase"] = "done"
    await db.save_party_state(game_id, state)
    await db.complete_party_game(game_id)
    await send_game_finale(message, "\n".join(lines))
    expire_game_result(message)
    from community_bot.notify import emit_many

    await emit_many(message.bot, db, [int(player["user_id"]) for player in players], "games", "🕶 Мафия окончена.")


@router.callback_query(F.data.startswith("maf:"))
async def mafia_private_action(callback: CallbackQuery, db: Database) -> None:
    if not callback.data:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    _, action, raw_game, raw_target = parts
    game_id = int(raw_game)
    target_id = int(raw_target)
    game = await db.get_party_game(game_id)
    if not game or str(game["game_type"]) != "mafia" or game["status"] != "active":
        await callback.answer("Ночь уже кончилась.", show_alert=True)
        return
    state = dict(game["state"])
    uid = callback.from_user.id
    role = str(state.get("roles", {}).get(str(uid)) or "")
    if str(state.get("phase")) != "night":
        await callback.answer("Сейчас не ночь.", show_alert=True)
        return
    if uid not in {int(item) for item in state.get("alive") or []}:
        await callback.answer("Вы уже выбыли.", show_alert=True)
        return
    if action == "kill" and not mafia_team(role):
        await callback.answer("Это ход мафии.", show_alert=True)
        return
    if action == "heal" and role != "doctor":
        await callback.answer("Это ход доктора.", show_alert=True)
        return
    if action == "check" and role != "sheriff":
        await callback.answer("Это ход шерифа.", show_alert=True)
        return
    await db.set_nested_state(game_id, ["night", action], target_id)
    await callback.answer("Принято.")
    if callback.message:
        with suppress(TelegramBadRequest):
            await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("sg:vote:"))
async def social_vote(callback: CallbackQuery, db: Database) -> None:
    if not callback.data:
        return
    _, _, raw_game, raw_target = callback.data.split(":")
    game_id = int(raw_game)
    target_id = int(raw_target)
    game = await db.get_party_game(game_id)
    if not game or game["status"] != "active":
        await callback.answer("Голосование закрыто.", show_alert=True)
        return
    state = dict(game["state"])
    uid = callback.from_user.id
    if str(state.get("phase")) not in {"vote", "bvote"}:
        await callback.answer("Сейчас нельзя голосовать.", show_alert=True)
        return
    if uid not in {int(item) for item in state.get("alive") or []}:
        await callback.answer("Вы уже выбыли.", show_alert=True)
        return
    if target_id not in {int(item) for item in state.get("alive") or []}:
        await callback.answer("Этого человека уже нет за столом.", show_alert=True)
        return
    await db.set_nested_state(game_id, ["votes", str(uid)], target_id)
    await callback.answer("Голос принят.")


async def _start_bunker(
    callback: CallbackQuery,
    db: Database,
    bot: Bot,
    game: dict[str, object],
    players: list[dict[str, object]],
) -> None:
    assert callback.message
    order = [int(player["user_id"]) for player in players]
    title, body = pick_catastrophe()
    cards = {uid: deal_bunker_card() for uid in order}
    secrets_by_user = {uid: {"card": cards[uid]} for uid in order}
    state = {
        "phase": "reveal",
        "round": 1,
        "alive": order,
        "cards": {str(uid): cards[uid] for uid in order},
        "revealed": {str(uid): [] for uid in order},
        "catastrophe": title,
        "cat_body": body,
        "picks": {},
    }
    if not await db.start_party_game(int(game["id"]), int(game["creator_id"]), state, secrets_by_user):
        await callback.answer("Не удалось начать.", show_alert=True)
        return
    await callback.answer("Люк закрывается.")
    failed: list[int] = []
    for player in players:
        uid = int(player["user_id"])
        if not await _dm_bunker(bot, uid, cards[uid], title):
            failed.append(uid)
    await _stage(
        callback.message,
        "bunker_weather",
        f"🛡 <b>{title}</b>\n{body}\nМест в бункере: <b>{BUNKER_CAPACITY}</b>.",
    )
    await _ping_dm(callback.message, players, failed, "карточка")
    await _bunker_reveal_round(callback.message, db, bot, int(game["id"]))


async def _bunker_reveal_round(message: Message, db: Database, bot: Bot, game_id: int) -> None:
    game = await db.get_party_game(game_id)
    if not game:
        return
    state = dict(game["state"])
    players = await db.list_game_players(game_id)
    alive = [int(item) for item in state["alive"]]
    event_key, cover, event_title, event_body = pick_event()
    del event_key
    state["phase"] = "reveal"
    state["picks"] = {}
    await db.save_party_state(game_id, state)
    await _stage(message, cover, f"🌩 <b>{event_title}</b>\n{event_body}")
    await _stage(
        message,
        "bunker_meeting",
        f"🛡 <b>Собрание · круг {state['round']}</b>\n"
        "В личке откройте одну закрытую карту. Потом город голосует, кого вывести.",
    )
    living = _alive_players(players, alive)
    for player in living:
        uid = int(player["user_id"])
        opened = set(state.get("revealed", {}).get(str(uid)) or [])
        left = [key for key in REVEAL_ORDER if key not in opened]
        with suppress(TelegramForbiddenError, TelegramBadRequest):
            await bot.send_message(
                uid,
                "Какую карту открыть этому кругу?",
                reply_markup=bunker_reveal_keyboard(game_id, left),
            )
    _cancel_phase(game_id)
    _PHASE_JOBS[game_id] = asyncio.create_task(
        _wait_then(REVEAL_SECONDS, _bunker_after_reveal, message, db, bot, game_id)
    )


async def _bunker_after_reveal(message: Message, db: Database, bot: Bot, game_id: int) -> None:
    game = await db.get_party_game(game_id)
    if not game or game["status"] != "active":
        return
    state = dict(game["state"])
    players = await db.list_game_players(game_id)
    picks = dict(state.get("picks") or {})
    revealed = {key: list(value) for key, value in dict(state.get("revealed") or {}).items()}
    cards = dict(state.get("cards") or {})
    lines = ["🛡 <b>Открытые карты</b>"]
    for player in _alive_players(players, [int(item) for item in state["alive"]]):
        uid = int(player["user_id"])
        key = str(picks.get(str(uid)) or "")
        if not key:
            closed = [item for item in REVEAL_ORDER if item not in revealed.get(str(uid), [])]
            key = closed[0] if closed else ""
        if key and key not in revealed.setdefault(str(uid), []):
            revealed[str(uid)].append(key)
        label = REVEAL_LABELS.get(key, key)
        value = dict(cards.get(str(uid)) or {}).get(key, "—")
        lines.append(f"• {_link(player)}: {label} — <b>{value}</b>")
    state["revealed"] = revealed
    state["phase"] = "bvote"
    state["votes"] = {}
    await db.save_party_state(game_id, state)
    living = _alive_players(players, [int(item) for item in state["alive"]])
    await _stage(message, "bunker_meeting", "\n".join(lines), social_vote_keyboard(game_id, living))
    _PHASE_JOBS[game_id] = asyncio.create_task(_wait_then(VOTE_SECONDS, _bunker_kick, message, db, bot, game_id))


async def _bunker_kick(message: Message, db: Database, bot: Bot, game_id: int) -> None:
    game = await db.get_party_game(game_id)
    if not game or game["status"] != "active":
        return
    state = dict(game["state"])
    players = await db.list_game_players(game_id)
    by_id = {int(player["user_id"]): player for player in players}
    votes = dict(state.get("votes") or {})
    counts: dict[int, int] = {}
    for target in votes.values():
        tid = int(target)
        counts[tid] = counts.get(tid, 0) + 1
    kicked = 0
    if counts:
        best = max(counts.values())
        champs = [uid for uid, count in counts.items() if count == best]
        if len(champs) == 1:
            kicked = champs[0]
        else:
            kicked = champs[0]
    if kicked and kicked in {int(item) for item in state["alive"]}:
        state["alive"] = [int(item) for item in state["alive"] if int(item) != kicked]
        victim = by_id.get(kicked)
        await message.answer(
            f"🚪 За люк уходит {_link(victim) if victim else kicked}.",
            parse_mode="HTML",
        )
    alive = [int(item) for item in state["alive"]]
    state["round"] = int(state.get("round") or 1) + 1
    await db.save_party_state(game_id, state)
    if len(alive) <= BUNKER_CAPACITY:
        await _finish_bunker(message, db, game_id, state, players)
        return
    await _bunker_reveal_round(message, db, bot, game_id)


async def _finish_bunker(
    message: Message,
    db: Database,
    game_id: int,
    state: dict[str, object],
    players: list[dict[str, object]],
) -> None:
    _cancel_phase(game_id)
    alive = [int(item) for item in list(state["alive"])]
    names = ", ".join(
        _link(player) for player in players if int(player["user_id"]) in alive
    )
    text = (
        f"🛡 <b>Бункер закрыт</b>\nКатастрофа: {state.get('catastrophe')}.\n"
        f"Внутри остаются: {names}."
    )
    state["phase"] = "done"
    await db.save_party_state(game_id, state)
    await db.complete_party_game(game_id)
    await send_game_finale(message, text)
    expire_game_result(message)
    from community_bot.notify import emit_many

    await emit_many(message.bot, db, [int(player["user_id"]) for player in players], "games", "🛡 Бункер закрыт.")


@router.callback_query(F.data.startswith("bk:open:"))
async def bunker_open_card(callback: CallbackQuery, db: Database) -> None:
    if not callback.data:
        return
    _, _, raw_game, key = callback.data.split(":")
    game_id = int(raw_game)
    game = await db.get_party_game(game_id)
    if not game or str(game["game_type"]) != "bunker" or game["status"] != "active":
        await callback.answer("Круг уже закрыт.", show_alert=True)
        return
    state = dict(game["state"])
    uid = callback.from_user.id
    if str(state.get("phase")) != "reveal":
        await callback.answer("Сейчас не время открывать карты.", show_alert=True)
        return
    if uid not in {int(item) for item in state.get("alive") or []}:
        await callback.answer("Вы уже за люком.", show_alert=True)
        return
    if key not in REVEAL_ORDER:
        await callback.answer("Нет такой карты.", show_alert=True)
        return
    opened = list(state.get("revealed", {}).get(str(uid)) or [])
    if key in opened:
        await callback.answer("Эта карта уже открыта.", show_alert=True)
        return
    await db.set_nested_state(game_id, ["picks", str(uid)], key)
    await callback.answer(f"Откроете: {REVEAL_LABELS[key]}.")
    if callback.message:
        with suppress(TelegramBadRequest):
            await callback.message.edit_reply_markup(reply_markup=None)
