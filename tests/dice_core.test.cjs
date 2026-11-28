const assert = require("node:assert/strict");
const { test } = require("node:test");
require("../community_bot/web/dice-core.js");
const C = globalThis.NoraDiceCore;
const make = (pool = [0, 8, 9, 10, 11], mode = "training") => C.create(pool, mode, () => .1);

test("summoning, power and all seven ranks", () => {
  const g = make(), p = g.you;
  assert.equal(C.dice.length, 18);
  assert.equal(p.board.length, 15);
  assert.ok(C.summon(g, p));
  assert.equal(p.sp, 490);
  assert.equal(p.cost, 20);
  assert.ok(C.power(p, 0));
  assert.equal(p.power[0], 2);
  for (let rank = 1; rank <= 6; rank++) {
    p.board.fill(null);
    C.add(g, p, 0, rank, 0);
    C.add(g, p, 0, rank, 1);
    assert.ok(C.merge(g, p, 0, 1));
    assert.equal(p.board[1].p, rank + 1);
    assert.equal(p.board[0], null);
  }
  C.add(g, p, 0, 7, 0);
  assert.equal(C.merge(g, p, 0, 1), false);
});

test("Joker, Mimic, Supplement and Switch respect matching pips", () => {
  const g = make(), p = g.you;
  C.add(g, p, 9, 3, 0);
  C.add(g, p, 0, 2, 1);
  assert.equal(C.merge(g, p, 0, 1), false);
  C.add(g, p, 0, 3, 2);
  assert.ok(C.merge(g, p, 0, 2));
  assert.equal(p.board[0].i, 0);
  assert.equal(p.board[2].p, 3);
  C.add(g, p, 10, 3, 3);
  assert.ok(C.merge(g, p, 3, 2));
  assert.equal(p.board[2].p, 4);
  C.add(g, p, 11, 4, 4);
  assert.ok(C.merge(g, p, 4, 2));
  assert.equal(p.board[2].p, 5);
  const original = p.board[2];
  C.add(g, p, 14, 5, 5);
  assert.ok(C.merge(g, p, 5, 2));
  assert.equal(p.board[5], original);
});

test("Growth, Sacrifice and Assassin", () => {
  const g = make([0,8,12,13,15], "duel"), p = g.you;
  C.add(g, p, 8, 1, 0);
  p.board[0].grow = .001;
  C.tick(g, .01);
  assert.equal(p.board[0].p, 2);
  C.add(g, p, 12, 1, 1);
  C.add(g, p, 12, 1, 2);
  const sp = p.sp;
  assert.ok(C.merge(g, p, 1, 2));
  assert.equal(p.sp, sp + 80);
  g.opp.board.fill(null);
  C.add(g, g.opp, 0, 2, 0);
  C.add(g, p, 15, 1, 3);
  C.add(g, p, 15, 1, 4);
  assert.ok(C.merge(g, p, 3, 4));
  assert.equal(g.opp.board[0].p, 1);
});

test("distinct projectile flight, splash, ice and boss skills", () => {
  const g = make([0,1,2,3,4]), p = g.you;
  C.add(g, p, 1, 1, 0);
  const e = C.spawn(g, p), other = C.spawn(g, p);
  e.pos = 50; other.pos = 49;
  const hp = e.h;
  C.tick(g, .01);
  assert.equal(e.h, hp);
  assert.ok(g.shots.some(s => s.arc === 28));
  for(let j=0;j<50;j++) C.tick(g, .01);
  assert.ok(e.h < hp && other.h < hp);
  const ice = make([0,1,2,3,4]), q = ice.you;
  C.add(ice, q, 2, 7, 0);
  const target=C.spawn(ice,q);target.h=target.max=10000;
  for(let j=0;j<200;j++) C.tick(ice,.01);
  assert.equal(target.ice, 3);
  const boss=C.spawn(ice,q,true);boss.h=boss.max=10000;boss.skill=.001;
  C.tick(ice,.01);
  assert.ok(ice.events.some(e=>e.kind==="boss"&&e.name==="KNIGHT"));
});

test("all dice can run through a long simulation without invalid state", () => {
  for(const pool of [[0,1,2,3,4],[5,6,7,8,9],[10,11,12,13,14],[15,16,17,0,8]]) {
    const g=make(pool,"duel");
    for(let i=0;i<15;i++) C.add(g,g.you,pool[i%5],(i%7)+1,i);
    for(let n=0;n<12000&&!g.done;n++){C.tick(g,1/120);g.events.length=0;}
    for(const p of [g.you,g.opp]) {
      assert.ok(Number.isFinite(p.sp));
      assert.ok(p.board.every(u=>!u||u.p>=1&&u.p<=7));
      assert.ok(p.enemies.every(e=>Number.isFinite(e.h)&&Number.isFinite(e.pos)));
    }
  }
});
