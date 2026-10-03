from datetime import timedelta

from community_bot.domain import (
    cookie_word,
    cookies_phrase,
    discounted_price,
    parse_duration,
    reputation_delta,
    reputation_tier,
    ru_plural,
    transfer_amount,
    transfer_commission_percent,
    win_after_commission,
)


def test_reputation_tiers_do_not_overlap() -> None:
    assert reputation_tier(100).key == "gold"
    assert reputation_tier(90).daily_actions == 5
    assert reputation_tier(89).key == "silver"
    assert reputation_tier(70).discount == 5
    assert reputation_tier(69).key == "bronze"
    assert reputation_tier(69).daily_actions == 1
    assert reputation_tier(69).can_minus is False
    assert reputation_tier(70).can_minus is True
    assert reputation_tier(-1).key == "restricted"
    assert reputation_tier(95).discount == 10
    assert reputation_tier(40).discount == 2


def test_discount_rounds_up() -> None:
    assert discounted_price(5, 20) == 4
    assert discounted_price(5, 10) == 5
    assert discounted_price(1, 20) == 1


def test_reputation_phrases() -> None:
    assert reputation_delta(" +РЕП ") == 5
    assert reputation_delta("пошёл   нахуй") == -5
    assert reputation_delta("обычный текст") is None


def test_duration_parser() -> None:
    assert parse_duration("30m") == timedelta(minutes=30)
    assert parse_duration("2ч") == timedelta(hours=2)
    assert parse_duration("3d") == timedelta(days=3)
    assert parse_duration("nope") is None


def test_transfer_phrase() -> None:
    assert transfer_amount("перевести 100 печенек") == 100
    assert transfer_amount("ПЕРЕДАТЬ 2 🍪") == 2
    assert transfer_amount("перевести 10") == 10
    assert transfer_amount("перевести 1 печеньку") == 1
    assert transfer_amount("передать 21 печеньку") == 21
    assert transfer_amount("перевести много печенек") is None


def test_cookie_declensions() -> None:
    assert ru_plural(1, "печенька", "печеньки", "печенек") == "печенька"
    assert ru_plural(2, "печенька", "печеньки", "печенек") == "печеньки"
    assert ru_plural(5, "печенька", "печеньки", "печенек") == "печенек"
    assert ru_plural(21, "печенька", "печеньки", "печенек") == "печенька"
    assert ru_plural(22, "печенька", "печеньки", "печенек") == "печеньки"
    assert cookie_word(1) == "печенька"
    assert cookie_word(3, case="acc") == "печеньки"
    assert cookie_word(1, case="acc") == "печеньку"
    assert cookies_phrase(21) == "21 печенька"


def test_transfer_commission_by_tier() -> None:
    assert transfer_commission_percent(100) == 10
    assert transfer_commission_percent(80) == 20
    assert transfer_commission_percent(50) == 30


def test_win_after_commission_matches_transfer_rates() -> None:
    assert win_after_commission(100, 95) == (90, 10)
    assert win_after_commission(100, 80) == (80, 20)
    assert win_after_commission(100, 40) == (70, 30)
