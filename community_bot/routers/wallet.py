from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, User

from community_bot.aliases import command_or_alias
from community_bot.blocks import answer_block, edit_block, replace_block
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.domain import reputation_tier, transfer_commission_percent
from community_bot.economy import (
    LOAN_DAYS,
    LOAN_PRINCIPAL,
    loan_interest_percent,
    loan_repay_amount,
    transaction_line,
    wallet_net,
)
from community_bot.helpers import register_telegram_user
from community_bot.keyboards import back_btn, close_btn, ibtn, wallet_keyboard, wallet_loan_confirm_keyboard
from community_bot.routers.group import _shop_home_markup, _shop_home_text
from community_bot.texts import WALLET_HELP_TEXT

router = Router(name="wallet")


def _due_label(due_at: str) -> str:
    try:
        due = datetime.fromisoformat(due_at)
        if due.tzinfo is None:
            due = due.replace(tzinfo=UTC)
        delta = due - datetime.now(UTC)
        hours = max(0, int(delta.total_seconds() // 3600))
        if hours >= 24:
            return f"{hours // 24} дн."
        return f"{hours} ч."
    except ValueError:
        return due_at[:16].replace("T", " ")


async def wallet_text(db: Database, settings: Settings, user: dict[str, object]) -> str:
    user_id = int(user["user_id"])
    tier = reputation_tier(int(user["reputation"]), settings.restricted_reputation_threshold)
    percent = transfer_commission_percent(int(user["reputation"]), settings.restricted_reputation_threshold)
    interest = loan_interest_percent(int(user["reputation"]), settings.restricted_reputation_threshold)
    repay = loan_repay_amount(LOAN_PRINCIPAL, interest)
    loan = await db.get_active_loan(user_id)
    debt = int(user.get("cookie_debt") or 0)
    cookies = int(user["cookies"])
    net = wallet_net(user)
    lines = [
        "💼 <b>Кошелёк</b>",
        "",
        f"Доступно: <b>{cookies} 🍪</b>",
        f"{tier.emoji} {tier.label} · комиссия переводов <b>{percent}%</b>",
    ]
    if debt:
        lines.extend([
            "", f"💳 Просроченный долг: <b>{debt} 🍪</b>",
            f"С учётом этого долга: {net} 🍪.",
            "Погашение — кнопкой ниже, после подтверждения суммы.",
        ])
    if loan:
        due = datetime.fromisoformat(str(loan["due_at"])).astimezone(ZoneInfo(settings.timezone))
        lines.extend([
            "", f"Открыт кредит: к возврату <b>{loan['due_amount']} 🍪</b>",
            f"До {due:%d.%m, %H:%M} · осталось {_due_label(str(loan['due_at']))}.",
        ])
    elif not debt:
        lines.extend([
            "", f"Можно взять {LOAN_PRINCIPAL} 🍪 на {LOAN_DAYS} дней.",
            f"Ставка {interest}% · вернуть {repay} 🍪.",
        ])
    return "\n".join(lines)


async def send_wallet(
    message: Message, db: Database, settings: Settings, *, actor: User | None = None, replace: bool = False,
) -> None:
    actor = actor or message.from_user
    if not actor or actor.is_bot:
        return
    user = await register_telegram_user(db, actor)
    loan = await db.get_active_loan(actor.id)
    can_borrow = loan is None and int(user.get("cookie_debt") or 0) == 0
    text = await wallet_text(db, settings, user)
    markup = wallet_keyboard(can_borrow, has_debt=bool(user.get("cookie_debt")))
    if replace:
        await replace_block(message, "wallet", text, parse_mode="HTML", reply_markup=markup)
        return
    from community_bot.ui_owner import bind_ui_owner

    sent = await answer_block(message, "wallet", text, parse_mode="HTML", reply_markup=markup)
    await bind_ui_owner(db, sent, actor.id, "wallet")


@router.message(command_or_alias("balance"))
async def balance_command(message: Message, db: Database, settings: Settings) -> None:
    await send_wallet(message, db, settings)


@router.callback_query(F.data == "wallet:back")
@router.callback_query(F.data == "wallet:home")
async def wallet_home(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message:
        return
    await callback.answer()
    await send_wallet(callback.message, db, settings, actor=callback.from_user, replace=True)


@router.callback_query(F.data == "wallet:history")
@router.callback_query(F.data.startswith("wallet:history:"))
async def wallet_history(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message:
        return
    raw_offset = (callback.data or "").removeprefix("wallet:history:")
    offset = int(raw_offset) if raw_offset.isdigit() else 0
    rows = await db.list_transactions(callback.from_user.id, 6, offset=offset)
    page = rows[:5]
    await callback.answer()
    if not rows:
        text = "📜 Пока нет движений по кошельку."
    else:
        text = "📜 <b>История операций</b>\n\n" + "\n\n".join(
            transaction_line(row, settings.timezone) for row in page
        )
    nav = []
    if offset:
        nav.append(ibtn("← Новее", f"wallet:history:{max(0, offset - 5)}"))
    if len(rows) > 5:
        nav.append(ibtn("Старее →", f"wallet:history:{offset + 5}"))
    await edit_block(
        callback.message,
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=([nav] if nav else []) + [[back_btn("wallet:home"), close_btn("ui:close")]],
        ),
    )


@router.callback_query(F.data == "wallet:shop")
async def wallet_shop(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message:
        return
    from community_bot.blocks import replace_block

    user = await register_telegram_user(db, callback.from_user)
    await callback.answer()
    await replace_block(
        callback.message,
        "shop",
        await _shop_home_text(db, user, settings),
        parse_mode="HTML",
        reply_markup=await _shop_home_markup(db),
    )


@router.callback_query(F.data == "wallet:help")
async def wallet_help(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await edit_block(
            callback.message,
            WALLET_HELP_TEXT,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_btn("wallet:home"), close_btn("ui:close")]]),
        )


@router.callback_query(F.data == "wallet:send")
async def wallet_send_hint(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await edit_block(
            callback.message,
            "💸 <b>Перевод</b>\nВ личке цели нет. В чате ответом на человека: "
            "<code>перевести 10</code> или <code>перевести 1 печеньку</code>.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_btn("wallet:home"), close_btn("ui:close")]]),
        )


@router.callback_query(F.data == "wallet:loan")
async def wallet_loan_ask(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    user = await register_telegram_user(db, callback.from_user)
    loan = await db.get_active_loan(callback.from_user.id)
    if loan or int(user.get("cookie_debt") or 0) > 0:
        await callback.answer("Сначала закройте текущий кредит или долг.", show_alert=True)
        return
    interest = loan_interest_percent(int(user["reputation"]), settings.restricted_reputation_threshold)
    repay = loan_repay_amount(LOAN_PRINCIPAL, interest)
    token = await db.create_wallet_intent(
        callback.from_user.id, "loan", LOAN_PRINCIPAL, payload={"interest_percent": interest},
    )
    await callback.answer()
    if callback.message:
        await edit_block(
            callback.message,
            f"💳 Взять <b>{LOAN_PRINCIPAL} 🍪</b> в долг?\n"
            f"Ставка <b>{interest}%</b> по вашему уровню. Через {LOAN_DAYS} дней спишется "
            f"<b>{repay} 🍪</b> (недостающее уйдёт в минус кошелька).",
            parse_mode="HTML",
            reply_markup=wallet_loan_confirm_keyboard(token),
        )


@router.callback_query(F.data == "wallet:loan:yes")
@router.callback_query(F.data.startswith("wallet:loan:yes:"))
async def wallet_loan_yes(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message:
        return
    token = (callback.data or "").removeprefix("wallet:loan:yes:")
    intent = await db.get_wallet_intent(callback.from_user.id, token)
    if not intent or intent["item"] != "loan":
        await callback.answer("Подтверждение устарело или уже выполнено. Откройте кошелёк.", show_alert=True)
        return
    user = await db.get_user(callback.from_user.id)
    interest = loan_interest_percent(int(user["reputation"]), settings.restricted_reputation_threshold)
    if interest != intent["payload"].get("interest_percent"):
        await callback.answer("Ставка изменилась. Откройте кредит и подтвердите условия заново.", show_alert=True)
        return
    ok, error, loan = await db.take_cookie_loan(
        callback.from_user.id,
        settings.restricted_reputation_threshold,
        intent_id=token,
    )
    if not ok or not loan:
        await callback.answer(error, show_alert=True)
        return
    user = await db.get_user(callback.from_user.id)
    assert user is not None
    await callback.answer("Кредит зачислен.")
    await edit_block(
        callback.message,
        f"✅ На кошелёк пришло {loan['principal']} 🍪.\n"
        f"Вернуть {loan['due_amount']} 🍪 до {str(loan['due_at'])[:16].replace('T', ' ')} UTC.\n\n"
        + await wallet_text(db, settings, user),
        parse_mode="HTML",
        reply_markup=wallet_keyboard(False),
    )


@router.callback_query(F.data == "wallet:repay")
async def wallet_repay_ask(callback: CallbackQuery, db: Database) -> None:
    user = await register_telegram_user(db, callback.from_user)
    amount = min(int(user["cookies"]), int(user.get("cookie_debt") or 0))
    if amount <= 0:
        await callback.answer(
            "Просроченного долга нет." if not user.get("cookie_debt") else "Для погашения сначала пополните кошелёк.",
            show_alert=True,
        )
        return
    token = await db.create_wallet_intent(callback.from_user.id, "debt_repay", amount)
    await callback.answer()
    if callback.message:
        await edit_block(
            callback.message,
            f"💳 <b>Погасить просроченный долг?</b>\n\nСпишется: <b>{amount} 🍪</b>\n"
            f"Останется на балансе: {int(user['cookies']) - amount} 🍪\n"
            f"Останется долга: {int(user['cookie_debt']) - amount} 🍪",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [ibtn(f"Погасить {amount} 🍪", f"wallet:repay:yes:{token}")],
                [back_btn("wallet:home"), close_btn("ui:close")],
            ]),
        )


@router.callback_query(F.data.startswith("wallet:repay:yes:"))
async def wallet_repay_yes(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    token = (callback.data or "").removeprefix("wallet:repay:yes:")
    intent = await db.get_wallet_intent(callback.from_user.id, token)
    if not intent or intent["item"] != "debt_repay":
        await callback.answer("Подтверждение устарело или уже выполнено. Откройте кошелёк.", show_alert=True)
        return
    ok, error = await db.repay_cookie_debt(callback.from_user.id, int(intent["price"]), intent_id=token)
    if not ok:
        await callback.answer(error, show_alert=True)
        return
    await callback.answer("Долг погашен." if not (await db.get_user(callback.from_user.id))["cookie_debt"]
                          else "Долг частично погашен.")
    if callback.message:
        await send_wallet(callback.message, db, settings, actor=callback.from_user, replace=True)
