import assert from "node:assert/strict";
import test from "node:test";
import { freshDeck } from "../src/lib/poker/cards";
import { evaluateFive } from "../src/lib/poker/evaluator";

const expected = [1_302_540, 1_098_240, 123_552, 54_912, 10_200, 5_108, 3_744, 624, 40];

test("all 2,598,960 five-card hands match canonical frequencies", {
  skip: process.env.EXHAUSTIVE_POKER_TEST !== "1" ? "run npm run test:exhaustive for the full verification" : false,
  timeout: 120_000,
}, () => {
  const deck = freshDeck();
  const frequencies = Array.from({ length: 9 }, () => 0);

  for (let a = 0; a < 48; a += 1) {
    for (let b = a + 1; b < 49; b += 1) {
      for (let c = b + 1; c < 50; c += 1) {
        for (let d = c + 1; d < 51; d += 1) {
          for (let e = d + 1; e < 52; e += 1) {
            frequencies[evaluateFive([deck[a], deck[b], deck[c], deck[d], deck[e]]).category] += 1;
          }
        }
      }
    }
  }

  assert.deepEqual(frequencies, expected);
});
