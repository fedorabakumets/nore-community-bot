'use strict';
const tg=window.Telegram?.WebApp; tg?.ready();tg?.expand();tg?.setHeaderColor('#101011');tg?.setBackgroundColor('#101011');
const auth=tg?.initData||'';const demo=false;let tab='home',filter='all',data,busy=false;
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number=n=>new Intl.NumberFormat('ru-RU').format(Number(n||0));
async function api(path,body){const r=await fetch('/api/'+path,{method:body?'POST':'GET',headers:{Authorization:'tma '+auth,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});let j;try{j=await r.json()}catch{throw Error('Сервис пока недоступен. Попробуй ещё раз')}if(!r.ok)throw Error(j.error||j.message||'Не удалось выполнить действие');return j}
function toast(s){$('#toast').textContent=s;$('#toast').style.display='block';clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>$('#toast').style.display='none',4000)}
function products(list){return window.NoraShop?NoraShop.cards(list):''}
function eventCard(e){return `<article class="card event"><span class="eyebrow"><i class="dot"></i>Собираемся вместе</span><h2>${esc(e.title)}</h2>${e.starts_at?`<p>📅 ${esc(new Date(e.starts_at).toLocaleString('ru-RU',{timeZone:data.profile.timezone}))}</p>`:''}${e.description?`<p>${esc(e.description)}</p>`:''}<p>${number(e.count)} в списке участников</p><div class="price">${e.price?number(e.price)+' 🍪':'Бесплатно'}</div><button class="primary" data-event="${esc(e.id)}" ${e.paid||(!e.price&&e.joined)?'disabled':''}>${e.paid?'Билет оплачен':!e.price&&e.joined?'Ты в списке ✓':e.price?'Купить билет':'Я буду'}</button></article>`}
function navIcon(id){if(id==='interactive')return window.NoraInteractive?.icon('game')||'';const paths={home:'M3 10 12 3l9 7v11h-6v-7H9v7H3z',shop:'M4 8h16v13H4z M8 8V5a4 4 0 0 1 8 0v3',events:'M4 5h16v16H4z M4 10h16 M8 2v5 M16 2v5',wallet:'M3 6h17v15H3z M3 6V3h14 M15 12h6v5h-6z',pet:'M8 11c-2 0-4 3-4 5s2 3 4 2c2-1 2-1 4-1s2 0 4 1c2 1 4 0 4-2s-2-5-4-5c-2 0-2 1-4 1s-2-1-4-1z M5 5v2 M10 3v3 M15 3v3 M20 5v2',lk:'M5 21v-2a7 7 0 0 1 14 0v2 M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8'};return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="${paths[id]}"/></svg>`}
const labels={loan:'НОРА — СТАРТЕР-ПАК',loan_repay:'Возврат стартер-пака',sbp_payment:'Пополнение СБП',pet_shop:'Припасы питомцу',pet_expedition:'Находка из похода',transfer:'Перевод',profile_complete:'Бонус за заполнение профиля',shop:'Покупка в магазине',rsvp:'Участие в мероприятии',rsvp_refund:'Возврат залога',transfer_in:'Входящий перевод',transfer_out:'Перевод',bonus:'Бонус',daily_leader:'Бонус за активность',admin:'Начисление',debt_repay:'Возврат долга'};
function transactions(){return data.history.length?data.history.map(t=>`<div class="transaction"><span class="tx-icon">${t.amount>0?'↙':'↗'}</span><div class="tx-info"><b>${esc(labels[t.kind]||'Операция с печеньками')}</b><span>${esc(new Date(t.date).toLocaleString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}))}</span></div><strong class="${t.amount>0?'positive':''}">${t.amount>0?'+':''}${number(t.amount)} 🍪</strong></div>`).join(''):'<div class="empty">Пока без операций.<br>Твоя история появится здесь.</div>'}
function render(){const feedback=pressFeedback.snapshot();pressFeedback.clear();const u=data.user,name=u.profile_name||u.telegram_name||'Друг';let content='';
if(tab==='home')content=window.NoraHome?.screen()||'';
if(tab==='shop')content=window.NoraShop?.screen()||'';
if(tab==='events')content=`<p class="eyebrow">Хорошая компания</p><h1>Повод<br><em>собраться.</em></h1>${data.events.length?data.events.map(eventCard).join(''):'<div class="card empty"><img src="/art/event.webp" alt="Бабушка-диджей">Пока без анонсов.<br>Новая встреча появится здесь.</div>'}`;
if(tab==='lk')content=profileScreen(u);
if(tab==='admin')content=window.NoraAdmin?.render()||'<p>Открываем админ-панель…</p>';
if(tab==='wallet')content=window.NoraCabinet?.walletScreen()||'';
if(tab==='pet')content=window.NoraCabinet?.petScreen()||'';
if(tab==='history')content=window.NoraCabinet?.historyScreen()||'';
if(tab==='notices')content=window.NoraCabinet?.noticesScreen()||'';
if(window.NoraInteractive?.handles(tab))content=NoraInteractive.screen(tab);
$('#app').innerHTML=`<header><div><div class="brand">N<i>O</i>RA</div><div class="city">Санкт-Петербург</div></div><div class="header-actions">${window.NoraCabinet?.header()||''}<button class="avatar profile-pulse" data-profile aria-label="Открыть личный кабинет"><span>${esc((name.match(/[\p{L}\p{N}]/u)?.[0]||name.slice(0,1)).toUpperCase())}</span></button></div></header>${demo?'<div class="demo">Демонстрация · пример данных, покупки отключены</div>':''}${content}`;if(tab==='admin')window.NoraAdmin?.mount();
const selected=['wallet','history','notices','admin','friends'].includes(tab)?'lk':tab;$('#nav').innerHTML=[['home','Главная'],['shop','Магазин'],['events','События'],['lk','Профиль']].map(([id,label])=>`<button class="${selected===id?'active':''}" data-tab="${id}" aria-current="${selected===id?'page':'false'}">${id==='lk'?`<span class="nav-profile-photo" data-own-avatar>${esc((name.match(/[\p{L}\p{N}]/u)?.[0]||'?').toUpperCase())}</span>`:navIcon(id)}${label}</button>`).join('');window.NoraShop?.syncBack();window.NoraInteractive?.mount();pressFeedback.restore(feedback);loadAvatar()}

function sheet(html){pressFeedback.clear();$('#sheet-content').innerHTML=html;if(!$('#sheet').open)$('#sheet').showModal()}
async function product(sku){await window.NoraShop?.product(sku)}
async function perform(path,payload){
  if(busy)return;
  busy=true;const b=$('#pay');if(b)b.disabled=true;
  try{
    const r=await api(path,payload);
    $('#sheet').close();toast(r.message||'Готово');tg?.HapticFeedback?.notificationOccurred('success');
    try{data=await api('me');render();loadAvatar()}catch{toast((r.message||'Готово')+' Данные обновятся при следующем открытии.')}
  }catch(e){toast(e.message);if(b)b.disabled=false}
  finally{busy=false}
}
document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.tab&&['shop','events'].includes(b.dataset.tab)&&data.profile.fill_percent<100){toast('Заполни профиль на 100% в ЛК, чтобы открыть магазин и события');return}if(b.dataset.tab){tab=b.dataset.tab;window.NoraShop?.tabChanged(tab);render();window.scrollTo(0,0);if(tab!=='admin')refresh()}if(b.dataset.filter){filter=b.dataset.filter;render()}if(b.dataset.product)product(b.dataset.product);if(b.dataset.event&&data.profile.fill_percent<100){toast('Заполни профиль на 100% в ЛК');return}if(b.hasAttribute('data-reputation'))showReputation();if(b.dataset.event){const event=data.events.find(x=>x.id===b.dataset.event);if(demo){toast('Это демонстрация. Запись доступна при входе через Telegram');return}sheet(`<span class="eyebrow">Встретимся?</span><h2>${esc(event.title)}</h2><p class="sub">${event.price?'Стоимость билета':'Участие бесплатное'}</p><div class="amount">${event.price?number(event.price)+' 🍪':'0 🍪'}</div><button class="primary" id="pay">${event.price?'Подтвердить оплату':'Подтвердить участие'}</button>`);$('#pay').onclick=()=>perform('events/join',{event_id:event.id,price:event.price})}if(b.hasAttribute('data-profile')){tab='lk';window.NoraShop?.tabChanged(tab);render();window.scrollTo(0,0)}if(b.id==='edit-profile')editProfile();if(b.id==='change-avatar')$('#avatar-file').click()});
$('#dismiss').onclick=()=>$('#sheet').close();$('#sheet').addEventListener('click',e=>{if(e.target===$('#sheet')){const r=e.target.getBoundingClientRect();if(e.clientY<r.top||e.clientY>r.bottom||e.clientX<r.left||e.clientX>r.right)e.target.close()}});
(async()=>{try{if(!auth){$('#app').innerHTML='<div class="empty"><h1>Для команды<br>Норы.</h1><p>Открой миниапку из меню Норы в Telegram. Доступ открыт от роли модератора.</p></div>';return}data=await api('me');window.NoraPeople?.start();const view=window.NoraShop?.route()?.view||'home';if(view==='admin'&&data.admin_available)tab='admin';else if(['pet','lk','wallet','history','notices','interactive','games','mafia','rocket','friends'].includes(view))tab=view;else if(view==='shop'&&data.profile.fill_percent===100){tab='shop';window.NoraShop?.resume()}render();loadAvatar()}catch(e){window.NoraIntro?.finish(true);$('#app').innerHTML=`<div class="empty"><h1>${e.message.includes('модератор')?'Доступ закрыт.':'Сейчас вернёмся.'}</h1><p>${esc(e.message)}</p><button class="primary" id="retry">Попробовать ещё раз</button></div>`;$('#retry').onclick=()=>location.reload()}})();

function profileScreen(u){return window.NoraCabinet?.profileScreen(u)||''}
function editProfile(){const u=data.user;const revision=data.revision;sheet(`<span class="eyebrow">Твой профиль</span><h2>Расскажи о себе</h2><form id="profile-form"><label>Имя<input name="profile_name" maxlength="50" required value="${esc(u.profile_name||u.telegram_name||'')}"></label><label>Возраст<input name="age" type="number" inputmode="numeric" min="14" max="120" required value="${esc(u.age||'')}"></label><label>Увлечения<textarea name="hobbies" maxlength="500" required rows="3">${esc(u.hobbies||'')}</textarea></label><label>Описание<textarea name="profile_bio" maxlength="280" required rows="3">${esc(u.profile_bio||'')}</textarea></label><p class="sub">Имя — до 50, увлечения — до 500, описание — до 280 символов. Возраст — от 14 до 120.</p><button class="primary" id="pay" type="submit">Сохранить профиль</button></form>`);$('#profile-form').onsubmit=e=>{e.preventDefault();const fields=Object.fromEntries(new FormData(e.target));fields.age=Number(fields.age);perform('profile',{fields,revision})}}
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
document.addEventListener('change',async e=>{if(e.target.id!=='avatar-file')return;const file=e.target.files?.[0];if(!file||busy)return;if(file.size>5*1024*1024){toast('Фото должно быть не больше 5 МБ');e.target.value='';return}if(!['image/jpeg','image/png','image/webp'].includes(file.type)){toast('Выбери JPG, PNG или WebP');return}busy=true;const b=$('#change-avatar');if(b){b.disabled=true;b.textContent='Загружаем фото…'}try{const r=await fetch('/api/profile/avatar',{method:'POST',headers:{Authorization:'tma '+auth,'Content-Type':file.type,'X-Profile-Revision':data.revision},body:file});const j=await r.json();if(!r.ok)throw Error(j.error||'Не удалось загрузить фото');toast(j.message);data=await api('me');render()}catch(err){toast(err.message);if(b){b.disabled=false;b.textContent='Повторить загрузку фото'}}finally{busy=false}});
async function refresh(){if(!auth||!data||busy||tab==='admin'||document.hidden||$('#sheet').open)return;if(window.NoraInteractive?.refreshCurrent())return;try{data=await api('me');render();window.NoraCabinet?.refreshCurrent()}catch(e){if(e.message.includes('модератор')){$('#nav').innerHTML='';$('#app').innerHTML='<div class="empty"><h1>Доступ закрыт.</h1><p>Миниапка доступна от роли модератора.</p></div>';data=null}else toast(e.message)}}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});setInterval(refresh,30000);

function showReputation(){const levels=data.levels||[];sheet(`<span class="eyebrow">Репутация в Норе</span><h2>Твой вклад —<br>твои возможности</h2><p class="sub">Сейчас у тебя ${number(data.user.reputation)} / 100. Поддержка участников даёт +5 репутации, отрицательная оценка — −5. Себе менять репутацию нельзя. Одного человека можно отметить один раз в день.</p>${levels.map(l=>`<section class="rep-level"><h3>${esc(l.label)} · ${esc(l.range)}</h3><p>Скидка ${number(l.discount)}% · ${number(l.daily_actions)} действий в день.<br>${l.can_minus?'Можно поддерживать и понижать репутацию.':'Можно только поддерживать участников.'}</p></section>`).join('')}<p class="sub">Серебро — от 70, золото — от 90. Чтобы расти выше 69, заполни все пять блоков профиля. Автоматический рост за активность ограничен 89; до золота помогает поддержка участников. Ниже порога ограничений взаимодействия недоступны.</p><h2>Для твоей репутации</h2>${products(data.products.filter(p=>p.category==='reputation'))}`)}
// Feedback belongs to the activated control, never to a viewport overlay.
const pressFeedback = (() => {
  let gesture = null, holdTimer = null;
  const active = new Map();
  function clear() {
    clearTimeout(holdTimer);
    for (const [node, state] of active) {
      clearTimeout(state.timer);
      node.classList.remove('press-feedback');
    }
    active.clear();
  }
  function cancel() {
    if (gesture) gesture.cancelled = true;
    clear();
  }
  document.addEventListener('pointerdown', e => {
    clear();
    if (!e.isPrimary || e.button !== 0) { cancel(); return; }
    gesture = {id:e.pointerId,x:e.clientX,y:e.clientY,
      node:e.target.closest?.('button,a.admin-control'),cancelled:false,ended:false};
    const press = gesture;
    holdTimer = setTimeout(() => {
      if (gesture === press && !press.cancelled && !press.ended) show(press.node);
    },80);
  }, {capture:true,passive:true});
  document.addEventListener('pointermove', e => {
    if (gesture?.id === e.pointerId && Math.hypot(e.clientX-gesture.x,e.clientY-gesture.y)>8) cancel();
  }, {capture:true,passive:true});
  document.addEventListener('pointercancel', cancel, {capture:true,passive:true});
  document.addEventListener('pointerup', e => {
    if (gesture?.id === e.pointerId) {
      if (Math.hypot(e.clientX-gesture.x,e.clientY-gesture.y)>8) cancel();
      gesture.ended = true;
    }
  }, {capture:true,passive:true});
  function show(node, duration=460) {
    if (!node?.isConnected || node.disabled || node.getAttribute('aria-disabled') === 'true') return;
    clear();
    // Restart an existing press without creating a floating layer.
    void node.offsetWidth;
    node.classList.add('press-feedback');
    active.set(node,{until:performance.now()+duration,timer:setTimeout(() => {
      node.classList.remove('press-feedback');
      active.delete(node);
    },duration)});
  }
  document.addEventListener('click', e => {
    const node = e.target.closest?.('button,a.admin-control');
    const tap = gesture;
    gesture = null;
    if (!node || node.disabled || node.getAttribute('aria-disabled') === 'true') return;
    if (e.detail !== 0 && (!tap || !tap.ended || tap.cancelled || tap.node !== node)) return;
    // Let every screen/modal action finish before deciding whether this control is still visible.
    queueMicrotask(() => {
      const dialog = document.querySelector('dialog[open]');
      let control = node;
      if (!control.isConnected) {
        if (node.dataset.tab) control = [...document.querySelectorAll('#nav button[data-tab]')].find(b => b.dataset.tab === node.dataset.tab);
        else if (node.hasAttribute('data-profile')) control = document.querySelector('[data-profile]');
      }
      if (!control?.isConnected || control.disabled || (dialog && !dialog.contains(control))) return;
      show(control);
    });
  }, true);
  document.addEventListener('scroll', cancel, {capture:true,passive:true});
  document.addEventListener('visibilitychange', cancel);
  document.addEventListener('close', clear, true);
  window.addEventListener('blur', cancel);
  window.addEventListener('popstate', cancel);
  new MutationObserver(clear).observe(document.querySelector('#sheet'), {attributes:true,attributeFilter:['open']});
  function snapshot() {
    return [...active].map(([node,state]) => ({
      tab:node.closest('#nav') ? node.dataset.tab : null,
      profile:node.hasAttribute('data-profile'), until:state.until,
    }));
  }
  function restore(saved) {
    for (const item of saved) {
      const node = item.profile ? document.querySelector('[data-profile]') :
        [...document.querySelectorAll('#nav button.active')].find(b => b.dataset.tab === item.tab);
      if (node && item.until>performance.now()) show(node,item.until-performance.now());
    }
  }
  return {clear,snapshot,restore};
})();
