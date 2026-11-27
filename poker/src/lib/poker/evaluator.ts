import { combinations } from "./cards";
import { RANKS, type Card, type HandScore } from "./types";

const RANK_VALUE = new Map(RANKS.map((rank, index) => [rank, index + 2]));

function compareNumbers(a: number[], b: number[]): number {
  const length = Math.max(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    const difference = (a[index] ?? 0) - (b[index] ?? 0);
    if (difference !== 0) return difference;
  }
  return 0;
}

export function compareScores(a: HandScore, b: HandScore): number {
  return a.category - b.category || compareNumbers(a.kickers, b.kickers);
}

export function evaluateFive(cards: Card[]): HandScore {
  if (cards.length !== 5) throw new Error("A five-card hand is required");

  const values = cards.map((card) => RANK_VALUE.get(card[0] as (typeof RANKS)[number])!).sort((a, b) => b - a);
  const suits = cards.map((card) => card[1]);
  const counts = new Map<number, number>();
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1);
  const groups = [...counts.entries()].sort((a, b) => b[1] - a[1] || b[0] - a[0]);
  const unique = [...new Set(values)];
  const wheel = unique.join(",") === "14,5,4,3,2";
  const straightHigh = unique.length === 5 && (wheel || unique[0] - unique[4] === 4) ? (wheel ? 5 : unique[0]) : 0;
  const flush = suits.every((suit) => suit === suits[0]);

  if (flush && straightHigh) return { category: 8, kickers: [straightHigh], name: "Straight flush", cards };
  if (groups[0][1] === 4) return { category: 7, kickers: [groups[0][0], groups[1][0]], name: "Four of a kind", cards };
  if (groups[0][1] === 3 && groups[1][1] === 2) return { category: 6, kickers: [groups[0][0], groups[1][0]], name: "Full house", cards };
  if (flush) return { category: 5, kickers: values, name: "Flush", cards };
  if (straightHigh) return { category: 4, kickers: [straightHigh], name: "Straight", cards };
  if (groups[0][1] === 3) {
    return { category: 3, kickers: [groups[0][0], ...groups.slice(1).map(([value]) => value).sort((a, b) => b - a)], name: "Three of a kind", cards };
  }
  if (groups[0][1] === 2 && groups[1][1] === 2) {
    const pairs = [groups[0][0], groups[1][0]].sort((a, b) => b - a);
    return { category: 2, kickers: [...pairs, groups[2][0]], name: "Two pair", cards };
  }
  if (groups[0][1] === 2) {
    return { category: 1, kickers: [groups[0][0], ...groups.slice(1).map(([value]) => value).sort((a, b) => b - a)], name: "Pair", cards };
  }
  return { category: 0, kickers: values, name: "High card", cards };
}

export function evaluateHand(cards: Card[]): HandScore {
  if (cards.length < 5 || cards.length > 7) throw new Error("A poker hand needs five to seven cards");
  return combinations(cards, 5).map(evaluateFive).reduce((best, score) => compareScores(score, best) > 0 ? score : best);
}
