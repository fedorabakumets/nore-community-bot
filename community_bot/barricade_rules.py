"""Server-authoritative rules for NORA's two-player Barricade game."""
from collections import deque

SIZE = 9
WALLS = 10
TURN_SECONDS = 60
DIRECTIONS = ((-1, 0), (1, 0), (0, -1), (0, 1))


def start():
    return {"pawns": [[0, 4], [8, 4]], "walls": [], "stock": [WALLS, WALLS], "turn": 0}


def _cell(r, c):
    return 0 <= r < SIZE and 0 <= c < SIZE


def _edge(a, b):
    return (a, b) if a < b else (b, a)


def _segments(r, c, axis):
    if axis == "h":
        return (((r, c), (r + 1, c)), ((r, c + 1), (r + 1, c + 1)))
    return (((r, c), (r, c + 1)), ((r + 1, c), (r + 1, c + 1)))


def _barriers(game):
    return {edge for wall in game["walls"] for edge in _segments(*wall)}


def _neighbors(pos, blocked):
    r, c = pos
    for dr, dc in DIRECTIONS:
        dest = (r + dr, c + dc)
        if _cell(*dest) and _edge(pos, dest) not in blocked:
            yield dest


def moves(game, seat):
    own, other = (tuple(game["pawns"][i]) for i in (seat, 1 - seat))
    blocked = _barriers(game)
    result = []
    for dest in _neighbors(own, blocked):
        if dest != other:
            result.append(dest)
            continue
        jump = (2 * other[0] - own[0], 2 * other[1] - own[1])
        around = tuple(_neighbors(other, blocked))
        result.extend((jump,) if jump in around else (p for p in around if p != own))
    return result


def _path(start, goal, blocked):
    seen, todo = {start}, deque([start])
    while todo:
        pos = todo.popleft()
        if pos[0] == goal:
            return True
        for dest in _neighbors(pos, blocked):
            if dest not in seen:
                seen.add(dest)
                todo.append(dest)
    return False


def _wall_reason(game, r, c, axis, blocked, centers):
    segments = _segments(r, c, axis)
    if (r, c) in centers or blocked.intersection(segments):
        return "Здесь баррикада пересечёт или перекроет другую"
    paths = blocked.union(segments)
    if not all(_path(tuple(pawn), (SIZE - 1, 0)[seat], paths) for seat, pawn in enumerate(game["pawns"])):
        return "У обоих игроков должен остаться путь к цели"
    return None


def wall_options(game, seat):
    if not game["stock"][seat]:
        return []
    blocked = _barriers(game)
    centers = {(r, c) for r, c, _ in game["walls"]}
    return [(r, c, axis) for axis in ("h", "v") for r in range(SIZE - 1) for c in range(SIZE - 1)
            if not _wall_reason(game, r, c, axis, blocked, centers)]


def finish(game, loser, reason):
    # The existing two-seat settlement pays the entire pot to the other seat.
    game.update(result={"reason": reason, "loser": loser, "forfeit": []}, out=[])


def play(game, seat, move):
    if game["turn"] != seat:
        raise ValueError("Сейчас ход соперника")
    if not isinstance(move, dict):
        raise ValueError("Выбери действие на поле")
    kind, r, c, axis = (move.get(k) for k in ("kind", "row", "col", "axis"))
    if type(r) is not int or type(c) is not int or not _cell(r, c):
        raise ValueError("Выбери позицию на поле")
    if kind == "pawn" and move.keys() == {"kind", "row", "col"}:
        if (r, c) not in moves(game, seat):
            raise ValueError("В эту клетку сейчас нельзя пойти")
        game["pawns"][seat] = [r, c]
        if r == (SIZE - 1, 0)[seat]:
            finish(game, 1 - seat, "goal")
    elif kind == "wall" and move.keys() == {"kind", "row", "col", "axis"}:
        if axis not in ("h", "v") or max(r, c) >= SIZE - 1 or not game["stock"][seat]:
            raise ValueError("Здесь нельзя поставить баррикаду")
        reason = _wall_reason(game, r, c, axis, _barriers(game),
                              {(wr, wc) for wr, wc, _ in game["walls"]})
        if reason:
            raise ValueError(reason)
        game["walls"].append([r, c, axis])
        game["stock"][seat] -= 1
    else:
        raise ValueError("Выбери ход или установку баррикады")
    game["turn"] = 1 - seat
