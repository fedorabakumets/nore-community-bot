import shutil
import subprocess
from pathlib import Path

import pytest


def test_community_opens_before_game_dependencies_load():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is required for the frontend regression test')
    root = Path(__file__).resolve().parents[1]
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const html = fs.readFileSync('community_bot/web/index.html', 'utf8');
const history = {state: null, replaceState(state) { this.state = state; }};
const storage = new Map();
let click, reloads = 0;
const context = {
  Image: class {}, data: {pet: null}, NoraShop: {svg: () => ''},
  document: {
    documentElement: {}, body: {querySelectorAll: () => []}, title: 'Нора — свои рядом',
    createTreeWalker: () => ({nextNode: () => null}),
    addEventListener(type, listener) { if (type === 'click' && !click) click = listener; },
    querySelectorAll: () => [],
  },
  NodeFilter: {SHOW_TEXT: 4}, history,
  localStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)},
  location: {reload: () => ++reloads},
  setInterval() {}, esc: String,
};
context.window = context;
vm.createContext(context);
// Respect the actual entry point's order, with the game still unopened.
for (const match of html.matchAll(/<script src="\/([^"?]+)(?:\?[^"]*)?" defer><\/script>/g)) {
  if (['i18n-en.js', 'i18n.js', 'nora-game.js', 'nora-records.js', 'community.js'].includes(match[1])) {
    vm.runInContext(fs.readFileSync('community_bot/web/' + match[1], 'utf8'), context);
  }
}
assert.equal(context.NoraVoxel, undefined);
assert.equal(context.NoraWorld, undefined);
assert.equal(context.NoraObservatory, undefined);
assert.equal(context.NoraI18n.language, 'ru');
assert.match(context.NoraI18n.button(), /English/);
for (let visit = 0; visit < 2; visit++) {
  const screen = context.NoraCommunity.screen();
  assert.ok(screen.includes('Коммьюнити'));
  assert.ok(screen.includes('data-record-gift'));
  assert.ok(screen.includes('nora-vinyl-art'));
  assert.ok(screen.includes('<svg'));
}
const button = {};
click({target: {closest: () => button}});
assert.equal(reloads, 1);
assert.equal(storage.get('nora-miniapp-language'), 'en');
vm.runInContext(fs.readFileSync('community_bot/web/i18n.js', 'utf8'), context);
assert.equal(context.document.documentElement.lang, 'en');
assert.match(context.NoraI18n.button(), /Русский/);
assert.ok(context.NoraCommunity.screen().includes('Community'));
assert.equal(context.NoraI18n.server('Не хватает печенек на ставку 7 🍪'), 'You need 7 🍪 to place this bet.');
'''
    subprocess.run([node, '-e', script], cwd=root, check=True, capture_output=True, text=True, encoding='utf-8')
