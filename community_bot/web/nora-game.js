'use strict';
(() => {
  let overlay = null, active = 0, requestedFullscreen = false, sceneStop = null;
  const defaults = { shirt: 'white', pants: 'blue_slim', shoes: 'white_stripes' };
  let outfit = { ...defaults };
  const logo = '<span class="nora-game-logo">N<span>O</span>RA</span>';
  function close() {
    active++;
    sceneStop?.(); sceneStop = null;
    overlay?.remove(); overlay = null;
    if (requestedFullscreen) { try { tg?.exitFullscreen?.(); } catch (_) {} }
    requestedFullscreen = false;
    document.getElementById('nora-game-open')?.focus();
  }
  function frame(content) {
    if (!overlay) return;
    overlay.innerHTML = `<div class="nora-game-inner"><button type="button" class="nora-game-back" aria-label="Вернуться к играм">← Игры</button><div class="nora-game-body">${content}</div><div class="nora-game-foot">NORA / НОВЫЙ МИР</div></div>`;
    overlay.querySelector('.nora-game-back').onclick = close;
  }
  function welcome(nickname) {
    frame(`${logo}<div class="nora-game-mark" aria-hidden="true">✦</div><p class="nora-game-kicker">ИГРОК / ${esc(nickname)}</p><h1>Добро пожаловать<br>в Нору</h1><p>Твой персонаж готов.</p>`);
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
      shirt: [['white', 'Белая'], ['gray', 'Серая'], ['burgundy', 'Бордовая']],
      pants: [['blue_slim', 'Узкие синие'], ['gray_slim', 'Узкие серые'], ['burgundy_wide', 'Широкие бордовые']],
      shoes: [['white_stripes', 'Белые Adidas'], ['black_stripes', 'Чёрные Adidas'], ['red_air', 'Бордовые Air Max 97']],
    };
    let category = 'shirt';
    function options() {
      root.querySelector('.nora-editor-options').innerHTML = choices[category].map(([value, label]) => `<button data-choice="${value}" class="${outfit[category] === value ? 'selected' : ''}">${label}</button>`).join('');
    }
    root.querySelector('.nora-editor-tabs').onclick = e => { const b = e.target.closest('[data-category]'); if (!b) return; category = b.dataset.category; root.querySelectorAll('[data-category]').forEach(el => el.classList.toggle('active', el === b)); options(); };
    root.querySelector('.nora-editor-options').onclick = e => { const b = e.target.closest('[data-choice]'); if (!b) return; outfit[category] = b.dataset.choice; options(); root.dispatchEvent(new Event('outfit-change')); };
    root.querySelector('.nora-editor-save').onclick = async e => { const b = e.currentTarget; b.disabled = true; const version = active; try { await api('nora-game/outfit', outfit); if (version === active) { sceneStop?.(); sceneStop = null; welcome(nickname); } } catch (error) { if (version === active) { root.querySelector('.nora-game-error').textContent = error.message; b.disabled = false; } } };
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
    try { if (tg?.requestFullscreen && !tg.isFullscreen) { tg.requestFullscreen(); requestedFullscreen = true; } } catch (_) {}
    frame(`${logo}<p>Открываем новый мир…</p>`);
    try { const result = await api('nora-game'); if (version === active) { outfit = result.outfit || { ...defaults }; result.nickname ? (result.outfit ? editor(result.nickname) : portal(result.nickname)) : registration(); } }
    catch (error) { if (version === active) { frame(`${logo}<h1>Не удалось открыть игру</h1><p>${esc(error.message)}</p><button class="nora-game-retry" type="button">Попробовать снова</button>`); overlay.querySelector('.nora-game-retry').onclick = () => { close(); open(); }; } }
  }
  document.addEventListener('click', event => { if (event.target.closest('#nora-game-open')) open(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && overlay) close(); });
})();
