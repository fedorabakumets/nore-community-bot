"""Validation shared by the chat and Mini App applications."""
import re


def validate_application_age(value: object) -> int:
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,3}', value.strip()):
        value = int(value.strip())
    if type(value) is not int or not 14 <= value <= 120:
        raise ValueError('Укажи возраст целым числом от 14 до 120.')
    return value
