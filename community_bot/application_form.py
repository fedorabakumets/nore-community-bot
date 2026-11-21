"""Validation shared by the chat and Mini App applications."""
import re


def validate_application_age(value: object) -> int:
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,3}', value.strip()):
        value = int(value.strip())
    if type(value) is not int or not 14 <= value <= 120:
        raise ValueError('Укажи возраст целым числом от 14 до 120.')
    return value


def validate_city(value: object) -> str:
    """Normalize a participant's free-text city without geolocating them."""
    if not isinstance(value, str):
        raise ValueError('Укажи город текстом (от 2 до 100 символов).')
    city = ' '.join(value.split())
    if not 2 <= len(city) <= 100 or any(ord(char) < 32 or ord(char) == 127 for char in city):
        raise ValueError('Укажи город текстом (от 2 до 100 символов).')
    return city
