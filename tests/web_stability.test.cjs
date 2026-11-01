const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

function environment(script) {
  const docHandlers = {}, winHandlers = {}, nodes = new Map(), timers = [];
  function node(id) {
    const item = {
      id, dataset: {}, disabled: false, isConnected: true, textContent: '', value: '', style: {},
      classList: {add() {}, remove() {}, toggle() {}},
      getAttribute() { return null; }, hasAttribute() { return false; },
      addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
      replaceChildren() { this.innerHTML = ''; }, setAttribute() {},
      remove() { this.isConnected = false; nodes.delete('#' + id); },
      insertAdjacentHTML(_where, html) { this._html += html; register(html); },
    };
    Object.defineProperty(item, 'innerHTML', {
      get() { return this._html || ''; },
      set(html) { this._html = html; register(html); },
    });
    return item;
  }
  function register(html) {
    for (const match of String(html).matchAll(/\bid=["']([^"']+)["']/g)) {
      if (!nodes.has('#' + match[1])) nodes.set('#' + match[1], node(match[1]));
    }
  }
  const sheet = node('sheet');
  sheet.open = false;
  sheet.close = () => { sheet.open = false; };
  sheet.showModal = () => { sheet.open = true; };
  nodes.set('#sheet', sheet);
  for (const id of ['sheet-content', 'app', 'nav', 'toast', 'dismiss']) nodes.set('#' + id, node(id));
  const document = {
    hidden: false, body: {}, documentElement: {scrollHeight: 0},
    addEventListener(type, cb) { (docHandlers[type] ||= []).push(cb); },
    querySelector(selector) { return nodes.get(selector) || null; },
    querySelectorAll() { return []; },
    getElementById(id) { return nodes.get('#' + id) || null; },
  };
  const ctx = {
    document, console, URL, Date, Intl, Math, Number, String, Object, Array, Set, Map,
    Promise, Error, TypeError, JSON, encodeURIComponent, decodeURIComponent,
    auth: 'test-auth', tab: 'home', busy: false,
    data: {user: {user_id: 1, cookies: 10}, profile: {fill_percent: 100}},
    esc: value => String(value ?? ''), number: value => String(value ?? 0), plural: () => 'минут',
    toast() {}, render() {}, scrollTo() {},
    sheet(html) { nodes.get('#sheet-content').innerHTML = html; sheet.open = true; },
    setTimeout() { return 1; }, clearTimeout() {},
    setInterval(cb, ms) { timers.push({cb, ms}); return timers.length; }, clearInterval() {},
    queueMicrotask, performance: {now: () => 0},
    MutationObserver: class { observe() {} },
    crypto: {randomUUID: () => 'test-session'},
    location: {href: 'https://example.test/', hash: '', reload() {}},
    history: {pushState() {}, replaceState() {}},
    fetch: async () => ({}), tg: {}, NoraShop: {tabChanged() {}},
    NoraInteractive: {parent() {}, refreshCurrent() { return false; }},
    NoraSea: {refreshCurrent() { return false; }}, NoraCabinet: {parent() {}},
    addEventListener(type, cb) { (winHandlers[type] ||= []).push(cb); },
  };
  ctx.window = ctx;
  ctx.$ = selector => document.querySelector(selector);
  vm.createContext(ctx);
  if (script) vm.runInContext(fs.readFileSync('community_bot/web/' + script, 'utf8'), ctx, {filename: script});
  return {
    ctx, nodes, timers, sheet,
    run(code) { return vm.runInContext(code, ctx); },
    async doc(type, event) { await Promise.all((docHandlers[type] || []).map(cb => cb(event))); },
    async win(type, event = {}) { await Promise.all((winHandlers[type] || []).map(cb => cb(event))); },
    put(selector, value) { nodes.set(selector, value); },
    node,
  };
}

function button(id, dataset = {}) {
  return {id, dataset, disabled: false, isConnected: true, textContent: '',
    closest() { return this; }, hasAttribute() { return false; }};
}

const tick = () => new Promise(resolve => setImmediate(resolve));

test('notification read failure keeps unread status and offers retry', async () => {
  const e = environment();
  e.ctx.tab = 'notices';
  const posts = [];
  let failRead = true;
  e.ctx.api = async (_path, body) => {
    if (!body) return {items: [{id: 12, text: 'Новость', read: false, created_at: '2026-01-01'}], unread: 1, channels: []};
    posts.push(body);
    if (failRead) throw Error('Нет связи');
    return {ok: true, unread: 1}; // A newer notice arrived after the snapshot.
  };
  vm.runInContext(fs.readFileSync('community_bot/web/cabinet.js', 'utf8'), e.ctx);
  await e.ctx.NoraCabinet.reloadNotices();
  let html = e.ctx.NoraCabinet.noticesScreen();
  assert.match(html, /Новость/);
  assert.match(html, /новое/);
  assert.match(html, /Не удалось отметить/);
  assert.match(html, /data-notices-retry/);
  assert.equal(e.ctx.data.unread_notices, 1);
  failRead = false;
  await e.ctx.NoraCabinet.reloadNotices();
  html = e.ctx.NoraCabinet.noticesScreen();
  assert.doesNotMatch(html, /новое/);
  assert.equal(e.ctx.data.unread_notices, 1);
  assert.equal(posts[1].through_id, 12);
});

test('history and notification load errors are not shown as empty lists', async () => {
  const e = environment();
  e.ctx.tab = 'history';
  let fail = true;
  e.ctx.api = async path => {
    if (fail) throw Error('Нет связи');
    assert.match(path, /offset=0/);
    return {items: [{label: 'Покупка', amount: -1, date: '2026-01-01'}], has_more: false};
  };
  vm.runInContext(fs.readFileSync('community_bot/web/cabinet.js', 'utf8'), e.ctx);
  e.ctx.NoraCabinet.historyScreen();
  await tick();
  let html = e.ctx.NoraCabinet.historyScreen();
  assert.match(html, /history-retry/);
  assert.doesNotMatch(html, /Здесь появятся/);
  fail = false;
  await e.doc('click', {target: button('history-retry')});
  await tick();
  html = e.ctx.NoraCabinet.historyScreen();
  assert.match(html, /Покупка/);
  e.ctx.tab = 'notices';
  fail = true;
  await e.ctx.NoraCabinet.reloadNotices();
  html = e.ctx.NoraCabinet.noticesScreen();
  assert.match(html, /data-notices-retry/);
  assert.doesNotMatch(html, /Пока тихо/);
});

test('a failed history page preserves the last page and retries the requested offset', async () => {
  const e = environment();
  e.ctx.tab = 'history';
  let olderAttempts = 0;
  e.ctx.api = async path => {
    if (path.endsWith('offset=0')) return {items: [{label: 'Новая операция', amount: 1, date: '2026-01-01'}], has_more: true};
    assert.match(path, /offset=20/);
    if (++olderAttempts === 1) throw Error('Нет связи');
    return {items: [{label: 'Старая операция', amount: 1, date: '2025-01-01'}], has_more: false};
  };
  vm.runInContext(fs.readFileSync('community_bot/web/cabinet.js', 'utf8'), e.ctx);
  e.ctx.NoraCabinet.historyScreen();
  await tick();
  await e.doc('click', {target: button('history-older')});
  await tick();
  assert.match(e.ctx.NoraCabinet.historyScreen(), /Новая операция/);
  assert.match(e.ctx.NoraCabinet.historyScreen(), /history-retry/);
  await e.doc('click', {target: button('history-retry')});
  await tick();
  assert.match(e.ctx.NoraCabinet.historyScreen(), /Старая операция/);
  assert.equal(olderAttempts, 2);
});

test('a failed next page of community search preserves earlier results', async () => {
  const e = environment();
  let secondAttempts = 0;
  e.ctx.api = async path => {
    if (path.includes('offset=0')) return {items: [{id: 2, name: 'Первый'}], total: 2, next_offset: 50};
    if (++secondAttempts === 1) throw Error('Нет связи');
    return {items: [{id: 3, name: 'Второй'}], total: 2, next_offset: null};
  };
  vm.runInContext(fs.readFileSync('community_bot/web/community.js', 'utf8'), e.ctx);
  e.ctx.NoraCommunity.search();
  await tick();
  e.nodes.get('#community-search-more').onclick();
  await tick();
  assert.match(e.nodes.get('#community-search-results').innerHTML, /Первый/);
  e.nodes.get('#community-search-retry').onclick();
  await tick();
  const html = e.nodes.get('#community-search-results').innerHTML;
  assert.match(html, /Первый/);
  assert.match(html, /Второй/);
  assert.equal(secondAttempts, 2);
});

function lobby(title) {
  return {id: 'room1', title, status: 'lobby', bot: true, stake: 0, host_id: 1,
    players: [{id: 1, name: 'Игрок', ready: true}], ships_left: {}, timeline: []};
}

test('a stale Battleship poll cannot overwrite a completed action', async () => {
  const e = environment();
  e.ctx.tab = 'sea';
  const old = deferred();
  e.ctx.api = (path) => path === 'sea/action'
    ? Promise.resolve({room: lobby('Новая комната'), server_now: 100000}) : old.promise;
  vm.runInContext(fs.readFileSync('community_bot/web/sea.js', 'utf8'), e.ctx);
  const poll = e.ctx.NoraSea.load();
  await e.doc('click', {target: button('sea-create-bot')});
  await tick();
  assert.match(e.ctx.NoraSea.screen(), /Новая комната/);
  old.resolve({room: lobby('Старое состояние'), server_now: 99000});
  await poll;
  assert.match(e.ctx.NoraSea.screen(), /Новая комната/);
  assert.doesNotMatch(e.ctx.NoraSea.screen(), /Старое состояние/);
});

test('declining a Battleship invitation refreshes the community board', async () => {
  const e = environment();
  e.ctx.tab = 'community';
  let reloads = 0;
  e.ctx.NoraCommunity = {reload() { reloads++; }};
  e.ctx.api = async () => ({room: null, server_now: 100000});
  vm.runInContext(fs.readFileSync('community_bot/web/sea.js', 'utf8'), e.ctx);
  await e.doc('click', {target: button('', {seaRespond: 'no', roomId: 'room1'})});
  await tick();
  assert.equal(reloads, 1);
});

test('community reload after an invitation waits out an older board response', async () => {
  const e = environment();
  e.ctx.tab = 'community';
  const old = deferred();
  let requests = 0;
  e.ctx.NoraSea.inviteCard = item => `<p>${item.title}</p>`;
  e.ctx.NoraShop.svg = () => '';
  e.ctx.NoraInteractive.screen = () => '';
  e.ctx.NoraInteractive.icon = () => '';
  e.ctx.api = path => {
    if (path === 'community/presence') return Promise.resolve({});
    if (++requests === 1) return old.promise;
    return Promise.resolve({leaders: [], staff: [], sea_invites: [], revision_day: '2026-01-01'});
  };
  vm.runInContext(fs.readFileSync('community_bot/web/community.js', 'utf8'), e.ctx);
  const first = e.ctx.NoraCommunity.reload();
  e.ctx.NoraCommunity.reload();
  old.resolve({leaders: [], staff: [], sea_invites: [{title: 'Устаревшее приглашение'}]});
  await first;
  await tick();
  assert.equal(requests, 2);
  assert.doesNotMatch(e.ctx.NoraCommunity.screen(), /Устаревшее приглашение/);
});

test('Battleship clears the old room after leaving and counts down between polls', async () => {
  const e = environment();
  e.ctx.tab = 'sea';
  let clock = 0;
  e.ctx.performance.now = () => clock;
  const calls = [];
  const timer = e.node('sea-timer');
  e.put('#sea-timer', timer);
  e.ctx.api = async (path, body) => {
    calls.push(path);
    if (body) return {room: null, server_now: 100000};
    return {room: lobby('Комната'), server_now: 100000};
  };
  vm.runInContext(fs.readFileSync('community_bot/web/sea.js', 'utf8'), e.ctx);
  await e.ctx.NoraSea.load();
  await e.doc('click', {target: button('', {seaAction: 'cancel'})});
  await e.nodes.get('#sea-leave-confirm').onclick();
  await e.ctx.NoraSea.load();
  assert.equal(calls.at(-1), 'sea');

  // The server clock advances locally between network updates.
  const active = lobby('Бой');
  active.status = 'active'; active.deadline = 110000; active.turn = 1;
  active.players[0].shots = Array.from({length: 100}, () => ({fired: false}));
  active.players[0].board = Array.from({length: 100}, () => ({}));
  e.ctx.api = async () => ({room: active, server_now: 100000});
  await e.ctx.NoraSea.load();
  const updateTimer = e.timers.find(t => t.ms === 1000).cb;
  updateTimer();
  assert.equal(timer.textContent, '10с');
  clock = 3000;
  updateTimer();
  assert.equal(timer.textContent, '7с');
});

test('back navigation restores any permitted section, including events', async () => {
  const e = environment();
  e.ctx.tab = 'community';
  e.ctx.location.href = 'https://example.test/?view=events';
  let renders = 0;
  e.ctx.render = () => { renders++; };
  vm.runInContext(fs.readFileSync('community_bot/web/shop.js', 'utf8'), e.ctx);
  vm.runInContext(fs.readFileSync('community_bot/web/cabinet.js', 'utf8'), e.ctx);
  vm.runInContext(fs.readFileSync('community_bot/web/interactive.js', 'utf8'), e.ctx);
  await e.win('popstate');
  assert.equal(e.ctx.tab, 'events');
  assert.equal(renders, 1);
  e.ctx.location.href = 'https://example.test/#community';
  e.ctx.location.hash = '#community';
  await e.win('popstate');
  assert.equal(e.ctx.tab, 'community');
  e.ctx.data.profile.fill_percent = 20;
  e.ctx.location.href = 'https://example.test/?view=shop';
  await e.win('popstate');
  assert.equal(e.ctx.tab, 'home');
  e.ctx.location.href = 'https://example.test/?view=admin';
  await e.win('popstate');
  assert.equal(e.ctx.tab, 'home');
});

test('an incoming friend request is never labelled as sent', async () => {
  const e = environment();
  let message = '';
  e.ctx.toast = text => { message = text; };
  e.ctx.api = async () => ({message: 'У тебя уже есть входящий запрос'});
  vm.runInContext(fs.readFileSync('community_bot/web/people.js', 'utf8'), e.ctx);
  const b = button('', {personAdd: '2'});
  await e.doc('click', {target: b});
  assert.match(message, /входящий/);
  assert.equal(b.textContent, 'К друзьям и заявкам');
  b.onclick();
  assert.equal(e.ctx.tab, 'friends');
});

test('a delayed profile error cannot replace a different open sheet', async () => {
  const e = environment();
  const late = deferred();
  e.ctx.api = path => path === 'people/2' && !e.sheet.open
    ? Promise.resolve({id: 2, name: 'Друг', hidden: true, friend: false}) : late.promise;
  vm.runInContext(fs.readFileSync('community_bot/web/people.js', 'utf8'), e.ctx);
  await e.ctx.NoraPeople.visit(2);
  const refresh = e.timers.find(t => t.ms === 15000).cb();
  await e.doc('close', {target: e.sheet});
  e.nodes.get('#sheet-content').innerHTML = '<h2>Другая форма</h2>';
  e.sheet.open = true;
  late.reject(Error('Нет связи'));
  await refresh;
  assert.match(e.nodes.get('#sheet-content').innerHTML, /Другая форма/);
});

test('overview refresh ignores stale data and reports network errors in Russian', async () => {
  const e = environment();
  e.ctx.Telegram = {WebApp: {initData: 'test-auth', ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {}}};
  const bootstrap = deferred(), stale = deferred();
  let reads = 0;
  e.ctx.fetch = (path, options) => {
    if (options.method === 'POST') return Promise.resolve({ok: true, json: async () => ({ok: true})});
    if (path === '/api/me') return ++reads === 1 ? bootstrap.promise : stale.promise;
    return Promise.reject(Error('offline'));
  };
  vm.runInContext(fs.readFileSync('community_bot/web/app.js', 'utf8'), e.ctx);
  e.run("data={marker:'before',user:{user_id:1},profile:{fill_percent:100}}; render=()=>{};");
  const refresh = e.run('refresh()');
  await e.run("api('pet/action',{token:'test'})");
  e.run("data={marker:'after'}");
  stale.resolve({ok: true, json: async () => ({marker: 'stale'})});
  await refresh;
  assert.equal(e.run('data.marker'), 'after');
  await assert.rejects(e.run("api('network-test')"), /Нет связи с Норой/);
});

test('selecting the same avatar again works after an invalid file', async () => {
  const e = environment();
  e.ctx.Telegram = {WebApp: {initData: '', ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {}}};
  vm.runInContext(fs.readFileSync('community_bot/web/app.js', 'utf8'), e.ctx);
  const input = {id: 'avatar-file', files: [{type: 'image/gif', size: 100}], value: 'chosen.gif'};
  await e.doc('change', {target: input});
  assert.equal(input.value, '');
});

test('a failed avatar upload can retry the same file', async () => {
  const e = environment();
  e.ctx.Telegram = {WebApp: {initData: 'test-auth', ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {}}};
  const bootstrap = deferred();
  let attempts = 0;
  e.ctx.fetch = path => {
    if (path === '/api/me') return bootstrap.promise;
    attempts++;
    return Promise.reject(Error('offline'));
  };
  vm.runInContext(fs.readFileSync('community_bot/web/app.js', 'utf8'), e.ctx);
  e.run("data={revision:'test'}");
  const input = {id: 'avatar-file', files: [{type: 'image/png', size: 100}], value: 'chosen.png'};
  await e.doc('change', {target: input});
  assert.equal(input.value, '');
  input.value = 'chosen.png';
  await e.doc('change', {target: input});
  assert.equal(input.value, '');
  assert.equal(attempts, 2);
});

test('game and pet screens keep the Community navigation item selected', () => {
  const e = environment();
  e.ctx.Telegram = {WebApp: {initData: '', ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {}}};
  vm.runInContext(fs.readFileSync('community_bot/web/app.js', 'utf8'), e.ctx);
  e.ctx.NoraShop = {syncBack() {}};
  e.ctx.NoraCabinet = {petScreen: () => 'Питомец'};
  e.ctx.NoraInteractive = {handles: () => false, mount() {}};
  e.ctx.NoraSea = {handles: () => false, mount() {}};
  e.run("data={user:{profile_name:'Друг'},profile:{fill_percent:100},has_avatar:false}; tab='pet'; render()");
  assert.match(e.nodes.get('#nav').innerHTML, /class="active" data-tab="community"/);
});
