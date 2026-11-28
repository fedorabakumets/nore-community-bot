const assert = require("node:assert/strict");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.join(__dirname, "../community_bot/web");
const window = {};
const sandbox = vm.createContext({ window });
for (const name of ["dice-core.js", "dice.js"]) {
  vm.runInContext(fs.readFileSync(path.join(root, name), "utf8"), sandbox);
}
const { previewScenario, previewStep, previewStatus, previewDraw } = window.NoraDice;
const noop = () => {};
const ctx = new Proxy({}, {
  get: (t, k) => t[k] ?? noop,
  set: (t, k, v) => (t[k] = v, true),
});

test("all eighteen previews render and follow merge limits at every rank", () => {
  for (let i = 0; i < 18; i++) {
    for (let rank = 1; rank <= 7; rank++) {
      const s = previewScenario(i, rank);
      previewDraw(ctx, s);
      for (let j = 0; j < 240; j++) previewStep(s, 1 / 60);
      previewDraw(ctx, s);
      assert.ok(previewStatus(s), "empty preview status " + i);
      assert.ok(s.p.board.every(d => !d || (d.p >= 1 && d.p <= 7)));
      if (i >= 9 && i <= 16) assert.equal(s.merged, rank < 7 || i === 9 || i === 14);
      if (i === 8) assert.equal(s.p.board[7].p, Math.min(7, rank + 1));
      if (i === 17) assert.equal(s.p.board[12].i, 17);
    }
  }
});

test("special ability demonstrations change actual simulation state", () => {
  const simulate = (id, rank = 1) => {
    const s = previewScenario(id, rank);
    for (let j = 0; j < 240; j++) previewStep(s, 1 / 60);
    return s;
  };
  const joker = simulate(9, 3);
  assert.equal(joker.p.board[6].i, joker.p.board[8].i);
  assert.equal(joker.p.board[8].p, 3);
  const supplement = simulate(11, 3);
  assert.equal(supplement.p.board[8].i, 0);
  assert.equal(supplement.p.board[8].p, 4);
  assert.equal(simulate(12, 3).p.sp, 740);
  assert.equal(simulate(13).p.board.filter(Boolean).length, 2);
  assert.equal(simulate(14).p.board[6].i, 0);
  assert.equal(simulate(15).g.opp.board[7].p, 2);
  assert.equal(simulate(16).p.combo, 1);
  assert.ok(simulate(2).p.enemies.some(e => e.ice === 3));
  assert.ok(simulate(5).p.enemies.some(e => e.poison > 0));
});
