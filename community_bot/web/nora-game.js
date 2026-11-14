'use strict';
(() => {
  let overlay = null, active = 0, requestedFullscreen = false, sceneStop = null;
  let defaults;
  let outfit = { ...defaults };
  let wingState;
  let wingShop;
  const scripts = new Map();
  function loadScript(name) {
    if (!scripts.has(name)) scripts.set(name, new Promise((resolve, reject) => {
      const script = document.createElement("script"); script.src = "/" + name + ".js" + (name === "nora-companion" ? "?v=pet-game" : "");
      script.onload = resolve; script.onerror = () => { script.remove(); scripts.delete(name); reject(Error("Не удалось загрузить игру")); };
      document.head.appendChild(script);
    }));
    return scripts.get(name);
  }
  async function loadGame() {
    for (const name of ["nora-wings", "nora-voxel", "nora-scenery", "nora-companion", "nora-world"]) await loadScript(name);
    defaults = window.NoraVoxel.defaults; wingShop = window.NoraWings;
  }
  let helpDismissed = false;
  let music = null, entry = null, petTrigger = null;
  const settings = {pov: 100, music: 100, effects: 100};
  const logo = '<span class="nora-game-logo">N<span>O</span>RA</span>';
  function createMusic() {
    let context = null, master = null, buffer = null, muted = false, closed = false, blocked = false;
    let button = null, panel = null, slider = null, muteButton = null, expanded = false, level = .4, nextStart = 0, overlap = 0;
    const sources = new Set();
    let recordPlaying=true, selectedRecord='/game/nora-theme.mp3', trackVersion=0, recordOnce=false;
    const tracks=new Map();
    let musicGain=null, musicFilter=null, musicPan=null, musicLevel=null, effectsLevel=null, spatial={gain:1,cutoff:18000,pan:0};
    function positionMusic(value) {
      spatial=value;
      if(!context||!musicGain)return;
      musicGain.gain.setTargetAtTime(recordPlaying?value.gain:0,context.currentTime,.22);
      musicFilter.frequency.setTargetAtTime(value.cutoff,context.currentTime,.22);
      musicPan?.pan.setTargetAtTime(value.pan,context.currentTime,.18);
    }
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
      source.buffer = buffer; source.recordGain=gain; source.connect(gain); gain.connect(musicGain);
      gain.gain.setValueAtTime(0, start);
      gain.gain.linearRampToValueAtTime(1, start + overlap);
      gain.gain.setValueAtTime(1, end - overlap);
      gain.gain.linearRampToValueAtTime(0, end);
      sources.add(source); source.onended = () => { sources.delete(source); source.disconnect(); gain.disconnect(); if (!closed && !recordOnce) schedule(); };
      source.start(start); nextStart = start + buffer.duration - overlap;
    }
    async function selectRecord(url,force=false,once=recordOnce) {
      if(!force&&url===selectedRecord&&once===recordOnce)return;
      selectedRecord=url;recordOnce=once;const version=++trackVersion;
      for(const source of sources){source.onended=null;try{source.stop();}catch(_){}source.disconnect();source.recordGain?.disconnect();}
      sources.clear();buffer=null;
      if(!url||!context||closed)return;
      const current=context;
      try {
        if(!tracks.has(url))tracks.set(url,(async()=>{
          const response=await fetch(url);if(!response.ok)throw Error('audio unavailable');
          return current.decodeAudioData(await response.arrayBuffer());
        })());
        const decoded=await tracks.get(url);
        if(closed||version!==trackVersion||current!==context)return;
        if(!Number.isFinite(decoded.duration)||decoded.duration<.2)throw Error('invalid audio');
        buffer=decoded;overlap=recordOnce?0:Math.min(3,buffer.duration/3);nextStart=context.currentTime+.03;
        schedule();if(!recordOnce)schedule();blocked=context.state!=='running';update();
      }catch(_){tracks.delete(url);if(!closed&&version===trackVersion){blocked=true;update();}}
    }
    async function start() {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) { blocked = true; update(); return; }
      try {
        context = new AudioContext(); master = context.createGain(); master.gain.value = 0; master.connect(context.destination);
        musicLevel=context.createGain();musicLevel.gain.value=settings.music/100;musicLevel.connect(master); effectsLevel=context.createGain();effectsLevel.gain.value=settings.effects/100;effectsLevel.connect(master);
        musicGain=context.createGain();musicFilter=context.createBiquadFilter();musicFilter.type='lowpass';musicFilter.Q.value=.35;
        musicGain.connect(musicFilter);
        if(context.createStereoPanner){musicPan=context.createStereoPanner();musicFilter.connect(musicPan);musicPan.connect(musicLevel);}else musicFilter.connect(musicLevel);
        positionMusic(spatial);
        await context.resume();
        if (closed) return;
        await selectRecord(selectedRecord,true);
        if (!muted) volume(level, .6);
      } catch (_) { if (!closed) { blocked = true; update(); } }
    }
    async function ensureAudio() {
      if (!context) { blocked = false; start(); return; }
      if (blocked || context.state !== 'running') {
        try { await context.resume(); blocked = context.state !== 'running'; } catch (_) { blocked = true; }
        if (!blocked && !buffer && selectedRecord) { context.close(); context = null; start(); }
      }
    }
    function attach(parent) {
      button = document.createElement('button'); button.type = 'button'; button.className = 'nora-game-music';
      panel = document.createElement('div'); panel.className = 'nora-game-mixer';
      panel.innerHTML = '<label>Громкость <input type="range" min="0" max="100" step="1" aria-label="Громкость игры"></label><button type="button" class="nora-game-mute"></button>';
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
    function worldAudio() {
      let stopped = false, ambience = [], daylight = 1, indoors = false, distance = 0;
      recordPlaying=true; positionMusic({gain:.12,cutoff:1000,pan:0});
      const buffers = new Map();
      const names = ['birds_dawn', 'crickets', 'doorOpen_1', 'doorClose_1',
        'footstep_grass_000', 'footstep_grass_001', 'footstep_wood_000', 'footstep_wood_001'];
      function mix() {
        if (!context || stopped) return;
        for (const [i, item] of ambience.entries()) {
          if (!item) continue;
          item.gain.gain.setTargetAtTime(indoors ? 0 : (i === 0 ? daylight : 1-daylight)*.22, context.currentTime, 1.5);
        }
      }
      async function load() {
        await ensureAudio();
        if (!context || stopped) return;
        const audioContext = context;
        await Promise.all(names.map(async name => {
          try {
            const response = await fetch(`/game/sounds/${name}.mp3`);
            if (!response.ok) return;
            const data = await audioContext.decodeAudioData(await response.arrayBuffer());
            if (!stopped) buffers.set(name, data);
          } catch (_) { /* An unavailable effect must not interrupt the game. */ }
        }));
        if (stopped || context !== audioContext) return;
        for (const name of ['birds_dawn', 'crickets']) {
          const buffer = buffers.get(name);
          if (!buffer) { ambience.push(null); continue; }
          const source = context.createBufferSource(), gain = context.createGain();
          source.buffer = buffer; source.loop = true; gain.gain.value = 0;
          source.connect(gain); gain.connect(effectsLevel); source.start(); ambience.push({source, gain});
        }
        mix();
      }
      function play(name, gainValue = .55, rate = 1) {
        const buffer = buffers.get(name);
        if (stopped || !buffer || !context || context.state !== 'running') return;
        const source = context.createBufferSource(), gain = context.createGain();
        source.buffer = buffer; source.playbackRate.value = rate; gain.gain.value = gainValue;
        source.connect(gain); gain.connect(effectsLevel);
        source.onended = () => { source.disconnect(); gain.disconnect(); };
        source.start();
      }
      function step(inside, strength = 1) {
        const surface = inside ? 'wood' : 'grass';
        play(`footstep_${surface}_00${Math.random() < .5 ? 0 : 1}`, .5*strength, .92+Math.random()*.16);
      }
      load();
      return {
        update(inside, light, travelled, grounded) {
          if (indoors !== inside || Math.abs(daylight-light) > .01) { indoors = inside; daylight = light; mix(); }
          if (!grounded) { distance = 0; return; }
          distance += travelled;
          if (distance >= .65) { distance %= .65; step(inside); }
        },
        record(url, once=false) { if(!stopped)return selectRecord(url,false,once); },
        playing(value) { if(!stopped){recordPlaying=value;positionMusic(spatial);if(value)ensureAudio();} },
        spatial(value) { if(!stopped)positionMusic(value); },
        jump(inside) { distance = 0; step(inside, .8); },
        land(inside) { distance = 0; step(inside, 1.15); },
        door(inside) { play(inside ? 'doorOpen_1' : 'doorClose_1', .7); },
        stop() { stopped = true; recordPlaying=true; positionMusic({gain:1,cutoff:18000,pan:0}); for (const item of ambience) if (item) { try { item.source.stop(); } catch (_) {} item.source.disconnect(); item.gain.disconnect(); } ambience = []; },
      };
    }
    function setLevel(kind,value){settings[kind]=value;const gain=kind==='music'?musicLevel:effectsLevel;if(context&&gain)gain.gain.setTargetAtTime(value/100,context.currentTime,.05);}
    return {start,attach,close,worldAudio,setLevel};
  }
  function close() {
    active++;entry=null;
    const trigger = petTrigger;
    petTrigger = null;
    music?.close(); music = null;
    sceneStop?.(); sceneStop = null;
    overlay?.remove(); overlay = null;
    if (requestedFullscreen) { try { tg?.exitFullscreen?.(); } catch (_) {} }
    requestedFullscreen = false;
    (trigger || document.getElementById('nora-game-open'))?.focus();
    if (trigger && tab === 'pet') void refresh();
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
    frame(`<div class="nora-world"><canvas aria-label="Стартовый остров Норы. Обзор поворачивается пальцем"></canvas><div class="nora-world-bar"><span>${esc(nickname)}<small>ЛЕСНАЯ ПОЛЯНА</small></span><button class="nora-world-outfit" type="button">Внешность</button></div><p class="nora-world-help"${helpDismissed?' hidden':''}><span class="nora-world-help-copy">Джойстик / WASD — идти · Shift — бег · Пробел — прыжок</span><button class="nora-world-help-close" type="button" aria-label="Закрыть инструкцию движения">×</button></p><div class="nora-world-context"><button class="nora-world-action" type="button" hidden>Войти в таверну</button><button class="nora-world-action nora-record-toggle" type="button" aria-pressed="true" hidden>Выключить проигрыватель</button></div><button class="nora-world-view" type="button" aria-label="Сменить вид камеры">◉<small>ВИД</small></button><button class="nora-world-jump" type="button" aria-label="Прыжок">↑<small>ПРЫЖОК</small></button><button class="nora-world-sprint" type="button" aria-label="Спринт" aria-pressed="false">»<small>БЕГ</small></button><div class="nora-pet-actions" hidden><button type="button" class="nora-pet-open">Питомец</button><button type="button" class="nora-pet-stroke"><span aria-hidden="true">♥</span> Погладить <span aria-hidden="true">♥</span></button></div><dialog class="nora-pet-panel" aria-label="Мой питомец"><div class="nora-pet-content"></div><p class="nora-pet-message" role="status"></p><button type="button" class="nora-pet-close">Вернуться в мир</button></dialog><div class="nora-world-joystick" role="group" aria-label="Джойстик передвижения"><span class="nora-world-knob"></span></div></div>`);
    const root = overlay.querySelector('.nora-world');
    const back = overlay.querySelector('.nora-game-back');
    back.textContent='⚙ Настройки'; back.setAttribute('aria-label','Настройки игры');
    const dialog=document.createElement('dialog'); dialog.className='nora-settings'; dialog.setAttribute('aria-label','Настройки игры');
    dialog.innerHTML=`<h2>Настройки</h2><div class="nora-settings-menu"><button type="button" data-section="video">Видео</button><button type="button" data-section="sounds">Звуки</button><button type="button" class="nora-settings-continue">Продолжить</button><button type="button" class="nora-settings-exit">Вылезти из норы</button></div><div data-settings-section="video" hidden><h3>Видео</h3><label>Перспектива <span>1-е лицо — 3-е лицо</span><div class="nora-settings-control"><input type="range" min="0" max="100" step="1" data-setting="pov" aria-label="Перспектива"><input type="number" min="0" max="100" step="1" data-number="pov" aria-label="Значение перспективы"></div></label><button type="button" data-settings-back>Назад</button></div><div data-settings-section="sounds" hidden><h3>Звуки</h3><label>Музыка <output data-output="music"></output><input type="range" min="0" max="100" step="1" data-setting="music" aria-label="Громкость музыки"></label><label>Эффекты игры <output data-output="effects"></output><input type="range" min="0" max="100" step="1" data-setting="effects" aria-label="Громкость эффектов игры"></label><button type="button" data-settings-back>Назад</button></div>`;
    root.appendChild(dialog);
    function showSection(name){dialog.querySelector('.nora-settings-menu').hidden=!!name;dialog.querySelectorAll('[data-settings-section]').forEach(el=>{el.hidden=el.dataset.settingsSection!==name;});}
    function updateSetting(kind,value){if(!Number.isFinite(value))return;value=Math.max(0,Math.min(100,Math.round(value)));settings[kind]=value;dialog.querySelector(`[data-setting="${kind}"]`).value=value;const number=dialog.querySelector(`[data-number="${kind}"]`),output=dialog.querySelector(`[data-output="${kind}"]`);if(number)number.value=value;if(output)output.textContent=value+'%';if(kind==='pov')root.dispatchEvent(new CustomEvent('nora-pov',{detail:value}));else music?.setLevel(kind,value);}
    for(const kind of ['pov','music','effects'])updateSetting(kind,settings[kind]);
    root.addEventListener('nora-view-pov',e=>{settings.pov=e.detail;dialog.querySelector('[data-setting="pov"]').value=e.detail;dialog.querySelector('[data-number="pov"]').value=e.detail;});
    dialog.addEventListener('input',e=>{if(e.target.dataset.setting)updateSetting(e.target.dataset.setting,Number(e.target.value));});
    dialog.addEventListener('change',e=>{if(e.target.dataset.number)updateSetting(e.target.dataset.number,e.target.value===''?settings.pov:Number(e.target.value));});
    dialog.querySelectorAll('[data-section]').forEach(button=>button.onclick=()=>showSection(button.dataset.section));
    dialog.querySelectorAll('[data-settings-back]').forEach(button=>button.onclick=()=>showSection(null));
    dialog.querySelector('.nora-settings-continue').onclick=()=>dialog.close(); dialog.querySelector('.nora-settings-exit').onclick=close;
    back.onclick=()=>{showSection(null);root.dispatchEvent(new Event('nora-settings-open'));dialog.showModal();}; root.dataset.pov=String(settings.pov);
    root.dataset.recordGift = entry === 'record' ? '1' : '';
    root.dataset.playWithPet = entry === 'pet' ? '1' : '';
    entry = null;
    root.querySelector('.nora-world-outfit').onclick = () => editor(nickname);
    root.querySelector('.nora-world-help-close').onclick = () => {
      helpDismissed = true;
      root.querySelector('.nora-world-help').hidden = true;
    };
    const sounds = music?.worldAudio();
    try {
      const stop = await window.NoraWorld.mount(root.querySelector('canvas'), root, outfit, sounds);
      if (root.isConnected) sceneStop = stop; else stop();
    } catch (_) {
      sounds?.stop();
      if (root.isConnected) {
        root.querySelector('.nora-world-help').hidden = false;
        root.querySelector('.nora-world-help-copy').textContent = 'Не удалось открыть 3D-мир. Закрой и открой игру снова.';
      }
    }
  }
  function portal(nickname) {
    frame(`<div class="nora-game-portal-scene" aria-label="Вход в Нору"><div class="nora-game-portal"></div><span class="nora-game-portal-caption">ВХОД В НОРУ</span></div>`);
    const version = active;
    setTimeout(() => { if (version === active) editor(nickname); }, matchMedia('(prefers-reduced-motion: reduce)').matches ? 150 : 2100);
  }
  async function editor(nickname) {
    const categories = {gender:'Пол',hairstyle:'Причёска',hair_color:'Цвет волос',eye_color:'Цвет глаз',shirt:'Футболка',pants:'Штаны',shoes:'Обувь',wings:'Крылья'};
    const {choices, icon} = window.NoraVoxel;
    frame(`<div class="nora-editor"><header><span class="nora-game-kicker">ИГРОК / ${esc(nickname)}</span><h1>Твой персонаж</h1></header><div class="nora-editor-stage"><canvas aria-label="Трёхмерный персонаж, вращайте пальцем"></canvas><span class="nora-editor-hint">↔ ПОВЕРНИ ПЕРСОНАЖА</span></div><div class="nora-editor-controls"><div class="nora-editor-tabs" role="group" aria-label="Разделы внешности">${Object.entries(categories).map(([key,label])=>`<button type="button" data-category="${key}" aria-label="${label}" title="${label}" aria-pressed="${key==='gender'}" class="${key==='gender'?'active':''}">${key==='wings'?wingShop.icon():icon(key,outfit[key],outfit)}</button>`).join('')}</div><div class="nora-editor-caption"><span class="nora-editor-category">Пол</span><span class="nora-editor-selection" role="status"></span></div><div class="nora-editor-options" role="group" aria-label="Пол"></div><p class="nora-game-error" role="alert"></p><button class="nora-editor-save">СОХРАНИТЬ И ВОЙТИ <span>↗</span></button></div></div>`);
    const root = overlay.querySelector('.nora-editor');
    let category = 'gender', saving = false, preview = wingState.equipped;
    const optionList = root.querySelector('.nora-editor-options');
    function selection() {
      optionList.querySelectorAll('[data-choice]').forEach(el => {
        const selected = el.dataset.choice === outfit[category];
        el.classList.toggle('selected', selected);
        el.setAttribute('aria-pressed', String(selected));
      });
      root.querySelector('.nora-editor-selection').textContent = choices[category].find(([value]) => value === outfit[category])?.[1] || '';
    }
    function previewWings(id,inspect=false) {
      preview=id;
      root.dispatchEvent(new CustomEvent('wings-preview',{detail:{id,inspect}}));
    }
    function wingCards() {
      optionList.innerHTML = Object.entries(wingShop.catalog).map(([id,item])=>{
        const equipped = wingState.equipped===id;
        const owned = wingState.owned.includes(id);
        const action = equipped?'Снять':owned?'Надеть':'Купить';
        return `<article class="nora-wing-card">
          <button type="button" data-wing-preview="${id}" aria-label="Примерить: ${item.name}"
            aria-pressed="${preview===id}" class="${preview===id?'selected':''}">
            ${wingShop.icon(id)}<strong>${item.name}</strong>
          </button>
          <span>50 🍪</span><small>Двойной прыжок с плавным спуском</small>
          <button type="button" data-wing-action="${id}">${action}</button>
        </article>`;
      }).join('');
      root.querySelector('.nora-editor-selection').textContent = wingShop.catalog[preview]?.name || 'Выбери пару для примерки';
    }
    function options() {
      optionList.classList.toggle('nora-editor-swatches', category.endsWith('_color'));
      optionList.setAttribute('aria-label', categories[category]);
      root.querySelector('.nora-editor-category').textContent = categories[category];
      if(category==='wings') { wingCards();return; }
      optionList.innerHTML = choices[category].map(([value, label]) => `<button type="button" data-choice="${value}" aria-label="${label}" title="${label}">${icon(category,value,outfit)}</button>`).join('');
      selection();
    }
    root.querySelector('.nora-editor-tabs').onclick = e => {
      const b = e.target.closest('[data-category]'); if (!b || saving) return;
      const next = b.dataset.category;
      if(next!==category) {
        if(next==='wings') previewWings(wingState.equipped,true);
        else if(category==='wings') previewWings(wingState.equipped);
      }
      category = next;
      root.querySelectorAll('[data-category]').forEach(el => { el.classList.toggle('active', el === b); el.setAttribute('aria-pressed', String(el === b)); });
      options();
    };
    optionList.onclick = async e => {
      if(saving) return;
      const tryOn = e.target.closest('[data-wing-preview]');
      if(tryOn) {
        previewWings(tryOn.dataset.wingPreview,true);
        wingCards();
        optionList.querySelector(`[data-wing-preview="${preview}"]`).focus({preventScroll:true});
        return;
      }
      const wingButton = e.target.closest('[data-wing-action]');
      if(wingButton) {
        const id = wingButton.dataset.wingAction;
        const owned = wingState.owned.includes(id);
        const removing = wingState.equipped===id;
        saving=true;
        root.querySelectorAll('.nora-editor-controls button').forEach(button=>{button.disabled=true;});
        root.querySelector('.nora-game-error').textContent='';
        try {
          const state = await api('nora-game/wings',{action:owned?'equip':'buy',item:removing?null:id});
          if(!root.isConnected) return;
          wingState=state;
          outfit.wings=state.equipped;
          previewWings(removing?null:id,!removing);
          wingCards();
        } catch(error) {
          if(root.isConnected) {
            root.querySelector('.nora-game-error').textContent=error.message;
            toast(error.message);
          }
        } finally {
          saving=false;
          if(root.isConnected) {
            root.querySelectorAll('.nora-editor-controls button').forEach(button=>{button.disabled=false;});
            optionList.querySelector(`[data-wing-action="${id}"]`).focus({preventScroll:true});
          }
        }
        return;
      }
      const b = e.target.closest('[data-choice]'); if (!b) return;
      outfit[category] = b.dataset.choice;
      selection();
      root.querySelectorAll('[data-category]').forEach(el => { const key=el.dataset.category; if(key!=='wings')el.innerHTML=icon(key,outfit[key],outfit); });
      root.dispatchEvent(new Event('outfit-change'));
    };
    root.querySelector('.nora-editor-save').onclick = async () => {
      if(saving) return;
      saving = true;
      root.querySelectorAll('.nora-editor-controls button').forEach(b => { b.disabled=true; });
      root.querySelector('.nora-game-error').textContent = '';
      const version = active;
      try {
        const result = await api('nora-game/outfit', {...outfit});
        if (version === active && root.isConnected) { outfit={...defaults,...result.outfit,wings:wingState.equipped}; world(nickname); }
      } catch (error) {
        if (version === active && root.isConnected) {
          root.querySelector('.nora-game-error').textContent = error.message;
          saving = false;
          root.querySelectorAll('.nora-editor-controls button').forEach(b => { b.disabled=false; });
        }
      }
    };
    options();
    try {
      const stop = await window.NoraVoxel.mount(root.querySelector('canvas'), outfit, root);
      if (root.isConnected) {
        sceneStop = stop;
        if (category==='wings') previewWings(preview,true);
      } else stop();
    }
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
  async function open(destination=null, trigger=null) {
    if (overlay) return;
    entry = destination;
    petTrigger = trigger;
    const version = ++active;
    overlay = document.createElement('section'); overlay.className = 'nora-game-screen';
    overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-modal', 'true'); overlay.setAttribute('aria-label', 'Игра НОРА');
    document.body.appendChild(overlay);
    music = createMusic(); music.start();
    try { if (tg?.requestFullscreen && !tg.isFullscreen) { tg.requestFullscreen(); requestedFullscreen = true; } } catch (_) {}
    frame(`${logo}<p>Открываем новый мир…</p>`);
    try { await loadGame(); if (version !== active) return; const result = await api('nora-game'); if (version === active) { wingState = result.wings || {owned:[],equipped:null}; outfit = {...defaults,...result.outfit,wings:wingState.equipped}; result.nickname ? (result.outfit ? world(result.nickname) : portal(result.nickname)) : registration(); } }
    catch (error) { if (version === active) { frame(`${logo}<h1>Не удалось открыть игру</h1><p>${esc(error.message)}</p><button class="nora-game-retry" type="button">Попробовать снова</button>`); overlay.querySelector('.nora-game-retry').onclick = () => { const destination=entry, trigger=petTrigger;close();open(destination,trigger); }; } }
  }
  window.NoraGame = {open};
  document.addEventListener('click', event => {
    if (event.target.closest('#nora-game-open')) open();
    if (event.target.closest('button[data-record-gift]')) open('record');
    const petButton = event.target.closest('button[data-play-with-pet]');
    if (petButton) open('pet', petButton);
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && overlay && ![...overlay.querySelectorAll('dialog')].some(dialog=>dialog.open)) close(); });
})();
