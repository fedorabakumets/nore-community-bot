from __future__ import annotations

import html
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from community_bot.domain import format_duration, parse_duration, parse_duration_or_permanent

STATUS_GREEN = "green"
STATUS_YELLOW = "yellow"
STATUS_RED = "red"
STATUS_EMOJI = {STATUS_GREEN: "🟢", STATUS_YELLOW: "🟡", STATUS_RED: "🔴"}
SYSTEM_ACTOR_ID = 0

ACTION_LABELS: dict[str, str] = {
    "mute": "Мут",
    "unmute": "Снятие мута",
    "warn": "Предупреждение",
    "unwarn": "Снятие предупреждения",
    "kick": "Кик",
    "ban": "Бан",
    "unban": "Разбан",
    "purge": "Очистка чата",
    "botsweep": "Очистка сообщений бота",
    "delete_message": "Удаление сообщения",
    "give_cookies": "Начисление 🍪",
    "set_cookies": "Установка баланса 🍪",
    "role": "Смена роли",
    "role_create": "Создание роли",
    "role_perm": "Права роли",
    "role_delete": "Удаление роли",
    "set_status": "Кастомный статус",
    "chat_mute": "Закрытие чата",
    "chat_unmute": "Открытие чата",
    "broadcast_private": "Рассылка в личку",
    "post_community": "Сообщение в сообщество",
    "feature_toggle": "Переключение функции",
    "application_approved": "Анкета одобрена",
    "application_rejected": "Анкета отклонена",
    "payment_approved": "Оплата подтверждена",
    "payment_rejected": "Оплата отклонена",
    "ticket_close": "Тикет закрыт",
    "user_cookies": "Баланс 🍪",
    "user_add_cookies": "Начисление 🍪",
    "user_name": "Имя профиля",
    "user_age": "Возраст",
    "user_avatar": "Аватар",
    "user_warnings": "Предупреждения",
    "restart": "Перезапуск бота",
    "contest_publish": "Конкурс опубликован",
    "contest_draw": "Итог конкурса",
    "contest_cancel": "Конкурс снят",
}

PUNITIVE_ACTIONS = {"mute", "warn", "kick", "ban"}
REVERSAL_ACTIONS = {"unmute", "unwarn", "unban"}
_DOUBTFUL_WITHOUT_REASON = {
    "give_cookies",
    "set_cookies",
    "chat_mute",
    "user_cookies",
    "user_add_cookies",
    "user_warnings",
    "set_status",
}


def person_label(user: dict[str, Any] | None, fallback: str = "неизвестный") -> str:
    if not user:
        return fallback
    return str(
        user.get("profile_name")
        or user.get("telegram_name")
        or user.get("username")
        or user.get("user_id")
        or fallback
    )


def action_label(action: str) -> str:
    if action in ACTION_LABELS:
        return ACTION_LABELS[action]
    if action.startswith("user_"):
        return ACTION_LABELS.get(action, "Админское действие")
    return "Админское действие"


def classify_status(
    action: str,
    *,
    reason: str = "",
    details: str = "",
    target: str = "",
    target_name: str = "",
    default_duration: bool = False,
) -> str:
    reason = (reason or "").strip()
    target_name = (target_name or "").strip()
    target = str(target or "")
    if action in PUNITIVE_ACTIONS:
        if not reason:
            return STATUS_RED
        if default_duration:
            return STATUS_YELLOW
        return STATUS_GREEN
    if action in REVERSAL_ACTIONS:
        if not target_name and target.lstrip("-").isdigit():
            return STATUS_YELLOW
        return STATUS_GREEN
    if action == "delete_message":
        return STATUS_GREEN if (reason or details) else STATUS_RED
    if action == "unban" and not target_name:
        return STATUS_YELLOW
    if action in _DOUBTFUL_WITHOUT_REASON and not reason:
        return STATUS_YELLOW
    return STATUS_GREEN


def parse_moderation_args(text: str) -> tuple[timedelta, str, bool]:
    from community_bot.aliases import remainder_args

    args = remainder_args(text)
    if not args:
        return timedelta(hours=1), "", False
    duration = parse_duration(args[0])
    if duration:
        return duration, " ".join(args[1:]).strip(), True
    return timedelta(hours=1), " ".join(args).strip(), False


def parse_punitive_args(
    text: str,
    *,
    need_duration: bool,
    allow_permanent: bool = False,
) -> tuple[timedelta | None, str, str | None]:
    from community_bot.aliases import remainder_args

    args = remainder_args(text)
    if need_duration:
        if not args:
            hint = "30m флуд" if not allow_permanent else "7d мошенничество (или навсегда)"
            return None, "", f"Нужны время и причина. Пример: {hint}"
        duration = parse_duration_or_permanent(args[0]) if allow_permanent else parse_duration(args[0])
        if not duration:
            extra = " либо «навсегда»" if allow_permanent else ""
            return None, "", f"Первым укажите время: 10m, 2h, 1d{extra}."
        reason = " ".join(args[1:]).strip()
        if len(reason) < 2:
            return None, "", "После времени напишите причину — минимум два символа."
        return duration, reason, None
    reason = " ".join(args).strip()
    if len(reason) < 2:
        return None, "", "Нужна причина — минимум два символа."
    return None, reason, None


def parse_warn_args(text: str) -> tuple[timedelta | None, str, str | None]:
    from community_bot.aliases import remainder_args

    args = remainder_args(text)
    if not args:
        return None, "", "Нужна причина. Пример: /warn спам или /warn 2h токсик"
    duration = parse_duration(args[0])
    if duration:
        reason = " ".join(args[1:]).strip()
        if len(reason) < 2:
            return None, "", "После времени напишите причину — минимум два символа."
        return duration, reason, None
    reason = " ".join(args).strip()
    if len(reason) < 2:
        return None, "", "Нужна причина — минимум два символа."
    return None, reason, None


def duration_label(delta: timedelta | None) -> str:
    if delta is None:
        return ""
    return format_duration(delta)


def _when(iso: str) -> str:
    try:
        moment = datetime.fromisoformat(iso)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return moment.astimezone(ZoneInfo("Europe/Moscow")).strftime("%d.%m %H:%M")
    except ValueError:
        return iso[:16]


def format_audit_row(row: dict[str, Any]) -> str:
    action = str(row.get("action") or "")
    reason = str(row.get("reason") or "").strip()
    details = str(row.get("details") or "").strip()
    target = str(row.get("target") or "")
    actor_name = str(
        row.get("actor_name")
        or row.get("actor_display")
        or ("Система" if int(row.get("actor_id") or 0) == SYSTEM_ACTOR_ID else row.get("actor_id"))
    )
    target_name = str(row.get("target_name") or row.get("target_display") or "")
    status = str(row.get("status") or "") or classify_status(
        action,
        reason=reason,
        details=details,
        target=target,
        target_name=target_name,
    )
    emoji = STATUS_EMOJI.get(status, "🟡")
    who = html.escape(actor_name)
    what = html.escape(action_label(action))
    whom = html.escape(target_name or target or "—")
    bits = [item for item in (reason, details) if item]
    if status == STATUS_RED and not reason:
        note = "нет причины"
    elif status == STATUS_YELLOW and not reason:
        note = "не хватает данных · сомнительное действие"
    elif bits:
        note = " · ".join(bits)
    else:
        note = "всё в порядке"
    when = _when(str(row.get("created_at") or ""))
    return f"{emoji} <b>{who}</b> · {what} · {whom}\n<i>{html.escape(note)}</i> · <code>{html.escape(when)}</code>"


def format_audit_log(rows: list[dict[str, Any]]) -> str:
    lines = [
        "🧾 <b>Журнал аудита</b>",
        "🟢 полный отчёт · 🟡 мало данных / сомнительно · 🔴 нет причины",
        "",
    ]
    if not rows:
        lines.append("Журнал пока пуст.")
        return "\n".join(lines)
    lines.extend(format_audit_row(row) for row in rows)
    return "\n".join(lines)
