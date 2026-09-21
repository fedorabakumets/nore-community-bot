from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

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
    pet_status_line,
    transaction_line,
    wallet_net,
)
from community_bot.ephemeral import keep_in_chat
from community_bot.helpers import register_telegram_user
from community_bot.keyboards import back_btn, close_btn, wallet_keyboard, wallet_loan_confirm_keyboard
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


def _pad(text: str, width: int, *, right: bool = False) -> str:
    text = str(text)
    if len(text) >= width:
        return text[:width]
    pad = " " * (width - len(text))
    return pad + text if right else text + pad


async def wallet_text(db: Database, settings: Settings, user: dict[str, object]) -> str:
    user_id = int(user["user_id"])
    tier = reputation_tier(int(user["reputation"]), settings.restricted_reputation_threshold)
    percent = transfer_commission_percent(int(user["reputation"]), settings.restricted_reputation_threshold)
    interest = loan_interest_percent(int(user["reputation"]), settings.restricted_reputation_threshold)
    repay = loan_repay_amount(LOAN_PRINCIPAL, interest)
    pet = await db.get_pet(user_id)
    loan = await db.get_active_loan(user_id)
    debt = int(user.get("cookie_debt") or 0)
    cookies = int(user["cookies"])
    net = wallet_net(user)
    if not pet:
        expedition = "нет"
    elif pet.get("expedition_until"):
        expedition = "в пути"
    else:
        expedition = "дома"
    table = (
        "<pre>"
        "┌──────────────┬────────────┐\n"
        f"│ {_pad('Печеньки', 12)} │ {_pad(str(cookies) + ' 🍪', 10, right=True)} │\n"
        f"│ {_pad('Долг', 12)} │ {_pad(str(debt) + ' 🍪', 10, right=True)} │\n"
        f"│ {_pad('Итого', 12)} │ {_pad(str(net) + ' 🍪', 10, right=True)} │\n"
        f"│ {_pad('Комиссия', 12)} │ {_pad(str(percent) + ' %', 10, right=True)} │\n"
        f"│ {_pad('Кредит', 12)} │ {_pad(str(LOAN_PRINCIPAL) + ' 🍪', 10, right=True)} │\n"
        f"│ {_pad('Ставка', 12)} │ {_pad(str(interest) + ' %', 10, right=True)} │\n"
        f"│ {_pad('Репутация', 12)} │ {_pad(str(int(user['reputation'])) + ' %', 10, right=True)} │\n"
        f"│ {_pad('Уровень', 12)} │ {_pad(tier.label, 10, right=True)} │\n"
        f"│ {_pad('Экспедиция', 12)} │ {_pad(expedition, 10, right=True)} │\n"
        "└──────────────┴────────────┘"
        "</pre>"
    )
    lines = [
        "💼 <b>Кошелёк</b>",
        "",
        table,
        "",
        f"Уровень: {tier.emoji} {tier.label} · комиссия переводов <b>{percent}%</b>.",
        f"Кредит 100 🍪: ставка <b>{interest}%</b>, к возврату {repay} 🍪 через {LOAN_DAYS} дней.",
        "",
        pet_status_line(pet),
    ]
    if loan:
        lines.append("")
        lines.append(
            f"💳 Открыт кредит: {loan['principal']} 🍪, вернуть {loan['due_amount']} 🍪 "
            f"(осталось {_due_label(str(loan['due_at']))})."
        )
    lines.append("")
    lines.append("Итого = печеньки минус долг. История, пополнение и кредит — кнопками ниже.")
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
        text = "📜 Пока нет движений по кошельку."
    else:
        text = "📜 <b>История печенек</b>\n\n" + "\n".join(transaction_line(row) for row in rows)
    await edit_block(
        callback.message,
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[back_btn("wallet:home"), close_btn("ui:close")]]),
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
            "💸 <b>Перевод</b>\nВ личке цели нет. В чате ответом на человека: <code>перевести 10</code>.",
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
    await callback.answer()
    if callback.message:
        await edit_block(
            callback.message,
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
    await edit_block(
        callback.message,
        f"✅ На кошелёк пришло {loan['principal']} 🍪.\n"
        f"Вернуть {loan['due_amount']} 🍪 до {str(loan['due_at'])[:16].replace('T', ' ')} UTC.\n\n"
        + await wallet_text(db, settings, user),
        parse_mode="HTML",
        reply_markup=wallet_keyboard(False),
    )
