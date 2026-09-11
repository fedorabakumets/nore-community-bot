from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from community_bot.aliases import command_or_alias
from community_bot.blocks import answer_block, edit_block
from community_bot.config import Settings
from community_bot.database import Database
from community_bot.domain import reputation_tier, transfer_commission_percent
from community_bot.economy import (
    LOAN_DAYS,
    LOAN_PRINCIPAL,
    loan_interest_percent,
    loan_repay_amount,
    pet_farm_rate_line,
    transaction_line,
    wallet_net,
)
from community_bot.ephemeral import keep_in_chat
from community_bot.helpers import register_telegram_user
from community_bot.keyboards import wallet_keyboard, wallet_loan_confirm_keyboard
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
    pet = await db.get_pet(user_id)
    loan = await db.get_active_loan(user_id)
    debt = int(user.get("cookie_debt") or 0)
    net = wallet_net(user)
    lines = [
        "💼 <b>Кошелёк Норы</b>",
        "",
        f"Печеньки: <b>{int(user['cookies'])} 🍪</b>",
    ]
    if debt:
        lines.append(f"Долг: <b>−{debt} 🍪</b>")
        lines.append(f"Итого: <b>{net} 🍪</b>")
    lines.append(f"Уровень: {tier.emoji} {tier.label} · комиссия переводов <b>{percent}%</b>")
    lines.append(f"Кредит 100 🍪: ставка <b>{interest}%</b>, к возврату {repay} 🍪 через {LOAN_DAYS} дней.")
    lines.append("")
    lines.append(pet_farm_rate_line(pet))
    if loan:
        lines.append("")
        lines.append(
            f"💳 Открыт кредит: {loan['principal']} 🍪, вернуть {loan['due_amount']} 🍪 "
            f"(осталось {_due_label(str(loan['due_at']))})."
        )
    lines.append("")
    lines.append("История, пополнение и кредит — кнопками ниже.")
    return "\n".join(lines)


async def send_wallet(message: Message, db: Database, settings: Settings) -> None:
    if not message.from_user:
        return
    user = await register_telegram_user(db, message.from_user)
    loan = await db.get_active_loan(message.from_user.id)
    can_borrow = loan is None and int(user.get("cookie_debt") or 0) == 0
    text = await wallet_text(db, settings, user)
    with keep_in_chat():
        await answer_block(message, "wallet", text, parse_mode="HTML", reply_markup=wallet_keyboard(can_borrow))


@router.message(command_or_alias("balance"))
async def balance_command(message: Message, db: Database, settings: Settings) -> None:
    await send_wallet(message, db, settings)


@router.callback_query(F.data == "wallet:back")
@router.callback_query(F.data == "wallet:home")
async def wallet_home(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message:
        return
    user = await register_telegram_user(db, callback.from_user)
    loan = await db.get_active_loan(callback.from_user.id)
    can_borrow = loan is None and int(user.get("cookie_debt") or 0) == 0
    await callback.answer()
    await edit_block(
        callback.message,
        await wallet_text(db, settings, user),
        parse_mode="HTML",
        reply_markup=wallet_keyboard(can_borrow),
    )


@router.callback_query(F.data == "wallet:history")
async def wallet_history(callback: CallbackQuery, db: Database) -> None:
    if not callback.message:
        return
    rows = await db.list_transactions(callback.from_user.id, 12)
    await callback.answer()
    if not rows:
        await callback.message.answer("📜 Пока нет движений по кошельку.")
        return
    lines = ["📜 <b>История печенек</b>", ""]
    lines.extend(transaction_line(row) for row in rows)
    await callback.message.answer("\n".join(lines), parse_mode="HTML", reply_markup=wallet_keyboard(True))


@router.callback_query(F.data == "wallet:shop")
async def wallet_shop(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message:
        return
    user = await register_telegram_user(db, callback.from_user)
    await callback.answer()
    await answer_block(
        callback.message,
        "shop",
        _shop_home_text(user, settings),
        parse_mode="HTML",
        reply_markup=await _shop_home_markup(db),
    )


@router.callback_query(F.data == "wallet:help")
async def wallet_help(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await answer_block(callback.message, "wallet", WALLET_HELP_TEXT, parse_mode="HTML")


@router.callback_query(F.data == "wallet:loan")
async def wallet_loan_ask(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    user = await register_telegram_user(db, callback.from_user)
    loan = await db.get_active_loan(callback.from_user.id)
    if loan or int(user.get("cookie_debt") or 0) > 0:
        await callback.answer("Сначала закройте текущий кредит или долг.", show_alert=True)
        return
    interest = loan_interest_percent(int(user["reputation"]), settings.restricted_reputation_threshold)
    repay = loan_repay_amount(LOAN_PRINCIPAL, interest)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"💳 Взять <b>{LOAN_PRINCIPAL} 🍪</b> в долг?\n"
            f"Ставка <b>{interest}%</b> по вашему уровню. Через {LOAN_DAYS} дней спишется "
            f"<b>{repay} 🍪</b> (недостающее уйдёт в минус кошелька).",
            parse_mode="HTML",
            reply_markup=wallet_loan_confirm_keyboard(),
        )


@router.callback_query(F.data == "wallet:loan:yes")
async def wallet_loan_yes(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    if not callback.message:
        return
    ok, error, loan = await db.take_cookie_loan(
        callback.from_user.id,
        settings.restricted_reputation_threshold,
    )
    if not ok or not loan:
        await callback.answer(error, show_alert=True)
        return
    user = await db.get_user(callback.from_user.id)
    assert user is not None
    await callback.answer("Кредит зачислен.")
    await callback.message.edit_text(
        f"✅ На кошелёк пришло {loan['principal']} 🍪.\n"
        f"Вернуть {loan['due_amount']} 🍪 до {str(loan['due_at'])[:16].replace('T', ' ')} UTC.\n\n"
        + await wallet_text(db, settings, user),
        parse_mode="HTML",
        reply_markup=wallet_keyboard(False),
    )
