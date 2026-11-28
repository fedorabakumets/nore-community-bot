import assert from "node:assert/strict";
import test from "node:test";
import { freshDeck } from "../src/lib/poker/cards";
import { compareScores, evaluateFive, evaluateHand } from "../src/lib/poker/evaluator";
import { applyPokerAction, legalActions, startHand, totalPot } from "../src/lib/poker/engine";
import type { Card, PlayerState, RoomState } from "../src/lib/poker/types";

function player(id: string, seat: number, stack = 2_000): PlayerState {
  return {
    id,
    tokenHash: id,
    name: id,
    avatar: seat,
    seat,
    stack,
    bet: 0,
    committed: 0,
    folded: false,
    allIn: false,
    sittingOut: false,
    connected: true,
    isBot: false,
    hole: [],
    handsWon: 0,
    biggestPot: 0,
    timeBankMs: 30_000,
  };
}

function room(players: PlayerState[]): RoomState {
  return {
    code: "TESTROOM",
    version: 1,
    hostId: players[0].id,
    settings: { smallBlind: 10, bigBlind: 20, buyIn: 2_000, actionSeconds: 25 },
    players,
    hand: null,
    paused: false,
    createdAt: 1,
    updatedAt: 1,
    history: [],
    chat: [],
    recentCommandIds: [],
  };
}

const hand = (cards: string[]) => evaluateFive(cards as Card[]);

test("orders every standard hand class", () => {
  const scores = [
    hand(["As", "Kd", "9c", "6h", "3s"]),
    hand(["As", "Ad", "9c", "6h", "3s"]),
    hand(["As", "Ad", "9c", "9h", "3s"]),
    hand(["As", "Ad", "Ac", "6h", "3s"]),
    hand(["9s", "8d", "7c", "6h", "5s"]),
    hand(["As", "Js", "9s", "6s", "3s"]),
    hand(["As", "Ad", "Ac", "9h", "9s"]),
    hand(["As", "Ad", "Ac", "Ah", "3s"]),
    hand(["9s", "8s", "7s", "6s", "5s"]),
  ];
  for (let index = 1; index < scores.length; index += 1) assert.ok(compareScores(scores[index], scores[index - 1]) > 0);
});

test("recognizes an ace-low straight and chooses the best five of seven", () => {
  assert.equal(hand(["As", "2d", "3c", "4h", "5s"]).name, "Straight");
  const score = evaluateHand(["As", "Ad", "Ac", "Kh", "Ks", "2c", "3d"]);
  assert.equal(score.name, "Full house");
  assert.deepEqual(score.kickers, [14, 13]);
});

test("starts three-handed with the correct positions and legal action", () => {
  const state = startHand(room([player("A", 0), player("B", 1), player("C", 2)]), 100, freshDeck());
  assert.equal(state.hand?.dealerSeat, 0);
  assert.equal(state.hand?.smallBlindSeat, 1);
  assert.equal(state.hand?.bigBlindSeat, 2);
  assert.equal(state.hand?.actorId, "A");
  assert.equal(legalActions(state, "A")?.toCall, 20);
  assert.equal(new Set(state.players.flatMap((candidate) => candidate.hole)).size, 6);
});

test("uses the dealer as small blind and first actor heads-up", () => {
  const state = startHand(room([player("A", 0), player("B", 3)]), 100, freshDeck());
  assert.equal(state.hand?.dealerSeat, 0);
  assert.equal(state.hand?.smallBlindSeat, 0);
  assert.equal(state.hand?.bigBlindSeat, 3);
  assert.equal(state.hand?.actorId, "A");
});

test("constructs main and side pots without losing chips", () => {
  const state = startHand(room([player("A", 0, 100), player("B", 1, 200), player("C", 2, 300)]), 100, freshDeck());
  applyPokerAction(state, "A", { type: "raise", amount: 100 }, 101);
  applyPokerAction(state, "B", { type: "raise", amount: 200 }, 102);
  applyPokerAction(state, "C", { type: "call" }, 103);
  assert.equal(state.hand?.street, "complete");
  assert.deepEqual(state.hand?.pots.map((pot) => pot.amount), [300, 200]);
  assert.equal(state.players.reduce((sum, candidate) => sum + candidate.stack, 0), 600);
  assert.equal(totalPot(state), 500);
});

test("rejects an undersized non-all-in raise", () => {
  const state = startHand(room([player("A", 0), player("B", 1), player("C", 2)]), 100, freshDeck());
  assert.throws(() => applyPokerAction(state, "A", { type: "raise", amount: 30 }, 101), /below the minimum/);
});

test("gives every player dealt in a turn before the flop, including players without a blind", () => {
  const state = startHand(room([player("A", 0), player("B", 1), player("C", 2), player("D", 3)]), 100, freshDeck());
  applyPokerAction(state, "D", { type: "fold" }, 101);
  assert.equal(state.hand?.actorId, "A");
  applyPokerAction(state, "A", { type: "call" }, 102);
  applyPokerAction(state, "B", { type: "call" }, 103);
  applyPokerAction(state, "C", { type: "check" }, 104);
  assert.equal(state.hand?.street, "flop");
  assert.equal(state.hand?.board.length, 3);
});

test("runs the board when a heads-up blind is all in and the other player has already matched it", () => {
  const state = startHand(room([player("A", 0, 5), player("B", 1)]), 100, freshDeck());
  assert.equal(state.hand?.street, "complete");
  assert.equal(state.hand?.actorId, null);
  assert.equal(state.hand?.board.length, 5);
  assert.equal(totalPot(state), 10);
  assert.equal(state.players.reduce((sum, candidate) => sum + candidate.stack, 0), 2005);
});
