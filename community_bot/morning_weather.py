"""Weather card for the expandable section of NORA DAILY."""
from __future__ import annotations

import logging
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

from community_bot.morning import WEATHER_URL, WEEKDAYS, WeatherNow, format_temp, weather_kind, weather_label

logger = logging.getLogger(__name__)
FONT = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Rubik-Variable.ttf"
MORNING_WEATHER_URL = (
    WEATHER_URL.replace("forecast_days=2", "forecast_days=6")
    .replace(",precipitation", ",precipitation,relative_humidity_2m")
    .replace(
        "daily=sunrise,sunset,weather_code", "daily=sunrise,sunset,weather_code,temperature_2m_min,temperature_2m_max",
    )
)


def render_weather_card(payload: dict[str, object], weather: WeatherNow, now: datetime) -> bytes | None:
    """Omit the illustration when the forecast is incomplete; keep the text summary."""
    try:
        return _draw_weather_card(payload, weather, now)
    except (KeyError, IndexError, OSError, TypeError, ValueError, OverflowError):
        logger.warning("Карточка погоды недоступна, используем текстовую сводку")
        return None


def _draw_weather_card(payload: dict[str, object], weather: WeatherNow, now: datetime) -> bytes:
    local = now.astimezone(ZoneInfo("Europe/Moscow")).replace(tzinfo=None)
    current, hourly, daily = (payload[key] for key in ("current", "hourly", "daily"))
    hours = [
        (stamp, float(temp), int(code))
        for raw_time, temp, code in zip(hourly["time"], hourly["temperature_2m"], hourly["weather_code"], strict=True)
        if (stamp := datetime.fromisoformat(raw_time)) > local
    ][:12:2]
    days = [
        (datetime.fromisoformat(stamp).date(), float(low), float(high), int(code))
        for stamp, low, high, code in zip(
            daily["time"], daily["temperature_2m_min"], daily["temperature_2m_max"], daily["weather_code"], strict=True,
        )
    ][:6]
    if not hours or not days or any(low > high for _, low, high, _ in days):
        raise ValueError("Incomplete forecast")
    humidity = int(current["relative_humidity_2m"])
    updated = datetime.fromisoformat(current["time"])
    width, height = 840, 532 + 67 * len(days)
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        fraction = y / height
        draw.line((0, y, width, y), fill=(26 - int(11 * fraction), 40 - int(16 * fraction), 61 - int(23 * fraction)))
    white, muted = "#f5f8ff", "#b8c8e0"
    fonts = {size: ImageFont.truetype(str(FONT), size) for size in (24, 26, 30, 36, 40, 116)}

    def text(x, y, value, size=30, fill=white, anchor="lt"):
        draw.text((x, y), value, font=fonts[size], fill=fill, anchor=anchor)

    text(40, 35, "Санкт-Петербург", 40)
    text(40, 100, format_temp(weather.temperature), 116)
    _icon(draw, 706, 147, 2.6, weather.kind)
    text(40, 227, weather_label(weather.code), 36)
    text(
        40, 281, f"Ощущается {format_temp(weather.feels_like)}   ·   "
        f"Ветер {round(weather.wind_kmh / 3.6)} м/с   ·   Влажность {humidity}%", 26, muted,
    )
    draw.line((40, 332, 800, 332), fill="#3b495e", width=2)
    for index, (stamp, temp, code) in enumerate(hours):
        x = round(40 + 760 * (index + 0.5) / len(hours))
        text(x, 350, stamp.strftime("%H:%M"), 24, muted, "mt")
        _icon(draw, x, 399, 0.67, weather_kind(code))
        text(x, 425, format_temp(temp), 26, white, "mt")
    draw.line((40, 469, 800, 469), fill="#3b495e", width=2)
    lowest = min(low for _, low, _, _ in days)
    spread = max(max(high for _, _, high, _ in days) - lowest, 1)
    for index, (day, low, high, code) in enumerate(days):
        y = 494 + 67 * index
        text(40, y, "Сегодня" if day == local.date() else WEEKDAYS[day.weekday()][:2])
        _icon(draw, 222, y + 12, 0.8, weather_kind(code))
        text(350, y, format_temp(low), 30, muted, "rt")
        text(751, y, format_temp(high))
        draw.rounded_rectangle((377, y + 7, 720, y + 19), 6, fill="#3b495e")
        left = 377 + int(331 * (low - lowest) / spread)
        right = 389 + int(331 * (high - lowest) / spread)
        for x in range(left, right):
            ratio = (x - left) / (right - left)
            color = (int(121 + 134 * ratio), int(198 + 13 * ratio), int(248 - 160 * ratio))
            draw.line((x, y + 8, x, y + 18), fill=color)
    text(40, height - 42, f"Данные на {updated:%H:%M}  ·  Open-Meteo", 24, muted)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _icon(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float, kind: str) -> None:
    def box(left, top, right, bottom):
        return tuple(round(value * scale + offset) for value, offset in zip(
            (left, top, right, bottom), (x, y, x, y), strict=True,
        ))

    if kind == "clear":
        draw.ellipse(box(-16, -16, 16, 16), fill="#ffd378")
        return
    cloud = "#c9d6e8"
    draw.rounded_rectangle(box(-25, -4, 25, 13), radius=round(8 * scale), fill=cloud)
    draw.ellipse(box(-17, -13, 3, 8), fill=cloud)
    draw.ellipse(box(-6, -19, 18, 8), fill=cloud)
    for offset in (-10, 0, 10):
        if kind in {"rain", "storm"}:
            draw.line(box(offset + 2, 17, offset - 1, 23), fill="#7cc6ff", width=max(1, round(2 * scale)))
        elif kind == "snow":
            draw.ellipse(box(offset - 2, 17, offset + 2, 21), fill="#f5f8ff")
    if kind == "fog":
        draw.line(box(-13, 19, 13, 19), fill=cloud, width=max(1, round(2 * scale)))
