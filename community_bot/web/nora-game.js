'use strict';
(() => {
  let overlay = null, active = 0, requestedFullscreen = false, sceneStop = null;
  const defaults = { shirt: 'white', pants: 'blue_slim', shoes: 'white_stripes' };
  let outfit = { ...defaults };
  let music = null;
  const logo = '<span class="nora-game-logo">N<span>O</span>RA</span>';
  function createMusic() {
    let context = null, master = null, buffer = null, muted = false, closed = false, blocked = false;
    let button = null, panel = null, slider = null, muteButton = null, expanded = false, level = .4, nextStart = 0, overlap = 0;
    const sources = new Set();
    function update() {
      if (!button) return;
      const silent = muted || blocked || level === 0;
      button.setAttribute('aria-label', 'Настройки громкости');
      button.setAttribute('aria-expanded', String(expanded));
      button.innerHTML = silent ? '<span aria-hidden="true">🔇</span>' : '<span aria-hidden="true">🔊</span>';
      panel.hidden = !expanded;
      slider.value = Math.round(level*100);
      muteButton.textContent = muted || level === 0 ? 'Включить звук' : 'Выключить звук';
      muteButton.setAttribute('aria-pressed', String(muted || level === 0));
    }
    function volume(value, seconds) {
      if (!context || !master) return;
      const t = context.currentTime;
      master.gain.cancelScheduledValues(t);
      master.gain.setTargetAtTime(value, t, seconds);
    }
    function schedule() {
      if (closed || !buffer) return;
      const source = context.createBufferSource(), gain = context.createGain();
      const start = Math.max(context.currentTime + .02, nextStart), end = start + buffer.duration;
      source.buffer = buffer; source.connect(gain); gain.connect(master);
      gain.gain.setValueAtTime(0, start);
      gain.gain.linearRampToValueAtTime(1, start + overlap);
      gain.gain.setValueAtTime(1, end - overlap);
      gain.gain.linearRampToValueAtTime(0, end);
      sources.add(source); source.onended = () => { sources.delete(source); source.disconnect(); gain.disconnect(); if (!closed) schedule(); };
      source.start(start); nextStart = start + buffer.duration - overlap;
    }
    async function start() {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) { blocked = true; update(); return; }
      try {
        context = new AudioContext(); master = context.createGain(); master.gain.value = 0; master.connect(context.destination);
        await context.resume();
        if (closed) return;
        const response = await fetch('/game/nora-theme.mp3');
        if (!response.ok) throw Error('audio unavailable');
        const bytes = await response.arrayBuffer();
        buffer = await context.decodeAudioData(bytes);
        if (closed) return;
        if (!Number.isFinite(buffer.duration) || buffer.duration < .2) throw Error('invalid audio');
        overlap = Math.min(3, buffer.duration / 3);
        nextStart = context.currentTime + .03; schedule(); schedule();
        blocked = context.state !== 'running'; update();
        if (!muted) volume(level, .6);
      } catch (_) { if (!closed) { blocked = true; update(); } }
    }
    async function ensureAudio() {
      if (!context) { blocked = false; start(); return; }
      if (blocked || context.state !== 'running') {
        try { await context.resume(); blocked = context.state !== 'running'; } catch (_) { blocked = true; }
        if (!blocked && !buffer) { context.close(); context = null; start(); }
      }
    }
    function attach(parent) {
      button = document.createElement('button'); button.type = 'button'; button.className = 'nora-game-music';
      panel = document.createElement('div'); panel.className = 'nora-game-mixer';
      panel.innerHTML = '<label>Громкость <input type="range" min="0" max="100" step="1" aria-label="Громкость музыки"></label><button type="button" class="nora-game-mute"></button>';
      slider = panel.querySelector('input'); muteButton = panel.querySelector('button');
      button.onclick = async () => { expanded = !expanded; update(); if(expanded) await ensureAudio(); update(); };
      slider.oninput = async () => { level = Number(slider.value)/100; muted = level===0; await ensureAudio(); volume(muted?0:level,.12); update(); };
      muteButton.onclick = async () => { if(level===0)level=.4; muted=!muted; if(level>0 && muteButton.textContent==='Включить звук')muted=false; await ensureAudio(); volume(muted?0:level,.2); update(); };
      parent.appendChild(button);parent.appendChild(panel);update();
    }
    function close() {
      closed = true; button = null; panel = null;
      if (!context) return;
      const old = context; volume(0, .15);
      setTimeout(() => { for (const source of sources) { try { source.stop(); } catch (_) {} } sources.clear(); old.close().catch(() => {}); }, 750);
    }
    return {start,attach,close};
  }
  function close() {
    active++;
    music?.close(); music = null;
    sceneStop?.(); sceneStop = null;
    overlay?.remove(); overlay = null;
    if (requestedFullscreen) { try { tg?.exitFullscreen?.(); } catch (_) {} }
    requestedFullscreen = false;
    document.getElementById('nora-game-open')?.focus();
  }
  function frame(content) {
    if (!overlay) return;
    sceneStop?.(); sceneStop = null;
    overlay.classList.toggle('nora-world-active', content.includes('class="nora-world"'));
    overlay.innerHTML = `<div class="nora-game-inner"><button type="button" class="nora-game-back" aria-label="Вернуться к играм">← Игры</button><div class="nora-game-body">${content}</div><div class="nora-game-foot">NORA / НОВЫЙ МИР</div></div>`;
    overlay.querySelector('.nora-game-back').onclick = close;
    music?.attach(overlay);
  }
  async function world(nickname) {
    frame(`<div class="nora-world"><canvas aria-label="Стартовый остров Норы. Обзор поворачивается пальцем"></canvas><div class="nora-world-bar"><span>${esc(nickname)}<small>ЛЕСНАЯ ПОЛЯНА</small></span><button class="nora-world-outfit" type="button">Внешность</button></div><p class="nora-world-help">Джойстик / WASD — идти · Пробел — прыжок</p><button class="nora-world-action" type="button" hidden>Войти в таверну</button><button class="nora-world-view" type="button" aria-label="Сменить вид камеры">◉<small>ВИД</small></button><button class="nora-world-jump" type="button" aria-label="Прыжок">↑<small>ПРЫЖОК</small></button><div class="nora-world-joystick" role="group" aria-label="Джойстик передвижения"><span class="nora-world-knob"></span></div></div>`);
    const root = overlay.querySelector('.nora-world');
    root.querySelector('.nora-world-outfit').onclick = () => editor(nickname);
    try {
      const stop = await window.NoraWorld.mount(root.querySelector('canvas'), root, outfit);
      if (root.isConnected) sceneStop = stop; else stop();
    } catch (_) {
      if (root.isConnected) root.querySelector('.nora-world-help').textContent = 'Не удалось открыть 3D-мир. Закрой и открой игру снова.';
    }
  }
  function portal(nickname) {
    frame(`<div class="nora-game-portal-scene" aria-label="Вход в Нору"><div class="nora-game-portal"></div><span class="nora-game-portal-caption">ВХОД В НОРУ</span></div>`);
    const version = active;
    setTimeout(() => { if (version === active) editor(nickname); }, matchMedia('(prefers-reduced-motion: reduce)').matches ? 150 : 2100);
  }
  async function editor(nickname) {
    frame(`<div class="nora-editor"><header><span class="nora-game-kicker">ИГРОК / ${esc(nickname)}</span><h1>Твой персонаж</h1></header><div class="nora-editor-stage"><canvas aria-label="Трёхмерный персонаж, вращайте пальцем"></canvas><span class="nora-editor-hint">↔ ПОВЕРНИ ПЕРСОНАЖА</span></div><div class="nora-editor-controls"><div class="nora-editor-tabs"><button data-category="shirt" class="active">Футболка</button><button data-category="pants">Штаны</button><button data-category="shoes">Обувь</button></div><div class="nora-editor-options"></div><p class="nora-game-error" role="alert"></p><button class="nora-editor-save">ВОЙТИ В МИР <span>↗</span></button></div></div>`);
    const root = overlay.querySelector('.nora-editor');
    const choices = {
      shirt: [['white', 'Белая футболка'], ['gray', 'Серая футболка'], ['burgundy', 'Бордовая футболка']],
      pants: [['blue_slim', 'Узкие синие джинсы'], ['gray_slim', 'Узкие серые джинсы'], ['burgundy_wide', 'Широкие бордовые джинсы']],
      shoes: [['white_stripes', 'Белые кроссовки с чёрными полосками'], ['black_stripes', 'Чёрные кроссовки с белыми полосками'], ['red_air', 'Бордово-красные кроссовки с воздушной подошвой']],
    };
    let category = 'shirt';
    function options() {
      root.querySelector('.nora-editor-options').innerHTML = choices[category].map(([value, label]) => `<button data-choice="${value}" class="${outfit[category] === value ? 'selected' : ''}">${label}</button>`).join('');
    }
    root.querySelector('.nora-editor-tabs').onclick = e => { const b = e.target.closest('[data-category]'); if (!b) return; category = b.dataset.category; root.querySelectorAll('[data-category]').forEach(el => el.classList.toggle('active', el === b)); options(); };
    root.querySelector('.nora-editor-options').onclick = e => { const b = e.target.closest('[data-choice]'); if (!b) return; outfit[category] = b.dataset.choice; options(); root.dispatchEvent(new Event('outfit-change')); };
    root.querySelector('.nora-editor-save').onclick = async e => { const b = e.currentTarget; b.disabled = true; const version = active; try { await api('nora-game/outfit', outfit); if (version === active) { sceneStop?.(); sceneStop = null; world(nickname); } } catch (error) { if (version === active) { root.querySelector('.nora-game-error').textContent = error.message; b.disabled = false; } } };
    options();
    try { const stop = await window.NoraVoxel.mount(root.querySelector('canvas'), outfit, root); if (root.isConnected) sceneStop = stop; else stop(); }
    catch (_) { root.querySelector('.nora-editor-stage').textContent = '3D сейчас недоступно на этом устройстве'; root.querySelector('.nora-editor-save').disabled = true; }
  }
  function registration(message = '') {
    frame(`${logo}<div class="nora-game-mark" aria-hidden="true">✦</div><p class="nora-game-kicker">НОВЫЙ МИР ЖДЁТ</p><h1>Как тебя<br>звать в игре?</h1><p>Выбери имя для своей истории. Другие игроки увидят только игровой ник.</p><form class="nora-game-form"><label for="nora-game-nickname">ИГРОВОЙ НИКНЕЙМ</label><input id="nora-game-nickname" name="nickname" minlength="3" maxlength="16" pattern="[A-Za-z]{3,16}" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="YourName" required><small>3–16 латинских букв, без пробелов</small><p class="nora-game-error" role="alert">${esc(message)}</p><button type="submit">ВОЙТИ В НОРУ <span>↗</span></button></form>`);
    const form = overlay.querySelector('form');
    form.onsubmit = async (event) => {
      event.preventDefault();
      const button = form.querySelector('button'); button.disabled = true;
      const version = active;
      try { const result = await api('nora-game', { nickname: form.querySelector('input').value }); if (version === active) portal(result.nickname); }
      catch (error) { if (version === active) { form.querySelector('.nora-game-error').textContent = error.message; button.disabled = false; } }
    };
  }
  async function open() {
    if (overlay) return;
    const version = ++active;
    overlay = document.createElement('section'); overlay.className = 'nora-game-screen';
    overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-modal', 'true'); overlay.setAttribute('aria-label', 'Игра НОРА');
    document.body.appendChild(overlay);
    music = createMusic(); music.start();
    try { if (tg?.requestFullscreen && !tg.isFullscreen) { tg.requestFullscreen(); requestedFullscreen = true; } } catch (_) {}
    frame(`${logo}<p>Открываем новый мир…</p>`);
    try { const result = await api('nora-game'); if (version === active) { outfit = result.outfit || { ...defaults }; result.nickname ? (result.outfit ? world(result.nickname) : portal(result.nickname)) : registration(); } }
    catch (error) { if (version === active) { frame(`${logo}<h1>Не удалось открыть игру</h1><p>${esc(error.message)}</p><button class="nora-game-retry" type="button">Попробовать снова</button>`); overlay.querySelector('.nora-game-retry').onclick = () => { close(); open(); }; } }
  }
  document.addEventListener('click', event => { if (event.target.closest('#nora-game-open')) open(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && overlay) close(); });
})();
