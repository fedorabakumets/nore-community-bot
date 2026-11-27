import { randomUUID } from "node:crypto";
import { shuffleDeck } from "./cards";
import { compareScores, evaluateHand } from "./evaluator";
import type { Card, HandState, LegalActions, PlayerState, PokerAction, PotResult, RoomState } from "./types";

const MAX_SEATS = 5;

function nextPlayer(players: PlayerState[], fromSeat: number, predicate: (player: PlayerState) => boolean): PlayerState | undefined {
  for (let distance = 1; distance <= MAX_SEATS; distance += 1) {
    const seat = (fromSeat + distance) % MAX_SEATS;
    const player = players.find((candidate) => candidate.seat === seat && predicate(candidate));
    if (player) return player;
  }
}

function commit(player: PlayerState, amount: number): number {
  const paid = Math.max(0, Math.min(player.stack, amount));
  player.stack -= paid;
  player.bet += paid;
  player.committed += paid;
  player.allIn = player.stack === 0;
  return paid;
}

function activePlayers(room: RoomState): PlayerState[] {
  return room.players.filter((player) => !player.sittingOut && player.stack > 0);
}

function contenders(room: RoomState): PlayerState[] {
  return room.players.filter((player) => player.hole.length === 2 && !player.folded);
}

function draw(hand: HandState, count: number): Card[] {
  const cards = hand.deck.splice(0, count);
  if (cards.length !== count) throw new Error("Deck exhausted");
  return cards;
}

function setActor(room: RoomState, player: PlayerState | undefined, now: number): void {
  if (!room.hand) return;
  room.hand.actorId = player?.id ?? null;
  room.hand.deadlineAt = player ? now + (player.isBot ? 900 : room.settings.actionSeconds * 1000) : null;
}

export function legalActions(room: RoomState, playerId: string): LegalActions | null {
  const hand = room.hand;
  const player = room.players.find((candidate) => candidate.id === playerId);
  if (!hand || hand.street === "complete" || hand.actorId !== playerId || !player || player.folded || player.allIn) return null;
  const toCall = Math.max(0, hand.currentBet - player.bet);
  const maxRaiseTo = player.bet + player.stack;
  return {
    actorId: playerId,
    toCall,
    canFold: true,
    canCheck: toCall === 0,
    canCall: toCall > 0 && player.stack > 0,
    canRaise: maxRaiseTo > hand.currentBet && (!hand.actedIds.includes(playerId) || toCall >= hand.minRaise)
      && contenders(room).some((opponent) => opponent.id !== playerId && !opponent.allIn),
    minRaiseTo: hand.currentBet === 0 ? room.settings.bigBlind : hand.currentBet + hand.minRaise,
    maxRaiseTo,
  };
}

export function startHand(room: RoomState, now = Date.now(), deck = shuffleDeck()): RoomState {
  const eligible = activePlayers(room).sort((a, b) => a.seat - b.seat);
  if (eligible.length < 2) throw new Error("At least two funded players are required");

  for (const player of room.players) {
    player.bet = 0;
    player.committed = 0;
    player.folded = player.sittingOut || player.stack === 0;
    player.allIn = false;
    player.hole = [];
    player.lastAction = undefined;
  }

  const previousDealer = room.hand?.dealerSeat ?? eligible[eligible.length - 1].seat;
  const dealer = nextPlayer(eligible, previousDealer, () => true)!;
  const smallBlind = eligible.length === 2 ? dealer : nextPlayer(eligible, dealer.seat, () => true)!;
  const bigBlind = nextPlayer(eligible, smallBlind.seat, () => true)!;

  room.hand = {
    id: randomUUID(),
    street: "preflop",
    dealerSeat: dealer.seat,
    smallBlindSeat: smallBlind.seat,
    bigBlindSeat: bigBlind.seat,
    actorId: null,
    deck: [...deck],
    board: [],
    burns: [],
    currentBet: room.settings.bigBlind,
    minRaise: room.settings.bigBlind,
    actedIds: [],
    lastAggressorId: bigBlind.id,
    deadlineAt: null,
    nextHandAt: null,
    startedAt: now,
    winners: [],
    pots: [],
    message: "Карты розданы",
  };

  const dealOrder: PlayerState[] = [];
  let cursor = dealer.seat;
  for (let count = 0; count < eligible.length; count += 1) {
    const player = nextPlayer(eligible, cursor, () => true)!;
    dealOrder.push(player);
    cursor = player.seat;
  }
  for (let round = 0; round < 2; round += 1) {
    for (const player of dealOrder) player.hole.push(draw(room.hand, 1)[0]);
  }

  commit(smallBlind, room.settings.smallBlind);
  smallBlind.lastAction = `Обязательная ставка ${smallBlind.bet}`;
  commit(bigBlind, room.settings.bigBlind);
  bigBlind.lastAction = `Обязательная ставка ${bigBlind.bet}`;
  const actionable = eligible.filter((player) => !player.allIn);
  if (actionable.length < 2) room.hand.currentBet = Math.max(...eligible.map((player) => player.bet));
  if (!actionable.length || (actionable.length === 1 && actionable[0].bet === room.hand.currentBet)) {
    finishHand(room, now);
  } else {
    setActor(room, nextActor(room, bigBlind.seat), now);
  }
  room.updatedAt = now;
  return room;
}

function bettingComplete(room: RoomState): boolean {
  if (!room.hand) return true;
  return contenders(room).every((player) => player.allIn || (player.bet === room.hand!.currentBet && room.hand!.actedIds.includes(player.id)));
}

function nextActor(room: RoomState, fromSeat: number): PlayerState | undefined {
  const hand = room.hand!;
  return nextPlayer(room.players, fromSeat, (player) => !player.folded && !player.allIn && player.hole.length === 2 && (player.bet < hand.currentBet || !hand.actedIds.includes(player.id)));
}

function runBoardToFive(hand: HandState): void {
  while (hand.board.length < 5) {
    hand.burns.push(draw(hand, 1)[0]);
    hand.board.push(...draw(hand, hand.board.length === 0 ? 3 : 1));
  }
}

function buildPots(room: RoomState): Array<{ amount: number; eligible: PlayerState[] }> {
  const levels = [...new Set(room.players.filter((player) => player.committed > 0).map((player) => player.committed))].sort((a, b) => a - b);
  const pots: Array<{ amount: number; eligible: PlayerState[] }> = [];
  let previous = 0;
  for (const level of levels) {
    const contributors = room.players.filter((player) => player.committed >= level);
    const amount = (level - previous) * contributors.length;
    const eligible = contributors.filter((player) => !player.folded);
    if (amount > 0 && eligible.length > 0) pots.push({ amount, eligible });
    previous = level;
  }
  return pots;
}

function clockwiseFromDealer(players: PlayerState[], dealerSeat: number): PlayerState[] {
  return [...players].sort((a, b) => {
    const aDistance = (a.seat - dealerSeat + MAX_SEATS) % MAX_SEATS || MAX_SEATS;
    const bDistance = (b.seat - dealerSeat + MAX_SEATS) % MAX_SEATS || MAX_SEATS;
    return aDistance - bDistance;
  });
}

function finishHand(room: RoomState, now: number, uncontested?: PlayerState): void {
  const hand = room.hand!;
  const [highest, second] = [...room.players].sort((a, b) => b.committed - a.committed);
  const uncalled = highest.committed - (second?.committed ?? 0);
  if (uncalled > 0) {
    highest.committed -= uncalled;
    highest.bet = Math.max(0, highest.bet - uncalled);
    highest.stack += uncalled;
  }
  if (!uncontested) runBoardToFive(hand);
  const scores = new Map<string, ReturnType<typeof evaluateHand>>();
  if (!uncontested) {
    for (const player of contenders(room)) scores.set(player.id, evaluateHand([...player.hole, ...hand.board]));
  }

  const results: PotResult[] = [];
  const winnerAmounts = new Map<string, number>();
  for (const pot of buildPots(room)) {
    const winners = uncontested
      ? [uncontested]
      : pot.eligible.filter((player) => !pot.eligible.some((other) => compareScores(scores.get(other.id)!, scores.get(player.id)!) > 0));
    const ordered = clockwiseFromDealer(winners, hand.dealerSeat);
    const share = Math.floor(pot.amount / winners.length);
    let odd = pot.amount % winners.length;
    for (const winner of ordered) {
      const award = share + (odd > 0 ? 1 : 0);
      odd -= odd > 0 ? 1 : 0;
      winner.stack += award;
      winnerAmounts.set(winner.id, (winnerAmounts.get(winner.id) ?? 0) + award);
    }
    results.push({ amount: pot.amount, eligibleIds: pot.eligible.map((player) => player.id), winnerIds: winners.map((player) => player.id) });
  }

  hand.pots = results;
  hand.winners = [...winnerAmounts].map(([playerId, amount]) => {
    const player = room.players.find((candidate) => candidate.id === playerId)!;
    player.handsWon += 1;
    player.biggestPot = Math.max(player.biggestPot, amount);
    const score = scores.get(playerId);
    return { playerId, amount, handName: score?.name, cards: uncontested ? undefined : player.hole };
  });
  const winnerNames = hand.winners.map((winner) => room.players.find((player) => player.id === winner.playerId)?.name).join(" & ");
  const totalPot = [...winnerAmounts.values()].reduce((sum, amount) => sum + amount, 0);
  hand.street = "complete";
  hand.actorId = null;
  hand.deadlineAt = null;
  hand.nextHandAt = now + 5000;
  hand.message = uncontested ? `${winnerNames} забирает банк` : `${winnerNames} выигрывает банк`;
  room.history.unshift({ id: hand.id, at: now, text: hand.message, pot: totalPot });
  room.history = room.history.slice(0, 30);
}

function advanceStreet(room: RoomState, now: number): void {
  const hand = room.hand!;
  const live = contenders(room);
  const actionable = live.filter((player) => !player.allIn);
  if (hand.street === "river" || actionable.length <= 1) {
    finishHand(room, now);
    return;
  }

  hand.burns.push(draw(hand, 1)[0]);
  if (hand.street === "preflop") {
    hand.board.push(...draw(hand, 3));
    hand.street = "flop";
  } else if (hand.street === "flop") {
    hand.board.push(...draw(hand, 1));
    hand.street = "turn";
  } else {
    hand.board.push(...draw(hand, 1));
    hand.street = "river";
  }
  for (const player of room.players) player.bet = 0;
  hand.currentBet = 0;
  hand.minRaise = room.settings.bigBlind;
  hand.actedIds = [];
  hand.message = { preflop: "Префлоп", flop: "Флоп", turn: "Тёрн", river: "Ривер", complete: "Итог раздачи" }[hand.street];
  setActor(room, nextPlayer(room.players, hand.dealerSeat, (player) => !player.folded && !player.allIn && player.hole.length === 2), now);
}

export function applyPokerAction(room: RoomState, playerId: string, action: PokerAction, now = Date.now()): RoomState {
  const hand = room.hand;
  const player = room.players.find((candidate) => candidate.id === playerId);
  const legal = legalActions(room, playerId);
  if (!hand || !player || !legal) throw new Error("It is not this player's turn");

  if (action.type === "fold") {
    player.folded = true;
    player.lastAction = "Сбросил";
    hand.actedIds.push(player.id);
  } else if (action.type === "check") {
    if (!legal.canCheck) throw new Error("Checking is not legal");
    player.lastAction = "Пропустил";
    hand.actedIds.push(player.id);
  } else if (action.type === "call") {
    if (!legal.canCall) throw new Error("Calling is not legal");
    const paid = commit(player, legal.toCall);
    player.lastAction = player.allIn ? `Всё ${player.bet}` : `Уравнял ${paid}`;
    hand.actedIds.push(player.id);
  } else {
    if (!legal.canRaise) throw new Error("Raising is not legal");
    const amount = Math.trunc(action.amount);
    if (amount <= hand.currentBet || amount > legal.maxRaiseTo) throw new Error("Raise is outside the legal range");
    if (amount < legal.minRaiseTo && amount !== legal.maxRaiseTo) throw new Error("Raise is below the minimum");
    const previousBet = hand.currentBet;
    commit(player, amount - player.bet);
    const raiseSize = amount - previousBet;
    const fullRaise = raiseSize >= hand.minRaise;
    hand.currentBet = amount;
    hand.lastAggressorId = player.id;
    if (fullRaise) {
      hand.minRaise = raiseSize;
      hand.actedIds = [player.id];
    } else {
      hand.actedIds.push(player.id);
    }
    player.lastAction = player.allIn ? `Всё ${amount}` : `${previousBet === 0 ? "Ставка" : "Повысил до"} ${amount}`;
  }

  const remaining = contenders(room);
  if (remaining.length === 1) {
    finishHand(room, now, remaining[0]);
  } else if (bettingComplete(room)) {
    advanceStreet(room, now);
  } else {
    setActor(room, nextActor(room, player.seat), now);
  }
  room.updatedAt = now;
  return room;
}

export function processDeadline(room: RoomState, now = Date.now()): RoomState {
  const hand = room.hand;
  if (!hand) return room;
  if (hand.street === "complete" && hand.nextHandAt && now >= hand.nextHandAt && !room.paused && activePlayers(room).length >= 2) {
    return startHand(room, now);
  }
  if (hand.actorId && hand.deadlineAt && now >= hand.deadlineAt) {
    const legal = legalActions(room, hand.actorId);
    return applyPokerAction(room, hand.actorId, legal?.canCheck ? { type: "check" } : { type: "fold" }, now);
  }
  return room;
}

export function totalPot(room: RoomState): number {
  return room.players.reduce((sum, player) => sum + player.committed, 0);
}
