import { freshDeck } from "./cards";
import { compareScores, evaluateHand } from "./evaluator";
import { legalActions } from "./engine";
import type { BotStyle, Card, PokerAction, RoomState } from "./types";

function shuffle<T>(items: T[], random: () => number): T[] {
  const result = [...items];
  for (let index = result.length - 1; index > 0; index -= 1) {
    const target = Math.floor(random() * (index + 1));
    [result[index], result[target]] = [result[target], result[index]];
  }
  return result;
}

function preflopStrength(cards: Card[]): number {
  const values = cards.map((card) => "23456789TJQKA".indexOf(card[0]) + 2).sort((a, b) => b - a);
  const pair = values[0] === values[1];
  const suited = cards[0][1] === cards[1][1];
  const gap = values[0] - values[1];
  return Math.min(1, (values[0] + values[1]) / 28 + (pair ? 0.28 : 0) + (suited ? 0.06 : 0) + (gap <= 2 ? 0.05 : 0));
}

function estimateEquity(room: RoomState, playerId: string, random: () => number): number {
  const hand = room.hand!;
  const player = room.players.find((candidate) => candidate.id === playerId)!;
  if (hand.board.length === 0) return preflopStrength(player.hole);
  const opponents = Math.max(1, room.players.filter((candidate) => !candidate.folded && candidate.id !== playerId && candidate.committed > 0).length);
  const known = new Set([...player.hole, ...hand.board]);
  const unknown = freshDeck().filter((card) => !known.has(card));
  let score = 0;
  const simulations = 120;
  for (let iteration = 0; iteration < simulations; iteration += 1) {
    const sample = shuffle(unknown, random);
    const board = [...hand.board, ...sample.splice(0, 5 - hand.board.length)];
    const ours = evaluateHand([...player.hole, ...board]);
    const rivals = Array.from({ length: opponents }, () => evaluateHand([...sample.splice(0, 2), ...board]));
    const best = Math.max(...rivals.map((rival) => compareScores(rival, ours)));
    score += best < 0 ? 1 : best === 0 ? 0.5 : 0;
  }
  return score / simulations;
}

const STYLE: Record<BotStyle, { fold: number; raise: number; bluff: number }> = {
  tight: { fold: 0.42, raise: 0.72, bluff: 0.025 },
  balanced: { fold: 0.32, raise: 0.63, bluff: 0.06 },
  aggressive: { fold: 0.23, raise: 0.54, bluff: 0.13 },
};

export function chooseBotAction(room: RoomState, playerId: string, random = Math.random): PokerAction {
  const player = room.players.find((candidate) => candidate.id === playerId);
  const legal = legalActions(room, playerId);
  if (!player?.isBot || !legal) throw new Error("Bot cannot act now");
  const profile = STYLE[player.botStyle ?? "balanced"];
  const equity = estimateEquity(room, playerId, random);
  const pot = room.players.reduce((sum, candidate) => sum + candidate.committed, 0);
  const potOdds = legal.toCall > 0 ? legal.toCall / (pot + legal.toCall) : 0;
  const bluffing = random() < profile.bluff;

  if (legal.toCall > 0 && equity < Math.max(profile.fold, potOdds) && !bluffing) return { type: "fold" };
  if (legal.canRaise && (equity >= profile.raise || bluffing)) {
    const target = Math.min(legal.maxRaiseTo, Math.max(legal.minRaiseTo, room.hand!.currentBet + Math.max(room.settings.bigBlind, Math.round(pot * (bluffing ? 0.45 : 0.7)))));
    return { type: "raise", amount: target };
  }
  if (legal.canCheck) return { type: "check" };
  return { type: "call" };
}
