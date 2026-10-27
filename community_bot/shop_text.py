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
    return html.unescape(''.join(parser.parts)).strip()


def catalogue_row(row):
    if row is None:
        return None
    return {key: clean_shop_text(value) if key in {'title', 'description'} else value for key, value in row.items()}
