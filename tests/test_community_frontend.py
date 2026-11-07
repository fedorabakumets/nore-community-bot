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
const context = {
  Image: class {}, data: {pet: null}, NoraShop: {svg: () => ''},
  document: {addEventListener() {}, querySelectorAll: () => []},
  setInterval() {}, esc: String,
};
context.window = context;
vm.createContext(context);
// Respect the actual entry point's order, with the game still unopened.
for (const match of html.matchAll(/<script src="\/([^\"]+)" defer><\/script>/g)) {
  if (['nora-game.js', 'nora-records.js', 'community.js'].includes(match[1])) {
    vm.runInContext(fs.readFileSync('community_bot/web/' + match[1], 'utf8'), context);
  }
}
assert.equal(context.NoraVoxel, undefined);
assert.equal(context.NoraWorld, undefined);
for (let visit = 0; visit < 2; visit++) {
  const screen = context.NoraCommunity.screen();
  assert.ok(screen.includes('Коммьюнити'));
  assert.ok(screen.includes('data-record-gift'));
  assert.ok(screen.includes('nora-vinyl-art'));
  assert.ok(screen.includes('<svg'));
}
'''
    subprocess.run([node, '-e', script], cwd=root, check=True, capture_output=True, text=True, encoding='utf-8')
