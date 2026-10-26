from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from community_bot.morning import (
    MetroNote,
    MorningBrief,
    NewsItem,
    WeatherNow,
    clothing_advice,
    due_morning,
    format_day,
    metro_status,
    news_bucket,
    parse_closed_stations,
    parse_traffic_xml,
    render_brief,
    render_news_line,
    render_weather_command,
    select_day_news,
    select_news,
    telegram_length,
    weather_kind,
)


def _weather(**overrides) -> WeatherNow:
    data = {
        "temperature": 8,
        "feels_like": 5,
        "code": 3,
        "wind_kmh": 14,
        "precipitation": 0,
        "sunrise": "2026-10-05T07:13",
        "sunset": "2026-10-05T18:19",
    }
    data.update(overrides)
    return WeatherNow(**data)


def test_weather_kind_and_clothing() -> None:
    assert weather_kind(0) == "clear"
    assert weather_kind(3) == "cloudy"
    assert weather_kind(63) == "rain"
    assert weather_kind(73) == "snow"
    assert weather_kind(45) == "fog"
    assert weather_kind(95) == "storm"
    wet = clothing_advice(_weather(code=61, precipitation=1.2, feels_like=6))
    assert "Зонт" in wet
    cold = clothing_advice(_weather(feels_like=-16, temperature=-14, code=71))
    assert "Пуховик" in cold


def test_day_fact_and_schedule_window() -> None:
    day = datetime(2026, 10, 5, tzinfo=ZoneInfo("Europe/Moscow")).date()
    assert format_day(day) == "Понедельник, 5 октября"
    nine = datetime(2026, 10, 5, 9, 5, tzinfo=ZoneInfo("Europe/Moscow"))
    assert due_morning(nine, None) is True
    assert due_morning(nine, "2026-10-05") is False
    assert due_morning(nine.replace(hour=8), None) is False
    assert due_morning(nine.replace(hour=12), None) is False
    from community_bot.morning import brief_title

    assert "Доброе утро" in brief_title(nine)
    assert "Сводка на сегодня" in brief_title(nine.replace(hour=20))


def test_news_keeps_city_incidents_and_drops_crime() -> None:
    assert news_bucket("Грузовику разворотило кабину на Выборгском шоссе") == "night"
    assert news_bucket("Ограничен вход на станцию метро «Горный институт»") == "transport"
    assert news_bucket("Набережная Черной речки встала в пробке со всех сторон") == "transport"
    assert news_bucket("Ремонт добавит пробок на Космонавтов и Бухарестской") == "transport"
    assert news_bucket("В Якутии застрелили почти две сотни медведей") is None
    assert news_bucket("В Петербурге вынесли приговор женщине, убившей экс-супруга") is None
    assert news_bucket("Дежавю. На набережной Фонтанки второй день спасают кота") is None
    assert news_bucket("Чиновники предложили бизнесу судиться из-за пожара в особняке") is None
    now = datetime(2026, 10, 5, 9, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    items = [
        NewsItem("Грузовику разворотило кабину на Выборгском шоссе", datetime(2026, 10, 5, 4, 53, tzinfo=UTC)),
        NewsItem("Ограничен вход на станцию метро «Горный институт»", datetime(2026, 10, 5, 5, 0, tzinfo=UTC)),
        NewsItem("В Якутии застрелили почти две сотни медведей", datetime(2026, 10, 5, 5, 30, tzinfo=UTC)),
        NewsItem("Старый пожар на набережной Мойки", datetime(2026, 10, 3, 4, 0, tzinfo=UTC)),
    ]
    transport, night = select_news(items, now)
    assert any("метро" in line for line in transport)
    assert any("Выборгском" in line for line in night)
    assert all("Якутии" not in line for line in night + transport)
    assert all("Мойки" not in line for line in night)
    evening = datetime(2026, 10, 5, 20, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    late = NewsItem("Пожар на набережной Мойки", datetime(2026, 10, 5, 12, 0, tzinfo=UTC))
    _, evening_night = select_news([*items, late], evening)
    assert all("Мойки" not in line for line in evening_night)
    assert any("Выборгском" in line for line in evening_night)


def test_metro_keeps_active_restriction_and_clears_restored_line() -> None:
    now = datetime(2026, 10, 5, 9, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    notes = [
        MetroNote(
            datetime(2026, 8, 8, 11, 0, tzinfo=UTC),
            "С 10.08.2026 по 16.12.2026 вход в вестибюль станции «Чкаловская» ограничен.",
        ),
        MetroNote(
            datetime(2026, 10, 5, 4, 10, tzinfo=UTC),
            "На участке линии 5 увеличен интервал по техническим причинам.",
        ),
        MetroNote(
            datetime(2026, 10, 5, 4, 19, tzinfo=UTC),
            "Движение поездов на линии 5 осуществляется в обычном режиме, интервалы восстанавливаются.",
        ),
    ]
    lines, stations = metro_status(notes, now)
    assert lines[5] == ""
    assert any("Чкаловская" in note for note in stations)


def test_traffic_xml_and_caption_fit_photo() -> None:
    level, hint = parse_traffic_xml(
        """
        <info>
          <traffic><level>6</level><hint lang="ru">Местами затруднения</hint></traffic>
        </info>
        """
    )
    assert level == 6
    assert "затруднения" in hint
    now = datetime(2026, 10, 5, 9, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    brief = MorningBrief(
        when=now,
        weather=_weather(),
        traffic_level=level,
        traffic_hint=hint,
        transport_notes=["На Московском проспекте затруднение движения."],
        night=["Пожар на набережной Мойки локализован."] * 6,
    )
    text = render_brief(brief)
    assert "Доброе утро" in text
    assert "пробки 6/10" in text
    assert "ощущается +5°" in text
    assert "Этот день в Петербурге" in text
    assert "Московском" not in text
    assert "Подходящих новостей" in text
    assert telegram_length(text) <= 1024
    assert brief.photo is not None and brief.photo.name == "cloudy.jpg"


def test_closed_stations_and_day_news_stay_in_one_brief() -> None:
    page = """
    <p>Вестибюль станции</p>
    <tr><td>29</td><td>Парк Победы</td><td>Станция закрыта на реконструкцию</td></tr>
    <tr><td>32</td><td>Фрунзенская</td><td>Станция закрыта на реконструкцию</td></tr>
    <tr><td></td><td>Зенит</td><td>Вестибюль закрыт по выходным</td></tr>
    """
    assert parse_closed_stations(page) == ["Парк Победы", "Фрунзенская"]
    now = datetime(2026, 10, 8, 9, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    items = [
        NewsItem(
            "На Коломяжском проспекте изменили движение автобусов",
            datetime(2026, 10, 8, 5, 0, tzinfo=UTC),
            link="https://www.fontanka.ru/2026/10/08/3/?from=yanews",
            lead="Автобусы временно объезжают участок ремонта. Изменения действуют сегодня.",
        ),
        NewsItem("Федеральная заметка", datetime(2026, 10, 8, 6, 0, tzinfo=UTC), lead="Далеко от города."),
        NewsItem("Старая драка на набережной", datetime(2026, 10, 6, 5, 0, tzinfo=UTC), lead="Это было раньше."),
    ]
    selected = select_day_news(items, now)
    assert [item.title for item in selected] == ["На Коломяжском проспекте изменили движение автобусов"]
    line = render_news_line(selected[0])
    assert "Автобусы временно объезжают" in line
    assert 'href="https://www.fontanka.ru/2026/10/08/3/"' in line
    brief = MorningBrief(
        when=now,
        weather=_weather(),
        traffic_level=4,
        traffic_hint="Местами затруднения",
        closed_stations=parse_closed_stations(page) or [],
        day_news=selected,
    )
    text = render_brief(brief)
    assert "закрыты: Парк Победы, Фрунзенская" in text
    assert "пробки 4/10" in text
    assert "За сутки" in text
    assert "fontanka.ru/2026/10/08/3/" in text
    forecast = render_weather_command(
        {
            "current": {
                "temperature_2m": 9.4,
                "apparent_temperature": 7.2,
                "weather_code": 3,
                "wind_speed_10m": 7.2,
                "precipitation": 0,
            },
            "daily": {"sunrise": ["2026-10-08T07:20"], "sunset": ["2026-10-08T18:10"]},
            "hourly": {
                "time": ["2026-10-08T09:00", "2026-10-08T12:00"],
                "temperature_2m": [8, 11],
                "weather_code": [3, 2],
            },
        },
        now,
    )
    assert forecast is not None
    assert "Сейчас: +9°" in forecast
    assert "12:00 +11°, облачно" in forecast
    assert "Источник: Open-Meteo" in forecast
