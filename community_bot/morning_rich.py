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
    MorningBrief,
    clean_link,
    clothing_advice,
    format_day,
    format_temp,
    weather_label,
)


def render_rich_brief(brief: MorningBrief, bot_username: str | None = None) -> InputRichMessage:
    local = brief.when.astimezone(ZoneInfo("Europe/Moscow"))
    day = local.date()
    blocks = [
        InputRichBlockSectionHeading(text="NORA DAILY", size=1),
        InputRichBlockParagraph(text=f"{format_day(day)} · Петербург"),
    ]
    if brief.photo:
        blocks.append(InputRichBlockPhoto(photo=InputMediaPhoto(media=FSInputFile(brief.photo))))
    blocks.extend([InputRichBlockDivider(), InputRichBlockSectionHeading(text="🌤 Погода", size=2)])
    if brief.weather:
        weather = brief.weather
        advice = clothing_advice(weather)
        blocks.append(InputRichBlockParagraph(text=(
            f"{ {'clear': '☀️', 'cloudy': '☁️', 'rain': '🌧', 'snow': '❄️', 'fog': '🌫', 'storm': '⛈'}[weather.kind]} "
            f"{format_temp(weather.temperature)} · {weather_label(weather.code).lower()} · "
            f"ощущается {format_temp(weather.feels_like)}\nНа улицу: {advice}"
        )))
    else:
        blocks.append(InputRichBlockParagraph(text="Погоду сейчас получить не удалось."))
    transport = []
    if brief.traffic_level is not None:
        transport.append(f"{brief.traffic_level} из 10 баллов")
    if brief.metro_available and brief.closed_stations:
        transport.append("закрыты: " + ", ".join(brief.closed_stations))
    if transport:
        blocks.extend([InputRichBlockSectionHeading(text="🚦 Пробки", size=3),
                       InputRichBlockParagraph(text=" · ".join(transport))])
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
    if bot_username:
        blocks.extend([InputRichBlockDivider(), InputRichBlockButtons(
            buttons=[RichMessageButton(text="НОРА", url=f"https://t.me/{bot_username}?start=private")], align="center",
        )])
    return InputRichMessage(blocks=blocks)
