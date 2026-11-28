"""The self-service fields shared by the bot and Mini App."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

EDITABLE = {'profile_name': (1, 50), 'hobbies': (1, 500), 'profile_bio': (1, 280), 'city': (2, 100)}
REVISION_FIELDS = (*EDITABLE, 'birth_date', 'avatar_file_id', 'avatar_media_type', 'profile_private')


def normalize_tg_channel_url(value: str) -> str:
    """Allow only Telegram channel/user paths or private channel invitations.

    Telegram channel ownership cannot be established from a bare URL.
    """
    if not isinstance(value, str) or len(value) > 200:
        raise ValueError('Пришли ссылку на Telegram-канал, например https://t.me/channel')
    raw = value.strip()
    if raw.lower() in {'-', 'удалить'}:
        return ''
    if raw.startswith('@'):
        path = raw[1:]
    else:
        match = re.fullmatch(
            r'(?:https?://)?(?:t\.me|telegram\.me)/([a-zA-Z0-9_+/-]+)/?',
            raw, flags=re.IGNORECASE,
        )
        if not match:
            raise ValueError('Нужна ссылка t.me/название или t.me/+приглашение')
        path = match.group(1)
    if re.fullmatch(r'[a-zA-Z0-9_]{5,32}', path):
        if path.lower() in {'share', 'proxy', 'login', 'joinchat', 'addstickers', 'addemoji'}:
            raise ValueError('Укажи ссылку именно на свой Telegram-канал')
    elif re.fullmatch(r'\+[a-zA-Z0-9_-]{8,128}', path):
        pass
    elif re.fullmatch(r'joinchat/[a-zA-Z0-9_-]{8,128}', path):
        pass
    else:
        raise ValueError('Неверная ссылка на Telegram-канал')
    return f'https://t.me/{path}'


def age_on(birth_date: str, today: date) -> int:
    born = date.fromisoformat(birth_date)
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def profile_age(user, today: date | None = None) -> int | None:
    value = user.get('birth_date')
    if not value:
        return None
    try:
        return age_on(value, today or datetime.now(ZoneInfo('Europe/Moscow')).date())
    except (ValueError, TypeError):
        return None


def validate_birth_date(value):
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError('Укажи настоящую дату рождения') from None
    age = profile_age({'birth_date': value})
    if age is None or not 14 <= age <= 120:
        raise ValueError('Возраст по дате рождения должен быть от 14 до 120 лет')
    return value


def parse_birth_date(value: str) -> str:
    try:
        value = datetime.strptime(value.strip(), '%d.%m.%Y').date().isoformat()
    except ValueError:
        raise ValueError('Введи дату рождения в формате ДД.ММ.ГГГГ') from None
    return validate_birth_date(value)


def profile_revision(user):
    raw = json.dumps([user.get(k) for k in REVISION_FIELDS], ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def validate_profile_fields(values):
    if not isinstance(values, dict) or not values or set(values) - {*EDITABLE, 'birth_date'}:
        raise ValueError('Можно изменить только имя, дату рождения, город, увлечения и описание')
    clean = {}
    for key, value in values.items():
        if key == 'birth_date':
            value = validate_birth_date(value)
        elif key == 'city':
            from community_bot.application_form import validate_city

            value = validate_city(value)
        else:
            minimum, maximum = EDITABLE[key]
            if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
                raise ValueError(f'Проверь длину поля: от {minimum} до {maximum} символов')
            value = value.strip()
        clean[key] = value
    return clean
