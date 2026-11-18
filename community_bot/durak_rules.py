"""Server-side adaptation of JakiCuk's MIT Duren engine (see web/durak-cards/LICENSE).

Card identifiers, clockwise traversal, low-trump opening, bounded attacks and
refill order follow the upstream engine. All seat numbers are local to a table.
"""
from __future__ import annotations

import secrets
from copy import deepcopy

DEFAULTS = {
    "stake": 100, "players": 2, "deck": 36, "speed": "normal", "variant": "throw",
    "scope": "neighbours", "honesty": "fair", "ending": "classic", "private": False,
}
CHOICES = {
    "players": (2, 3, 4, 5, 6), "deck": (24, 36, 52), "speed": ("normal", "fast"),
    "variant": ("throw", "transfer"), "scope": ("neighbours", "all"),
    "honesty": ("fair", "cheats"), "ending": ("classic", "draw"),
}
SECONDS = {"normal": 60, "fast": 20}
REVIEW_SECONDS = 5


def settings(values):
    if not isinstance(values, dict) or values.keys() - DEFAULTS.keys():
        raise ValueError("Неизвестная настройка партии")
    config = DEFAULTS | values
    for key, value in config.items():
        if type(value) is not type(DEFAULTS[key]) or (key in CHOICES and value not in CHOICES[key]):
            raise ValueError("Проверь настройки партии")
    if not 5 <= config["stake"] <= 10_000:
        raise ValueError("Ставка должна быть от 5 до 10 000 печенек")
    if config["players"] * 6 > config["deck"]:
        raise ValueError("В колоде не хватит шести карт каждому. Выбери больше карт или меньше игроков")
    return config


def beats(defence, attack, trump):
    if defence % 4 == attack % 4:
        return defence // 4 > attack // 4
    return defence % 4 == trump


def deal(config, *, rng=None):
    deck = list(range(52 - config["deck"], 52))
    (rng or secrets.SystemRandom()).shuffle(deck)
    bottom = deck[-1]
    hands = [[] for _ in range(config["players"])]
    for _ in range(6):
        for hand in hands:
            hand.append(deck.pop(0))
    for hand in hands:
        hand.sort()
    trump = bottom % 4
    attacker = min(range(len(hands)), key=lambda p: min(
        (c for c in hands[p] if c % 4 == trump), default=52 + hands[p][0]))
    game = {
        "config": config, "hands": hands, "deck": deck, "trump": trump, "discard": [],
        "round": 1, "first_beaten": False, "out": [], "forfeit": [], "marked": [],
        "result": None, "events": [{"kind": "deal"}],
    }
    _open_round(game, attacker)
    return game


def _in(game, seat):
    return seat not in game["out"] and seat not in game["forfeit"]


def _ring(game, start):
    n = len(game["hands"])
    return [(start + i) % n for i in range(n) if _in(game, (start + i) % n)]


def _open_round(game, attacker):
    defender = _ring(game, attacker + 1)[0]
    game.update(attacker=attacker, defender=defender, origin=attacker, capacity=len(game["hands"][defender]),
                table=[], journal=[], passed=[], taking=False, transfers=0, phase="attack")


def _cap(game, capacity=None):
    limit = 6 if game["first_beaten"] else 5
    return min(limit, game["capacity"] if capacity is None else capacity)


def _throwers(game):
    ring = _ring(game, game["defender"] + 1)
    eligible = ring[:-1]
    if game["config"]["scope"] == "neighbours":
        eligible = [ring[-2], ring[0]]
    lead = game["attacker"]
    order = [lead, *eligible] if lead in eligible else eligible
    return [p for p in dict.fromkeys(order) if game["hands"][p] and p not in game["passed"]]


def _thrower(game):
    if len(game["table"]) >= _cap(game):
        return None
    return next(iter(_throwers(game)), None)


def turn(game):
    phase = game["phase"]
    if phase == "attack":
        return game["attacker"]
    if phase == "defend":
        return game["defender"]
    if phase == "throw":
        return _thrower(game)
    return None


def _table_ranks(game):
    return {c // 4 for pair in game["table"] for c in pair if c is not None}


def _can_transfer(game, card):
    table = game["table"]
    if game["config"]["variant"] != "transfer" or not table or game["taking"]:
        return False
    if any(d is not None or a // 4 != card // 4 for a, d in table):
        return False
    target = _ring(game, game["defender"] + 1)[0]
    return len(table) + 1 <= _cap(game, len(game["hands"][target]))


def moves(game, seat):
    """Only this seat's hand and public state affect its available controls."""
    result = []
    if not _in(game, seat) or game["phase"] in ("review", "finished"):
        return result
    phase, hand, table = game["phase"], game["hands"][seat], game["table"]
    relaxed = game["config"]["honesty"] == "cheats" and seat not in game["marked"]
    if phase == "attack" and seat == game["attacker"]:
        return [{"kind": "attack", "card": c} for c in hand]
    if phase == "defend" and seat == game["defender"]:
        result.append({"kind": "take"})
        for c in hand:
            if _can_transfer(game, c):
                result.append({"kind": "transfer", "card": c})
            for i, (a, d) in enumerate(table):
                if d is None and (relaxed or beats(c, a, game["trump"])):
                    result.append({"kind": "defend", "slot": i, "card": c})
    if phase in ("defend", "throw") and seat == _thrower(game):
        ranks = _table_ranks(game)
        result.extend({"kind": "attack", "card": c} for c in hand if relaxed or c // 4 in ranks)
        if phase == "throw":
            result.append({"kind": "pass"})
    return result


def _remember(game, seat, move, illegal):
    before = {k: game[k] for k in ("attacker", "defender", "capacity", "taking", "phase", "transfers")}
    before["passed"] = game["passed"][:]
    game["journal"].append({"seat": seat, **move, "illegal": illegal, "before": before})


def _rewind(game, index):
    entries = game["journal"][index:]
    for entry in reversed(entries):
        if entry["kind"] == "defend":
            game["table"][entry["slot"]][1] = None
        else:
            game["table"].pop()
        hand = game["hands"][entry["seat"]]
        hand.append(entry["card"])
        hand.sort()
    if entries:
        game.update(entries[0]["before"])
    del game["journal"][index:]


def _challenge(game, seat, card):
    if game["config"]["honesty"] != "cheats" or not _in(game, seat) or game["phase"] == "finished":
        raise ValueError("Оспорить карту сейчас нельзя")
    index = next((i for i, e in enumerate(game["journal"]) if e["card"] == card), None)
    if index is None or game["journal"][index]["seat"] == seat:
        raise ValueError("Выбери чужую карту на столе")
    accused = game["journal"][index]["seat"]
    illegal = game["journal"][index]["illegal"]
    marked = accused if illegal else seat
    if not illegal and marked in game["marked"]:
        raise ValueError("Карта сыграна по правилам")
    if marked not in game["marked"]:
        game["marked"].append(marked)
    if illegal:
        _rewind(game, index)
    game["events"].append({"kind": "challenge", "seat": seat, "marked": marked, "upheld": illegal})


def play(game, seat, move):
    if not isinstance(move, dict) or not isinstance(move.get("kind"), str):
        raise ValueError("Некорректный ход")
    if move["kind"] == "attack_many":
        _play_many(game, seat, move)
        return
    if any(type(v) is not int for k, v in move.items() if k != "kind"):
        raise ValueError("Некорректная карта")
    game["events"] = []
    kind = move["kind"]
    if kind == "challenge" and move.keys() == {"kind", "card"}:
        _challenge(game, seat, move["card"])
        return
    if move not in moves(game, seat):
        raise ValueError("Сейчас такой ход невозможен")
    card = move.get("card")
    if card is not None:
        illegal = (kind == "attack" and bool(game["table"]) and card // 4 not in _table_ranks(game)) or (
            kind == "defend" and not beats(card, game["table"][move["slot"]][0], game["trump"]))
        _remember(game, seat, move, illegal)
        game["hands"][seat].remove(card)
        game["passed"] = []
    game["events"].append({"seat": seat, **move})
    if kind == "attack":
        game["table"].append([card, None])
    elif kind == "defend":
        game["table"][move["slot"]][1] = card
    elif kind == "transfer":
        game["table"].append([card, None])
        game["attacker"] = seat
        game["defender"] = _ring(game, seat + 1)[0]
        game["capacity"] = len(game["hands"][game["defender"]])
        game["transfers"] += 1
    elif kind == "take":
        game["taking"] = True
        game["passed"] = []
    elif kind == "pass":
        game["passed"].append(seat)
    _advance(game)


def _play_many(game, seat, move):
    cards = move.get("cards")
    if (move.keys() != {"kind", "cards"} or not isinstance(cards, list) or not 2 <= len(cards) <= 6
            or any(type(c) is not int for c in cards) or len(set(cards)) != len(cards)):
        raise ValueError("Выбери от двух до шести разных карт")
    if not game["table"] and len({c // 4 for c in cards}) != 1:
        raise ValueError("Заходить несколькими картами можно только одного достоинства")
    if len(game["table"]) + len(cards) > _cap(game):
        raise ValueError("Столько карт подкинуть нельзя")
    # Commit the group only if each individual card is legal at its exact position.
    trial = deepcopy(game)
    events = []
    for card in cards:
        play(trial, seat, {"kind": "attack", "card": card})
        events.extend(trial["events"])
    trial["events"] = events
    game.update(trial)


def _classic_end(game):
    return (game["config"]["ending"] == "classic" and not game["deck"] and
            all(not game["hands"][p] for p in _ring(game, 0) if p != game["defender"]))


def _advance(game):
    if not _classic_end(game):
        if not game["taking"] and any(d is None for _, d in game["table"]):
            game["phase"] = "defend"
            return
        if _thrower(game) is not None:
            game["phase"] = "throw"
            return
    if game["config"]["honesty"] == "cheats":
        game["phase"] = "review"
    else:
        close_round(game)


def _finish(game, reason, loser=None):
    game["phase"] = "finished"
    game["result"] = {"reason": reason, "loser": loser, "forfeit": game["forfeit"][:]}
    game["events"].append({"kind": "finish", "reason": reason})


def close_round(game):
    if _classic_end(game):
        _finish(game, "played", game["defender"])
        return
    defender, attacker = game["defender"], game["attacker"]
    cards = [c for pair in game["table"] for c in pair if c is not None]
    if game["taking"]:
        game["hands"][defender].extend(cards)
        game["hands"][defender].sort()
        game["events"].append({"kind": "collect", "seat": defender, "cards": cards})
    else:
        game["discard"].extend(cards)
        game["first_beaten"] = True
        game["events"].append({"kind": "discard", "cards": cards})
    game["table"] = []
    game["journal"] = []
    order = [p for p in _ring(game, attacker) if p != defender] + [defender]
    for p in order:
        hand = game["hands"][p]
        count = min(len(game["deck"]), max(0, 6 - len(hand)))
        if count:
            hand.extend(game["deck"][:count])
            del game["deck"][:count]
            hand.sort()
            game["events"].append({"kind": "draw", "seat": p, "count": count})
    game["out"].extend(p for p in order if not game["hands"][p])
    remaining = _ring(game, defender + int(game["taking"]))
    if len(remaining) < 2:
        _finish(game, "played" if remaining else "draw", remaining[0] if remaining else None)
    else:
        game["round"] += 1
        _open_round(game, remaining[0])


def forfeit(game, seat, reason):
    if not _in(game, seat) or game["phase"] == "finished":
        raise ValueError("Ты уже закончил партию")
    # Abandon the interrupted bout. Return each card to its original owner before
    # removing the forfeiting hand, so a third player's cards cannot disappear.
    game["events"] = [{"kind": reason, "seat": seat}]
    _rewind(game, 0)
    game["discard"].extend(game["hands"][seat])
    game["hands"][seat] = []
    game["forfeit"].append(seat)
    remaining = _ring(game, game["origin"])
    if len(remaining) < 2:
        _finish(game, reason)
    else:
        game["round"] += 1
        _open_round(game, remaining[0])


def public_view(game, seat):
    return {
        "hand": game["hands"][seat], "counts": [len(h) for h in game["hands"]],
        "stock": len(game["deck"]), "trump": game["trump"], "bottom": game["deck"][-1] if game["deck"] else None,
        "discard": len(game["discard"]), "table": game["table"], "round": game["round"], "capacity": _cap(game),
        "attacker": game["attacker"], "defender": game["defender"], "turn": turn(game),
        "phase": game["phase"], "taking": game["taking"], "out": game["out"], "forfeit": game["forfeit"],
        "marked": game["marked"], "events": game["events"], "moves": moves(game, seat), "result": game["result"],
        "challenge": [e["card"] for e in game["journal"] if e["seat"] != seat]
        if game["config"]["honesty"] == "cheats" and _in(game, seat) and game["phase"] != "finished" else [],
    }
