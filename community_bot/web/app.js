'use strict';
const tg=window.Telegram?.WebApp; tg?.ready();tg?.expand();tg?.setHeaderColor('#111013');tg?.setBackgroundColor('#111013');
const auth=tg?.initData||'';const demo=false;let tab='home',filter='all',data,busy=false;
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number=n=>new Intl.NumberFormat('ru-RU').format(Number(n||0));
const plural=(n,one,few,many)=>{n=Math.abs(Math.trunc(Number(n)||0));return n%100>=11&&n%100<=14?many:n%10===1?one:n%10>=2&&n%10<=4?few:many};
async function api(path,body,signal){const r=await fetch('/api/'+path,{signal,method:body?'POST':'GET',headers:{Authorization:'tma '+auth,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});let j;try{j=await r.json()}catch{throw Error('Сервис пока недоступен. Попробуй ещё раз')}if(!r.ok)throw Error(j.error||j.message||'Не удалось выполнить действие');return j}
function showTesterAccess(){data=null;$('#nav').innerHTML='';$('#app').innerHTML='<section class="tester-access"><img src="/home-art/tester-recruitment.jpg" alt="Открыт набор к бета-тестированию приложения Нора"><h1>Стань тестировщиком Норы</h1><p>Сейчас доступ к приложению открыт только тестировщикам. Хочешь вступить в команду? Открой тикет и расскажи нам об этом.</p><button type="button" class="primary" id="tester-ticket">Вступить в команду</button></section>';$('#tester-ticket').onclick=()=>{const url='https://t.me/nora_community_bot?start=idea';if(tg?.openTelegramLink)tg.openTelegramLink(url);else window.open(url,'_blank','noopener,noreferrer')}}
function toast(s){$('#toast').textContent=s;$('#toast').style.display='block';clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>$('#toast').style.display='none',4000)}
function products(list){return window.NoraShop?NoraShop.cards(list):''}
function eventCard(e){return `<article class="card event"><span class="eyebrow"><i class="dot"></i>Собираемся вместе</span><h2>${esc(e.title)}</h2>${e.starts_at?`<p>📅 ${esc(new Date(e.starts_at).toLocaleString('ru-RU',{timeZone:data.profile.timezone}))}</p>`:''}${e.description?`<p>${esc(e.description)}</p>`:''}<p>${number(e.count)} в списке участников</p><div class="price">${e.price?number(e.price)+' 🍪':'Бесплатно'}</div><button class="primary" data-event="${esc(e.id)}" ${e.paid||(!e.price&&e.joined)?'disabled':''}>${e.paid?'Билет оплачен':!e.price&&e.joined?'Ты в списке ✓':e.price?'Купить билет':'Я буду'}</button></article>`}
function navIcon(id){if(id==='interactive')return window.NoraInteractive?.icon('game')||'';const paths={community:'M20 12a8 8 0 1 1-16 0 8 8 0 0 1 16 0 M3 17c-5-1 1-7 9-10s15-2 9 3S4 19 3 17',home:'M3 10 12 3l9 7v11h-6v-7H9v7H3z',shop:'M4 8h16v13H4z M8 8V5a4 4 0 0 1 8 0v3',events:'M4 5h16v16H4z M4 10h16 M8 2v5 M16 2v5',wallet:'M3 6h17v15H3z M3 6V3h14 M15 12h6v5h-6z',pet:'M8 11c-2 0-4 3-4 5s2 3 4 2c2-1 2-1 4-1s2 0 4 1c2 1 4 0 4-2s-2-5-4-5c-2 0-2 1-4 1s-2-1-4-1z M5 5v2 M10 3v3 M15 3v3 M20 5v2',lk:'M5 21v-2a7 7 0 0 1 14 0v2 M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8'};return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="${paths[id]}"/></svg>`}
const navTabShapes={home:'<path d="M10 27.5 32 9l22 18.5V52a4 4 0 0 1-4 4H14a4 4 0 0 1-4-4Z"/><path d="M26 56V37a6 6 0 0 1 12 0v19"/>',shop:'<rect x="11" y="24" width="42" height="33" rx="6"/><path d="M22 26v-7a10 10 0 0 1 20 0v7"/>',community:'<circle cx="32" cy="32" r="17"/><path d="M13.2 37.2C3 43.4 4.5 48 10.8 48.3c7.7.4 22.5-5.7 33.4-12.2C54.7 29.9 60 24.4 57 20.9c-2.4-2.8-8-1.9-14.7.7"/>',events:'<rect x="12" y="17" width="40" height="39" rx="6"/><path d="M22 10v14M42 10v14M12 29h40"/><circle cx="23" cy="40" r="2.5" fill="currentColor" stroke="none"/>'};
function navTabIcon(id){return navTabShapes[id]?`<svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${navTabShapes[id]}</svg>`:navIcon(id)}
const labels={loan:'НОРА — СТАРТЕР-ПАК',loan_repay:'Возврат стартер-пака',sbp_payment:'Пополнение СБП',pet_shop:'Припасы питомцу',pet_expedition:'Находка из похода',transfer:'Перевод',profile_complete:'Бонус за заполнение профиля',shop:'Покупка в магазине',seasonal_purchase:'Сезонный предмет',rsvp:'Участие в мероприятии',rsvp_refund:'Возврат залога',transfer_in:'Входящий перевод',transfer_out:'Перевод',bonus:'Бонус',daily_leader:'Бонус за активность',admin:'Начисление',debt_repay:'Возврат долга'};
function transactions(){return data.history.length?data.history.map(t=>`<div class="transaction"><span class="tx-icon">${t.amount>0?'↙':'↗'}</span><div class="tx-info"><b>${esc(labels[t.kind]||'Операция с печеньками')}</b><span>${esc(new Date(t.date).toLocaleString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}))}</span></div><strong class="${t.amount>0?'positive':''}">${t.amount>0?'+':''}${number(t.amount)} 🍪</strong></div>`).join(''):'<div class="empty">Пока без операций.<br>Твоя история появится здесь.</div>'}
function render(){window.NoraShop?.preloadSeasonal();const u=data.user,name=u.profile_name||u.telegram_name||'Друг';let content='';
if(tab==='home')content=window.NoraHome?.screen()||'';
if(tab==='shop')content=window.NoraShop?.screen()||'';
if(tab==='events')content=window.NoraEvents?.screen()||'';
if(tab==='lk')content=profileScreen(u);
if(tab==='community')content=window.NoraCommunity?.screen()||'';
if(tab==='admin')content=window.NoraAdmin?.render()||'<p>Открываем админ-панель…</p>';
if(tab==='wallet')content=window.NoraCabinet?.walletScreen()||'';
if(tab==='pet')content=window.NoraCabinet?.petScreen()||'';
if(tab==='history')content=window.NoraCabinet?.historyScreen()||'';
if(tab==='notices')content=window.NoraCabinet?.noticesScreen()||'';
if(window.NoraSea?.handles(tab))content=NoraSea.screen(tab);else if(window.NoraInteractive?.handles(tab))content=NoraInteractive.screen(tab);
$('#app').innerHTML=`${demo?'<div class="demo">Демонстрация · пример данных, покупки отключены</div>':''}${content}`;if(tab==='admin')window.NoraAdmin?.mount();
const selected=['interactive','games','mafia','rocket','sea','friends','pet'].includes(tab)?'community':['wallet','history','notices','admin'].includes(tab)?'lk':tab;renderNav(selected,name);window.NoraShop?.syncBack();window.NoraInteractive?.mount();window.NoraSea?.mount?.();window.NoraCommunity?.mount();window.NoraEvents?.mount();loadAvatar()}


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
  }
  if(navSelection!==selected){positionNavDrop(!!navSelection);navSelection=selected;}
}
new ResizeObserver(()=>positionNavDrop()).observe($('#nav'));
navReducedMotion.addEventListener('change',()=>positionNavDrop());

function sheet(html){$('#sheet-content').innerHTML=html;if(!$('#sheet').open)$('#sheet').showModal()}
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
document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.tab&&['shop','events'].includes(b.dataset.tab)&&data.profile.fill_percent<100&&!(b.dataset.tab==='events'&&data.events_admin)){toast('Заполни профиль на 100% в ЛК, чтобы открыть магазин и события');return}if(b.dataset.tab){tab=b.dataset.tab;window.NoraShop?.tabChanged(tab);render();window.scrollTo(0,0);if(tab!=='admin')refresh()}if(b.dataset.filter){filter=b.dataset.filter;render()}if(b.dataset.product)product(b.dataset.product);if(b.dataset.event&&data.profile.fill_percent<100){toast('Заполни профиль на 100% в ЛК');return}if(b.hasAttribute('data-reputation'))showReputation();if(b.dataset.event){const event=data.events.find(x=>x.id===b.dataset.event);if(demo){toast('Это демонстрация. Запись доступна при входе через Telegram');return}sheet(`<span class="eyebrow">Встретимся?</span><h2>${esc(event.title)}</h2><p class="sub">${event.price?'Стоимость билета':'Участие бесплатное'}</p><div class="amount">${event.price?number(event.price)+' 🍪':'0 🍪'}</div><button class="primary" id="pay">${event.price?'Подтвердить оплату':'Подтвердить участие'}</button>`);$('#pay').onclick=()=>perform('events/join',{event_id:event.id,price:event.price})}if(b.hasAttribute('data-profile')){tab='lk';window.NoraShop?.tabChanged(tab);render();window.scrollTo(0,0)}if(b.id==='edit-profile')editProfile();if(b.id==='change-avatar')$('#avatar-file').click()});
$('#sheet').addEventListener('close',()=>{if(!$('#sheet').open)$('#sheet-content').replaceChildren()});
$('#dismiss').onclick=()=>$('#sheet').close();$('#sheet').addEventListener('click',e=>{if(e.target===$('#sheet')){const r=e.target.getBoundingClientRect();if(e.clientY<r.top||e.clientY>r.bottom||e.clientX<r.left||e.clientX>r.right)e.target.close()}});
(async()=>{try{if(!auth){$('#app').innerHTML='<div class="empty"><h1>Для команды<br>Норы.</h1><p>Открой миниапку из меню Норы в Telegram. Доступ открыт от роли модератора.</p></div>';return}data=await api('me');window.NoraPeople?.start();const view=window.NoraShop?.route()?.view||'home';if(view==='admin'&&data.admin_available)tab='admin';else if(['pet','lk','wallet','history','notices','interactive','games','mafia','rocket','sea','friends','community','events'].includes(view))tab=view;else if(view==='shop'&&data.profile.fill_percent===100){tab='shop';window.NoraShop?.resume()}render();loadAvatar()}catch(e){window.NoraIntro?.finish(true);if(e.message.includes('от 30 ранга')){showTesterAccess();return}$('#app').innerHTML=`<div class="empty"><h1>Сейчас вернёмся.</h1><p>${esc(e.message)}</p><button class="primary" id="retry">Попробовать ещё раз</button></div>`;$('#retry').onclick=()=>location.reload()}finally{window.NoraIntro?.ready()}})();

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
async function refresh(){if(!auth||!data||busy||tab==='admin'||document.hidden||$('#sheet').open)return;if(window.NoraEvents?.editorOpen())return;if(window.NoraSea?.refreshCurrent())return;if(window.NoraInteractive?.refreshCurrent())return;try{data=await api('me');render();window.NoraCabinet?.refreshCurrent()}catch(e){if(e.message.includes('от 30 ранга')){showTesterAccess()}else toast(e.message)}}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});setInterval(refresh,30000);

// Capture the activation before a button handler replaces its screen.
document.addEventListener('click', event => {
  if (!event.isTrusted) return;
  const button = event.target.closest?.('button');
  if (!button || button.matches(':disabled, [aria-disabled="true"]') || button.closest('.nora-game-screen')) return;
  tg?.HapticFeedback?.impactOccurred?.('light');
}, {capture: true});

function showReputation(){const levels=data.levels||[];sheet(`<span class="eyebrow">Репутация в Норе</span><h2>Твой вклад —<br>твои возможности</h2><p class="sub">Сейчас у тебя ${number(data.user.reputation)} / 100. Поддержка участников даёт +5 репутации, отрицательная оценка — −5. Себе менять репутацию нельзя. Одного человека можно отметить один раз в день.</p>${levels.map(l=>`<section class="rep-level"><h3>${esc(l.label)} · ${esc(l.range)}</h3><p>Скидка ${number(l.discount)}% · ${number(l.daily_actions)} ${plural(l.daily_actions,"действие","действия","действий")} в день.<br>${l.can_minus?'Можно поддерживать и понижать репутацию.':'Можно только поддерживать участников.'}</p></section>`).join('')}<p class="sub">Серебро — от 70, золото — от 90. Чтобы расти выше 69, заполни все пять блоков профиля. Автоматический рост за активность ограничен 89; до золота помогает поддержка участников. Ниже порога ограничений взаимодействия недоступны.</p><h2>Для твоей репутации</h2>${products(data.products.filter(p=>p.category==='reputation'))}`)}
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
