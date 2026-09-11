from community_bot.cookie_logic import (
    apply_trap_round,
    deal_trap_doors,
    hand_score,
    hand_value,
    settle_blackjack_pot,
    split_pot,
)


def test_blackjack_best_hand_takes_the_whole_player_pot() -> None:
    payouts, tags, champs = settle_blackjack_pot(
        10,
        [1, 2],
        {1: ["KS", "TS"], 2: ["9H", "TH"]},
        ["5C", "6D", "7S"],
    )
    assert champs == [1]
    assert payouts[1] == 20
    assert 2 not in payouts or payouts.get(2, 0) == 0
    assert tags[1] == "champ"
    assert tags[2] == "qualify"


def test_blackjack_dealer_bust_does_not_refund_everyone() -> None:
    payouts, tags, champs = settle_blackjack_pot(
        10,
        [1, 2],
        {1: ["KS", "9S"], 2: ["8H", "7D"]},
        ["KS", "QS", "5H"],
    )
    assert hand_value(["KS", "QS", "5H"]) > 21
    assert champs == [1]
    assert payouts[1] == 20
    assert tags[2] == "qualify"
    assert payouts.get(2, 0) == 0


def test_blackjack_natural_beats_built_twenty_one() -> None:
    assert hand_score(["AS", "KS"]) == 22
    assert hand_score(["7H", "7D", "7C"]) == 21
    payouts, tags, champs = settle_blackjack_pot(
        10,
        [1, 2],
        {1: ["AS", "KS"], 2: ["7H", "7D", "7C"]},
        ["5C", "6D", "6S"],
    )
    assert champs == [1]
    assert payouts[1] == 20
    assert tags[2] == "qualify"


def test_blackjack_all_lose_to_dealer_returns_stakes() -> None:
    payouts, tags, champs = settle_blackjack_pot(
        10,
        [1, 2],
        {1: ["KS", "8S"], 2: ["QH", "7D"]},
        ["AS", "KS"],
    )
    assert champs == []
    assert payouts == {1: 10, 2: 10}
    assert tags[1] == "lose"
    assert tags[2] == "lose"


def test_blackjack_push_leaves_the_pot_then_winner_takes_the_rest() -> None:
    payouts, tags, champs = settle_blackjack_pot(
        10,
        [1, 2, 3],
        {1: ["KS", "TS"], 2: ["QH", "9D"], 3: ["8H", "7C"]},
        ["TS", "9C"],
    )
    assert tags[2] == "push"
    assert champs == [1]
    assert payouts[1] == 20
    assert payouts[2] == 10
    assert payouts.get(3, 0) == 0


def test_split_pot_distributes_remainder_by_user_id() -> None:
    assert split_pot(10, [3, 1]) == {1: 5, 3: 5}
    assert split_pot(10, [3, 1, 2]) == {1: 4, 2: 3, 3: 3}


def test_trap_stash_gives_shield_to_a_lone_raider() -> None:
    result = apply_trap_round(
        [1, 2],
        {"1": "A", "2": "B"},
        {"A": "stash", "B": "safe", "C": "trap"},
        {},
    )
    assert result["wipe"] is False
    assert result["stash_winner"] == 1
    assert result["survivors"] == [1, 2]
    assert result["shields"] == {1: 1}


def test_trap_greed_collapses_the_stash() -> None:
    result = apply_trap_round(
        [1, 2, 3],
        {"1": "A", "2": "A", "3": "B"},
        {"A": "stash", "B": "safe", "C": "trap"},
        {},
    )
    assert result["wipe"] is False
    assert result["survivors"] == [3]
    assert result["deaths"] == {1: "greed", 2: "greed"}
    assert result["stash_winner"] is None


def test_trap_shield_saves_from_trap_and_timeout_is_a_trap() -> None:
    result = apply_trap_round(
        [1, 2],
        {"1": "C"},
        {"A": "safe", "B": "stash", "C": "trap"},
        {1: 1},
    )
    assert result["wipe"] is False
    assert result["survivors"] == [1]
    assert result["saved"] == [1]
    assert result["deaths"][2] == "timeout"


def test_trap_full_wipe_retries_without_killing_the_table() -> None:
    result = apply_trap_round(
        [1, 2],
        {"1": "C", "2": "C"},
        {"A": "safe", "B": "stash", "C": "trap"},
        {},
    )
    assert result["wipe"] is True
    assert result["survivors"] == [1, 2]


def test_deal_trap_doors_is_a_permutation() -> None:
    doors = deal_trap_doors()
    assert set(doors) == {"A", "B", "C"}
    assert set(doors.values()) == {"trap", "safe", "stash"}
