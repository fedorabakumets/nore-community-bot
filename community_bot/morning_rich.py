"""Structured Telegram Rich Message for the morning digest."""
from __future__ import annotations

from zoneinfo import ZoneInfo

from aiogram.types import (
    BufferedInputFile,
    FSInputFile,
    InputMediaPhoto,
    InputRichBlockDetails,
    InputRichBlockDivider,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichBlockSectionHeading,
    InputRichMessage,
    RichTextUrl,
)

from community_bot.morning import (
    MONTHS,
    WEEKDAYS,
    MorningBrief,
    NewsItem,
    clean_link,
    clothing_advice,
    format_temp,
    weather_label,
)


def render_rich_brief(brief: MorningBrief, bot_username: str | None = None) -> InputRichMessage:
    local = brief.when.astimezone(ZoneInfo("Europe/Moscow"))
    day = local.date()
    blocks = [
        InputRichBlockSectionHeading(text="NORA DAILY", size=1),
        InputRichBlockParagraph(text=f"📆 {WEEKDAYS[day.weekday()]} • {day.day} {MONTHS[day.month - 1]}"),
    ]
    blocks.append(weather_block(brief))
    traffic_summary = (f"🚦 Пробки · {brief.traffic_level} из 10 баллов"
                       if brief.traffic_level is not None else "🚦 Пробки · данные недоступны")
    road_details = []
    if brief.road_incidents:
        road_details.append(InputRichBlockParagraph(text="Сообщения за сутки:"))
        for item in brief.road_incidents:
            road_details.append(InputRichBlockParagraph(text=item.title))
            if link := clean_link(item.link):
                road_details.append(InputRichBlockParagraph(text=RichTextUrl(text=item.source or "Источник", url=link)))
    else:
        message = ("Сообщений о происшествиях в доступных лентах не найдено." if brief.news_available
                   else "Дорожные новости не загрузились.")
        road_details.append(InputRichBlockParagraph(text=message))
    blocks.append(InputRichBlockDetails(summary=traffic_summary, blocks=road_details))
    if brief.metro_available and brief.closed_stations:
        blocks.append(InputRichBlockParagraph(text="🚇 Закрыты: " + ", ".join(brief.closed_stations)))
    if brief.photo:
        blocks.append(InputRichBlockPhoto(photo=InputMediaPhoto(media=FSInputFile(brief.photo))))
    blocks.extend([InputRichBlockDivider(), InputRichBlockSectionHeading(text="📰 Свежие новости", size=2)])
    if brief.day_news:
        blocks.extend(news_block(item) for item in brief.day_news[:2])
    else:
        message = ("Подходящих новостей за сутки не нашлось." if brief.news_available
                   else "Новости пока не загрузились.")
        blocks.append(InputRichBlockParagraph(text=message))
    blocks.extend([InputRichBlockDivider(), InputRichBlockSectionHeading(text="Этот день в Петербурге", size=2)])
    event = brief.history
    if event and event.year < day.year and (event.month, event.day) == (day.month, day.day):
        from community_bot.day_note import years_ago

        details = [
            InputRichBlockParagraph(text=f"{day.day} {MONTHS[day.month - 1]} · {years_ago(day.year - event.year)}"),
            InputRichBlockParagraph(text=event.text),
        ]
        if event.context:
            details.append(InputRichBlockParagraph(text=event.context))
        if link := clean_link(event.url):
            details.append(InputRichBlockParagraph(text=RichTextUrl(text="Подробнее", url=link)))
        summary = f"{event.year} · {event.title or 'Событие в городе'}"
        blocks.append(InputRichBlockDetails(summary=summary, blocks=details))
    else:
        blocks.append(InputRichBlockParagraph(text="Подтверждённого события на эту дату пока нет."))
    return InputRichMessage(blocks=blocks)


def weather_block(brief: MorningBrief) -> InputRichBlockDetails | InputRichBlockParagraph:
    weather = brief.weather
    if weather is None:
        return InputRichBlockParagraph(text="🌤 Погоду сейчас получить не удалось.")
    emoji = {"clear": "☀️", "cloudy": "☁️", "rain": "🌧", "snow": "❄️", "fog": "🌫", "storm": "⛈"}
    summary = f"{emoji[weather.kind]} Петербург · {format_temp(weather.temperature)} · {weather_label(weather.code)}"
    if brief.weather_card:
        photo = BufferedInputFile(brief.weather_card, filename="weather.png")
        details = [InputRichBlockPhoto(photo=InputMediaPhoto(media=photo))]
    else:
        details = [
            InputRichBlockParagraph(text=f"Ощущается как {format_temp(weather.feels_like)}"),
            InputRichBlockParagraph(text=f"💨 Ветер {round(weather.wind_kmh / 3.6)} м/с"),
        ]
    details.append(InputRichBlockParagraph(text=f"👕 {clothing_advice(weather)}"))
    return InputRichBlockDetails(summary=summary, blocks=details)


def news_block(item: NewsItem) -> InputRichBlockDetails:
    # The Bot API treats strings in structured blocks as plain text.
    details = []
    if item.body != item.title:
        details.append(InputRichBlockParagraph(text=item.body))
    if link := clean_link(item.link):
        details.append(InputRichBlockParagraph(text=RichTextUrl(text=item.source or "Источник", url=link)))
    if not details:
        details.append(InputRichBlockParagraph(text="Подробности недоступны."))
    return InputRichBlockDetails(summary=item.title, blocks=details)
