'use strict';
window.NoraCommunity = (() => {
  let board=null, loading=false, lastTab='', query='', generation=0, debounce=null, lastBoardUpdate=0, searchLimit=50;
  let metric='messages', boardFailed=false;
  const metrics={
    likes:{icon:'❤️',label:'Лайки',title:'Топ по лайкам',empty:'Пока никто не получил лайков.'},
    messages:{icon:'💬',label:'Сообщения',title:'Топ сообщений сегодня',empty:'Сегодня сообщений пока нет.'},
    cookies:{icon:'🍪',label:'Печеньки',title:'Топ по печенькам',empty:'Пока нет данных по печенькам.'},
    invites:{icon:'🏆',label:'Конкурс',title:'Топ конкурса приглашений',empty:'Пока никто не пригласил новых участников.'},
  };
  const day=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const avatar=p=>`<span class="person-avatar" data-person-avatar="${p.id}" ${p.has_avatar===false?'data-avatar-unavailable':''}>${esc((p.name.match(/[\p{L}\p{N}]/u)?.[0]||'?').toUpperCase())}</span>`;
  function row(p,kind,index){return `<div data-staff-rank="${p.rank||0}" class="community-person ${kind==='leader'&&index<3?'community-place-'+(index+1):''}"><button class="person-visit" data-person-view="${p.id}">${kind==='leader'?`<span class="community-rank">${index+1}</span>`:''}${avatar(p)}<span><b>${NoraPrefix(p.prefix)}${esc(p.name)}</b>${kind==='staff'?`<small class="person-presence" data-staff-presence-label="${p.id}">Загружаем активность…</small>`:''}</span></button>${kind==='leader'?`<strong>${number(p[metric])} <span aria-hidden="true">${metrics[metric].icon}</span></strong>`:`<span class="community-online" data-staff-online="${p.id}" role="img" aria-label="Не в сети"></span>`}</div>`}
  function updatedLabel(){if(!board?.updated_at)return 'Обновление рейтинга…';const at=new Date(board.updated_at);if(isNaN(at))return 'Время обновления недоступно';const s=Math.max(0,Math.floor((Date.now()-at.getTime())/1000));let rel;if(s<60)rel='обновлено только что';else if(s<3600)rel=`обновлено ${plural(Math.floor(s/60),'минуту','минуты','минут')} назад`;else if(s<86400)rel=`обновлено ${plural(Math.floor(s/3600),'час','часа','часов')} назад`;else rel=`обновлено ${plural(Math.floor(s/86400),'день','дня','дней')} назад`;const abs=at.toLocaleString('ru-RU',{day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'});return `${rel} · ${abs}`}
  function updateClock(){const el=document.getElementById('community-updated');if(el)el.textContent=updatedLabel()}
  function leaders(){
    const buttons=Object.entries(metrics).map(([id,item])=>`<button type="button" data-community-metric="${id}" aria-label="${item.label}" aria-pressed="${metric===id}" title="${item.label}">${item.icon}</button>`).join('');
    return `<div class="community-table community-leaders"><h2 id="community-top-title">ТОП</h2><div class="community-table-body"><div class="community-top-filters" role="group" aria-label="Фильтр рейтинга">${buttons}</div><div id="community-top-results">${leaderResults()}</div></div></div>`;
  }
  function leaderResults(){
    if(!board)return boardFailed?'<p class="sub">Таблица не загрузилась.</p><button type="button" class="text-btn" data-community-retry>Повторить</button>':'<p class="sub" role="status">Загружаем рейтинг…</p>';
    const rows=(board.boards?.[metric]||(metric==='messages'?board.leaders:[])).slice(0,3);
    const winner=board.winner?`Вчера печеньку получил(а) <button class="text-btn" data-person-view="${board.winner.id}">${NoraPrefix(board.winner.prefix)}${esc(board.winner.name)}</button> 🍪`:board.awarded?'Вчера награда начислена участнику со скрытым доступом.':'За вчера печенька пока не начислена.';
    return `<h3 class="community-top-heading">${metrics[metric].title}</h3>${rows.length?rows.map((p,i)=>row(p,'leader',i)).join(''):`<p class="sub">${metrics[metric].empty}</p>`}${metric==='messages'?`<p class="community-winner">${winner}</p>`:''}`;
  }
  function staff(){
    return `<details class="community-table community-staff" data-board="staff" data-retain-open="staff"><summary>Команда Норы <span class="community-chevron" aria-hidden="true">⌄</span></summary><div class="community-table-body">${!board?'<p class="sub">Загружаем команду…</p>':board.staff.length?board.staff.map(p=>row(p,'staff')).join(''):'<p class="sub">Список команды пока пуст.</p>'}<p class="footer-note">Зелёный — сейчас в Норе. Для остальных показаны время выхода или последней активности, если она открыта.</p></div></details>`;
  }
  let musicUntil=0, musicSending=false;
  const socialIcon=kind=>kind==='telegram'?'<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="m21 3-4 18-6-5-3 3 1-6 9-7-11 6-5-2z"/></svg>':'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor" stroke="none"/></svg>';
  function musicCard(){return `<article class="card community-music"><div class="community-music-top"><span class="eyebrow">Сезон 1 · Bloody Nora</span></div><div class="community-music-art">${window.NoraRecords.art()}</div><h2>Музыкальная пластинка «?» (S1) — dedzytwo</h2><p class="community-music-motto">Старое ≠ бесполезное</p><p class="community-music-copy">Привычные краски в особой палитре — невероятные мэшапы от dedzytwo, начинающего автора из Санкт-Петербурга, теперь в Норе.</p><div class="community-music-socials"><a href="https://t.me/thededzzyDJ" target="_blank" rel="noopener noreferrer">${socialIcon('telegram')}<span>ТГК</span></a><a href="https://www.instagram.com/dedzytwo?exln=MWZ3aXJjcGlvbDlmNg==" target="_blank" rel="noopener noreferrer">${socialIcon('instagram')}<span>ИНСТ</span></a></div><div class="community-music-actions"><button type="button" class="community-music-play" data-music-send aria-label="Отправить песню в чат и в личку"><svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="m8 4 13 8-13 8z"/></svg><span data-music-cooldown></span></button><button type="button" class="community-music-gift" data-record-gift aria-label="Забрать пластинку в игре НОРА">${window.NoraRecords.giftIcon}</button><small>Отправь плейлист в чат или забери пластинку в игру.</small></div></article>`}
  function musicClock(){const button=document.querySelector('[data-music-send]');if(!button)return;const seconds=Math.max(0,Math.ceil((musicUntil-Date.now())/1000));button.disabled=musicSending||seconds>0;button.querySelector('[data-music-cooldown]').textContent=musicSending?'…':seconds?`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`:'';button.setAttribute('aria-label',seconds?`Повторить отправку через ${seconds} секунд`:'Отправить песню в чат и в личку')}
  async function musicStatus(){try{const result=await api('community/music');musicUntil=Math.max(musicUntil,Date.now()+result.retry_after*1000);musicClock()}catch{}}
  async function sendMusic(){if(musicSending||musicUntil>Date.now())return;musicSending=true;musicClock();try{const result=await api('community/music',{});musicUntil=Date.now()+result.retry_after*1000;sheet(`<div class="community-music-sent"><span aria-hidden="true">🎧</span><h2>${esc(result.message)}</h2></div>`)}catch(error){toast(error.message)}finally{musicSending=false;musicClock()}}
  setInterval(musicClock,1000);
  function gameTiles() {
    const pad='<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 11c-5 0-8 4-10 11L3.7 29c-1.6 6 1.8 11 6.7 10 4.3-.8 6.5-5.2 10-5.2h7.2c3.5 0 5.7 4.4 10 5.2 4.9 1 8.3-4 6.7-10L43 22c-2-7-5-11-10-11-4 0-5.5 2.5-9 2.5S19 11 15 11Z"/><path d="M14 19v10m-5-5h10" stroke-width="2.7"/><g fill="currentColor" stroke="none"><circle cx="33" cy="18.5" r="1.8"/><circle cx="38" cy="23.5" r="1.8"/><circle cx="33" cy="28.5" r="1.8"/><circle cx="28" cy="23.5" r="1.8"/></g></svg>';
    const paw='<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="10.8" cy="20.3" rx="4.3" ry="6" transform="rotate(-24 10.8 20.3)"/><ellipse cx="19.1" cy="11.6" rx="4.5" ry="6.2" transform="rotate(-9 19.1 11.6)"/><ellipse cx="29.4" cy="11.6" rx="4.5" ry="6.2" transform="rotate(9 29.4 11.6)"/><ellipse cx="37.2" cy="20.3" rx="4.3" ry="6" transform="rotate(24 37.2 20.3)"/><path d="M24 23c-5.5 0-7.6 4.8-11.5 9.4-4.2 5.2-1.5 10 3.7 10 3 0 5-2 7.8-2s4.8 2 7.8 2c5.2 0 7.9-4.8 3.7-10C31.6 27.8 29.5 23 24 23Z"/></svg>';
    const arrow='<span class="community-launch-arrow" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><path d="m9 5 7 7-7 7"/></svg></span>';
    const tile=(route,label,glyph)=>`<button type="button" class="community-tile community-${route}-tile community-launch-tile" data-tab="${route}">
        <span class="community-launch-icon" aria-hidden="true">${glyph}</span><span class="community-tile-title">${label}</span>${arrow}
      </button>`;
    return `<div class="community-tiles">${tile('games','Игры',pad)}${tile('pet','Питомец',paw)}</div>`;
  }
  function staffChatLaunch(){return data?.staff_chat_available?`<button type="button" class="community-chat-launch" data-tab="staffchat"><span class="community-chat-launch-icon" aria-hidden="true">◉</span><span>Чат Норы <small>Тест · для команды</small></span><span aria-hidden="true">›</span></button>`:"";}
  function screen(){return `<div class="community-heading nora-page-heading"><h1>Коммьюнити</h1></div>${gameTiles()}${staffChatLaunch()}<section id="community-leaders" aria-labelledby="community-top-title">${leaders()}</section><div class="community-actions">${window.NoraInteractive?.screen('friends')||''}<section id="community-staff">${staff()}</section></div><p class="footer-note" id="community-updated">${updatedLabel()}</p>${musicCard()}`}
  async function load(){
    if(loading)return;
    loading=true;
    try{
      board=await api('community');lastBoardUpdate=Date.now();boardFailed=false;
      for(const [id,render] of [['community-leaders',leaders],['community-staff',staff]]){
        const el=$('#'+id);if(!el)continue;
        const open=[...el.querySelectorAll('details[open]')].map(n=>n.dataset.board);
        const focused=el.contains(document.activeElement)?document.activeElement.dataset.communityMetric:null;
        el.innerHTML=render();
        open.forEach(k=>{const d=el.querySelector(`[data-board="${k}"]`);if(d)d.open=true});
        if(focused)el.querySelector(`[data-community-metric="${focused}"]`)?.focus({preventScroll:true});
      }
      updateClock();
      await online();
    }catch{boardFailed=true;const results=$('#community-top-results');if(!board&&results)results.innerHTML=leaderResults()}
    finally{loading=false}
  }
  async function online(){if(tab!=='community'||document.hidden)return;try{const s=await api('community/presence');document.querySelectorAll('[data-staff-online]').forEach(n=>{const presence=s[n.dataset.staffOnline];const on=!!presence?.online;const status=window.NoraPeople?.presenceLine(presence)||'Статус недоступен';n.classList.toggle('online',on);n.setAttribute('aria-label',status);const label=n.parentElement.querySelector('[data-staff-presence-label]');if(label){label.textContent=status;label.classList.toggle('online',on)}});}catch{document.querySelectorAll('[data-staff-online]').forEach(n=>{n.classList.remove('online');n.setAttribute('aria-label','Статус недоступен');const label=n.parentElement.querySelector('[data-staff-presence-label]');if(label){label.textContent='Статус недоступен';label.classList.remove('online')}})}}
  function mount(){
    if(tab==='community'){
      musicClock();
      if(lastTab!==tab)musicStatus();
    }
    if(tab==='community'&&(!board||board.revision_day!==day()||lastTab!==tab))load();
    lastTab=tab;
  }
  setInterval(()=>{
    if(document.hidden||tab!=='community')return;
    if(!board||board.revision_day!==day()||Date.now()-lastBoardUpdate>=(metric==='invites'?15000:60000))load();
    else online();
  },15000);
  setInterval(()=>{if(tab==='community'&&!document.hidden)updateClock()},30000);
  async function searchPage(version,offset=0,limit=50){const target=$('#community-search-results');if(!target)return;try{const r=await api('community/people?q='+encodeURIComponent(query)+'&offset='+offset+'&limit='+limit);if(version!==generation||!$('#community-search-results'))return;searchLimit=Math.min(500,Math.max(50,offset+r.items.length));const html=r.items.map(p=>`<button class="invite-person directory-person" data-person-view="${p.id}">${avatar(p)}<span><b>${NoraPrefix(p.prefix)}${esc(p.name)}</b><small>${p.username?'@'+esc(p.username):'Участник Норы'}</small><small class="person-presence ${p.presence?.online?'online':''}">${esc(window.NoraPeople?.presenceLine(p.presence)||'Статус недоступен')}</small></span><span class="community-online ${p.presence?.online?'online':''}" role="img" aria-label="${esc(window.NoraPeople?.presenceLine(p.presence)||'Статус недоступен')}"></span><span aria-hidden="true">›</span></button>`).join('');const el=$('#community-search-results');if(offset===0)el.innerHTML=html||'<p class="empty">Никого не нашли. Попробуй другое имя.</p>';else el.insertAdjacentHTML('beforeend',html);$('#community-search-count').textContent='Найдено: '+number(r.total);$('#community-search-more')?.remove();if(r.next_offset!==null){el.insertAdjacentHTML('beforeend',`<button class="secondary" id="community-search-more">Показать ещё</button>`);$('#community-search-more').onclick=()=>{$('#community-search-more').remove();searchPage(version,r.next_offset)}}}catch(e){if(version===generation&&$('#community-search-results')){target.innerHTML=`<p class="sub">${esc(e.message)}</p><button class="secondary" id="community-search-retry">Повторить</button>`;$('#community-search-retry').onclick=()=>searchPage(version,offset)}}}
  setInterval(()=>{if(!document.hidden&&$('#community-search-results'))searchPage(generation,0,searchLimit)},15000);
  function search(){query='';searchLimit=50;const v=++generation;sheet(`<h2>Найти своих</h2><label for="community-search">Имя в Норе, Telegram или @username</label><input id="community-search" type="search" maxlength="80" autocomplete="off" placeholder="Начни вводить имя…"><p class="footer-note" id="community-search-count">Все участники сообщества</p><div id="community-search-results"><p class="sub">Загружаем участников…</p></div>`);searchPage(v);$('#community-search').oninput=e=>{query=e.target.value;const next=++generation;clearTimeout(debounce);$('#community-search-results').innerHTML='<p class="sub">Ищем…</p>';debounce=setTimeout(()=>searchPage(next),180)}}
  document.addEventListener('click',e=>{
    if(e.target.closest('[data-music-send]'))sendMusic();
    if(e.target.closest('[data-community-search]'))search();
    if(e.target.closest('[data-community-retry]'))load();
    const filter=e.target.closest('[data-community-metric]');
    if(!filter||filter.dataset.communityMetric===metric)return;
    metric=filter.dataset.communityMetric;
    document.querySelectorAll('[data-community-metric]').forEach(b=>b.setAttribute('aria-pressed',b===filter));
    $('#community-top-results').innerHTML=leaderResults();
  });
  document.addEventListener('close',()=>{generation++;clearTimeout(debounce)},true);
  return {screen,mount,search};
})();
