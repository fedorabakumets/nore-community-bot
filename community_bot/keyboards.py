from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from community_bot.permissions import PERMISSIONS, permission_label, role_has_permission
from community_bot.shop_catalog import GIFTABLE_ITEMS, ITEM_LABELS, SHOP_CATEGORIES

# Telegram: success=green, primary=blue, danger=red, omit=pastel/default.
STYLE_GO = "success"
STYLE_FUN = "primary"
STYLE_CLOSE = "danger"

FLOW_CANCEL = "❌ Отмена"
FLOW_RESTART = "🔄 Начать заново"
BTN_PROFILE = "👤 Профиль"
BTN_WALLET = "💼 Кошелёк"
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


def game_hide_button() -> InlineKeyboardButton:
    return ibtn("✖️ Скрыть", "g:hide", STYLE_CLOSE)


def game_hide_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[game_hide_button()]])


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
        keyboard=[[kbtn(BTN_PROFILE, STYLE_GO), kbtn(BTN_WALLET, STYLE_FUN), kbtn(BTN_MENU, STYLE_FUN)]],
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


def admin_panel_keyboard(
    permissions: list[str] | None = None,
    stats: dict[str, int] | None = None,
) -> InlineKeyboardMarkup:
    stats = stats or {}
    queue_n = (
        int(stats.get("pending_applications") or 0)
        + int(stats.get("pending_orders") or 0)
        + int(stats.get("pending_reports") or 0)
        + int(stats.get("pending_mail") or 0)
    )
    queue_label = f"📋 Очередь ({queue_n})" if queue_n else "📋 Очередь"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn(queue_label, "admin:queue", STYLE_GO), ibtn("👤 Люди", "admin:people", STYLE_FUN)],
            [ibtn("💬 Чат", "admin:chatroom"), ibtn("🛠 Система", "admin:system")],
            [close_btn("ui:close")],
        ]
    )


def _allow(perms: list[str], key: str) -> bool:
    return role_has_permission(perms, key)


def admin_queue_keyboard(permissions: list[str], stats: dict[str, int] | None = None) -> InlineKeyboardMarkup:
    stats = stats or {}
    rows: list[list[InlineKeyboardButton]] = []
    if _allow(permissions, "applications"):
        n = int(stats.get("pending_applications") or 0)
        rows.append([ibtn(f"📋 Анкеты ({n})" if n else "📋 Анкеты", "admin:applications")])
    if _allow(permissions, "payments"):
        n = int(stats.get("pending_orders") or 0)
        rows.append([ibtn(f"💳 Платежи ({n})" if n else "💳 Платежи", "admin:orders")])
    if _allow(permissions, "tickets") or _allow(permissions, "admin.panel"):
        n = int(stats.get("pending_reports") or 0)
        rows.append([ibtn(f"🚩 Репорты ({n})" if n else "🚩 Репорты", "admin:reports")])
        n = int(stats.get("pending_mail") or 0)
        rows.append([ibtn(f"✉️ Почта ({n})" if n else "✉️ Почта", "admin:mail")])
    rows.append([back_btn("admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_people_keyboard(permissions: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if _allow(permissions, "roles.assign") or _allow(permissions, "roles.edit"):
        rows.append([ibtn("👥 Права", "admin:roles")])
    if _allow(permissions, "users.edit") or _allow(permissions, "users.cookies"):
        rows.append([ibtn("👤 Профили и 🍪", "admin:users", STYLE_FUN)])
        rows.append([ibtn("🔎 Найти человека", "admin:search")])
    rows.append([ibtn("💤 Инактив", "admin:inactive")])
    rows.append([back_btn("admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_chat_keyboard(permissions: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if _allow(permissions, "chat.lock"):
        rows.append(
            [
                ibtn("🔇 Мут чата", "admin:chat:mute", STYLE_CLOSE),
                ibtn("🔊 Открыть чат", "admin:chat:unmute", STYLE_GO),
            ]
        )
    chat_row: list[InlineKeyboardButton] = []
    if _allow(permissions, "chat.mention"):
        chat_row.append(ibtn("📣 Упомянуть всех", "admin:mention"))
    if _allow(permissions, "chat.broadcast"):
        chat_row.append(ibtn("💌 Рассылка в ЛС", "admin:broadcast"))
    if chat_row:
        rows.append(chat_row)
    if _allow(permissions, "chat.post"):
        rows.append([ibtn("📢 Сообщение в сообщество", "admin:post")])
        rows.append([ibtn("🎲 Розыгрыш", "admin:lottery")])
    if _allow(permissions, "automessages"):
        rows.append([ibtn("⏱ Автосообщения", "admin:auto:list")])
    if _allow(permissions, "features"):
        rows.append([ibtn("⚙️ Функции", "admin:features")])
        rows.append([ibtn("🚫 Стоп-слова", "admin:stopwords")])
    rows.append([back_btn("admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_system_keyboard(permissions: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [ibtn("📊 Сводка дня", "admin:health")],
        [ibtn("✨ Обновления", "admin:updates", STYLE_FUN)],
        [ibtn("📚 Справка админки", "admin:staffguide", STYLE_GO)],
    ]
    if _allow(permissions, "audit"):
        rows.append([ibtn("🧾 Журнал", "admin:audit")])
    if _allow(permissions, "features") or _allow(permissions, "users.edit"):
        rows.append([ibtn("⭐ Витрина магазина", "admin:vitrine")])
        rows.append([ibtn("🎟 Название мероприятия", "admin:eventtitle")])
        rows.append([ibtn("🍪 Залог RSVP", "admin:rsvpstake")])
    rows.append([back_btn("admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_vitrine_keyboard() -> InlineKeyboardMarkup:
    from community_bot.shop_catalog import ITEM_LABELS, VITRINE_KEYS

    rows: list[list[InlineKeyboardButton]] = []
    for key in VITRINE_KEYS:
        rows.append([ibtn(str(ITEM_LABELS[key])[:42], f"admin:vitrine:{key}")])
    rows.append([ibtn("✖️ Убрать витрину", "admin:vitrine:off", STYLE_CLOSE)])
    rows.append([back_btn("admin:system")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_reports_keyboard(rows_data: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for row in rows_data:
        report_id = int(row["id"])
        rows.append(
            [
                ibtn(f"✅ #{report_id}", f"admin:report:ok:{report_id}", STYLE_GO),
                ibtn("❌", f"admin:report:no:{report_id}", STYLE_CLOSE),
            ]
        )
    rows.append([back_btn("admin:queue")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_mail_keyboard(rows_data: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for row in rows_data:
        mail_id = int(row["id"])
        rows.append(
            [
                ibtn(f"📢 #{mail_id}", f"admin:mail:ok:{mail_id}", STYLE_GO),
                ibtn("❌", f"admin:mail:no:{mail_id}", STYLE_CLOSE),
            ]
        )
    rows.append([back_btn("admin:queue")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_stopwords_keyboard(words: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [[ibtn("➕ Добавить слово", "admin:stopword:add", STYLE_GO)]]
    for row in words:
        word = str(row["word"])
        rows.append([ibtn(f"🗑 {word}", f"admin:stopword:del:{row['id']}", STYLE_CLOSE)])
    rows.append([back_btn("admin:chatroom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def role_users_keyboard(users: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    icons = {"owner": "👑", "admin": "🛡", "moderator": "🔨", "member": "👤"}
    for user in users:
        role = str(user["role"])
        name = str(user.get("profile_name") or user.get("telegram_name") or user.get("username") or user["user_id"])
        rows.append([ibtn(f"{icons.get(role, '👤')} {name[:40]}", f"admin:user:{user['user_id']}")])
    rows.append([back_btn("admin:roles")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def roles_hub_keyboard(can_edit_roles: bool) -> InlineKeyboardMarkup:
    rows = [
        [ibtn("👤 Назначить человеку", "admin:roleusers", STYLE_FUN)],
        [ibtn("📜 Список ролей", "admin:rolelist", STYLE_GO)],
    ]
    if can_edit_roles:
        rows.append([ibtn("➕ Создать роль", "admin:rolenew", STYLE_GO)])
    rows.append([back_btn("admin:people")])
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
    rows.append([back_btn("admin:people")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_user_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("🍪 Установить баланс", f"admin:edit:cookies:{user_id}"),
                ibtn("➕ Начислить 🍪", f"admin:edit:add_cookies:{user_id}", STYLE_GO),
            ],
            [
                ibtn("🏅 Репутация", f"admin:edit:rep:{user_id}"),
                ibtn("📝 Заметка", f"admin:edit:note:{user_id}"),
            ],
            [
                ibtn("✏️ Имя", f"admin:edit:name:{user_id}"),
                ibtn("🎂 Возраст", f"admin:edit:age:{user_id}"),
            ],
            [
                ibtn("🖼 Аватар", f"admin:edit:avatar:{user_id}"),
                ibtn("⚠️ Нарушения", f"admin:edit:warnings:{user_id}"),
            ],
            [ibtn("⭐ Титул недели", f"admin:weekstar:{user_id}", STYLE_FUN)],
            [back_btn("admin:people")],
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


def shop_home_keyboard(featured_key: str | None = None, featured_label: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if featured_key and featured_label:
        rows.append([ibtn(f"⭐ {featured_label}", f"shop:{featured_key}", STYLE_GO)])
    rows.extend(
        [
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
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
            row = [ibtn(f"{ITEM_LABELS[key]} — {price} 🍪", f"shop:{key}", style)]
            if key in GIFTABLE_ITEMS:
                row.append(ibtn("🎁", f"shop:g:{key}", STYLE_FUN))
            rows.append(row)
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
            ],
            [game_hide_button()],
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
            [ibtn("🌲 Экспедиция · 4 ч", "pet:expedition", STYLE_FUN)],
            [ibtn("✏️ Переименовать", "pet:rename"), ibtn("🛒 Магазин", "pet:shop", STYLE_GO)],
            [close_btn("ui:close")],
        ]
    )


FEATURE_META = {
    "games": (
        "🎮 Мини-игры",
        "Рулетка на мут, блэкджек, кубик и рейс. Выключение прячет игровые команды.",
    ),
    "tamagotchi": (
        "🐾 Тамагочи",
        "Питомцы, фарм печенек и магазин припасов. Не влияет на уже существующих питомцев в базе.",
    ),
    "profile_video": (
        "🎬 Видео-профили",
        "Разрешает видео-аватар в карточке. Если выключено, остаётся только фото.",
    ),
    "activity_rewards": (
        "🎁 Награды за активность",
        "За каждые 120 сообщений в чате владелец тамагочи тихо получает еду и воду — без лички.",
    ),
    "anti_flood": (
        "🛡 Антифлуд",
        "Больше 6 сообщений за 10 секунд — сообщение удаляется, "
        "участник получает мут на 5 минут. Не касается модераторов.",
    ),
    "link_filter": (
        "🔗 Фильтр ссылок",
        "Удаляет сообщения обычных участников со ссылками http/https/t.me. Модераторам можно.",
    ),
    "media_filter": (
        "🖼 Фильтр медиа",
        "Удаляет фото, видео, файлы, кружки, голосовые и GIF обычных участников. Стикеры этим флагом не трогает.",
    ),
    "sticker_filter": (
        "🎞 Фильтр стикеров",
        "Отдельно от медиа: удаляет только стикеры обычных участников. Выключите, если стикеры должны проходить.",
    ),
    "quiet_hours": (
        "🌙 Ночной режим 00–07",
        "С полуночи до семи по часовому поясу бота обычные участники не могут писать в чат.",
    ),
    "raid_mode": (
        "🚨 Рейд-режим",
        "Первые два сообщения новых участников удаляются, пока режим включён.",
    ),
    "word_filter": (
        "🚫 Стоп-слова",
        "Удаляет сообщения со словами из списка. Список правите в комнате «Чат».",
    ),
    "join_captcha": (
        "🤖 Капча на вход",
        "Новый человек должен нажать кнопку «Я человек», иначе писать нельзя.",
    ),
}

FEATURE_LABELS = {key: meta[0] for key, meta in FEATURE_META.items()}


def features_panel_text(flags: list[dict[str, object]]) -> str:
    enabled = {str(row["key"]): bool(int(row["enabled"])) for row in flags}
    lines = [
        "⚙️ <b>Функции и защита чата</b>",
        "",
        "🟢 включено · ⚪ выключено. Каждая кнопка — переключатель.",
        "«Сброс» возвращает заводские значения (игры и тамагочи включены, фильтры выключены).",
        "",
    ]
    for key, (title, description) in FEATURE_META.items():
        mark = "🟢" if enabled.get(key) else "⚪"
        lines.append(f"{mark} <b>{title}</b>")
        lines.append(description)
        lines.append("")
    extra = [str(row["key"]) for row in flags if str(row["key"]) not in FEATURE_META]
    for key in extra:
        mark = "🟢" if enabled.get(key) else "⚪"
        lines.append(f"{mark} <code>{key}</code>")
    return "\n".join(lines).strip()


def feature_flags_keyboard(flags: list[dict[str, object]]) -> InlineKeyboardMarkup:
    enabled = {str(row["key"]): bool(int(row["enabled"])) for row in flags}
    rows: list[list[InlineKeyboardButton]] = []
    keys = list(FEATURE_META) + [str(row["key"]) for row in flags if str(row["key"]) not in FEATURE_META]
    for key in keys:
        on = enabled.get(key, False)
        title = FEATURE_LABELS.get(key, key)
        rows.append(
            [
                ibtn(
                    f"{'🟢' if on else '⚪'} {title}",
                    f"admin:feature:{key}",
                    STYLE_GO if on else STYLE_CLOSE,
                )
            ]
        )
    rows.append([ibtn("♻️ Сброс до заводских", "admin:features:reset", STYLE_CLOSE)])
    rows.append([back_btn("admin:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def feature_reset_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("Да, сбросить всё", "admin:features:reset:yes", STYLE_CLOSE)],
            [ibtn("Не надо", "admin:features", STYLE_FUN)],
        ]
    )


def games_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("🔫 Рулетка · мут 30 мин", "game:pick:roulette", STYLE_CLOSE)],
            [
                ibtn("🃏 Блэкджек 🍪", "cg:pick:bj", STYLE_GO),
                ibtn("🎲 Кубик 🍪", "cg:pick:dice", STYLE_FUN),
            ],
            [ibtn("🚀 Рейс 🍪", "cg:pick:crash", STYLE_GO)],
            [ibtn("📚 Правила", "game:rules:all")],
            [game_hide_button()],
        ]
    )


COOKIE_STAKE_CHOICES = (5, 10, 25, 50, 100)


def cookie_stake_keyboard(game_type: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("5 🍪", f"cg:new:{game_type}:5", STYLE_FUN),
                ibtn("10 🍪", f"cg:new:{game_type}:10", STYLE_FUN),
                ibtn("25 🍪", f"cg:new:{game_type}:25", STYLE_GO),
            ],
            [
                ibtn("50 🍪", f"cg:new:{game_type}:50", STYLE_GO),
                ibtn("100 🍪", f"cg:new:{game_type}:100", STYLE_GO),
            ],
            [back_btn("cg:home"), game_hide_button()],
        ]
    )


def cookie_lobby_keyboard(game_id: int, current_stake: int = 10) -> InlineKeyboardMarkup:
    first = [
        ibtn(
            f"{'• ' if stake == current_stake else ''}{stake}",
            f"cg:stake:{game_id}:{stake}",
            STYLE_GO if stake == current_stake else STYLE_FUN,
        )
        for stake in COOKIE_STAKE_CHOICES[:3]
    ]
    second = [
        ibtn(
            f"{'• ' if stake == current_stake else ''}{stake}",
            f"cg:stake:{game_id}:{stake}",
            STYLE_GO if stake == current_stake else STYLE_FUN,
        )
        for stake in COOKIE_STAKE_CHOICES[3:]
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("➕ Войти (ставка спишется)", f"cg:join:{game_id}", STYLE_GO)],
            first,
            second,
            [
                ibtn("▶️ Начать", f"cg:start:{game_id}", STYLE_FUN),
                ibtn("❌ Отмена", f"cg:cancel:{game_id}", STYLE_CLOSE),
            ],
            [game_hide_button()],
        ]
    )


def blackjack_turn_keyboard(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("🃏 Взять", f"cg:hit:{game_id}", STYLE_FUN),
                ibtn("✋ Хватит", f"cg:stand:{game_id}", STYLE_GO),
            ],
            [game_hide_button()],
        ]
    )


def crash_keyboard(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("💰 Забрать", f"cg:cash:{game_id}", STYLE_GO)],
            [game_hide_button()],
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
            [game_hide_button()],
        ]
    )


def game_vote_keyboard(game_id: int, players: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for player in players:
        name = str(
            player.get("profile_name") or player.get("telegram_name") or player.get("username") or player["user_id"]
        )
        rows.append([ibtn(f"🗳 {name[:38]}", f"game:vote:{game_id}:{player['user_id']}", STYLE_FUN)])
    rows.append([game_hide_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wallet_keyboard(can_borrow: bool) -> InlineKeyboardMarkup:
    loan_label = "🍪 Взять 100 в долг" if can_borrow else "🍪 Кредит уже открыт"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                ibtn("📜 История", "wallet:history", STYLE_FUN),
                ibtn("🛒 Пополнить", "wallet:shop", STYLE_GO),
            ],
            [ibtn(loan_label, "wallet:loan", STYLE_GO if can_borrow else None)],
            [ibtn("❓ Помощь по кошельку", "wallet:help")],
            [close_btn("ui:close")],
        ]
    )


def wallet_loan_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ibtn("Да, взять 100 🍪", "wallet:loan:yes", STYLE_GO)],
            [ibtn("Не надо", "wallet:back", STYLE_CLOSE)],
        ]
    )
