import { randomInt } from "node:crypto";
import { RANKS, SUITS, type Card } from "./types";

export function freshDeck(): Card[] {
  return SUITS.flatMap((suit) => RANKS.map((rank) => `${rank}${suit}` as Card));
}

export function shuffleDeck(deck: Card[] = freshDeck()): Card[] {
  const shuffled = [...deck];
  for (let i = shuffled.length - 1; i > 0; i -= 1) {
    const j = randomInt(i + 1);
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
}

export function combinations<T>(items: T[], size: number): T[][] {
  const result: T[][] = [];
  const pick = (start: number, chosen: T[]) => {
    if (chosen.length === size) {
      result.push(chosen);
      return;
    }
    for (let index = start; index <= items.length - (size - chosen.length); index += 1) {
      pick(index + 1, [...chosen, items[index]]);
    }
  };
  pick(0, []);
  return result;
}
