import {cue, soundEnabled, supported as soundSupported, toggleSound, unlock} from '/barricade-audio.js?v=2';
import {attachBoard, buttonPosition, previewPosition} from '/barricade-board.js?v=1';

const endpoint = 'barricade';
const nonce = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const chips = n => number(n) + ' 🍪';
const btn = (action, label, cls = 'dk-secondary', extra = '') =>
  '<button type="button" class="' + cls + '" data-bc="' + action + '" ' + extra + '>' + label + '</button>';
const errorLabel = e => e.status && e.status < 500 ? e.message : 'Связь с Норой прервалась. Попробуй ещё раз.';
const avatar = person => '<span class="dk-avatar" data-person-avatar="' + person.id + '" ' +
  (person.avatar || person.has_avatar ? '' : 'data-avatar-unavailable') + '>' +
  esc(Array.from(person.name)[0] || '•') + '</span>';

let root, scene, screen, model, room, invited, friendList, selectedFriend, busy, sequence = 0;
let watch, timer, demoTimer, activeEntry, connected, selectedWall, placing, orientation, error;
let stamp, lastInvite, celebrated, actionNonce;
let stake = 5;

function heading(title, back = 'Баррикада') {
  const button = back === 'Игры'
    ? '<button class="dk-back" type="button" data-tab="games">← Игры</button>'
    : btn('back', '← ' + back, 'dk-back');
  return '<header class="dk-heading">' + button + '<h1>' + title + '</h1></header>';
}

function boardMarkup(extra = '') {
  return '<div class="bc-board ' + extra + '">' +
    '<canvas width="360" height="315" aria-hidden="true"></canvas><div class="bc-targets"></div></div>';
}

function soundButton() {
  return soundSupported() ? btn('sound', `<svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M4 9h4l5-4v14l-5-4H4z"/><path class="bc-sound-wave" d="M16 8a6 6 0 0 1 0 8m3-10a9 9 0 0 1 0 12"/>
    <path class="bc-sound-muted" d="m16 10 4 4m0-4-4 4"/></svg>`, 'bc-sound',
    'aria-label="Звук" aria-pressed="' + soundEnabled() + '"') : '';
}

function menuAction(action, label, sub, path) {
  return btn(action, `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"/></svg>
    <span><strong>${label}</strong>${sub ? '<small>' + sub + '</small>' : ''}</span>`, 'bc-menu-action');
}

function renderMenu() {
  const me = data.user;
  const name = me.profile_name || me.telegram_name || 'Участник';
  const canResume = model?.active?.kind === endpoint;
  const roomButtons = (model?.invites || []).map(item => btn('preview', '<span>' +
    esc(item.host_name) + '</span><small>Приглашение · ' + chips(item.config.stake) + '</small>',
  'bc-room dk-secondary', 'data-id="' + item.id + '"')).join('');
  const recentButtons = (model?.recent || []).filter(item => item.status === 'finished' || item.status === 'cancelled')
    .map(item => btn('resume', '<span>' + (item.status === 'finished' ? 'Завершённая партия' : 'Закрытая комната') +
      '</span><small>' + chips(item.config.stake) + '</small>', 'bc-room dk-secondary', 'data-id="' + item.id + '"')).join('');
  return heading('Баррикада', 'Игры') + '<div class="dk-player-strip">' +
    avatar({id: me.user_id, name, avatar: data.has_avatar && !data.avatar_video}) +
    '<strong>' + esc(name) + '</strong><span class="bc-balance">' + chips(model?.balance ?? me.cookies) + '</span>' + soundButton() + '</div>' +
    boardMarkup('bc-demo') +
    (canResume ? btn('resume', 'Вернуться к партии', 'dk-primary dk-wide', 'data-id="' + model.active.id + '"') : '') +
    '<div class="bc-menu-actions">' + btn('quick', window.NoraLogo.quickGame(), 'nora-quick-action') +
    menuAction('create', 'Создать игру', 'Приватная комната', 'M5 7v10m0-9h14m-3-3v14m-6-8h8') +
    menuAction('friends', 'Друзья', '', 'M8 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2 20v-3a5 5 0 0 1 5-5h2a5 5 0 0 1 5 5v3M16 4a3 3 0 0 1 0 6m1 3a5 5 0 0 1 5 5v2') +
    menuAction('items', 'Предметы', '', 'm3 9 9-5 9 5-9 5-9-5zm0 0v7l9 4 9-4V9m-9 5v6m-4-14 9 5') + '</div>' +
    (roomButtons ? '<section class="bc-list"><h2>Приглашения</h2>' + roomButtons + '</section>' : '') +
    (recentButtons ? '<details class="bc-panel"><summary>Последние партии</summary>' + recentButtons + '</details>' : '') +
    '<details class="bc-panel bc-rules"><summary>Правила игры</summary>' +
    '<p>Дойди до противоположной стороны. За ход можно передвинуть фигуру или поставить одну из 10 баррикад.</p>' +
    '<p>Через соседнюю фигуру можно перепрыгнуть. Если сзади стена или край поля, обходи сбоку. ' +
    'У обоих игроков всегда должен оставаться путь к цели.</p>' +
    '<p>На ход даётся 60 секунд. При сдаче или истечении времени банк получает соперник.</p></details>';
}

function restriction() {
  if (model?.active) return model.active.kind === endpoint ? 'Сначала заверши текущую партию.' :
    'Сначала закрой активный стол в «Дураке».';
  if (model?.restriction) return model.restriction;
  if (model && model.balance < 5) return 'Для игры нужно хотя бы 5 печенек.';
  return '';
}

function stakeScreen() {
  const quick = screen === 'quick';
  const maximum = Math.max(5, Math.min(10000, model?.balance ?? stake));
  const reason = restriction();
  return heading(quick ? 'Быстрая игра' : 'Создать игру') +
    '<form class="bc-panel bc-form"><p class="dk-muted">' +
    (quick ? 'Подберём соперника с такой же ставкой. Если его ещё нет, Нора позовёт игроков в основном чате.' :
      selectedFriend ? 'Приглашение получит ' + esc(selectedFriend.name) + '.' : 'Пригласи друга из Норы или отправь ссылку.') +
    '</p><label for="bc-stake">Ставка с игрока</label>' +
    '<div class="bc-presets">' + [5, 10, 25, 50, 100].map(value => btn('stake', chips(value), 'dk-secondary',
      'data-stake="' + value + '" aria-pressed="' + (stake === value) + '"' + (value > maximum ? ' disabled' : ''))).join('') +
    '</div><input id="bc-stake" name="stake" type="number" inputmode="numeric" min="5" max="' +
    maximum + '" required value="' + Math.min(stake, maximum) + '"><p class="dk-muted">Баланс ' +
    chips(model?.balance ?? data.user.cookies) + ' · Резерв при старте партии</p>' +
    (reason ? '<p class="bc-feedback">' + esc(reason) + '</p>' : '') +
    '<button type="submit" class="dk-primary dk-wide" ' + (!model || reason || busy ? 'disabled' : '') + '>' +
    (quick ? 'Найти соперника' : 'Создать приватную комнату') + '</button></form>';
}

function friendScreen() {
  const friends = (friendList || []).map(person => {
    const presence = person.presence;
    const status = presence?.visible ? (presence.online ? 'В сети' : 'Не в сети') : '';
    const details = [person.username ? '@' + person.username : '', status].filter(Boolean).join(' · ');
    const sent = room?.invited.includes(person.id);
    return '<div class="bc-friend">' + avatar(person) + '<span><strong>' + esc(person.name) +
      '</strong><small>' + esc(details) + '</small></span>' + btn('friend', sent ? 'Отправлено' : 'Позвать',
      'dk-secondary', 'data-id="' + person.id + '"' + (sent ? ' disabled' : '')) + '</div>';
  }).join('');
  return heading('Друзья', room ? 'Комната' : 'Баррикада') + '<div class="bc-panel bc-list">' +
    (friends || '<p class="dk-muted">' + (friendList ? 'В списке ещё нет друзей.' : 'Загружаем друзей…') + '</p>') +
    '<button type="button" class="dk-back" data-tab="friends">Список друзей Норы →</button></div>';
}

function inviteScreen() {
  return heading('Приглашение') + '<div class="bc-panel"><h2>' + esc(invited.host_name) +
    ' ждёт тебя</h2><p class="dk-muted">Ставка ' + chips(invited.config.stake) + ' · банк ' +
    chips(invited.config.stake * 2) + '</p><div class="dk-tools">' +
    btn('join', 'Сыграть на ' + chips(invited.config.stake), 'dk-primary', restriction() ? 'disabled' : '') +
    btn(invited.code || invited.config.quick ? 'back' : 'decline', invited.code || invited.config.quick ? 'В меню' : 'Отклонить') +
    '</div>' + (restriction() ? '<p class="bc-feedback">' + esc(restriction()) + '</p>' : '') + '</div>';
}

function waitingScreen() {
  const quick = room.config.quick;
  const title = quick ? 'Ищем соперника' : 'Приватная комната';
  return heading(title) + '<section class="bc-panel bc-wait"><i aria-hidden="true"></i><h2>' +
    (quick ? 'Подбираем игрока' : 'Ждём второго игрока') + '</h2><p class="dk-muted">Ставка ' +
    chips(room.config.stake) + ' · Резерв при старте партии</p>' +
    '<p class="bc-connection" role="status"></p>' +
    (quick ? '' : '<p class="bc-invited" role="status"></p><div class="dk-tools">' +
      btn('friends', 'Позвать друга', 'dk-primary') + btn('share', 'Поделиться в Telegram') + '</div>') +
    btn('cancel', 'Отменить ' + (quick ? 'поиск' : 'комнату')) + '</section>';
}

function playerCards() {
  return room.members.map((m, i) => '<div class="bc-player" data-seat="' + i + '">' + avatar(m) +
    '<div><strong>' + esc(m.name) + '</strong><small data-bc-player="' + i + '"></small></div></div>').join('');
}

function matchScreen() {
  return heading('Баррикада', 'Игры') + '<div class="bc-players">' + playerCards() + '</div>' +
    '<div class="bc-match-line"><strong class="bc-turn" role="status"></strong><time class="bc-clock"></time>' +
    '<span class="bc-pot">' + chips(room.config.stake) + '</span>' + soundButton() + '</div>' +
    boardMarkup() + '<p class="bc-connection" role="status"></p><div class="bc-actions"></div><div class="bc-end"></div>';
}

function render() {
  if (!root) return;
  scene?.close();
  scene = null;
  clearInterval(demoTimer);
  let html;
  if (screen === 'menu') html = renderMenu();
  else if (screen === 'quick' || screen === 'create') html = stakeScreen();
  else if (screen === 'friends') html = friendScreen();
  else if (screen === 'invite') html = inviteScreen();
  else if (screen === 'waiting') html = waitingScreen();
  else if (screen === 'match') html = matchScreen();
  else if (screen === 'items') html = heading('Предметы') + '<section class="bc-panel bc-items"><h2>Скоро</h2>' +
    '<p class="dk-muted">Здесь появится оформление фигур, баррикад и поля.</p></section>';
  else html = heading('Баррикада') + '<section class="bc-panel"><p>Открываем комнату…</p></section>';
  root.innerHTML = html + '<p class="bc-feedback" data-bc-error role="status"></p>';
  const canvas = root.querySelector('canvas');
  if (canvas) scene = attachBoard(canvas);
  if (screen === 'menu') animatePreview();
  if (screen === 'waiting' || screen === 'match') syncRoom();
  showError(error);
}

function animatePreview() {
  scene?.update(previewPosition, null, false);
  if (reduced()) return;
  let step = 0;
  const frames = [[[2, 6], [6, 2]], [[3, 6], [6, 2]], [[3, 6], [6, 3]], [[2, 6], [6, 3]]];
  demoTimer = setInterval(() => {
    if (!document.hidden && !reduced()) scene?.update({...previewPosition, pawns: frames[++step % frames.length]});
  }, 1750);
}

function showError(message = '') {
  error = message;
  const output = root?.querySelector('[data-bc-error]');
  if (output && output.textContent !== message) output.textContent = message;
}

function text(selector, value) {
  const element = root?.querySelector(selector);
  if (element && element.textContent !== value) element.textContent = value;
}

function clock() {
  if (room?.status !== 'playing' || screen !== 'match') return;
  const elapsed = (performance.now() - stamp) / 1000;
  const seconds = Math.max(0, Math.ceil(room.deadline - room.now - elapsed));
  text('.bc-clock', seconds + ' с');
}

function syncRoom() {
  if (!room || !root) return;
  const other = room.members[1 - room.own];
  const presence = other && room.presence?.[other.id];
  const disconnected = presence === 'offline' ? 'Соперник вне игры. Ждём возвращения…' : 'Соперник подключается…';
  text('.bc-connection', !connected ? 'Связь прервалась. Восстанавливаем…' :
    room.status === 'playing' && presence !== 'online' ? disconnected : '');
  if (screen === 'waiting') {
    text('.bc-invited', room.invited.length ? 'Приглашение отправлено · ждём ответа' :
      lastInvite ? 'Приглашение отклонено' : '');
  }
  if (screen !== 'match') return;
  const finished = room.status !== 'playing';
  if (!room.board) {
    root.querySelector('.bc-board').hidden = true;
  } else {
    const {stock, turn} = room.board;
    room.members.forEach((_, i) => {
      root.querySelector('[data-seat="' + i + '"]').classList.toggle('bc-current', !finished && turn === i);
      text('[data-bc-player="' + i + '"]', (i === room.own ? 'Ты · ' : '') + 'Стен ' + stock[i]);
    });
    scene?.update(room.board, selectedWall);
  }
  const actions = root.querySelector('.bc-actions');
  if (finished) {
    if (actions.hasChildNodes()) actions.replaceChildren();
    root.querySelector('.bc-targets').replaceChildren();
    text('.bc-turn', room.status === 'finished' ? 'Партия окончена' : 'Комната закрыта');
    text('.bc-clock', '');
    renderResult();
  } else {
    const {turn, stock} = room.board;
    const ownTurn = turn === room.own;
    text('.bc-turn', ownTurn ? 'Твой ход' : 'Ход соперника');
    const actionsKey = [room.rev, placing, orientation, selectedWall?.join('-'), busy, connected].join('/');
    if (actions.dataset.key !== actionsKey) {
      actions.dataset.key = actionsKey;
      updateControls(actions, ownTurn, stock[room.own]);
    }
    clock();
  }
}

function updateControls(actions, ownTurn, stock) {
  const targets = root.querySelector('.bc-targets');
  const active = ownTurn && connected && !busy;
  const positions = active ? (placing ? room.board.wall_options.filter(w => w[2] === orientation) : room.board.moves) : [];
  const targetHtml = positions.map(([r, c], i) => {
    const isSelected = placing && selectedWall?.[0] === r && selectedWall?.[1] === c;
    return btn(placing ? 'target' : 'move', '', 'bc-target ' + (placing ? 'bc-anchor' : 'bc-move'),
      'style="' + buttonPosition(c + (placing ? 1 : .5), r + (placing ? 1 : .5)) + '" data-r="' + r +
      '" data-c="' + c + '" tabindex="' + ((i === 0 || isSelected) && !(i === 0 && selectedWall && !isSelected) ? 0 : -1) +
      '" aria-label="' + (placing ? 'Баррикада' : 'Клетка') + ', ряд ' + (r + 1) + ', столбец ' + (c + 1) +
      '" aria-pressed="' + isSelected + '"');
  }).join('');
  const targetBefore = targets.contains(document.activeElement) ? document.activeElement.dataset : null;
  targets.innerHTML = targetHtml;
  if (targetBefore) targets.querySelector('[data-r="' + targetBefore.r + '"][data-c="' + targetBefore.c + '"]')?.focus();
  const actionBefore = actions.contains(document.activeElement) ? document.activeElement.dataset.bc : null;
  actions.innerHTML = '<div class="bc-modes">' +
    btn('pawn', 'Фигура', 'dk-secondary', 'aria-pressed="' + !placing + '"' + (active ? '' : ' disabled')) +
    btn('wall', 'Баррикада', 'dk-secondary', 'aria-pressed="' + placing + '"' + (active && stock ? '' : ' disabled')) +
    btn('surrender', 'Сдаться', 'dk-back', busy || !connected ? 'disabled' : '') + '</div>' +
    (placing && ownTurn ? '<div class="bc-orientation">' +
      btn('horizontal', '↔ Горизонтально', 'dk-secondary', 'aria-pressed="' + (orientation === 'h') + '"') +
      btn('vertical', '↕ Вертикально', 'dk-secondary', 'aria-pressed="' + (orientation === 'v') + '"') +
      btn('place', 'Поставить', 'dk-primary', active && selectedWall ? '' : 'disabled') + '</div>' : '');
  if (actionBefore) actions.querySelector('[data-bc="' + actionBefore + '"]')?.focus();
}

function renderResult() {
  const end = root.querySelector('.bc-end');
  if (end.hasChildNodes()) return;
  const win = room.status === 'finished' && room.result.loser !== room.own;
  const reason = {goal: 'Достигнута противоположная сторона.', surrender: 'Игрок сдался.', timeout: 'Время хода истекло.',
    technical: 'Партия прервана. Ставки возвращены.', expired: 'Время ожидания истекло.',
    unfunded: 'Для начала партии не хватило печенек.', account_reset: 'Комната закрыта. Ставки возвращены.',
    maintenance: 'Игра остановлена на обслуживание. Ставки возвращены.'}[room.result?.reason];
  end.innerHTML = '<section class="bc-panel bc-result"><h2>' +
    (win ? 'Победа!' : room.status === 'finished' ? 'Поражение' : 'Игра закрыта') + '</h2>' +
    (win ? '<strong class="bc-payout">+' + chips(room.members[room.own].payout) + ' в кошелёк</strong>' : '') +
    (reason ? '<p class="dk-muted">' + reason + '</p>' : '') + '<div class="dk-tools">' +
    btn('again', 'Играть снова', 'dk-primary') + btn('menu', 'В меню') + '</div></section>';
  if (win && celebrated !== room.id && !reduced()) {
    celebrated = room.id;
    const confetti = document.createElement('div');
    confetti.className = 'bc-confetti';
    confetti.setAttribute('aria-hidden', 'true');
    for (let i = 0; i < 28; i++) {
      const flake = document.createElement('i');
      flake.style.cssText = '--x:' + ((i * 37) % 99) + '%;--d:' + ((i * 13) % 22) / 100 + 's;--a:' + (i * 53) + 'deg';
      confetti.append(flake);
    }
    end.firstElementChild.append(confetti);
    setTimeout(() => confetti.remove(), 1400);
  }
}

function stop() {
  watch?.abort();
  watch = null;
  sequence++;
}

function change(next) {
  screen = next;
  showError();
  render();
}

async function loadMenu(entry) {
  const generation = sequence;
  try {
    const result = await api(endpoint);
    if (generation !== sequence || !root) return;
    model = result;
    if (entry?.quick) {
      if (model.active?.id === entry.quick) {openRoom(entry.quick);return;}
      const found = await api('games/quick/' + endpoint + '/' + entry.quick);
      if (generation !== sequence || !root) return;
      invited = found;
      change('invite');
    } else if (entry?.code) {
      const found = await api(endpoint + '/preview', {code: entry.code});
      if (generation !== sequence || !root) return;
      invited = {...found, code: entry.code};
      change('invite');
    } else if (entry?.id) {
      if (model.recent.some(item => item.id === entry.id)) openRoom(entry.id);
      else {
        invited = model.invites.find(item => item.id === entry.id);
        if (!invited) throw Object.assign(Error('Приглашение больше не действует'), {status: 400});
        change('invite');
      }
    } else if (entry?.restore && model.active?.kind === endpoint) {
      openRoom(model.active.id);
    } else if (['menu', 'quick', 'create', 'invite'].includes(screen)) render();
  } catch (err) {
    if (root && generation === sequence) showError(errorLabel(err));
  }
}

function soundForSnapshot(previous, next) {
  if (next.status === 'finished' && previous?.status === 'playing') {
    cue(next.result.loser === next.own ? 'loss' : 'win');
  } else if (next.status === 'playing' && previous?.status !== 'playing') {
    cue('start');
  } else if (previous?.board && next.board) {
    if (next.board.walls.length > previous.board.walls.length) cue('wall');
    else if (JSON.stringify(next.board.pawns) !== JSON.stringify(previous.board.pawns)) cue('move');
  }
}

function accept(view) {
  if (!root || (room && view.rev < room.rev)) return;
  connected = true;
  if (view.unchanged) {
    room.presence = view.presence;
    syncRoom();
    return;
  }
  const previous = room;
  soundForSnapshot(previous, view);
  room = view;
  stamp = performance.now();
  if (previous?.rev !== room.rev) {
    placing = false;
    selectedWall = null;
  }
  if (previous?.status === 'waiting' && previous.invited.length) lastInvite = true;
  const next = room.status === 'waiting' ? 'waiting' : 'match';
  if (screen !== next && !(screen === 'friends' && next === 'waiting')) change(next);
  else if (screen === 'friends') render();
  else syncRoom();
}

function delay(ms, signal) {
  return new Promise(resolve => {
    if (signal.aborted) {resolve();return;}
    const wake = () => {clearTimeout(wait);signal.removeEventListener('abort', wake);resolve();};
    const wait = setTimeout(wake, ms);
    signal.addEventListener('abort', wake, {once: true});
  });
}

async function stream(id, signal) {
  while (!signal.aborted) {
    if (document.hidden) return;
    try {
      const suffix = room?.id === id ? '?after=' + room.rev : '';
      const view = await api(endpoint + '/room/' + id + suffix, undefined, signal);
      if (signal.aborted) return;
      accept(view);
      if (room.status === 'finished' || room.status === 'cancelled') {
        loadMenu();
        return;
      }
      if (view.retry) await delay(view.retry * 1000, signal);
    } catch (err) {
      if (signal.aborted) return;
      connected = false;
      if (err.status === 400 || err.status === 403 || err.status === 404) {
        returnToMenu();
        showError(errorLabel(err));
        return;
      }
      syncRoom();
      if (!room) showError(errorLabel(err));
      await delay(1800, signal);
    }
  }
}

function openRoom(id, keep = false) {
  if (keep) watch?.abort();
  else stop();
  if (!keep) {
    room = null;
    lastInvite = false;
    activeEntry = id;
    change('loading');
  }
  if (document.hidden) return;
  watch = new AbortController();
  stream(id, watch.signal);
}

function returnToMenu() {
  stop();
  room = null;
  invited = null;
  activeEntry = null;
  selectedWall = null;
  selectedFriend = null;
  actionNonce = null;
  change('menu');
  loadMenu();
}

async function submitAction(action, fields, next) {
  if (busy || !root) return;
  const generation = sequence;
  const key = JSON.stringify({action, ...fields});
  if (actionNonce?.key !== key) actionNonce = {key, value: nonce()};
  const request = {action, ...fields, nonce: actionNonce.value};
  busy = true;
  showError();
  if (screen === 'match') syncRoom();
  root.querySelectorAll('form button[type="submit"], [data-bc="join"]').forEach(button => {button.disabled = true;});
  try {
    const reply = await api(endpoint + '/action', request);
    if (generation !== sequence || !root) return;
    actionNonce = null;
    busy = false;
    if (screen === 'match') syncRoom();
    await next?.(reply.id);
  } catch (err) {
    if (generation !== sequence || !root) return;
    if (err.status && err.status < 500) actionNonce = null;
    busy = false;
    if (screen === 'match') syncRoom();
    if (['create', 'quick', 'invite'].includes(screen)) render();
    showError(errorLabel(err));
  } finally {
    if (generation === sequence) busy = false;
  }
}

async function openFriends() {
  const at = sequence;
  change('friends');
  try {
    const result = await api('friends');
    if (at !== sequence || screen !== 'friends' || !root) return;
    friendList = result.friends;
    render();
  } catch (err) {
    if (at === sequence) showError(errorLabel(err));
  }
}

async function share() {
  try {
    const {url} = await api(endpoint + '/room/' + room.id + '/link');
    const link = 'https://t.me/share/url?url=' + encodeURIComponent(url) +
      '&text=' + encodeURIComponent('Сыграем в Баррикаду в Норе?');
    if (tg?.openTelegramLink) tg.openTelegramLink(link);
    else sheet('<h2>Приглашение в Баррикаду</h2><input value="' + esc(url) + '" readonly aria-label="Ссылка на игру">');
  } catch (err) {showError(errorLabel(err));}
}

function back() {
  if (!root || screen === 'menu' || screen === 'match') return false;
  if (screen === 'friends' && room) change(room.status === 'waiting' ? 'waiting' : 'match');
  else if (screen === 'waiting' || screen === 'loading' || busy) requestGameExit(returnToMenu);
  else returnToMenu();
  return true;
}

function click(event) {
  const button = event.target.closest('[data-bc]');
  if (!button || button.disabled) return;
  unlock();
  const {bc, id, r, c} = button.dataset;
  if (bc === 'sound') {
    toggleSound();
    button.setAttribute('aria-pressed', String(soundEnabled()));
  }
  if (bc === 'back') back();
  if (bc === 'menu') returnToMenu();
  if (bc === 'again') {
    stake = room.config.stake;
    const next = room.config.quick ? 'quick' : 'create';
    returnToMenu();
    change(next);
  }
  if (bc === 'resume') openRoom(id);
  if (bc === 'preview') {
    invited = model.invites.find(item => item.id === id);
    change('invite');
  }
  if (bc === 'join') submitAction(invited.config.quick ? 'join-quick' : 'join',
    invited.config.quick ? {room: invited.id} : {room: invited.id, code: invited.code}, openRoom);
  if (bc === 'decline') submitAction('decline', {room: invited.id}, returnToMenu);
  if (bc === 'quick' || bc === 'create' || bc === 'items') {
    selectedFriend = null;
    change(bc);
    if (!model) loadMenu();
  }
  if (bc === 'stake') {
    stake = Number(button.dataset.stake);
    root.querySelector('#bc-stake').value = stake;
    root.querySelectorAll('[data-bc="stake"]').forEach(el => el.setAttribute('aria-pressed', String(el === button)));
  }
  if (bc === 'friends') openFriends();
  if (bc === 'share') share();
  if (bc === 'friend') {
    const person = friendList.find(friend => friend.id === Number(id));
    if (room) submitAction('invite', {room: room.id, friend: person.id});
    else {
      selectedFriend = person;
      change('create');
      if (!model) loadMenu();
    }
  }
  if (bc === 'cancel') requestGameExit(returnToMenu);
  if (bc === 'surrender') goToTab('games');
  if (bc === 'pawn' || bc === 'wall' || bc === 'horizontal' || bc === 'vertical' || bc === 'target') {
    if (bc === 'pawn' || bc === 'wall') {
      placing = bc === 'wall';
      selectedWall = null;
    } else if (bc === 'target') {
      selectedWall = [Number(r), Number(c), orientation];
    } else {
      orientation = bc[0];
      selectedWall = room.board.wall_options.find(([row, col, axis]) =>
        row === selectedWall?.[0] && col === selectedWall?.[1] && axis === orientation) || null;
    }
    syncRoom();
  }
  if (bc === 'move' || bc === 'place') {
    const [row, col, axis] = bc === 'move' ? [Number(r), Number(c)] : selectedWall || [];
    if (row === undefined) return;
    const move = {kind: axis ? 'wall' : 'pawn', row, col, ...(axis ? {axis} : {})};
    submitAction('move', {room: room.id, rev: room.rev, move}, id => openRoom(id, true));
  }
}

function submit(event) {
  event.preventDefault();
  stake = Number(new FormData(event.target).get('stake'));
  submitAction(screen, {config: {stake}}, async id => {
    if (selectedFriend) {
      const person = selectedFriend;
      selectedFriend = null;
      try {await api(endpoint + '/action', {action: 'invite', room: id, friend: person.id, nonce: nonce()});}
      catch (err) {openRoom(id);showError(errorLabel(err));return;}
    }
    openRoom(id);
  });
}

function keydown(event) {
  const key = event.key;
  if (!key.startsWith('Arrow') || !event.target.matches('.bc-target')) return;
  event.preventDefault();
  const {r, c} = event.target.dataset;
  const candidates = [...root.querySelectorAll('.bc-target')].map(el =>
    ({el, dy: Number(el.dataset.r) - Number(r), dx: Number(el.dataset.c) - Number(c)}))
    .filter(({dx, dy}) => ({ArrowLeft: dx < 0, ArrowRight: dx > 0, ArrowUp: dy < 0, ArrowDown: dy > 0}[key]))
    .sort((a, b) => a.dx ** 2 + a.dy ** 2 - b.dx ** 2 - b.dy ** 2);
  if (!candidates.length) return;
  event.target.tabIndex = -1;
  candidates[0].el.tabIndex = 0;
  candidates[0].el.focus();
}

function visibility() {
  if (document.hidden) watch?.abort();
  else if (activeEntry && (!room || ['waiting', 'playing'].includes(room.status))) openRoom(activeEntry, true);
}

function mount(element, entry) {
  if (!element || root === element) return;
  root = element;
  root.classList.add('dk-root', 'bc-root');
  screen = entry?.create ? 'create' : 'menu';
  model = room = invited = friendList = selectedFriend = selectedWall = activeEntry = null;
  placing = busy = false;
  connected = true;
  orientation = 'h';
  error = '';
  for (const [type, fn] of Object.entries({click, submit, keydown})) root.addEventListener(type, fn);
  root.addEventListener('pointerdown', unlock);
  root.addEventListener('touchend', unlock, {passive: true});
  root.addEventListener('keydown', unlock);
  document.addEventListener('visibilitychange', visibility);
  timer = setInterval(clock, 250);
  render();
  loadMenu(entry || {restore: true});
}

function unmount() {
  if (!root) return;
  stop();
  scene?.close();
  scene = null;
  clearInterval(timer);
  clearInterval(demoTimer);
  root.removeEventListener('pointerdown', unlock);
  root.removeEventListener('touchend', unlock);
  root.removeEventListener('keydown', unlock);
  document.removeEventListener('visibilitychange', visibility);
  for (const [type, fn] of Object.entries({click, submit, keydown})) root.removeEventListener(type, fn);
  root = null;
}

export {mount, unmount, back};
