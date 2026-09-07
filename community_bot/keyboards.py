from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from community_bot.shop_catalog import ITEM_LABELS, SHOP_CATEGORIES

# Telegram: success=green, primary=blue, danger=red, omit=pastel/default.
STYLE_GO = "success"
STYLE_FUN = "primary"
STYLE_CLOSE = "danger"

FLOW_CANCEL = "❌ Отмена"
FLOW_RESTART = "🔄 Начать заново"


def ibtn(text: str, data: str, style: str | None = None) -> InlineKeyboardButton:
    if style:
        return InlineKeyboardButton(text=text, callback_data=data, style=style)
    return InlineKeyboardButton(text=text, callback_data=data)


def kbtn(text: str, style: str | None = None) -> KeyboardButton:
    if style:
        return KeyboardButton(text=text, style=style)
    return KeyboardButton(text=text)


def close_btn(data: str = "ui:close") -> InlineKeyboardButton:
    return ibtn("❌ Закрыть", data, STYLE_CLOSE)


def back_btn(data: str) -> InlineKeyboardButton:
    return ibtn("↩️ Назад", data)


def flow_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn(FLOW_RESTART, "flow:restart", STYLE_FUN),
                ibtn(FLOW_CANCEL, "flow:cancel", STYLE_CLOSE),
            ]
        ]
    )


def flow_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[kbtn(FLOW_RESTART, STYLE_FUN), kbtn(FLOW_CANCEL, STYLE_CLOSE)]],
        resize_keyboard=True,
        is_persistent=True,
    )


def main_private_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [kbtn("📝 Заполнить анкету", STYLE_GO), kbtn("❓ Задать вопрос")],
        [kbtn("👤 Мой профиль"), kbtn("🛒 Магазин", STYLE_FUN)],
        [kbtn("🐾 Тамагочи", STYLE_FUN)],
    ]
    if is_admin:
        rows.append([kbtn("🛡 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


MAIN_PRIVATE_KEYBOARD = main_private_keyboard()


def start_apply_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[ibtn("📝 Заполнить анкету", "start:apply", STYLE_GO)]]
    )


YES_NO_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            ibtn("Да", "application:interview:yes", STYLE_GO),
            ibtn("Нет", "application:interview:no", STYLE_CLOSE),
        ],
        [
            ibtn(FLOW_RESTART, "flow:restart", STYLE_FUN),
            ibtn(FLOW_CANCEL, "flow:cancel", STYLE_CLOSE),
        ],
    ]
)


def application_review_keyboard(application_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("✅ Одобрить", f"application:approve:{application_id}", STYLE_GO),
                ibtn("❌ Отклонить", f"application:reject:{application_id}", STYLE_CLOSE),
            ]
        ]
    )


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("📋 Анкеты", "admin:applications"), ibtn("💳 Платежи", "admin:orders")],
            [ibtn("👥 Права", "admin:roles"), ibtn("👤 Профили и 🍪", "admin:users")],
            [ibtn("⏱ Автосообщения", "admin:auto:list")],
            [
                ibtn("🔇 Мут чата", "admin:chat:mute", STYLE_CLOSE),
                ibtn("🔊 Открыть чат", "admin:chat:unmute", STYLE_GO),
            ],
            [ibtn("📣 Упомянуть всех", "admin:mention"), ibtn("💌 Рассылка в ЛС", "admin:broadcast")],
            [ibtn("📢 Сообщение в сообщество", "admin:post")],
            [ibtn("⚙️ Функции", "admin:features"), ibtn("📊 Состояние", "admin:health")],
            [ibtn("💤 Инактив", "admin:inactive"), ibtn("🧾 Журнал", "admin:audit")],
            [close_btn("ui:close")],
        ]
    )


def role_users_keyboard(users: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    icons = {"owner": "👑", "admin": "🛡", "moderator": "🔨", "member": "👤"}
    for user in users:
        role = str(user["role"])
        name = str(user.get("profile_name") or user.get("telegram_name") or user.get("username") or user["user_id"])
        rows.append([ibtn(f"{icons.get(role, '👤')} {name[:40]}", f"admin:user:{user['user_id']}")])
    rows.append([back_btn("admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def role_selection_keyboard(user_id: int, can_assign_admin: bool) -> InlineKeyboardMarkup:
    row = [
        ibtn("👤 Участник", f"admin:setrole:{user_id}:member"),
        ibtn("🔨 Модератор", f"admin:setrole:{user_id}:moderator"),
    ]
    rows = [row]
    if can_assign_admin:
        rows.append([ibtn("🛡 Админ", f"admin:setrole:{user_id}:admin", STYLE_FUN)])
    rows.append([back_btn("admin:roles")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_users_keyboard(users: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for user in users:
        name = str(user.get("profile_name") or user.get("telegram_name") or user.get("username") or user["user_id"])
        rows.append([ibtn(f"👤 {name[:42]}", f"admin:manage:{user['user_id']}")])
    rows.append([back_btn("admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_user_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("🍪 Установить баланс", f"admin:edit:cookies:{user_id}"),
                ibtn("➕ Начислить 🍪", f"admin:edit:add_cookies:{user_id}", STYLE_GO),
            ],
            [
                ibtn("✏️ Имя", f"admin:edit:name:{user_id}"),
                ibtn("🎂 Возраст", f"admin:edit:age:{user_id}"),
            ],
            [
                ibtn("🖼 Аватар", f"admin:edit:avatar:{user_id}"),
                ibtn("⚠️ Нарушения", f"admin:edit:warnings:{user_id}"),
            ],
            [back_btn("admin:users")],
        ]
    )


def automessage_target_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("📢 В чат сообщества", "admin:auto:new:community", STYLE_FUN)],
            [ibtn("💌 Всем в личку бота", "admin:auto:new:private_all", STYLE_FUN)],
            [back_btn("admin:auto:list")],
        ]
    )


def automessages_keyboard(rows: list[dict[str, object]]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = [
        [ibtn("➕ Создать автосообщение", "admin:auto:new", STYLE_GO)]
    ]
    for row in rows[:20]:
        icon = "✅" if int(row["enabled"]) else "⏸"
        target = "чат" if row["target"] == "community" else "ЛС"
        schedule_id = int(row["id"])
        buttons.append(
            [
                ibtn(
                    f"{icon} №{schedule_id} · {target} · {row['interval_minutes']} мин",
                    f"admin:auto:toggle:{schedule_id}",
                ),
                ibtn("🗑", f"admin:auto:delete:{schedule_id}", STYLE_CLOSE),
            ]
        )
    buttons.append([back_btn("admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def ticket_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("💬 Ответить", f"ticket:reply:{ticket_id}", STYLE_FUN),
                ibtn("Закрыть", f"ticket:close:{ticket_id}", STYLE_CLOSE),
            ]
        ]
    )


def profile_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("Имя", f"profile:name:{user_id}"),
                ibtn("Возраст", f"profile:age:{user_id}"),
            ],
            [
                ibtn("Увлечения", f"profile:hobbies:{user_id}"),
                ibtn("Аватар", f"profile:avatar:{user_id}"),
            ],
            [close_btn("ui:close")],
        ]
    )


def public_profile_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("👍 +реп", f"profile_action:rep_up:{user_id}", STYLE_GO),
                ibtn("👎 −реп", f"profile_action:rep_down:{user_id}", STYLE_CLOSE),
            ],
            [
                ibtn("💌 Обнять", f"profile_action:hug:{user_id}", STYLE_FUN),
                ibtn("🍪 Перевести", f"profile_action:transfer:{user_id}", STYLE_FUN),
            ],
        ]
    )


def profile_transfer_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("5 🍪", f"profile_transfer:{user_id}:5", STYLE_FUN),
                ibtn("10 🍪", f"profile_transfer:{user_id}:10", STYLE_FUN),
                ibtn("25 🍪", f"profile_transfer:{user_id}:25", STYLE_FUN),
            ],
            [
                ibtn("50 🍪", f"profile_transfer:{user_id}:50", STYLE_FUN),
                ibtn("100 🍪", f"profile_transfer:{user_id}:100", STYLE_GO),
            ],
            [ibtn("↩️ Назад", f"profile_action:back:{user_id}"), close_btn("ui:close")],
        ]
    )


def shop_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("🐾 Тамагочи", "shop:cat:pets", STYLE_GO),
                ibtn("🏅 Репутация", "shop:cat:reputation", STYLE_FUN),
            ],
            [
                ibtn("✨ Профиль", "shop:cat:profile"),
                ibtn("🎟 Мероприятия", "shop:cat:extra"),
            ],
            [ibtn("🍪 Купить печеньки", "shop:buy_cookies", STYLE_GO)],
            [close_btn("shop:close")],
        ]
    )


def shop_category_keyboard(category: str, prices: dict[str, int]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if category == "extra":
        rows.append([ibtn("🎟 Оплата мероприятия · 🍪", "shop:event_pass", STYLE_FUN)])
        rows.append([ibtn("💚 Поддержать развитие · 🍪", "shop:support", STYLE_GO)])
    else:
        meta = SHOP_CATEGORIES[category]
        style = STYLE_GO if category == "pets" else STYLE_FUN if category == "reputation" else None
        for key in meta["items"]:
            price = prices.get(key, 0)
            if price <= 0:
                continue
            rows.append([ibtn(f"{ITEM_LABELS[key]} — {price} 🍪", f"shop:{key}", style)])
    rows.append([back_btn("shop:home"), close_btn("shop:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shop_keyboard(prices: dict[str, int]) -> InlineKeyboardMarkup:
    del prices
    return shop_home_keyboard()


def cookie_packages_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("10 🍪 — 100 ₽", "cookies:sbp:10", STYLE_FUN)],
            [ibtn("50 🍪 — 500 ₽", "cookies:sbp:50", STYLE_FUN)],
            [ibtn("100 🍪 — 1 000 ₽", "cookies:sbp:100", STYLE_GO)],
            [back_btn("shop:home"), close_btn("shop:close")],
        ]
    )


def sbp_payment_keyboard(payment_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить через СБП", url=payment_url, style=STYLE_GO)],
            [ibtn(FLOW_CANCEL, "flow:cancel", STYLE_CLOSE)],
        ]
    )


def cookie_order_review_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("✅ Подтвердить", f"cookie_order:approve:{order_id}", STYLE_GO),
                ibtn("❌ Отклонить", f"cookie_order:reject:{order_id}", STYLE_CLOSE),
            ]
        ]
    )


def roulette_invite_keyboard(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("🎯 Играть", f"roulette:accept:{game_id}", STYLE_GO),
                ibtn("Отказаться", f"roulette:decline:{game_id}", STYLE_CLOSE),
            ]
        ]
    )


def freebie_keyboard(channel_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📣 Подписаться", url=channel_url, style=STYLE_FUN)],
            [ibtn("✅ Проверить подписку", "freebie:check", STYLE_GO)],
        ]
    )


def transfer_keyboard(transfer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("✅ Подтвердить", f"transfer:yes:{transfer_id}", STYLE_GO),
                ibtn("Отмена", f"transfer:no:{transfer_id}", STYLE_CLOSE),
            ]
        ]
    )


def pet_species_keyboard(price: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("🐈 Кот", f"pet:species:cat:{price}", STYLE_FUN),
                ibtn("🐕 Пёс", f"pet:species:dog:{price}", STYLE_FUN),
            ],
            [
                ibtn("🦝 Енот", f"pet:species:raccoon:{price}", STYLE_FUN),
                ibtn("🦊 Лиса", f"pet:species:fox:{price}", STYLE_FUN),
            ],
            [ibtn("🐉 Дракончик", f"pet:species:dragon:{price}", STYLE_GO)],
            [ibtn(FLOW_CANCEL, "flow:cancel", STYLE_CLOSE)],
        ]
    )


def pet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("🍗 Накормить", "pet:use:food", STYLE_GO),
                ibtn("💧 Напоить", "pet:use:water", STYLE_FUN),
            ],
            [ibtn("💬 Поговорить", "pet:talk", STYLE_FUN)],
            [ibtn("✏️ Переименовать", "pet:rename"), ibtn("🛒 Магазин", "pet:shop", STYLE_GO)],
            [close_btn("ui:close")],
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
                ibtn(
                    f"{'🟢' if enabled else '⚪'} {FEATURE_LABELS.get(key, key)}",
                    f"admin:feature:{key}",
                    STYLE_GO if enabled else STYLE_CLOSE,
                )
            ]
        )
    rows.append([back_btn("admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def games_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("🧳 Контрабанда", "game:new:smuggle", STYLE_FUN)],
            [ibtn("🧩 Сбой протокола", "game:new:protocol", STYLE_FUN)],
            [ibtn("☢️ Аукцион убежища", "game:new:bunker", STYLE_GO)],
            [ibtn("📚 Подробные правила", "game:rules:all")],
            [close_btn("ui:close")],
        ]
    )


def game_lobby_keyboard(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("➕ Войти в игру", f"game:join:{game_id}", STYLE_GO)],
            [
                ibtn("▶️ Начать", f"game:start:{game_id}", STYLE_FUN),
                ibtn("❌ Отмена", f"game:cancel:{game_id}", STYLE_CLOSE),
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
        rows.append([ibtn(f"🗳 {name[:38]}", f"game:vote:{game_id}:{player['user_id']}", STYLE_FUN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
