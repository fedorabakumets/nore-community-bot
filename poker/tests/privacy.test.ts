import assert from "node:assert/strict";
import test from "node:test";
import { freshDeck } from "../src/lib/poker/cards";
import { applyPokerAction, startHand } from "../src/lib/poker/engine";
import type { PlayerState, RoomState } from "../src/lib/poker/types";
import { snapshot } from "../src/lib/poker/view";

function player(id: string, seat: number): PlayerState {
  return { id, tokenHash: `secret-${id}`, name: id, avatar: seat, seat, stack: 2_000, bet: 0, committed: 0, folded: false, allIn: false, sittingOut: false, connected: true, isBot: false, hole: [], handsWon: 0, biggestPot: 0, timeBankMs: 30_000 };
}

test("a player snapshot never exposes another live hand or server secrets", () => {
  const room: RoomState = { code: "PRIVACY1", version: 1, hostId: "A", settings: { smallBlind: 10, bigBlind: 20, buyIn: 2_000, actionSeconds: 25 }, players: [player("A", 0), player("B", 1)], hand: null, paused: false, createdAt: 1, updatedAt: 1, history: [], chat: [], recentCommandIds: [] };
  startHand(room, 10, freshDeck());
  const view = snapshot(room, "A");
  assert.deepEqual(view.players.find((candidate) => candidate.id === "A")?.hole, room.players[0].hole);
  assert.deepEqual(view.players.find((candidate) => candidate.id === "B")?.hole, [null, null]);
  const encoded = JSON.stringify(view);
  assert.equal(encoded.includes("secret-A"), false);
  assert.equal(encoded.includes("tokenHash"), false);
  assert.equal(encoded.includes("deck"), false);
  assert.equal(encoded.includes("burns"), false);
  applyPokerAction(room, "A", { type: "fold" }, 11);
  assert.deepEqual(snapshot(room, "A").players[1].hole, [null, null]);
});
