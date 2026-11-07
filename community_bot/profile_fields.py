"""The self-service fields shared by the bot and Mini App."""
from __future__ import annotations

import hashlib
import json

EDITABLE = {'profile_name': (1, 50), 'hobbies': (1, 500), 'profile_bio': (1, 280)}
REVISION_FIELDS = (*EDITABLE, 'age', 'avatar_file_id', 'avatar_media_type', 'profile_private')


def profile_revision(user):
    raw = json.dumps([user.get(k) for k in REVISION_FIELDS], ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def validate_profile_fields(values):
    if not isinstance(values, dict) or not values or set(values) - {*EDITABLE, 'age'}:
        raise ValueError('Можно изменить только имя, возраст, увлечения и описание')
    clean = {}
    for key, value in values.items():
        if key == 'age':
            if type(value) is not int or not 14 <= value <= 120:
                raise ValueError('Возраст — целое число от 14 до 120')
        else:
            minimum, maximum = EDITABLE[key]
            if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
                raise ValueError(f'Проверь длину поля: от {minimum} до {maximum} символов')
            value = value.strip()
        clean[key] = value
    return clean
