from types import SimpleNamespace

from community_bot.helpers import profile_text


def test_profile_card_keeps_role_and_custom_status_separate() -> None:
    user = {
        "user_id": 42,
        "profile_name": "Роман",
        "telegram_name": "Roman",
        "username": "roman",
        "role": "admin",
        "custom_status": "На стиле",
        "hobbies": "Музыка",
        "age": 24,
        "reputation": 95,
        "cookies": 250,
        "warnings": 0,
    }

    text = profile_text(user, SimpleNamespace(restricted_reputation_threshold=0))

    assert "NORA COMMUNITY" in text
    assert "Администратор" in text
    assert "На стиле" in text
    assert "95/100" in text
    assert "скидка 20%" in text
    assert "██████████" in text


def test_profile_reputation_bar_is_clamped() -> None:
    user = {
        "user_id": 7,
        "profile_name": None,
        "telegram_name": "User",
        "username": None,
        "role": "member",
        "custom_status": None,
        "hobbies": None,
        "age": None,
        "reputation": -5,
        "cookies": 0,
        "warnings": 2,
    }

    text = profile_text(user, SimpleNamespace(restricted_reputation_threshold=0))

    assert "<code>░░░░░░░░░░</code>" in text
    assert "Ограничен" not in text
    assert "ограничен" in text
