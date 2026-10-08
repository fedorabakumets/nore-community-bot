from datetime import datetime
from zoneinfo import ZoneInfo

from community_bot.city import (
    NewsItem,
    digest_is_due,
    format_temp,
    is_local_news,
    is_weather_text,
    parse_closed_stations,
    parse_news,
    parse_traffic,
    render_digest,
    render_metro_line,
    render_news_line,
    render_traffic_line,
    render_weather_brief,
    render_weather_detail,
    select_news,
    traffic_assessment,
)

MSK = ZoneInfo("Europe/Moscow")


def test_weather_word_and_commands() -> None:
    assert is_weather_text("погода")
    assert is_weather_text("  Погода! ")
    assert is_weather_text("/pogoda")
    assert is_weather_text("/погода@NoreBot")
    assert not is_weather_text("какая погода")
    assert not is_weather_text("/pogoda завтра")


def test_weather_formats_share_the_same_snapshot() -> None:
    payload = {
        "current": {
            "temperature_2m": 9.5,
            "apparent_temperature": 7.4,
            "weather_code": 3,
            "wind_speed_10m": 1.6,
            "precipitation": 0,
        },
        "hourly": {
            "time": ["2026-10-08T09:00", "2026-10-08T12:00", "2026-10-08T15:00"],
            "temperature_2m": [8.2, 11.2, 10.4],
            "weather_code": [3, 61, 3],
        },
    }
    now = datetime(2026, 10, 8, 9, 30, tzinfo=MSK)
    brief = render_weather_brief(payload)
    detail = render_weather_detail(payload, now)
    assert brief == "☁️ +10°, облачно"
    assert "Сейчас: +10°, ощущается как +7°. Облачно." in detail
    assert "Ветер 2 м/с. Осадков нет." in detail
    assert "12:00 +11°, небольшой дождь" in detail
    assert "09:00" not in detail
    assert "Источник: Open-Meteo" in detail
    assert format_temp(-0.4) == "0°"
    assert format_temp(-1.5) == "-2°"


def test_traffic_uses_score_and_short_hint() -> None:
    xml = """
    <traffic>
      <level>4</level>
      <hint lang="ru">Местами затруднения</hint>
      <hint lang="en">Congested in places</hint>
    </traffic>
    """
    assert parse_traffic(xml) == (4, "Местами затруднения")
    assert render_traffic_line(4, "Местами затруднения") == "🚗 Пробки: 4, местами затруднения"
    assert traffic_assessment(9, "") == "город стоит"
    assert render_traffic_line(None, None) == "🚗 Балл пробок сейчас недоступен"


def test_metro_page_keeps_long_repairs_and_skips_vestibules() -> None:
    page = """
    <p>Вестибюль станции</p>
    <tr><td>29</td><td>Парк Победы</td><td>Станция закрыта на реконструкцию</td></tr>
    <tr><td>30</td><td>Электросила</td><td>5:38</td></tr>
    <tr><td>32</td><td>Фрунзенская</td><td>Станция закрыта на   реконструкцию</td></tr>
    <tr><td></td><td>Зенит</td><td>Вестибюль закрыт кроме дней проведения мероприятий</td></tr>
    """
    assert parse_closed_stations(page) == ["Парк Победы", "Фрунзенская"]
    assert parse_closed_stations("<html>заглушка</html>") is None
    assert render_metro_line(["Парк Победы", "Фрунзенская"]) == "🚇 Не работают: Парк Победы, Фрунзенская"
    assert render_metro_line([]) == "🚇 Закрытых станций нет"


def test_news_keeps_two_local_items_from_last_day_with_source_link() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel>
      <item>
        <title>Федеральная заметка</title>
        <link>https://www.fontanka.ru/2026/10/08/1/?from=yanews</link>
        <pubDate>Thu, 08 Oct 2026 09:00:00 +0300</pubDate>
        <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">
          <p>Это событие произошло далеко от города. Второе предложение федеральной заметки.</p>
        </content:encoded>
      </item>
      <item>
        <title>Старая городская заметка</title>
        <link>https://www.fontanka.ru/2026/10/06/2/</link>
        <pubDate>Tue, 06 Oct 2026 09:00:00 +0300</pubDate>
        <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">
          <p>В Петербурге это было позавчера.</p>
        </content:encoded>
      </item>
      <item>
        <title>Драка у ТРК</title>
        <link>https://www.fontanka.ru/2026/10/08/3/?from=yanews</link>
        <pubDate>Thu, 08 Oct 2026 08:00:00 +0300</pubDate>
        <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">
          <figure><img src="https://example.test/a.jpg"/><figcaption>фото: FONTANKA.RU</figcaption></figure>
          <p>Подростки устроили драку на Коломяжском проспекте. Полиция задержала участников.</p>
          <p>Это уже третье предложение и в сводку не входит.</p>
        </content:encoded>
      </item>
      <item>
        <title>Авария на улице</title>
        <link>https://www.fontanka.ru/2026/10/07/4/</link>
        <pubDate>Wed, 07 Oct 2026 12:00:00 +0300</pubDate>
        <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">
          <p>На Новороссийской улице столкнулись две машины.</p>
        </content:encoded>
      </item>
    </channel></rss>
    """
    now = datetime(2026, 10, 8, 9, 30, tzinfo=MSK)
    selected = parse_news(xml, now)
    assert [item.title for item in selected] == ["Драка у ТРК", "Авария на улице"]
    line = render_news_line(selected[0])
    assert line.startswith("Подростки устроили драку на Коломяжском проспекте. Полиция задержала участников.")
    assert "третье предложение" not in line
    assert '(<a href="https://www.fontanka.ru/2026/10/08/3/">https://www.fontanka.ru/2026/10/08/3/</a>)' in line
    federal = NewsItem("Федеральная заметка", "https://example.test/1", now, "Это событие произошло далеко.")
    assert not is_local_news(federal)


def test_digest_is_one_post_and_only_due_in_the_morning_window() -> None:
    now = datetime(2026, 10, 8, 8, 5, tzinfo=MSK)
    text = render_digest(
        now,
        "☁️ +10°, облачно",
        "🚗 Пробки: 4, местами затруднения",
        "🚇 Не работают: Парк Победы, Фрунзенская",
        ["Короткий лид. (<a href=\"https://www.fontanka.ru/1/\">https://www.fontanka.ru/1/</a>)"],
    )
    assert "Сводка на 8 октября" in text
    assert text.count("<b>За сутки</b>") == 1
    assert "Короткий лид." in text
    assert digest_is_due(now, 8, None)
    assert not digest_is_due(now, 8, "2026-10-08")
    assert not digest_is_due(now.replace(hour=15), 8, None)
    assert select_news([]) == []
