from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from community_bot.permissions import PERMISSIONS, permission_label, role_has_permission
from community_bot.shop_catalog import ITEM_LABELS, SHOP_CATEGORIES

# Telegram: success=green, primary=blue, danger=red, omit=pastel/default.
STYLE_GO = "success"
STYLE_FUN = "primary"
STYLE_CLOSE = "danger"

FLOW_CANCEL = "❌ Отмена"
FLOW_RESTART = "🔄 Начать заново"
BTN_PROFILE = "👤 Профиль"
BTN_MENU = "📋 Меню"


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
    return main_private_keyboard()


def main_private_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    del is_admin
    return ReplyKeyboardMarkup(
        keyboard=[[kbtn(BTN_PROFILE, STYLE_GO), kbtn(BTN_MENU, STYLE_FUN)]],
        resize_keyboard=True,
        is_persistent=True,
    )


MAIN_PRIVATE_KEYBOARD = main_private_keyboard()


def private_menu_keyboard(show_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [ibtn("📝 Анкета", "menu:apply", STYLE_GO), ibtn("❓ Вопрос", "menu:question")],
        [ibtn("🛒 Магазин", "menu:shop", STYLE_FUN), ibtn("🐾 Тамагочи", "menu:pet", STYLE_FUN)],
    ]
    if show_admin:
        rows.append([ibtn("🛡 Админ-панель", "menu:admin")])
    rows.append([close_btn("ui:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def start_apply_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[ibtn("📝 Заполнить анкету", "start:apply", STYLE_GO)]])


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


def admin_panel_keyboard(permissions: list[str] | None = None) -> InlineKeyboardMarkup:
    perms = permissions if permissions is not None else ["*"]

    def allow(key: str) -> bool:
        return role_has_permission(perms, key)

    rows: list[list[InlineKeyboardButton]] = []
    first: list[InlineKeyboardButton] = []
    if allow("applications"):
        first.append(ibtn("📋 Анкеты", "admin:applications"))
    if allow("payments"):
        first.append(ibtn("💳 Платежи", "admin:orders"))
    if first:
        rows.append(first)
    second: list[InlineKeyboardButton] = []
    if allow("roles.assign") or allow("roles.edit"):
        second.append(ibtn("👥 Права", "admin:roles"))
    if allow("users.edit") or allow("users.cookies"):
        second.append(ibtn("👤 Профили и 🍪", "admin:users"))
    if second:
        rows.append(second)
    if allow("automessages"):
        rows.append([ibtn("⏱ Автосообщения", "admin:auto:list")])
    lock_row: list[InlineKeyboardButton] = []
    if allow("chat.lock"):
        lock_row.extend(
            [
                ibtn("🔇 Мут чата", "admin:chat:mute", STYLE_CLOSE),
                ibtn("🔊 Открыть чат", "admin:chat:unmute", STYLE_GO),
            ]
        )
    if lock_row:
        rows.append(lock_row)
    chat_row: list[InlineKeyboardButton] = []
    if allow("chat.mention"):
        chat_row.append(ibtn("📣 Упомянуть всех", "admin:mention"))
    if allow("chat.broadcast"):
        chat_row.append(ibtn("💌 Рассылка в ЛС", "admin:broadcast"))
    if chat_row:
        rows.append(chat_row)
    if allow("chat.post"):
        rows.append([ibtn("📢 Сообщение в сообщество", "admin:post")])
    extra: list[InlineKeyboardButton] = []
    if allow("features"):
        extra.append(ibtn("⚙️ Функции", "admin:features"))
    extra.append(ibtn("📊 Состояние", "admin:health"))
    extra.append(ibtn("✨ Обновления", "admin:updates", STYLE_FUN))
    rows.append(extra)
    bottom: list[InlineKeyboardButton] = [ibtn("💤 Инактив", "admin:inactive")]
    if allow("audit"):
        bottom.append(ibtn("🧾 Журнал", "admin:audit"))
    rows.append(bottom)
    rows.append([close_btn("ui:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def role_users_keyboard(users: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    icons = {"owner": "👑", "admin": "🛡", "moderator": "🔨", "member": "👤"}
    for user in users:
        role = str(user["role"])
        name = str(user.get("profile_name") or user.get("telegram_name") or user.get("username") or user["user_id"])
        rows.append([ibtn(f"{icons.get(role, '👤')} {name[:40]}", f"admin:user:{user['user_id']}")])
    rows.append([back_btn("admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def roles_hub_keyboard(can_edit_roles: bool) -> InlineKeyboardMarkup:
    rows = [
        [ibtn("👤 Назначить человеку", "admin:roleusers", STYLE_FUN)],
        [ibtn("📜 Список ролей", "admin:rolelist", STYLE_GO)],
    ]
    if can_edit_roles:
        rows.append([ibtn("➕ Создать роль", "admin:rolenew", STYLE_GO)])
    rows.append([back_btn("admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def staff_roles_keyboard(roles: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    icons = {"owner": "👑", "admin": "🛡", "moderator": "🔨", "member": "👤"}
    for role in roles:
        slug = str(role["slug"])
        icon = icons.get(slug, "💠")
        rows.append([ibtn(f"{icon} {role['name']} · {role['rank']}", f"admin:roleview:{slug}")])
    rows.append([back_btn("admin:roles")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def staff_role_view_keyboard(role: dict[str, object], can_edit: bool) -> InlineKeyboardMarkup:
    slug = str(role["slug"])
    perms = list(role.get("permissions") or [])
    rows: list[list[InlineKeyboardButton]] = []
    if can_edit and slug != "owner":
        for key, _label in PERMISSIONS:
            mark = "✅" if role_has_permission(perms, key) else "⚪"
            rows.append(
                [
                    ibtn(
                        f"{mark} {permission_label(key)}",
                        f"admin:roletog:{slug}:{key}",
                        STYLE_GO if role_has_permission(perms, key) else None,
                    )
                ]
            )
        rows.append(
            [
                ibtn("➖ Ранг", f"admin:rolerank:{slug}:-5"),
                ibtn("➕ Ранг", f"admin:rolerank:{slug}:+5", STYLE_FUN),
            ]
        )
        if not int(role.get("is_system") or 0):
            rows.append([ibtn("🗑 Удалить роль", f"admin:roledel:{slug}", STYLE_CLOSE)])
    rows.append([back_btn("admin:rolelist")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def role_selection_keyboard(
    user_id: int,
    roles: list[dict[str, object]],
    actor_rank: int,
    is_owner: bool,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    icons = {"owner": "👑", "admin": "🛡", "moderator": "🔨", "member": "👤"}
    for role in roles:
        slug = str(role["slug"])
        if slug == "owner":
            continue
        rank = int(role["rank"])
        if not is_owner and rank >= actor_rank:
            continue
        icon = icons.get(slug, "💠")
        rows.append([ibtn(f"{icon} {role['name']}", f"admin:setrole:{user_id}:{slug}")])
    rows.append([back_btn("admin:roleusers")])
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
    buttons: list[list[InlineKeyboardButton]] = [[ibtn("➕ Создать автосообщение", "admin:auto:new", STYLE_GO)]]
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


def profile_keyboard(user_id: int, is_private: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            ibtn("Имя", f"profile:name:{user_id}"),
            ibtn("Возраст", f"profile:age:{user_id}"),
        ],
        [
            ibtn("Увлечения", f"profile:hobbies:{user_id}"),
            ibtn("Аватар", f"profile:avatar:{user_id}"),
        ],
    ]
    if is_private:
        rows.append([ibtn("🌍 Сделать открытым", f"profile:public:{user_id}", STYLE_GO)])
    rows.append([close_btn("ui:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
            [
                ibtn("🃏 Блэкджек 🍪", "cg:pick:bj", STYLE_GO),
                ibtn("🎲 Кости 🍪", "cg:pick:dice", STYLE_FUN),
            ],
            [ibtn("📚 Подробные правила", "game:rules:all")],
            [close_btn("ui:close")],
        ]
    )


def cookie_stake_keyboard(game_type: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("5 🍪", f"cg:new:{game_type}:5", STYLE_FUN),
                ibtn("10 🍪", f"cg:new:{game_type}:10", STYLE_FUN),
                ibtn("25 🍪", f"cg:new:{game_type}:25", STYLE_GO),
            ],
            [ibtn("50 🍪", f"cg:new:{game_type}:50", STYLE_GO)],
            [back_btn("cg:home"), close_btn("ui:close")],
        ]
    )


def cookie_lobby_keyboard(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("➕ Войти (ставка спишется)", f"cg:join:{game_id}", STYLE_GO)],
            [
                ibtn("▶️ Начать", f"cg:start:{game_id}", STYLE_FUN),
                ibtn("❌ Отмена", f"cg:cancel:{game_id}", STYLE_CLOSE),
            ],
        ]
    )


def blackjack_turn_keyboard(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("🃏 Взять", f"cg:hit:{game_id}", STYLE_FUN),
                ibtn("✋ Хватит", f"cg:stand:{game_id}", STYLE_GO),
            ]
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
            player.get("profile_name") or player.get("telegram_name") or player.get("username") or player["user_id"]
        )
        rows.append([ibtn(f"🗳 {name[:38]}", f"game:vote:{game_id}:{player['user_id']}", STYLE_FUN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
