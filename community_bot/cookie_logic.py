from __future__ import annotations

import secrets

RANKS = "A23456789TJQK"
SUITS = "♠♥♦♣"
TRAP_DOORS = ("A", "B", "C")
TRAP_ROLES = ("trap", "safe", "stash")
TRAP_MAX_ROUNDS = 6
TRAP_WAITS = (5.5, 5.0, 4.5, 4.0, 3.5, 3.0)
DOOR_LABELS = {"A": "А", "B": "Б", "C": "В"}
ROLE_LABELS = {
    "trap": "💥 капкан",
    "safe": "✅ проход",
    "stash": "🍯 кладовая",
}


def hand_value(cards: list[str]) -> int:
    total = 0
    aces = 0
    for card in cards:
        rank = card[0]
        if rank == "A":
            total += 11
            aces += 1
        elif rank in {"T", "J", "Q", "K"}:
            total += 10
        else:
            total += int(rank)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def hand_score(cards: list[str]) -> int:
    """Comparable strength: bust = -1, natural 21 beats a built 21."""
    value = hand_value(cards)
    if value > 21:
        return -1
    if value == 21 and len(cards) == 2:
        return 22
    return value


def split_pot(amount: int, user_ids: list[int]) -> dict[int, int]:
    if amount <= 0 or not user_ids:
        return {}
    share, remainder = divmod(amount, len(user_ids))
    return {
        uid: share + (1 if index < remainder else 0)
        for index, uid in enumerate(sorted(user_ids))
    }


def settle_blackjack_pot(
    stake: int,
    order: list[int],
    hands: dict[int, list[str]],
    dealer: list[str],
) -> tuple[dict[int, int], dict[int, str], list[int]]:
    """Players fight for the pot. The dealer knocks people out but never takes a share.

    Among those who beat the dealer, the strongest hand takes the contested bank.
    Equal top hands split it. Pushes get the stake back and leave the pot.
    If nobody beat the dealer, stakes return — there is no player winner.
    """
    dealer_score = hand_score(dealer)
    dealer_bust = dealer_score < 0
    tags: dict[int, str] = {}
    scores: dict[int, int] = {}
    pushes: list[int] = []
    qualifiers: list[int] = []
    for uid in order:
        score = hand_score(list(hands[uid]))
        scores[uid] = score
        if score < 0:
            tags[uid] = "bust"
        elif not dealer_bust and score == dealer_score:
            tags[uid] = "push"
            pushes.append(uid)
        elif dealer_bust or score > dealer_score:
            tags[uid] = "qualify"
            qualifiers.append(uid)
        else:
            tags[uid] = "lose"

    if not qualifiers:
        return {uid: stake for uid in order}, tags, []

    contested = stake * len(order) - stake * len(pushes)
    best = max(scores[uid] for uid in qualifiers)
    champs = [uid for uid in qualifiers if scores[uid] == best]
    payouts: dict[int, int] = {uid: stake for uid in pushes}
    payouts.update(split_pot(contested, champs))
    for uid in champs:
        tags[uid] = "champ"
    return payouts, tags, champs


def deal_trap_doors(rng: secrets.SystemRandom | None = None) -> dict[str, str]:
    roll = rng or secrets.SystemRandom()
    roles = list(TRAP_ROLES)
    roll.shuffle(roles)
    return dict(zip(TRAP_DOORS, roles, strict=True))


def trap_wait(round_no: int) -> float:
    index = max(0, min(int(round_no) - 1, len(TRAP_WAITS) - 1))
    return float(TRAP_WAITS[index])


def apply_trap_round(
    alive: list[int],
    picks: dict[str, str],
    doors: dict[str, str],
    shields: dict[str, int] | dict[int, int],
) -> dict[str, object]:
    shield_map = {int(key): int(value) for key, value in shields.items() if int(value) > 0}
    deaths: dict[int, str] = {}
    saved: list[int] = []
    stash_pickers: list[int] = []
    timed_out: list[int] = []
    for uid in alive:
        door = picks.get(str(uid))
        if door not in doors:
            timed_out.append(uid)
            role = "trap"
        else:
            role = doors[door]
        if role == "stash":
            stash_pickers.append(uid)
        elif role == "trap":
            if shield_map.get(uid, 0) > 0:
                shield_map[uid] -= 1
                saved.append(uid)
            else:
                deaths[uid] = "timeout" if door not in doors else "trap"

    greed: list[int] = []
    stash_winner: int | None = None
    if len(stash_pickers) >= 2:
        greed = list(stash_pickers)
        for uid in greed:
            deaths[uid] = "greed"
    elif len(stash_pickers) == 1:
        stash_winner = stash_pickers[0]
        shield_map[stash_winner] = shield_map.get(stash_winner, 0) + 1

    survivors = [uid for uid in alive if uid not in deaths]
    if not survivors:
        return {
            "wipe": True,
            "survivors": list(alive),
            "shields": {int(key): int(value) for key, value in shields.items() if int(value) > 0},
            "deaths": deaths,
            "saved": saved,
            "greed": greed,
            "stash_winner": None,
            "timed_out": timed_out,
        }

    new_shields = {uid: count for uid, count in shield_map.items() if count > 0 and uid in survivors}
    return {
        "wipe": False,
        "survivors": survivors,
        "shields": new_shields,
        "deaths": deaths,
        "saved": saved,
        "greed": greed,
        "stash_winner": stash_winner,
        "timed_out": timed_out,
    }
