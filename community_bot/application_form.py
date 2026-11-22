"""Validation shared by the chat and Mini App applications."""
import re


def validate_application_age(value: object) -> int:
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,3}', value.strip()):
        value = int(value.strip())
    if type(value) is not int or not 14 <= value <= 120:
        raise ValueError('Укажи возраст целым числом от 14 до 120.')
    return value


def validate_city(value: object) -> str:
    """Basic input hygiene; existence is checked by city_lookup before saving."""
    error = 'Напиши название города (2–100 символов), затем выбери его из подсказок.'
    if not isinstance(value, str):
        raise ValueError(error)
    city = ' '.join(value.split())
    if (not 2 <= len(city) <= 100
            or sum(char.isalpha() for char in city) < 2
            or any(not (char.isalpha() or char.isdigit() or char in " -'’.(),") for char in city)
            or re.search(r'([^\\W\\d_])\\1{4,}', city, flags=re.IGNORECASE)):
        raise ValueError(error)
    return city
