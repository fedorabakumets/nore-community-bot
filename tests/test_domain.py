from datetime import timedelta

from community_bot.domain import (
    discounted_price,
    parse_duration,
    reputation_delta,
    reputation_tier,
    transfer_amount,
)


def test_reputation_tiers_do_not_overlap() -> None:
    assert reputation_tier(100).key == "gold"
    assert reputation_tier(90).daily_actions == 5
    assert reputation_tier(89).key == "silver"
    assert reputation_tier(70).discount == 10
    assert reputation_tier(69).key == "bronze"
    assert reputation_tier(-1).key == "restricted"


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
    assert transfer_amount("перевести много печенек") is None
