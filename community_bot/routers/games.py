from __future__ import annotations

import html
import secrets

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from community_bot.config import Settings
from community_bot.database import Database
from community_bot.helpers import has_permission, register_telegram_user, user_link
from community_bot.keyboards import game_lobby_keyboard, game_vote_keyboard, games_menu_keyboard
from community_bot.permissions import PERM_GAMES

router = Router(name="games")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))
router.callback_query.filter(F.message.chat.type.in_({"group", "supergroup"}))

GAME_META = {
    "smuggle": ("🧳", "Контрабанда", 3, 8),
    "protocol": ("🧩", "Сбой протокола", 4, 10),
    "bunker": ("☢️", "Аукцион убежища", 4, 10),
}

GAME_RULES = """🎮 <b>Игры NORA COMMUNITY</b>

🧳 <b>Контрабанда · 3–8 игроков</b>
Один игрок тайно становится контрабандистом. Остальные получают легальный груз.
Игроки описывают груз и задают вопросы, не показывая личную карточку.
Затем каждый голосует. Если контрабандиста нашли — побеждает группа, иначе он уходит с товаром.

🧩 <b>Сбой протокола · 4–10 игроков</b>
Большинство получает одно кодовое слово, а «сбой» — похожее, но другое.
Каждый пишет одну ассоциацию, не называя слово напрямую. После обсуждения проводится голосование.
Слишком точная подсказка может раскрыть код, слишком туманная — выдать сбой.

☢️ <b>Аукцион убежища · 4–10 игроков</b>
Каждому выдаются профессия, особенность и предмет. После катастрофы места хватает не всем.
Участники защищают пользу своей комбинации и голосуют, кого оставить снаружи.
Здесь нет заранее назначенного злодея — решает убедительность.

<b>Команды</b>
/games — выбрать игру и создать лобби.
/gamecancel — отменить текущую игру создателю или администратору.
Вход, старт и голосование выполняются кнопками. Секретные карточки приходят в личный чат,
поэтому каждый игрок должен заранее нажать Start у бота.

Игры не используют купленные печеньки и не влияют на основной баланс.

🍪 <b>Блэкджек и кости на печеньки · 2–4 игрока</b>
/cgames, /blackjack 10 или /dice 25. Ставка списывается при входе в лобби.
В блэкджеке сдаёт Нора, в костях банк забирает лучший 2d6. Отмена возвращает ставки."""


def _player_name(player: dict[str, object]) -> str:
    return str(player.get("profile_name") or player.get("telegram_name") or player.get("username") or player["user_id"])


def _lobby_text(game: dict[str, object], players: list[dict[str, object]]) -> str:
    emoji, title, minimum, maximum = GAME_META[str(game["game_type"])]
    names = "\n".join(
        f"• {user_link(int(player['user_id']), _player_name(player))}" for player in players
    )
    return (
        f"{emoji} <b>{title} · лобби №{game['id']}</b>\n\n"
        f"Игроков: <b>{len(players)}/{maximum}</b> · минимум {minimum}\n{names}\n\n"
        "Нажмите «Войти», затем создатель запускает игру. Секретная карточка придёт каждому в личку."
    )


def _secret_setup(
    game_type: str,
    players: list[dict[str, object]],
) -> tuple[dict[str, object], dict[int, dict[str, object]]]:
    user_ids = [int(player["user_id"]) for player in players]
    special_id = secrets.choice(user_ids)
    result: dict[int, dict[str, object]] = {}
    if game_type == "smuggle":
        cargos = ["старые виниловые пластинки", "кофейные зёрна", "детали радиоприёмника", "винтажные книги"]
        cargo = secrets.choice(cargos)
        for user_id in user_ids:
            result[user_id] = {
                "role": "smuggler" if user_id == special_id else "traveler",
                "cargo": "запрещённый прототип в двойном дне" if user_id == special_id else cargo,
            }
        return {"special_id": special_id, "cargo": cargo}, result
    if game_type == "protocol":
        word_pairs = [
            ("обсерватория", "маяк"),
            ("пустыня", "Марс"),
            ("метро", "бункер"),
            ("карнавал", "цирк"),
            ("архив", "библиотека"),
        ]
        common, glitch = secrets.choice(word_pairs)
        for user_id in user_ids:
            result[user_id] = {
                "role": "glitch" if user_id == special_id else "operator",
                "word": glitch if user_id == special_id else common,
            }
        return {"special_id": special_id, "common_word": common, "glitch_word": glitch}, result
    professions = ["врач", "инженер", "агроном", "психолог", "радиотехник", "повар", "геолог", "ветеринар"]
    traits = [
        "панически боится темноты",
        "знает три языка",
        "не умеет лгать",
        "спит по 3 часа",
        "отличная память",
        "конфликтный характер",
    ]
    items = ["семена редких растений", "аптечка", "сломанный дрон", "карта тоннелей", "генератор", "ящик консервов"]
    for user_id in user_ids:
        result[user_id] = {
            "profession": secrets.choice(professions),
            "trait": secrets.choice(traits),
            "item": secrets.choice(items),
        }
    return {"catastrophe": secrets.choice(["вечная зима", "солнечная буря", "токсичный туман"])}, result


def _secret_text(game_type: str, data: dict[str, object], state: dict[str, object]) -> str:
    if game_type == "smuggle":
        role = "КОНТРАБАНДИСТ" if data["role"] == "smuggler" else "ПУТЕШЕСТВЕННИК"
        return f"🧳 <b>Ваша карточка</b>\nРоль: <b>{role}</b>\nГруз: <b>{html.escape(str(data['cargo']))}</b>"
    if game_type == "protocol":
        role = "СБОЙ" if data["role"] == "glitch" else "ОПЕРАТОР"
        return f"🧩 <b>Ваша карточка</b>\nРоль: <b>{role}</b>\nКодовое слово: <b>{html.escape(str(data['word']))}</b>"
    return (
        "☢️ <b>Ваша карточка убежища</b>\n"
        f"Катастрофа: <b>{html.escape(str(state['catastrophe']))}</b>\n"
        f"Профессия: <b>{html.escape(str(data['profession']))}</b>\n"
        f"Особенность: <b>{html.escape(str(data['trait']))}</b>\n"
        f"Предмет: <b>{html.escape(str(data['item']))}</b>"
    )


@router.message(Command("games"))
async def games_menu(message: Message, db: Database) -> None:
    if not await db.feature_enabled("games"):
        await message.answer("Мини-игры временно выключены администрацией.")
        return
    await message.answer(
        "🎮 <b>Игровая</b>\n\nВыберите игру. Одновременно в чате может идти одна партия.",
        parse_mode="HTML",
        reply_markup=games_menu_keyboard(),
    )


@router.callback_query(F.data == "game:rules:all")
async def game_rules(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(GAME_RULES, parse_mode="HTML")


@router.callback_query(F.data.startswith("game:new:"))
async def create_game(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    if not await db.feature_enabled("games"):
        await callback.answer("Игры выключены администрацией.", show_alert=True)
        return
    game_type = callback.data.rsplit(":", 1)[1]
    if game_type not in GAME_META:
        await callback.answer("Неизвестная игра.", show_alert=True)
        return
    await register_telegram_user(db, callback.from_user)
    game_id, created = await db.create_party_game(callback.message.chat.id, game_type, callback.from_user.id)
    if not created:
        await callback.answer(f"В чате уже есть незавершённая игра №{game_id}.", show_alert=True)
        return
    game = await db.get_party_game(game_id)
    players = await db.list_game_players(game_id)
    assert game is not None
    await callback.answer("Лобби создано.")
    await callback.message.answer(
        _lobby_text(game, players),
        parse_mode="HTML",
        reply_markup=game_lobby_keyboard(game_id),
    )


@router.callback_query(F.data.startswith("game:join:"))
async def join_game(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    game = await db.get_party_game(game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return
    await register_telegram_user(db, callback.from_user)
    maximum = GAME_META[str(game["game_type"])][3]
    ok, message_text = await db.join_party_game(game_id, callback.from_user.id, maximum)
    await callback.answer(message_text, show_alert=not ok)
    players = await db.list_game_players(game_id)
    await callback.message.edit_text(
        _lobby_text(game, players),
        parse_mode="HTML",
        reply_markup=game_lobby_keyboard(game_id),
    )


@router.callback_query(F.data.startswith("game:start:"))
async def start_game(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    if not callback.data or not callback.message:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    game = await db.get_party_game(game_id)
    if not game or game["status"] != "lobby":
        await callback.answer("Лобби уже закрыто.", show_alert=True)
        return
    if callback.from_user.id != int(game["creator_id"]):
        await callback.answer("Начать игру может только создатель.", show_alert=True)
        return
    players = await db.list_game_players(game_id)
    minimum = GAME_META[str(game["game_type"])][2]
    if len(players) < minimum:
        await callback.answer(f"Нужно минимум {minimum} игроков.", show_alert=True)
        return
    unavailable: list[str] = []
    for player in players:
        try:
            await bot.send_chat_action(int(player["user_id"]), ChatAction.TYPING)
        except (TelegramBadRequest, TelegramForbiddenError):
            unavailable.append(_player_name(player))
    if unavailable:
        await callback.answer("Не всем можно отправить личную карточку.", show_alert=True)
        await callback.message.answer(
            "Этим игрокам нужно открыть бота и нажать Start: " + ", ".join(html.escape(name) for name in unavailable),
            parse_mode="HTML",
        )
        return
    state, secrets_by_user = _secret_setup(str(game["game_type"]), players)
    if not await db.start_party_game(game_id, callback.from_user.id, state, secrets_by_user):
        await callback.answer("Не удалось запустить игру.", show_alert=True)
        return
    for player in players:
        await bot.send_message(
            int(player["user_id"]),
            _secret_text(str(game["game_type"]), secrets_by_user[int(player["user_id"])], state),
            parse_mode="HTML",
        )
    emoji, title, _, _ = GAME_META[str(game["game_type"])]
    await callback.answer("Игра началась!")
    await callback.message.edit_text(
        f"{emoji} <b>{title} · партия №{game_id}</b>\n\n"
        "Карточки отправлены в личку. Обсудите их в чате, затем проголосуйте. "
        "Результат откроется, когда проголосуют все участники.",
        parse_mode="HTML",
        reply_markup=game_vote_keyboard(game_id, players),
    )


@router.callback_query(F.data.startswith("game:vote:"))
async def vote_game(callback: CallbackQuery, db: Database) -> None:
    if not callback.data or not callback.message:
        return
    _, _, raw_game_id, raw_target_id = callback.data.split(":")
    game_id = int(raw_game_id)
    target_id = int(raw_target_id)
    ok, response = await db.cast_party_vote(game_id, callback.from_user.id, target_id)
    await callback.answer(response, show_alert=not ok)
    if not ok:
        return
    result = await db.resolve_party_game(game_id)
    if not result:
        return
    game_type = str(result["game_type"])
    state = dict(result["state"])
    outcome = dict(result["outcome"])
    players = await db.list_game_players(game_id)
    selected = next(player for player in players if int(player["user_id"]) == int(outcome["selected_id"]))
    selected_link = user_link(int(selected["user_id"]), _player_name(selected))
    tie_text = " Судьба разрешила ничью случайным выбором." if outcome["tie"] else ""
    if game_type in {"smuggle", "protocol"}:
        special_id = int(state["special_id"])
        special = next(player for player in players if int(player["user_id"]) == special_id)
        caught = int(outcome["selected_id"]) == special_id
        role = "контрабандист" if game_type == "smuggle" else "сбой"
        text = (
            f"🏁 Голосование завершено. Выбор группы: {selected_link}.{tie_text}\n\n"
            f"Тайный {role}: {user_link(special_id, _player_name(special))}.\n"
            + ("✅ Группа раскрыла тайну!" if caught else "🕶 Тайный игрок обманул группу и победил!")
        )
    else:
        text = (
            f"☢️ Голосование завершено. Снаружи остаётся {selected_link}.{tie_text}\n\n"
            f"Катастрофа: <b>{html.escape(str(state['catastrophe']))}</b>. Остальные занимают места в убежище."
        )
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(text, parse_mode="HTML")


@router.message(Command("gamecancel"))
async def cancel_game_command(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    game = await db.active_party_game(message.chat.id)
    if not game:
        await message.answer("В этом чате нет активной игры.")
        return
    is_admin = await has_permission(db, settings, message.from_user.id, PERM_GAMES)
    if not await db.cancel_party_game(int(game["id"]), message.from_user.id, is_admin):
        await message.answer("Отменить игру может создатель или администратор.")
        return
    await message.answer(f"❌ Игра №{game['id']} отменена.")


@router.callback_query(F.data.startswith("game:cancel:"))
async def cancel_game_callback(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.data or not callback.message:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    is_admin = await has_permission(db, settings, callback.from_user.id, PERM_GAMES)
    if not await db.cancel_party_game(game_id, callback.from_user.id, is_admin):
        await callback.answer("Отменить игру может создатель или администратор.", show_alert=True)
        return
    await callback.answer("Игра отменена.")
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"❌ Игра №{game_id} отменена.")
