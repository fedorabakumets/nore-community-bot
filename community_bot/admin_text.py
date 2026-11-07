"""Small Telegram HTML-to-entities converter for the web admin composer."""
from html.parser import HTMLParser
from urllib.parse import urlparse

from aiogram.types import MessageEntity


class ComposerHTML(HTMLParser):
    types = {'b': 'bold', 'strong': 'bold', 'i': 'italic', 'em': 'italic', 'u': 'underline',
             's': 'strikethrough', 'del': 'strikethrough', 'code': 'code', 'pre': 'pre',
             'blockquote': 'blockquote', 'a': 'text_link'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.stack = []
        self.entities = []
        self.units = 0

    def handle_data(self, data):
        self.parts.append(data)
        self.units += len(data.encode('utf-16-le')) // 2

    def handle_starttag(self, tag, attrs):
        if tag == 'br':
            self.handle_data('\n')
            return
        if tag not in self.types:
            raise ValueError('Разрешены жирный, курсив, подчёркивание, зачёркивание, код, цитаты и ссылки')
        attrs = dict(attrs)
        url = attrs.get('href')
        if tag == 'a' and urlparse(url or '').scheme not in {'https', 'http', 'tg'}:
            raise ValueError('Нужна ссылка https, http или tg')
        kind = 'expandable_blockquote' if tag == 'blockquote' and 'expandable' in attrs else self.types[tag]
        self.stack.append((tag, kind, self.units, url))

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1][0] != tag:
            raise ValueError('Проверь закрывающие теги форматирования')
        _, kind, start, url = self.stack.pop()
        length = self.units - start
        if length:
            self.entities.append(MessageEntity(type=kind, offset=start, length=length, url=url))


def compose(text, mode):
    if mode == 'plain':
        return text, []
    if mode != 'html':
        raise ValueError('Неподдерживаемый формат текста')
    parser = ComposerHTML()
    parser.feed(text)
    parser.close()
    if parser.stack:
        raise ValueError('Закрой теги форматирования')
    return ''.join(parser.parts), sorted(parser.entities, key=lambda entity: (entity.offset, -entity.length))
