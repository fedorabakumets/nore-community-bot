"""Repair reversible catalogue mojibake without rewriting staff-entered content."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser


def clean_shop_text(value: object) -> str:
    text = str(value or '')
    for _ in range(2):
        def repair(match):
            word = match.group()
            if not any(c in word for c in 'РСÐÑðÃÂâрв'):
                return word
            for encoding in ('cp1251', 'cp1252', 'latin1'):
                try:
                    candidate = word.encode(encoding).decode('utf-8')
                except (UnicodeError, ValueError):
                    continue
                if candidate != word and all(c.isprintable() for c in candidate):
                    return candidate
            return word
        updated = re.sub(r'\S+', repair, text)
        if updated == text:
            break
        text = updated
    text = re.sub(r'\S*�\S*', lambda m: '' if any(c in m.group() for c in 'ðÃÂ')
                  else m.group().replace('�', ''), text)
    return text.strip()


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, text):
        self.parts.append(text)

    def handle_starttag(self, tag, attrs):
        if tag in {'br', 'p', 'blockquote'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'p', 'blockquote'}:
            self.parts.append('\n')


def plain_shop_text(value: object) -> str:
    parser = PlainText()
    parser.feed(clean_shop_text(value))
    return rename_pet_catalogue(html.unescape(''.join(parser.parts)).strip())


def rename_pet_catalogue(text: str) -> str:
    """Present legacy catalogue labels without rewriting staff data."""
    phrases = (
        (r'(?i)завести тамагочи', 'Завести питомца'),
        (r'(?i)для тамагочи', 'для питомца'),
        (r'(?i)у тамагочи', 'у питомца'),
        (r'(?i)тамагочи', 'питомец'),
        (r'(?i)талисмана', 'питомца'),
        (r'(?i)талисману', 'питомцу'),
        (r'(?i)талисманом', 'питомцем'),
        (r'(?i)талисмане', 'питомце'),
        (r'(?i)талисман', 'питомец'),
    )
    for pattern, replacement in phrases:
        def replace(match, value=replacement):
            return value.capitalize() if match.group()[0].isupper() else value.lower()
        text = re.sub(pattern, replace, text)
    return text.strip()


def catalogue_row(row):
    if row is None:
        return None
    return {
        key: rename_pet_catalogue(clean_shop_text(value)) if key in {'title', 'description'} else value
        for key, value in row.items()
    }
