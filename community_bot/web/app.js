'use strict';
const tg = window.Telegram?.WebApp;
if (tg) {
  const background = getComputedStyle(document.documentElement).getPropertyValue('--poster-bg').trim() || '#111013';
  if (tg.isVersionAtLeast?.('6.1')) tg.setBackgroundColor?.(background);
  if (tg.isVersionAtLeast?.('6.9')) tg.setHeaderColor?.(background);
  if (tg.isVersionAtLeast?.('7.10')) tg.setBottomBarColor?.(background);
  if (tg.isVersionAtLeast?.('7.7')) tg.disableVerticalSwipes?.();
  tg.ready();
  tg.expand();
}
const auth=tg?.initData||'';const demo=false;let tab='home',filter='all',data,busy=false;
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function profileTabLocked(target) {
  return data.profile.fill_percent < 100 && !['home','commands','lk','notices','admin','reputation','staffchat'].includes(target)
    && !(target==='events'&&data.events_admin);
}
const number=n=>new Intl.NumberFormat('ru-RU').format(Number(n||0));
const hasProfileFire=likes=>likes>=50;
const profileLikeText=likes=>`${hasProfileFire(likes)?'💜':'❤️'} ${number(likes)}`;
const plural=(n,one,few,many)=>{n=Math.abs(Math.trunc(Number(n)||0));return n%100>=11&&n%100<=14?many:n%10===1?one:n%10>=2&&n%10<=4?few:many};
const gameViews = new Set(['durak', 'barricade', 'sea', 'mafia', 'rocket']);
const gameWrites = new Map();
function api(path, body, signal, keepalive = false) {
  const request = (async () => {
    const r = await fetch('/api/'+path, {signal, keepalive, method:body?'POST':'GET', headers:{
      Authorization:'tma '+auth, ...(body?{'Content-Type':'application/json'}:{})
    }, body:body?JSON.stringify(body):undefined});
    let j;
    try {j=await r.json()} catch {throw Error('Сервис пока недоступен. Попробуй ещё раз')}
    if(!r.ok)throw Object.assign(Error(j.error||j.message||'Не удалось выполнить действие'),{status:r.status});
    return j;
  })();
  const game = path.split('/')[0];
  if (body && gameViews.has(game)) {
    if (!gameWrites.has(game)) gameWrites.set(game, new Set());
    const writes = gameWrites.get(game);
    writes.add(request);
    const remove = () => writes.delete(request);
    request.then(remove, remove);
  }
  return request;
}

function currentGame() {
  return window.NoraGame?.isOpen?.() ? 'world' : gameViews.has(tab) ? tab : null;
}

function requestGameExit(onExit) {
  const game = currentGame(), dialog = $('#game-exit');
  if (!game) { onExit(); return; }
  if (dialog.open) return;
  const exit = $('#game-exit-confirm'), stay = $('#game-exit-stay'), error = $('#game-exit-error');
  error.textContent = '';
  $('#game-exit-details').textContent = {
    world: 'Ты покинешь мир Норы.',
    rocket: 'Текущий полёт завершится. Ставка будет проиграна.',
    mafia: 'Ты выйдешь из лобби или сдашься в начавшейся партии.',
  }[game] || 'Поиск отменится. Если партия уже началась, тебе засчитается поражение.';
  stay.onclick = () => dialog.close();
  dialog.oncancel = event => { if (exit.disabled) event.preventDefault(); };
  exit.onclick = async () => {
    exit.disabled = stay.disabled = true;
    exit.textContent = 'Выходим…';
    error.textContent = '';
    try {
      if (game !== 'world') {
        await Promise.allSettled(gameWrites.get(game) || []);
        await api('games/exit/' + game, {});
        if (game === 'durak') window.NoraDurak?.clearRoom?.();
      }
      dialog.close();
      if ($('#sheet').open) $('#sheet').close();
      onExit();
    } catch (e) {
      error.textContent = e.message;
    } finally {
      exit.disabled = stay.disabled = false;
      exit.textContent = 'Выйти';
    }
  };
  dialog.showModal();
}

window.addEventListener('pagehide', () => {
  const game = currentGame();
  if (game === 'world') window.NoraGame.close();
  else if (game && auth) api('games/exit/' + game, {}, undefined, true).catch(() => {});
});
let applicationScreen = null;

function showCitySetup() {
  applicationScreen = null;
  barricadeView?.unmount();
  data = null;
  $('#nav').replaceChildren();
  if ($('#sheet').open) $('#sheet').close();
  tg?.BackButton?.hide?.();
  const app = $('#app');
  app.dataset.screen = 'city';
  window.scrollTo(0, 0);
  app.innerHTML = `<section class="application-panel card">
    <span class="eyebrow">Нора · твой профиль</span>
    <h1>Из какого ты города?</h1>
    <p class="sub">Укажи город, чтобы открыть Нору и пользоваться командами в чате.</p>
    <form id="city-setup-form">
      <label>Город
        <input name="city" autocomplete="address-level2" minlength="2" maxlength="100"
          placeholder="Например, Санкт-Петербург" required autofocus>
      </label>
      <p class="application-error" id="city-setup-error" role="alert"></p>
      <button type="submit" class="primary">Продолжить</button>
    </form>
  </section>`;
  const form = $('#city-setup-form');
  form.onsubmit = async event => {
    event.preventDefault();
    if (busy) return;
    const button = form.querySelector('[type="submit"]');
    const error = $('#city-setup-error');
    busy = button.disabled = true;
    button.textContent = 'Сохраняем…';
    error.textContent = '';
    try {
      await api('city', {city: form.elements.city.value});
      await openApp(await api('me'));
    } catch (err) {
      error.textContent = err.message;
    } finally {
      busy = button.disabled = false;
      button.textContent = 'Продолжить';
    }
  };
}

function showApplication(application) {
  applicationScreen = application;
  barricadeView?.unmount();
  data = null;
  $('#nav').replaceChildren();
  if ($('#sheet').open) $('#sheet').close();
  tg?.BackButton?.hide?.();
  const app = $('#app');
  app.dataset.screen = 'application';
  window.scrollTo(0, 0);

  if (application.status !== 'form') {
    const waiting = application.status === 'pending';
    const canAttach = waiting && application.application_id && !application.has_photo;
    app.innerHTML = `<section class="application-panel card">
      <h1>${waiting ? 'Анкета на проверке' : 'Анкета пока недоступна'}</h1>
      <p>${waiting ? 'Нора сообщит решение в Telegram.'
        : 'Ты сможешь подать анкету после разбана.'}</p>
      ${canAttach ? `<form id="application-photo-form">
        <label>Фото (необязательно)
          <input type="file" name="photo" accept="${AVATAR_ACCEPT}" required>
        </label>
        <button type="submit" class="primary">Прикрепить фото</button>
      </form>` : application.has_photo ? '<p role="status">Фото прикреплено.</p>' : ''}
      <button type="button" class="${canAttach ? 'secondary' : 'primary'}" id="application-close">${canAttach ? 'Пропустить фото' : 'Вернуться в чат'}</button>
      <button type="button" class="secondary" id="application-check">Проверить статус</button>
      <p class="application-error" id="application-error" role="status"></p>
    </section>`;
    $('#application-close').onclick = () => tg?.close?.();
    $('#application-check').onclick = event => refreshApplication(event.currentTarget);
    if (canAttach) $('#application-photo-form').onsubmit = event => attachApplicationPhoto(event, application);
    return;
  }

  app.innerHTML = `<section class="application-panel card">
    <h1>Анкета на вступление</h1>
    <form id="application-form">
      <label>Имя
        <input name="name" autocomplete="given-name" maxlength="50" required value="${esc(application.name)}">
      </label>
      <label>Возраст
        <input name="age" type="number" inputmode="numeric" min="14" max="120" step="1" required>
      </label>
      <label>Город
        <input name="city" autocomplete="address-level2" maxlength="100" required>
      </label>
      <label>О себе
        <textarea name="bio" rows="3" maxlength="1000" required></textarea>
      </label>
      <p class="application-error" id="application-error" role="alert"></p>
      <button type="submit" class="primary">Отправить анкету</button>
    </form>
  </section>`;
  const form = $('#application-form');
  form.onsubmit = async event => {
    event.preventDefault();
    if (busy) return;
    const submit = form.querySelector('[type=submit]');
    const error = $('#application-error');
    const answers = Object.fromEntries(new FormData(form));
    busy = submit.disabled = true;
    submit.textContent = 'Отправляем…';
    error.textContent = '';
    try {
      const result = await api('application', {...answers, ban_version: application.ban_version});
      if (result.status === 'admitted') await openApp(await api('me'));
      else showApplication(result);
    } catch (err) {
      error.textContent = err.message;
    } finally {
      busy = submit.disabled = false;
      submit.textContent = 'Отправить анкету';
    }
  };
}

async function attachApplicationPhoto(event, application) {
  event.preventDefault();
  if (busy) return;
  const form = event.currentTarget;
  const file = form.elements.photo.files[0];
  if (!file) return;
  const submit = form.querySelector('[type="submit"]');
  const error = $('#application-error');
  busy = submit.disabled = true;
  submit.textContent = 'Загружаем фото…';
  error.textContent = '';
  try {
    const result = await uploadPhoto(file, 'application/photo', {'X-Application-Id': application.application_id});
    showApplication(result);
  } catch (err) {
    error.textContent = err.message;
  } finally {
    busy = submit.disabled = false;
    submit.textContent = 'Прикрепить фото';
  }
}

async function refreshApplication(button) {
  if (busy) return;
  busy = true;
  const message = $('#application-error');
  if (button) {
    button.disabled = true;
    message.textContent = '';
  }
  try {
    const result = await api('me');
    const next = result.onboarding;
    if (next?.status !== applicationScreen.status || next?.application_id !== applicationScreen.application_id
      || next?.has_photo !== applicationScreen.has_photo) await openApp(result);
    else if (button) message.textContent = applicationScreen.status === 'pending' ? 'Модераторы ещё проверяют анкету.' : 'Анкета пока недоступна.';
  } catch (err) {
    if (button) message.textContent = err.message;
  } finally {
    busy = false;
    if (button) button.disabled = false;
  }
}
function toast(s){
  const notice=$('#toast');
  const dialog=$('#sheet');
  const parent=dialog.open?dialog:document.body;
  if(notice.parentElement!==parent)parent.append(notice);
  notice.textContent=s;
  notice.style.display='block';
  clearTimeout(window.toastTimer);
  window.toastTimer=setTimeout(()=>notice.style.display='none',4000);
}
function products(list){return window.NoraShop?NoraShop.cards(list):''}
function eventCard(e){return `<article class="card event"><span class="eyebrow"><i class="dot"></i>Собираемся вместе</span><h2>${esc(e.title)}</h2>${e.starts_at?`<p>📅 ${esc(new Date(e.starts_at).toLocaleString('ru-RU',{timeZone:data.profile.timezone}))}</p>`:''}${e.description?`<p>${esc(e.description)}</p>`:''}<p>${number(e.count)} в списке участников</p><div class="price">${e.price?number(e.price)+' 🍪':'Бесплатно'}</div><button class="primary" data-event="${esc(e.id)}" ${e.paid||(!e.price&&e.joined)?'disabled':''}>${e.paid?'Билет оплачен':!e.price&&e.joined?'Ты в списке ✓':e.price?'Купить билет':'Я буду'}</button></article>`}
function navIcon(id){if(id==='interactive')return window.NoraInteractive?.icon('game')||'';const paths={community:'M20 12a8 8 0 1 1-16 0 8 8 0 0 1 16 0 M3 17c-5-1 1-7 9-10s15-2 9 3S4 19 3 17',home:'M3 10 12 3l9 7v11h-6v-7H9v7H3z',shop:'M4 8h16v13H4z M8 8V5a4 4 0 0 1 8 0v3',events:'M4 5h16v16H4z M4 10h16 M8 2v5 M16 2v5',wallet:'M3 6h17v15H3z M3 6V3h14 M15 12h6v5h-6z',pet:'M8 11c-2 0-4 3-4 5s2 3 4 2c2-1 2-1 4-1s2 0 4 1c2 1 4 0 4-2s-2-5-4-5c-2 0-2 1-4 1s-2-1-4-1z M5 5v2 M10 3v3 M15 3v3 M20 5v2',lk:'M5 21v-2a7 7 0 0 1 14 0v2 M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8'};return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="${paths[id]}"/></svg>`}
const navTabShapes={home:'<path d="M10 27.5 32 9l22 18.5V52a4 4 0 0 1-4 4H14a4 4 0 0 1-4-4Z"/><path d="M26 56V37a6 6 0 0 1 12 0v19"/>',shop:'<rect x="11" y="24" width="42" height="33" rx="6"/><path d="M22 26v-7a10 10 0 0 1 20 0v7"/>',community:'<circle cx="32" cy="32" r="17"/><path d="M13.2 37.2C3 43.4 4.5 48 10.8 48.3c7.7.4 22.5-5.7 33.4-12.2C54.7 29.9 60 24.4 57 20.9c-2.4-2.8-8-1.9-14.7.7"/>',events:'<rect x="12" y="17" width="40" height="39" rx="6"/><path d="M22 10v14M42 10v14M12 29h40"/><circle cx="23" cy="40" r="2.5" fill="currentColor" stroke="none"/>'};
function navTabIcon(id){return navTabShapes[id]?`<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${navTabShapes[id]}</svg>`:navIcon(id)}
let durakModule, durakInboxRoom, durakEntry;
function openDurak(entry) {
  goToTab('durak', () => { durakEntry = entry; });
}
function mountDurak() {
  if (tab !== 'durak') { durakEntry = null; window.NoraDurak?.unmount(); return; }
  const root = document.getElementById('durak-root');
  if (window.NoraDurak) { window.NoraDurak.mount(root); return; }
  if (!document.getElementById('durak-style')) {
    const css = document.createElement('link');
    css.id = 'durak-style'; css.rel = 'stylesheet'; css.href = '/durak.css?v=quick-game';
    document.head.append(css);
  }
  durakModule ??= import('/durak.js?v=chat-invite').catch(() => {
    durakModule = null;
    if (tab === 'durak' && root.isConnected) {
      const retry = document.createElement('button');
      retry.className = 'secondary'; retry.textContent = 'Загрузить стол ещё раз';
      retry.onclick = mountDurak; root.replaceChildren(retry);
    }
  });
  durakModule.then(module => { if (module && tab === 'durak') module.mount(document.getElementById('durak-root')); });
}
let barricadeModule, barricadeView, barricadeEntry;

function openBarricade(entry) {
  goToTab('barricade', () => { barricadeEntry = entry; });
}
function mountBarricade() {
  if (tab !== 'barricade') { barricadeEntry = null; barricadeView?.unmount(); return; }
  const root = document.getElementById('barricade-root');
  for (const [id, href] of [['durak-style', '/durak.css?v=quick-game'], ['barricade-style', '/barricade.css?v=quick-game']]) {
    if (document.getElementById(id)) continue;
    const css = document.createElement('link');
    css.id = id; css.rel = 'stylesheet'; css.href = href;
    document.head.append(css);
  }
  barricadeModule ??= import('/barricade.js?v=game-exit').catch(() => {
    barricadeModule = null;
    if (!root.isConnected || tab !== 'barricade') return;
    const retry = document.createElement('button');
    retry.className = 'secondary'; retry.textContent = 'Загрузить Баррикаду ещё раз';
    retry.onclick = mountBarricade; root.replaceChildren(retry);
  });
  barricadeModule.then(view => {
    if (!view || !root.isConnected || tab !== 'barricade') return;
    barricadeView = view;
    view.mount(root, barricadeEntry);
    barricadeEntry = null;
  });
}

function render(){if(!data)return;if(data.onboarding){showApplication(data.onboarding);return}if(profileTabLocked(tab))tab='lk';window.NoraCabinet?.syncHistory();if(data.profile.fill_percent===100){window.NoraShop?.preloadSeasonal();window.NoraPeople?.start()}const u=data.user,name=u.profile_name||u.telegram_name||'Друг';let content='';
if(tab==='home')content=window.NoraHome?.screen()||'';
if(tab==='commands')content=NoraCommands.screen();
if(tab==='shop')content=window.NoraShop?.screen()||'';
if(tab==='events')content=window.NoraEvents?.screen()||'';
if(tab==='lk')content=profileScreen(u);
if(tab==='community')content=window.NoraCommunity?.screen()||'';
if(tab==='staffchat')content=window.NoraStaffChat?.screen()||'';
if(tab==='admin')content=window.NoraAdmin?.render()||'<p>Открываем админ-панель…</p>';
if(tab==='wallet')content=window.NoraCabinet?.walletScreen()||'';
if(tab==='pet')content=window.NoraPet?.screen()||'';
if(tab==='barricade')content='<section id="barricade-root"><p class="sub">Открываем Баррикаду…</p></section>';
if(tab==='durak')content='<section id="durak-root"><p class="sub">Открываем карточный стол…</p></section>';
if(tab==='history')content=window.NoraCabinet?.historyScreen()||'';
if(tab==='notices')content=window.NoraCabinet?.noticesScreen()||'';
if(window.NoraSea?.handles(tab))content=NoraSea.screen(tab);else if(window.NoraInteractive?.handles(tab))content=NoraInteractive.screen(tab);
const app=$('#app'), html=`${demo?'<div class="demo">Демонстрация · пример данных, покупки отключены</div>':''}${content}`;
const expanded=app.dataset.screen===tab
  ?new Set([...app.querySelectorAll('details[open][data-retain-open]')].map(el=>el.dataset.retainOpen))
  :null;
app.dataset.screen=tab;
if(tab==='home'&&window.NoraHome)NoraHome.render(app,html);
else if (!(tab === 'durak' && app.querySelector('#durak-root')) &&
         !(tab === 'barricade' && app.querySelector('#barricade-root'))) app.innerHTML=html;
mountDurak();
mountBarricade();
if(expanded?.size)for(const el of app.querySelectorAll('details[data-retain-open]')){
  if(expanded.has(el.dataset.retainOpen))el.open=true;
}
if(tab==='admin')window.NoraAdmin?.mount();
const selected=tab==='commands'?'home':['interactive','games','mafia','rocket','sea','durak','barricade','friends','pet','staffchat'].includes(tab)?'community':['wallet','history','notices','admin'].includes(tab)?'lk':tab;renderNav(selected,name);window.NoraShop?.syncBack();window.NoraInteractive?.mount();window.NoraSea?.mount?.();window.NoraCommunity?.mount();window.NoraStaffChat?.mount();window.NoraEvents?.mount();loadAvatar();animateRouteChange(app,selected)}


// Animate route changes only. Refreshes and game-internal renders should remain still.
const routeMotionExcluded = new Set(['durak', 'barricade', 'sea', 'mafia', 'rocket']);
const routeMotionOrder = ['home', 'shop', 'community', 'events', 'lk'];
let previousRouteKey = null, previousRouteSection = null, routeMotion = null;
function animateRouteChange(app, selected) {
  const category = tab === 'shop' ? (window.NoraShop?.route()?.category || '') : '';
  const key = tab + ':' + category;
  if (key === previousRouteKey) return;
  const oldKey = previousRouteKey, oldSection = previousRouteSection;
  previousRouteKey = key;
  previousRouteSection = selected;
  routeMotion?.cancel();
  routeMotion = null;
  if (!oldKey || routeMotionExcluded.has(tab) || navReducedMotion.matches || typeof app.animate !== 'function') return;
  const from = routeMotionOrder.indexOf(oldSection), to = routeMotionOrder.indexOf(selected);
  const distance = from >= 0 && to >= 0 && from !== to ? (to > from ? 14 : -14) : 0;
  const rise = distance ? 2 : 10;
  // Six steps create a smooth acceleration/deceleration profile on fast displays.
  const frame = (offset, remaining, opacity) => ({
    offset, opacity,
    transform: `translate3d(${(distance * remaining).toFixed(2)}px,${(rise * remaining).toFixed(2)}px,0) scale(${(1 - .008 * remaining).toFixed(4)})`
  });
  const animation = app.animate([
    frame(0, 1, .72),
    frame(.16, .86, .81),
    frame(.36, .52, .91),
    frame(.58, .23, .975),
    frame(.82, .045, .998),
    frame(1, 0, 1)
  ], {duration: 310, easing: 'linear'});
  routeMotion = animation;
  animation.addEventListener('finish', () => {
    if (routeMotion === animation) routeMotion = null;
  }, {once: true});
}


// Keep the dock mounted: polling must not restart the travelling selection.
let navSelection='', navMotion=null;
const navReducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
function positionNavDrop(animate=false){
  const nav=$('#nav'),drop=nav.querySelector('.nav-drop'),target=nav.querySelector('.active');
  if(!drop||!target)return;
  const before=getComputedStyle(drop),from=before.transform,opacity=before.opacity;
  navMotion?.cancel();
  const x=target.offsetLeft,y=target.offsetTop,profile=target.dataset.tab==='lk';
  drop.style.width=target.offsetWidth+'px';drop.style.height=target.offsetHeight+'px';
  const end=`translate(${x}px,${profile?y-14:y}px) scale(${profile?'.08': '1'})`;
  drop.style.transform=end;drop.style.opacity=profile?'0':'1';
  if(!animate||navReducedMotion.matches)return;
  const oldX=from==='none'?x:new DOMMatrixReadOnly(from).m41;
  navMotion=drop.animate([
    {transform:from,opacity,borderRadius:'18px',offset:0},
    {transform:`translate(${oldX+(x-oldX)*.65}px,${y}px) scale(1.14,.82)`,opacity:1,borderRadius:'45% 55% 55% 45% / 55% 45% 55% 45%',offset:.55},
    {transform:end,opacity:profile?0:1,borderRadius:'18px',offset:1}
  ],{duration:profile?760:640,easing:'cubic-bezier(.22,1,.36,1)'});
}
function renderNav(selected,name){
  const nav=$('#nav');
  if(!nav.querySelector('.nav-drop')){
    nav.innerHTML='<i class="nav-drop" aria-hidden="true"></i>'+[['home','Главная'],['shop','Магазин'],['community','Коммьюнити'],['events','События'],['lk','Профиль']].map(([id,label])=>`<button data-tab="${id}" aria-current="false">${id==='lk'?'<span class="nav-profile-wrap"><span class="nav-profile-photo" data-own-avatar></span><i class="nav-unread-dot" aria-hidden="true"></i></span>':navTabIcon(id)}${label}</button>`).join('');
    navSelection='';
  }
  const photo=nav.querySelector('[data-own-avatar]');
  if(!data.has_avatar||data.avatar_video||!photo.querySelector('img'))photo.textContent=(name.match(/[\p{L}\p{N}]/u)?.[0]||'?').toUpperCase();
  nav.querySelector('.nav-profile-wrap').classList.toggle('has-unread',!!data.unread_notices);
  for(const button of nav.querySelectorAll('button')){
    const active=button.dataset.tab===selected;
    button.classList.toggle('active',active);button.setAttribute('aria-current',active?'page':'false');
    button.setAttribute('aria-disabled',String(profileTabLocked(button.dataset.tab)));
  }
  if(navSelection!==selected){positionNavDrop(!!navSelection);navSelection=selected;}
}
new ResizeObserver(()=>positionNavDrop()).observe($('#nav'));
navReducedMotion.addEventListener('change',()=>positionNavDrop());

let sheetContentMotion = null;
function sheet(html) {
  const dialog = $('#sheet'), content = $('#sheet-content'), wasOpen = dialog.open;
  sheetContentMotion?.cancel();
  sheetContentMotion = null;
  content.innerHTML = html;
  if (!wasOpen) { dialog.showModal(); return; }
  // A confirmation inside the same drawer moves only its content.
  if (navReducedMotion.matches || typeof content.animate !== 'function') return;
  sheetContentMotion = content.animate([
    {offset: 0, opacity: .75, transform: 'translate3d(0,8px,0)'},
    {offset: .5, opacity: .95, transform: 'translate3d(0,2px,0)'},
    {offset: 1, opacity: 1, transform: 'translate3d(0,0,0)'}
  ], {duration: 220, easing: 'cubic-bezier(.2,.7,.3,1)'});
}
async function product(sku){await window.NoraShop?.product(sku)}
async function perform(path,payload,b=$('#pay')){
  if(busy)return;
  busy=true;if(b)b.disabled=true;
  try{
    const r=await api(path,payload);
    $('#sheet').close();toast(r.message||'Готово');tg?.HapticFeedback?.notificationOccurred('success');
    try{data=await api('me');render();loadAvatar()}catch{toast((r.message||'Готово')+' Данные обновятся при следующем открытии.')}
  }catch(e){toast(e.message);if(b)b.disabled=false}
  finally{busy=false}
}
function bookEvent(button) {
  const event = data.events.find(item => item.id === button.dataset.event);
  if (!event) return;
  if (demo) { toast('Это демонстрация. Запись доступна при входе через Telegram'); return; }
  const payload = {event_id: event.id, price: event.price};
  if (event.registration_only) {
    void perform('events/join', payload, button);
    return;
  }
  sheet(`<span class="eyebrow">Встретимся?</span><h2>${esc(event.title)}</h2><p class="sub">${event.price?'Стоимость билета':'Участие бесплатное'}</p><div class="amount">${event.price?number(event.price)+' 🍪':'0 🍪'}</div><button class="primary" id="pay">${event.price?'Подтвердить оплату':'Подтвердить участие'}</button>`);
  $('#pay').onclick = () => perform('events/join', payload);
}
function goToTab(next, prepare, refreshAfter = false) {
  if(next==='staffchat'&&!data?.staff_chat_available){toast('Чат пока доступен только команде Норы');return;}
  if (profileTabLocked(next)) {
    toast('Заполни профиль на 100%, чтобы открыть этот раздел');
    return;
  }
  NoraShop.leaveGameTo(next, () => {
    prepare?.();
    const from = tab;
    tab = next;
    NoraShop.tabChanged(tab, from);
    render();
    window.scrollTo(0, 0);
    if (refreshAfter && tab !== 'admin') refresh();
  });
}

document.addEventListener('click', e => {
  const b = e.target.closest('button');
  if (!b) return;
  if (b.dataset.tab) goToTab(b.dataset.tab, () => {
    if (b.dataset.barricadeInvite) barricadeEntry = {id:b.dataset.barricadeInvite};
    if (b.dataset.durakInvite) durakInboxRoom = b.dataset.durakInvite;
  }, true);
  if (b.dataset.filter) {filter=b.dataset.filter;render()}
  if (b.dataset.product) product(b.dataset.product);
  if (b.dataset.event && data.profile.fill_percent<100) {
    toast('Заполни профиль на 100% в ЛК');return;
  }
  if (b.hasAttribute('data-reputation')) showReputation();
  if (b.dataset.event) bookEvent(b);
  if (b.hasAttribute('data-profile')) goToTab('lk');
  if (b.id==='edit-profile') editProfile();
  if (b.id==='change-avatar') $('#avatar-file').click();
});
$('#sheet').addEventListener('close',()=>{
  sheetContentMotion?.cancel();
  sheetContentMotion = null;
  const dialog=$('#sheet');
  if(dialog.open)return;
  $('#sheet-content').replaceChildren();
  const notice=$('#toast');
  if(notice.parentElement===dialog)document.body.append(notice);
});
$('#dismiss').onclick=()=>$('#sheet').close();$('#sheet').addEventListener('click',e=>{if(e.target===$('#sheet')){const r=e.target.getBoundingClientRect();if(e.clientY<r.top||e.clientY>r.bottom||e.clientX<r.left||e.clientX>r.right)e.target.close()}});
function telegramStartParam() {
  return tg?.initDataUnsafe?.start_param || new URLSearchParams(location.search).get('tgWebAppStartParam') || '';
}

function botReplyRoute() {
  if (history.state?.noraView) return null;
  const param = telegramStartParam();
  const quick = /^nora_q_(durak|barricade)_([a-f0-9]{16})$/.exec(param);
  if (quick) return {view: quick[1], quickRoom: quick[2]};
  const invite = /^nora_inv_(mafia|sea|durak|barricade)_([1-9][0-9]{0,15})_([A-Za-z0-9_-]{16,22})$/.exec(param);
  if (invite) return {view: invite[1], invite: {game: invite[1], recipient: Number(invite[2]), room_id: invite[3]}};
  const barricade = /^nora_b_([A-Za-z0-9_-]{22})$/.exec(param);
  if (barricade) return {view: 'barricade', code: barricade[1]};
  if (/^nora_(?:d_[A-Za-z0-9_-]{22}|i_[a-f0-9]{16})$/.test(param)) return {view: 'durak'};
  const event = /^nora_event_([A-Za-z0-9_-]{1,64})$/.exec(param);
  if (event) return {view: 'events', eventId: event[1]};
  const screen = /^nora_to_(commands|cookies|shop|pet|notices|games|mafia|rocket|events|community)$/.exec(param);
  if (screen?.[1] === 'cookies') return {view: 'shop', category: '__cookies'};
  if (screen) return {view: screen[1]};
  const shop = /^nora_(cat|item)_([a-zA-Z0-9_-]{1,64})$/.exec(param);
  if (!shop) return null;
  if (shop[1] === 'cat') return {view: 'shop', category: shop[2]};
  const item = data.products.find(product => product.sku === shop[2]);
  return {view: 'shop', category: item?.category, sku: shop[2]};
}

function openLobbyFromLink() {
  if (telegramStartParam() !== 'nora_lobby') return;
  if (profileTabLocked('community')) {toast('Заполни профиль на 100%, чтобы открыть лобби');return}
  window.NoraIntro?.finish(true);
  // The game script is deferred and may still be loading when /api/me returns.
  if (window.NoraGame) window.NoraGame.open();
  else document.addEventListener('DOMContentLoaded', () => window.NoraGame?.open(), {once: true});
}

async function openGameProfileFromLink() {
  const match = /^nora_card_([A-Za-z]{3,16}_[a-f0-9]{24})$/.exec(telegramStartParam());
  if (!match) return;
  window.NoraIntro?.finish(true);
  try {
    await api('nora-game/chat/profile', {card:match[1]});
    if (tg?.close) tg.close();
    else toast('Профиль отправлен в группу Норы.');
  } catch (error) {
    toast(error.message);
  }
}

function openPersonFromLink() {
  const match = /^nora_profile_([1-9][0-9]{0,15})$/.exec(telegramStartParam());
  if (!match) return;
  const id = Number(match[1]);
  if (!Number.isSafeInteger(id)) return;
  window.NoraIntro?.finish(true);
  void window.NoraPeople?.visit(id);
}

async function openWidgetNoticeFromLink() {
  const match = /^nora_notice_([0-9a-f]{32})$/.exec(telegramStartParam());
  if (!match) return;

  try {
    const notice = await api('notices/widget/' + match[1]);
    const target = notice.target;
    const blocked = profileTabLocked(target);
    if (!blocked) {
      tab = target === 'reputation' ? 'lk' : target;
      window.NoraShop?.tabChanged(tab);
      render();
      window.scrollTo(0, 0);
    }
    const timestamp = new Date(notice.event_at).toLocaleString('ru-RU');
    const details = esc(notice.details || notice.preview).replace(/\r?\n/g, '<br>');
    sheet(`<span class="eyebrow">Уведомление от ${esc(notice.sender_label)}</span>
      <h2>${esc(notice.title)}</h2><p class="sub">${esc(timestamp)}${notice.context ? ' · ' + esc(notice.context) : ''}</p>
      <p>${details}</p>${blocked ? '<p class="sub">Заполни профиль на 100% в ЛК, чтобы открыть раздел.</p>' :
        `<button type="button" class="primary" id="notice-target">${esc(notice.target_label)}</button>`}`);
    const button = $('#notice-target');
    if (button) button.onclick = () => {
      if (target === 'reputation') showReputation();
      else $('#sheet').close();
    };
  } catch (error) {
    toast(error.message);
  }
}

const memberScreensReady = new Promise(resolve => {
  document.addEventListener('DOMContentLoaded', resolve, {once: true});
});

async function openApp(result) {
  if (result.onboarding) {
    showApplication(result.onboarding);
    window.NoraIntro?.finish(true);
    return;
  }
  if (result.city_required) {
    showCitySetup();
    window.NoraIntro?.finish(true);
    return;
  }
  await memberScreensReady;
  applicationScreen = null;
  data = result;
  tab = 'home';
  const linked = botReplyRoute();
  let view = linked?.view || window.NoraShop?.route()?.view || 'home';
  const blockedLink = linked && profileTabLocked(view);
  const topupClosed = linked?.category === '__cookies' && !data.cookie_shop?.enabled;
  let inviteError;
  if (linked?.invite && !blockedLink) {
    try {
      const {room_id} = await api('games/invite', linked.invite);
      if (view === 'durak') durakInboxRoom = room_id;
      if (view === 'barricade') barricadeEntry = {id: room_id};
    } catch (error) {
      view = 'games';
      inviteError = error.message;
    }
  }
  if (linked?.quickRoom && !blockedLink) {
    if (view === 'durak') durakEntry = {quick: linked.quickRoom};
    if (view === 'barricade') barricadeEntry = {quick: linked.quickRoom};
  }
  if (linked?.code && !blockedLink) barricadeEntry = {code: linked.code};
  if (linked?.invite || linked?.code || linked?.quickRoom) window.NoraIntro?.finish(true);
  if (blockedLink) tab = 'lk';
  else if (view === 'admin' && data.admin_available) tab = 'admin';
  else if (['commands','pet','lk','wallet','history','notices','interactive','games','mafia','rocket','sea','durak','barricade','friends','community','events'].includes(view)) tab = view;
  else if (view === 'shop' && data.profile.fill_percent === 100) {
    tab = 'shop';
    window.NoraShop?.resume(linked ? (topupClosed ? null : linked.category ?? null) : undefined);
  }
  if (tab === 'pet' && !profileTabLocked(tab) && history.state?.noraView !== 'pet') {
    window.NoraShop?.tabChanged(tab, 'community');
  } else if (linked && !blockedLink) {
    window.NoraShop?.tabChanged(tab);
  }
  if (linked?.eventId && !blockedLink) {
    window.NoraIntro?.finish(true);
    window.NoraEvents?.focusEvent(linked.eventId);
  }
  render();
  loadAvatar();
  if (telegramStartParam() === 'nora_home_screen') {
    window.NoraIntro?.finish(true);
    window.NoraHomeScreen?.open();
  }
  if (blockedLink) toast('Заполни профиль на 100%, чтобы открыть этот раздел');
  else if (inviteError) toast(inviteError);
  else if (topupClosed) toast('Пополнение временно недоступно');
  else if (linked?.eventId && !data.events?.some(event => event.id === linked.eventId)) {
    toast('Мероприятие больше недоступно');
  }
  if (tab === 'shop' && linked?.sku) {
    if (data.products.some(product => product.sku === linked.sku)) void product(linked.sku);
    else toast('Товар больше недоступен');
  }
  openLobbyFromLink();
  openPersonFromLink();
  void openWidgetNoticeFromLink();
  void openGameProfileFromLink();
}

async function startApp() {
  try {
    if (!auth) {
      $('#app').innerHTML = '<div class="empty"><h1>Нора</h1><p>Открой миниапку из меню Норы в Telegram.</p></div>';
      return;
    }
    await openApp(await api('me'));
  } catch (e) {
    window.NoraIntro?.finish(true);
    $('#app').innerHTML = `<div class="empty"><h1>Сейчас вернёмся.</h1><p>${esc(e.message)}</p><button class="primary" id="retry">Попробовать ещё раз</button></div>`;
    $('#retry').onclick = () => location.reload();
  } finally {
    window.NoraIntro?.ready();
  }
}
void startApp();

function profileScreen(u){return window.NoraCabinet?.profileScreen(u)||''}
function editProfile(){const u=data.user;const revision=data.revision;sheet(`<span class="eyebrow">Твой профиль</span><h2>Расскажи о себе</h2><form id="profile-form"><label>Имя<input name="profile_name" maxlength="50" required value="${esc(u.profile_name||u.telegram_name||'')}"></label><label>Дата рождения<input name="birth_date" type="date" required value="${esc(u.birth_date||'')}"></label><label>Город<input name="city" minlength="2" maxlength="100" required value="${esc(u.city||'')}"></label><label>Увлечения<textarea name="hobbies" maxlength="500" required rows="3">${esc(u.hobbies||'')}</textarea></label><label>Описание<textarea name="profile_bio" maxlength="280" required rows="3">${esc(u.profile_bio||'')}</textarea></label><p class="sub">Имя — до 50, город — от 2 до 100, увлечения — до 500, описание — до 280 символов. Возраст — от 14 до 120.</p><button class="primary" id="pay" type="submit">Сохранить профиль</button></form>`);$('#profile-form').onsubmit=e=>{e.preventDefault();const fields=Object.fromEntries(new FormData(e.target));perform('profile',{fields,revision})}}
const AVATAR_MAX_MB = 64;
const AVATAR_ACCEPT = 'image/*,.heic,.heif';
async function uploadPhoto(file, endpoint, headers) {
  if (!file.size) throw Error('Файл пустой. Выбери другое фото');
  if (file.size > AVATAR_MAX_MB * 1024 * 1024) throw Error(`Фото должно быть не больше ${AVATAR_MAX_MB} МБ`);
  const response = await fetch('/api/' + endpoint, {
    method: 'POST',
    headers: {Authorization: 'tma ' + auth, 'Content-Type': 'application/octet-stream', ...headers},
    body: file,
  }).catch(() => {
    throw Error('Не удалось отправить фото. Проверь интернет и попробуй ещё раз');
  });
  const result = await response.json().catch(() => ({}));
  if (response.status === 413) throw Error(result.error || `Фото должно быть не больше ${AVATAR_MAX_MB} МБ`);
  if (!response.ok) throw Error(result.error || 'Не удалось загрузить фото');
  return result;
}
let avatarURL=null,avatarKey='',avatarLoading=false;
function paintOwnAvatar(){if(!avatarURL)return;document.querySelectorAll('#profile-photo,[data-own-avatar]').forEach(el=>{el.innerHTML=`<img src="${avatarURL}" alt="Фото профиля">`})}
async function loadAvatar(){
  if(!data?.has_avatar||data.avatar_video){if(avatarURL)URL.revokeObjectURL(avatarURL);avatarURL=null;avatarKey='';return}
  const key=data.revision;
  if(avatarURL&&avatarKey===key){paintOwnAvatar();return}
  if(avatarLoading)return;
  avatarLoading=true;
  try{
    const r=await fetch('/api/profile/avatar',{headers:{Authorization:'tma '+auth}});if(!r.ok)return;
    const blob=await r.blob();if(!data?.has_avatar||data.avatar_video||data.revision!==key)return;
    const next=URL.createObjectURL(blob);if(avatarURL)URL.revokeObjectURL(avatarURL);avatarURL=next;avatarKey=key;paintOwnAvatar();
  }catch{ /* A failed photo request leaves a usable initial in the circle. */ }
  finally{avatarLoading=false;if(data?.has_avatar&&!data.avatar_video&&data.revision!==key)queueMicrotask(loadAvatar)}
}
document.addEventListener('change', async e => {
  if (e.target.id !== 'avatar-file') return;
  const file = e.target.files?.[0];
  if (!file || busy) return;
  e.target.value = '';
  const button = $('#change-avatar');
  busy = true;
  if (button) button.disabled = true;
  try {
    toast('Загружаем фото…');
    const result = await uploadPhoto(file, 'profile/avatar', {'X-Profile-Revision': data.revision});
    toast(result.message);
    data = await api('me');
    render();
  } catch (err) {
    toast(err.message);
  } finally {
    if (button) button.disabled = false;
    busy = false;
  }
});
async function refresh(){if(!auth||busy||document.hidden)return;if(applicationScreen&&applicationScreen.status!=='form'){await refreshApplication();return}if(!data||tab==='admin'||tab==='staffchat'||$('#sheet').open)return;if(window.NoraEvents?.editorOpen())return;if(tab==='durak'||tab==='barricade')return;if(window.NoraSea?.refreshCurrent())return;if(window.NoraInteractive?.refreshCurrent())return;try{data=await api('me');render();if(data)window.NoraCabinet?.refreshCurrent()}catch(e){toast(e.message)}}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});setInterval(refresh,30000);

// Capture the activation before a button handler replaces its screen.
document.addEventListener('click', event => {
  if (!event.isTrusted) return;
  const button = event.target.closest?.('button');
  if (!button || button.matches(':disabled, [aria-disabled="true"]') || button.closest('.nora-game-screen')) return;
  tg?.HapticFeedback?.impactOccurred?.('light');
}, {capture: true});

function showReputation(){const levels=data.levels||[];sheet(`<span class="eyebrow">Репутация в Норе</span><h2>Твой вклад —<br>твои возможности</h2><p class="sub">Сейчас у тебя ${number(data.user.reputation)} / 100. Поддержка участников даёт +5 репутации, отрицательная оценка — −5. Себе менять репутацию нельзя. Одного человека можно отметить до 10 раз в день в пределах общего лимита. Нора ИИ открывается со 2-го уровня питомца.</p>${levels.map(l=>`<section class="rep-level"><h3>${esc(l.label)} · ${esc(l.range)}</h3><p>Скидка ${number(l.discount)}% · ${number(l.daily_actions)} ${plural(l.daily_actions,"действие","действия","действий")} в день.<br>Нора ИИ · до ${number(l.ai_daily_requests)} запросов в день.<br>${l.can_minus?'Можно поддерживать и понижать репутацию.':'Можно только поддерживать участников.'}</p></section>`).join('')}<p class="sub">Серебро — от 70, золото — от 90. Чтобы расти выше 69, заполни все пять блоков профиля. Автоматический рост за активность ограничен 89; до золота помогает поддержка участников. Ниже порога ограничений взаимодействия недоступны.</p><h2>Для твоей репутации</h2>${products(data.products.filter(p=>p.category==='reputation'))}`)}
// Floating scroll toggle: jumps to the very bottom of the page and back to the top.
(() => {
  const btn = $('#scroll-jump');
  if (!btn) return;
  const atBottom = () => window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 24;
  function update() {
    const scrollable = document.documentElement.scrollHeight - window.innerHeight > 24;
    const down = !atBottom();
    btn.classList.toggle('visible', scrollable);
    btn.classList.toggle('show-up', !down);
    btn.setAttribute('aria-label', down ? 'В самый низ' : 'В самый верх');
  }
  btn.addEventListener('click', () => {
    window.scrollTo({top: atBottom() ? 0 : document.documentElement.scrollHeight, behavior: 'smooth'});
  });
  window.addEventListener('scroll', update, {passive: true});
  window.addEventListener('resize', update);
  new MutationObserver(update).observe($('#app'), {childList: true, subtree: true});
  update();
})();

// Monochrome symbols inherit the prefix color on every platform.
window.NoraPrefixSymbol = emoji => {
  const paths = {
    '🎉':'m4 20 4-13 9 9-13 4Z M7 11l6 6 M12 3v3 M17 3l-2 4 M21 8l-4 1 M19 13h2 M5 4l1 2',
    '🛡️':'M12 3 4 6v6c0 4 5 7 8 9 3-2 8-5 8-9V6l-8-3Z M9 12l2 2 4-4',
    '👑':'m3 6 5 5 4-7 4 7 5-5-2 12H5L3 6Z M6 21h12',
    '👮':'m4 7 8-4 8 4-3 4H7L4 7Z M7 11c-1 6 2 9 5 9s6-3 5-9 M10 7h4 M6 22l3-2 M18 22l-3-2',
    '♥':'M20 5c-3-3-6-1-8 1-2-2-5-4-8-1-5 5 2 11 8 16 6-5 13-11 8-16Z',
    '★':'m12 3 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1 3-6Z',
    '⭐':'m12 3 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1 3-6Z',
    '🔥':'M13 3c1 5 6 7 6 12a7 7 0 0 1-14 0c0-3 2-5 4-7 0 3 1 4 2 5 2-3 2-6 2-10Z',
    '🌙':'M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11Z',
    '💎':'m3 9 4-5h10l4 5-9 12L3 9Z M3 9h18 M7 4l5 17 5-17',
    '🌿':'M5 21C5 10 10 4 20 3c0 10-5 17-15 14 M5 17l9-8'
  };
  if (emoji === '67') return '<span class="role-prefix-symbol role-prefix-number" aria-hidden="true">67</span>';
  const path = Object.hasOwn(paths, emoji) ? paths[emoji] : '';
  return path ? `<svg class="role-prefix-symbol" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${path}"/></svg>` : '';
};
// Role colors and text are allowlisted/escaped before becoming markup.
window.NoraPrefix = p => {
  if (!p || !['red','orange','gold','green','blue','purple','pink'].includes(p.color)) return '';
  return `<span class="role-prefix role-prefix--${p.color}">${NoraPrefixSymbol(p.emoji)}${esc(p.text)}</span>`;
};
