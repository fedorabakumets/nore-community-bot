from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def main_private_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="📝 Заполнить анкету"), KeyboardButton(text="❓ Задать вопрос")],
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="🛒 Магазин")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="🛡 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


MAIN_PRIVATE_KEYBOARD = main_private_keyboard()

YES_NO_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="Да", callback_data="application:interview:yes"),
            InlineKeyboardButton(text="Нет", callback_data="application:interview:no"),
        ]
    ]
)


def application_review_keyboard(application_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"application:approve:{application_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"application:reject:{application_id}"),
            ]
        ]
    )


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Анкеты", callback_data="admin:applications"),
                InlineKeyboardButton(text="💳 Платежи", callback_data="admin:orders"),
            ],
            [
                InlineKeyboardButton(text="👥 Права", callback_data="admin:roles"),
                InlineKeyboardButton(text="👤 Профили и 🍪", callback_data="admin:users"),
            ],
            [InlineKeyboardButton(text="⏱ Автосообщения", callback_data="admin:auto:list")],
            [
                InlineKeyboardButton(text="🔇 Мут чата", callback_data="admin:chat:mute"),
                InlineKeyboardButton(text="🔊 Открыть чат", callback_data="admin:chat:unmute"),
            ],
            [
                InlineKeyboardButton(text="📣 Упомянуть всех", callback_data="admin:mention"),
                InlineKeyboardButton(text="💌 Рассылка в ЛС", callback_data="admin:broadcast"),
            ],
            [InlineKeyboardButton(text="📢 Сообщение в сообщество", callback_data="admin:post")],
            [
                InlineKeyboardButton(text="⚙️ Функции", callback_data="admin:features"),
                InlineKeyboardButton(text="📊 Состояние", callback_data="admin:health"),
            ],
            [
                InlineKeyboardButton(text="💤 Инактив", callback_data="admin:inactive"),
                InlineKeyboardButton(text="🧾 Журнал", callback_data="admin:audit"),
            ],
        ]
    )


def role_users_keyboard(users: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    icons = {"owner": "👑", "admin": "🛡", "moderator": "🔨", "member": "👤"}
    for user in users:
        role = str(user["role"])
        name = str(user.get("profile_name") or user.get("telegram_name") or user.get("username") or user["user_id"])
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{icons.get(role, '👤')} {name[:40]}",
                    callback_data=f"admin:user:{user['user_id']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="↩️ В панель", callback_data="admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def role_selection_keyboard(user_id: int, can_assign_admin: bool) -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(text="👤 Участник", callback_data=f"admin:setrole:{user_id}:member"),
        InlineKeyboardButton(text="🔨 Модератор", callback_data=f"admin:setrole:{user_id}:moderator"),
    ]
    rows = [row]
    if can_assign_admin:
        rows.append([InlineKeyboardButton(text="🛡 Админ", callback_data=f"admin:setrole:{user_id}:admin")])
    rows.append([InlineKeyboardButton(text="↩️ К пользователям", callback_data="admin:roles")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_users_keyboard(users: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for user in users:
        name = str(user.get("profile_name") or user.get("telegram_name") or user.get("username") or user["user_id"])
        rows.append(
            [InlineKeyboardButton(text=f"👤 {name[:42]}", callback_data=f"admin:manage:{user['user_id']}")]
        )
    rows.append([InlineKeyboardButton(text="↩️ В панель", callback_data="admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_user_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🍪 Установить баланс", callback_data=f"admin:edit:cookies:{user_id}"),
                InlineKeyboardButton(text="➕ Начислить 🍪", callback_data=f"admin:edit:add_cookies:{user_id}"),
            ],
            [
                InlineKeyboardButton(text="✏️ Имя", callback_data=f"admin:edit:name:{user_id}"),
                InlineKeyboardButton(text="🎂 Возраст", callback_data=f"admin:edit:age:{user_id}"),
            ],
            [
                InlineKeyboardButton(text="🖼 Аватар", callback_data=f"admin:edit:avatar:{user_id}"),
                InlineKeyboardButton(text="⚠️ Нарушения", callback_data=f"admin:edit:warnings:{user_id}"),
            ],
            [InlineKeyboardButton(text="↩️ К пользователям", callback_data="admin:users")],
        ]
    )


def automessage_target_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 В чат сообщества", callback_data="admin:auto:new:community")],
            [InlineKeyboardButton(text="💌 Всем в личку бота", callback_data="admin:auto:new:private_all")],
            [InlineKeyboardButton(text="↩️ Назад", callback_data="admin:auto:list")],
        ]
    )


def automessages_keyboard(rows: list[dict[str, object]]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="➕ Создать автосообщение", callback_data="admin:auto:new")]
    ]
    for row in rows[:20]:
        icon = "✅" if int(row["enabled"]) else "⏸"
        target = "чат" if row["target"] == "community" else "ЛС"
        schedule_id = int(row["id"])
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{icon} №{schedule_id} · {target} · {row['interval_minutes']} мин",
                    callback_data=f"admin:auto:toggle:{schedule_id}",
                ),
                InlineKeyboardButton(text="🗑", callback_data=f"admin:auto:delete:{schedule_id}"),
            ]
        )
    buttons.append([InlineKeyboardButton(text="↩️ В панель", callback_data="admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def ticket_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💬 Ответить", callback_data=f"ticket:reply:{ticket_id}"),
                InlineKeyboardButton(text="Закрыть", callback_data=f"ticket:close:{ticket_id}"),
            ]
        ]
    )


def profile_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Имя", callback_data=f"profile:name:{user_id}"),
                InlineKeyboardButton(text="Возраст", callback_data=f"profile:age:{user_id}"),
            ],
            [
                InlineKeyboardButton(text="Увлечения", callback_data=f"profile:hobbies:{user_id}"),
                InlineKeyboardButton(text="Аватар", callback_data=f"profile:avatar:{user_id}"),
            ],
        ]
    )


def public_profile_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👍 +реп", callback_data=f"profile_action:rep_up:{user_id}"),
                InlineKeyboardButton(text="👎 −реп", callback_data=f"profile_action:rep_down:{user_id}"),
            ],
            [
                InlineKeyboardButton(text="💌 Обнять", callback_data=f"profile_action:hug:{user_id}"),
                InlineKeyboardButton(text="🍪 Перевести", callback_data=f"profile_action:transfer:{user_id}"),
            ],
        ]
    )


def profile_transfer_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="5 🍪", callback_data=f"profile_transfer:{user_id}:5"),
                InlineKeyboardButton(text="10 🍪", callback_data=f"profile_transfer:{user_id}:10"),
                InlineKeyboardButton(text="25 🍪", callback_data=f"profile_transfer:{user_id}:25"),
            ],
            [
                InlineKeyboardButton(text="50 🍪", callback_data=f"profile_transfer:{user_id}:50"),
                InlineKeyboardButton(text="100 🍪", callback_data=f"profile_transfer:{user_id}:100"),
            ],
            [InlineKeyboardButton(text="↩️ Назад", callback_data=f"profile_action:back:{user_id}")],
        ]
    )


def shop_keyboard(prices: dict[str, int]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    labels = {
        "restore_rep": "Восстановить репутацию",
        "immunity": "Иммунитет на 24 часа",
        "event_pass": "Проходка на мероприятие",
        "custom_status": "Кастомный статус",
        "reset_limits": "Сброс лимитов",
        "forgive": "Прости меня…",
        "video_avatar": "Видео-аватар профиля",
        "tamagotchi": "Завести тамагочи",
        "pet_snack": "Перекус питомцу +10",
        "pet_meal": "Обед питомцу +35",
        "pet_feast": "Пир питомцу +70",
        "pet_water": "Вода питомцу +25",
        "pet_drink": "Большая поилка +70",
    }
    for key, label in labels.items():
        price = prices.get(key, 0)
        if price > 0:
            rows.append([InlineKeyboardButton(text=f"{label} — {price} 🍪", callback_data=f"shop:{key}")])
    rows.append([InlineKeyboardButton(text="🎟 Оплата мероприятия · 🍪", callback_data="shop:event_pass")])
    rows.append([InlineKeyboardButton(text="💚 Поддержать развитие · 🍪", callback_data="shop:support")])
    rows.append(
        [InlineKeyboardButton(text="🍪 Купить печеньки", callback_data="shop:buy_cookies", style="success")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cookie_packages_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="10 🍪 — 100 ₽", callback_data="cookies:sbp:10")],
            [InlineKeyboardButton(text="50 🍪 — 500 ₽", callback_data="cookies:sbp:50")],
            [InlineKeyboardButton(text="100 🍪 — 1 000 ₽", callback_data="cookies:sbp:100")],
        ]
    )


def sbp_payment_keyboard(payment_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💳 Оплатить через СБП", url=payment_url)]]
    )


def cookie_order_review_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"cookie_order:approve:{order_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"cookie_order:reject:{order_id}"),
            ]
        ]
    )


def roulette_invite_keyboard(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎯 Играть", callback_data=f"roulette:accept:{game_id}"),
                InlineKeyboardButton(text="Отказаться", callback_data=f"roulette:decline:{game_id}"),
            ]
        ]
    )


def freebie_keyboard(channel_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📣 Подписаться", url=channel_url)],
            [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="freebie:check")],
        ]
    )


def transfer_keyboard(transfer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"transfer:yes:{transfer_id}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"transfer:no:{transfer_id}"),
            ]
        ]
    )


def pet_species_keyboard(price: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🐈 Кот", callback_data=f"pet:species:cat:{price}"),
                InlineKeyboardButton(text="🐕 Пёс", callback_data=f"pet:species:dog:{price}"),
            ],
            [
                InlineKeyboardButton(text="🦝 Енот", callback_data=f"pet:species:raccoon:{price}"),
                InlineKeyboardButton(text="🦊 Лиса", callback_data=f"pet:species:fox:{price}"),
            ],
            [InlineKeyboardButton(text="🐉 Дракончик", callback_data=f"pet:species:dragon:{price}")],
        ]
    )


def pet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🍗 Накормить", callback_data="pet:use:food"),
                InlineKeyboardButton(text="💧 Напоить", callback_data="pet:use:water"),
            ],
            [InlineKeyboardButton(text="✏️ Переименовать", callback_data="pet:rename")],
            [InlineKeyboardButton(text="🛒 Магазин", callback_data="pet:shop")],
        ]
    )


FEATURE_LABELS = {
    "games": "Мини-игры",
    "tamagotchi": "Тамагочи",
    "profile_video": "Видео-профили",
    "activity_rewards": "Награды за активность",
    "anti_flood": "Антифлуд",
    "link_filter": "Фильтр ссылок",
    "media_filter": "Фильтр медиа",
    "quiet_hours": "Ночной режим 00–07",
    "raid_mode": "Рейд-режим",
}


def feature_flags_keyboard(flags: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for flag in flags:
        key = str(flag["key"])
        enabled = bool(int(flag["enabled"]))
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{'🟢' if enabled else '⚪'} {FEATURE_LABELS.get(key, key)}",
                    callback_data=f"admin:feature:{key}",
                    style="success" if enabled else "danger",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="↩️ В панель", callback_data="admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def games_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧳 Контрабанда", callback_data="game:new:smuggle")],
            [InlineKeyboardButton(text="🧩 Сбой протокола", callback_data="game:new:protocol")],
            [InlineKeyboardButton(text="☢️ Аукцион убежища", callback_data="game:new:bunker")],
            [InlineKeyboardButton(text="📚 Подробные правила", callback_data="game:rules:all")],
        ]
    )


def game_lobby_keyboard(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Войти в игру", callback_data=f"game:join:{game_id}", style="success")],
            [
                InlineKeyboardButton(text="▶️ Начать", callback_data=f"game:start:{game_id}", style="primary"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"game:cancel:{game_id}", style="danger"),
            ],
        ]
    )


def game_vote_keyboard(game_id: int, players: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for player in players:
        name = str(
            player.get("profile_name")
            or player.get("telegram_name")
            or player.get("username")
            or player["user_id"]
        )
        rows.append(
            [InlineKeyboardButton(text=f"🗳 {name[:38]}", callback_data=f"game:vote:{game_id}:{player['user_id']}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
