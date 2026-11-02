"""Structured Telegram Rich Message for the morning digest."""
from __future__ import annotations

from zoneinfo import ZoneInfo

from aiogram.types import (
    FSInputFile,
    InputMediaPhoto,
    InputRichBlockButtons,
    InputRichBlockDetails,
    InputRichBlockDivider,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichBlockSectionHeading,
    InputRichMessage,
    RichMessageButton,
    RichTextUrl,
)

from community_bot.morning import (
    MONTHS,
    WEEKDAYS,
    MorningBrief,
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
    if brief.weather:
        weather = brief.weather
        emoji = {"clear": "☀️", "cloudy": "☁️", "rain": "🌧", "snow": "❄️", "fog": "🌫", "storm": "⛈"}
        summary = (f"{emoji[weather.kind]} Петербург · {format_temp(weather.temperature)} · "
                   f"{weather_label(weather.code)}")
        details = [
            InputRichBlockParagraph(text=f"Ощущается как {format_temp(weather.feels_like)}"),
            InputRichBlockParagraph(text=f"💨 Ветер {round(weather.wind_kmh / 3.6)} м/с"),
            InputRichBlockParagraph(text=f"👕 {clothing_advice(weather)}"),
        ]
        blocks.append(InputRichBlockDetails(summary=summary, blocks=details))
    else:
        blocks.append(InputRichBlockParagraph(text="🌤 Погоду сейчас получить не удалось."))
    if brief.photo:
        blocks.append(InputRichBlockPhoto(photo=InputMediaPhoto(media=FSInputFile(brief.photo))))
    blocks.extend([InputRichBlockDivider(), InputRichBlockSectionHeading(text="📰 Свежие новости", size=2)])
    if brief.day_news:
        for item in brief.day_news[:2]:
            details = []
            if item.body != item.title:
                details.append(InputRichBlockParagraph(text=item.body))
            link = clean_link(item.link)
            if link:
                details.append(InputRichBlockParagraph(text=RichTextUrl(text=item.source or "Источник", url=link)))
            if not details:
                details.append(InputRichBlockParagraph(text="Подробности недоступны."))
            blocks.append(InputRichBlockDetails(summary=item.title, blocks=details))
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
    transport = []
    if brief.traffic_level is not None:
        transport.append(f"{brief.traffic_level} из 10 баллов")
    if brief.metro_available and brief.closed_stations:
        transport.append("закрыты: " + ", ".join(brief.closed_stations))
    if transport:
        blocks.extend([InputRichBlockDivider(), InputRichBlockSectionHeading(text="🚦 Пробки", size=3),
                       InputRichBlockParagraph(text=" · ".join(transport))])
    if bot_username:
        blocks.extend([InputRichBlockDivider(), InputRichBlockButtons(
            buttons=[
                RichMessageButton(text="BOT", url=f"https://t.me/{bot_username}?start=private"),
                RichMessageButton(text="APP", url=f"https://t.me/{bot_username}?startapp"),
            ], align="center",
        )])
    return InputRichMessage(blocks=blocks)
