"""Rules exercised through the same move validation and player views used by the Mini App."""
import itertools
import random

import pytest

from community_bot import durak_rules as game


def position(hands, *, stock=(), trump=3, **config):
    rules = game.settings({"players": len(hands), "deck": 52, **config})
    g = game.deal(rules, rng=random.Random(47))
    g.update(hands=[list(h) for h in hands], deck=list(stock), trump=trump, events=[])
    game._open_round(g, 0)
    return g


def play(g, seat, kind, card=None, slot=None):
    move = {"kind": kind}
    if card is not None:
        move["card"] = card
    if slot is not None:
        move["slot"] = slot
    game.play(g, seat, move)


def assert_cards(g, expected):
    cards = g["deck"] + g["discard"] + sum(g["hands"], []) + [c for pair in g["table"] for c in pair if c is not None]
    assert sorted(cards) == expected


def choose(g, rng):
    seat = game.turn(g)
    options = game.moves(g, seat)
    if g["phase"] == "defend":
        covers = [m for m in options if m["kind"] == "defend" and
                  game.beats(m["card"], g["table"][m["slot"]][0], g["trump"])]
        transfer = [m for m in options if m["kind"] == "transfer"]
        if transfer and rng.random() < .38:
            return seat, rng.choice(transfer)
        if covers:
            return seat, min(covers, key=lambda m: (m["card"] % 4 == g["trump"], m["card"]))
        return seat, {"kind": "take"}
    attacks = [m for m in options if m["kind"] == "attack" and
               (not g["table"] or m["card"] // 4 in game._table_ranks(g))]
    if attacks and (g["phase"] == "attack" or rng.random() < .72):
        return seat, rng.choice(attacks)
    return seat, {"kind": "pass"}


@pytest.mark.parametrize("players,deck", [(n, k) for n in range(2, 7) for k in (24, 36, 52) if n * 6 <= k])
@pytest.mark.parametrize("variant,scope,honesty,ending", list(itertools.product(
    ("throw", "transfer"), ("neighbours", "all"), ("fair", "cheats"), ("classic", "draw"))))
def test_complete_game_matrix(players, deck, variant, scope, honesty, ending):
    config = game.settings(dict(players=players, deck=deck, variant=variant, scope=scope,
                                honesty=honesty, ending=ending))
    rng = random.Random(players * deck + len(variant) + len(ending))
    g = game.deal(config, rng=rng)
    expected = list(range(52 - deck, 52))
    assert len(g["deck"]) == deck - players * 6
    assert all(len(h) == 6 for h in g["hands"])
    low = min((c for h in g["hands"] for c in h if c % 4 == g["trump"]), default=None)
    if low is not None:
        assert low in g["hands"][g["attacker"]]
    for _ in range(3000):
        assert_cards(g, expected)
        assert len(g["table"]) <= game._cap(g)
        if g["result"]:
            assert g["result"]["reason"] in ("draw", "played")
            assert ending != "classic" or g["result"]["loser"] is not None
            return
        if g["phase"] == "review":
            game.close_round(g)
        else:
            seat, move = choose(g, rng)
            game.play(g, seat, move)
    pytest.fail("Game did not terminate")


def test_settings_and_equal_deal_trump():
    for n in (5, 6):
        with pytest.raises(ValueError, match="не хватит"):
            game.settings({"deck": 24, "players": n})
    for bad in ({"players": True}, {"stake": 99}, {"stake": 10001}, {"private": "false"}, {"winner": 2}):
        with pytest.raises(ValueError):
            game.settings(bad)
    g = game.deal(game.settings({"deck": 24, "players": 4}), rng=random.Random(9))
    assert g["trump"] in range(4) and game.public_view(g, 0)["bottom"] is None
    assert all(not game.beats(c, c, g["trump"]) for c in range(52))


def test_transfer_capacity_and_no_transfer_after_defence():
    g = position([[16, 46], [17, 20, 21], [18, 28]], variant="transfer")
    play(g, 0, "attack", 16)
    play(g, 1, "transfer", 17)
    assert g["defender"] == 2
    with pytest.raises(ValueError):
        play(g, 2, "transfer", 18)  # Next player holds only one card.
    g = position([[16, 46], [17, 20, 21], [18, 28]], variant="transfer")
    play(g, 0, "attack", 16)
    play(g, 1, "defend", 20, 0)
    assert not any(m["kind"] == "transfer" for m in game.moves(g, 1))


def test_neighbours_take_throw_and_first_successful_bout_limit():
    g = position([[16, 17, 40], [24, 25, 26, 27, 28, 29], [18, 41], [19, 42]], scope="neighbours")
    play(g, 0, "attack", 16)
    play(g, 1, "take")
    play(g, 0, "attack", 17)
    play(g, 0, "pass")
    assert game.turn(g) == 2 and not game.moves(g, 3)
    play(g, 2, "attack", 18)
    play(g, 0, "pass")
    play(g, 2, "pass")
    assert {16, 17, 18} <= set(g["hands"][1]) and g["attacker"] == 2
    assert not g["first_beaten"]


@pytest.mark.parametrize("ending,reason", [("classic", "played"), ("draw", "draw")])
def test_last_attack_and_optional_draw(ending, reason):
    g = position([[16], [20]], ending=ending)
    play(g, 0, "attack", 16)
    if ending == "draw":
        play(g, 1, "defend", 20, 0)
    assert g["result"]["reason"] == reason


def test_cheat_rewind_suffix_mark_and_false_accusation():
    g = position([[16, 37, 44], [21, 24, 25], [17, 48]], honesty="cheats")
    play(g, 0, "attack", 16)
    play(g, 1, "defend", 21, 0)  # Different, non-trump suit.
    play(g, 0, "attack", 37)
    play(g, 2, "challenge", 21)
    assert g["table"] == [[16, None]] and 21 in g["hands"][1] and 37 in g["hands"][0]
    assert g["marked"] == [1] and g["phase"] == "defend"
    with pytest.raises(ValueError):
        play(g, 1, "defend", 21, 0)
    play(g, 2, "challenge", 16)
    assert g["marked"] == [1, 2] and g["table"] == [[16, None]]
    with pytest.raises(ValueError):
        play(g, 0, "challenge", 16)


def test_cheat_review_before_settlement_and_forfeit_restores_cards():
    g = position([[16], [21]], ending="draw", honesty="cheats")
    play(g, 0, "attack", 16)
    play(g, 1, "defend", 21, 0)
    assert g["phase"] == "review" and not g["result"]
    play(g, 0, "challenge", 21)
    assert g["phase"] == "defend" and g["hands"][1] == [21]
    g = position([[16, 48], [21, 24], [17, 40]])
    play(g, 0, "attack", 16)
    game.forfeit(g, 1, "timeout")
    assert g["hands"][0] == [16, 48] and g["defender"] == 2 and g["forfeit"] == [1]
    assert_cards(g, [16, 17, 21, 24, 40, 48])


def test_refill_order_and_view_secrecy():
    g = position([[16, 42], [20, 46], [22, 41]], stock=[4, 5, 6, 7, 8, 9])
    play(g, 0, "attack", 16)
    play(g, 1, "defend", 20, 0)
    play(g, 0, "pass")
    play(g, 2, "pass")
    assert g["hands"] == [[4, 5, 6, 7, 8, 42], [46], [9, 22, 41]]
    v = game.public_view(g, 0)
    assert v["hand"] == g["hands"][0] and v["counts"] == [6, 1, 3]
    assert not {"deck", "hands", "journal"} & v.keys()
    assert all("cards" not in e for e in v["events"] if e["kind"] == "draw")


def test_multi_card_opening_atomic_and_each_card_can_be_challenged():
    g = position([[16, 17, 21, 48], [24, 25, 26], [18, 41]], honesty="cheats")
    before = [h[:] for h in g["hands"]]
    with pytest.raises(ValueError):
        game.play(g, 0, {"kind": "attack_many", "cards": [16, 21]})
    with pytest.raises(ValueError):
        game.play(g, 0, {"kind": "attack_many", "cards": [16, 18]})
    assert g["table"] == [] and g["hands"] == before
    game.play(g, 0, {"kind": "attack_many", "cards": [16, 17]})
    assert g["table"] == [[16, None], [17, None]] and len(g["events"]) == 2
    play(g, 1, "defend", 24, 0)
    play(g, 0, "attack", 21)
    play(g, 2, "challenge", 21)
    assert g["table"] == [[16, 24], [17, None]] and 21 in g["hands"][0] and g["marked"] == [0]

