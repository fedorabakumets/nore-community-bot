'use strict';
window.NoraCommunity = (() => {
  let board=null, loading=false, lastTab='', query='', generation=0, debounce=null, lastBoardUpdate=0, searchLimit=50;
  let metric='messages', boardFailed=false;
  const metrics={
    likes:{icon:'❤️',label:'Лайки',title:'Топ по лайкам',empty:'Пока никто не получил лайков.'},
    messages:{icon:'💬',label:'Сообщения',title:'Топ сообщений сегодня',empty:'Сегодня сообщений пока нет.'},
    cookies:{icon:'🍪',label:'Печеньки',title:'Топ по печенькам',empty:'Пока нет данных по печенькам.'},
  };
  const day=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const avatar=p=>`<span class="person-avatar" data-person-avatar="${p.id}" ${p.has_avatar===false?'data-avatar-unavailable':''}>${esc((p.name.match(/[\p{L}\p{N}]/u)?.[0]||'?').toUpperCase())}</span>`;
  function row(p,kind,index){return `<div data-staff-rank="${p.rank||0}" class="community-person ${kind==='leader'&&index<3?'community-place-'+(index+1):''}"><button class="person-visit" data-person-view="${p.id}">${kind==='leader'?`<span class="community-rank">${index+1}</span>`:''}${avatar(p)}<span><b>${NoraPrefix(p.prefix)}${esc(p.name)}</b></span></button>${kind==='leader'?`<strong>${number(p[metric])} <span aria-hidden="true">${metrics[metric].icon}</span></strong>`:`<span class="community-online" data-staff-online="${p.id}" role="img" aria-label="Не в сети в Норе"></span>`}</div>`}
  function updatedLabel(){if(!board?.updated_at)return 'Обновление рейтинга…';const at=new Date(board.updated_at);if(isNaN(at))return 'Время обновления недоступно';const s=Math.max(0,Math.floor((Date.now()-at.getTime())/1000));let rel;if(s<60)rel='обновлено только что';else if(s<3600)rel=`обновлено ${plural(Math.floor(s/60),'минуту','минуты','минут')} назад`;else if(s<86400)rel=`обновлено ${plural(Math.floor(s/3600),'час','часа','часов')} назад`;else rel=`обновлено ${plural(Math.floor(s/86400),'день','дня','дней')} назад`;const abs=at.toLocaleString('ru-RU',{day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'});return `${rel} · ${abs}`}
  function updateClock(){const el=document.getElementById('community-updated');if(el)el.textContent=updatedLabel()}
  function leaders(){
    const buttons=Object.entries(metrics).map(([id,item])=>`<button type="button" data-community-metric="${id}" aria-label="${item.label}" aria-pressed="${metric===id}" title="${item.label}">${item.icon}</button>`).join('');
    return `<details class="community-table community-leaders" data-board="leaders" data-retain-open="leaders"><summary>Топ участников <span class="community-chevron">⌄</span></summary><div class="community-table-body"><div class="community-top-filters" role="group" aria-label="Фильтр рейтинга">${buttons}</div><div id="community-top-results">${leaderResults()}</div></div></details>${board?`<p class="footer-note" id="community-updated">${updatedLabel()}</p>`:''}`;
  }
  function leaderResults(){
    if(!board)return boardFailed?'<p class="sub">Таблица не загрузилась.</p><button type="button" class="text-btn" data-community-retry>Повторить</button>':'<p class="sub" role="status">Загружаем рейтинг…</p>';
    const rows=board.boards?.[metric]||(metric==='messages'?board.leaders:[]);
    const winner=board.winner?`Вчера печеньку получил(а) <button class="text-btn" data-person-view="${board.winner.id}">${NoraPrefix(board.winner.prefix)}${esc(board.winner.name)}</button> 🍪`:board.awarded?'Вчера награда начислена участнику со скрытым доступом.':'За вчера печенька пока не начислена.';
    return `<h3 class="community-top-heading">${metrics[metric].title}</h3>${rows.length?rows.map((p,i)=>row(p,'leader',i)).join(''):`<p class="sub">${metrics[metric].empty}</p>`}${metric==='messages'?`<p class="community-winner">${winner}</p>`:''}`;
  }
  function staff(){
    if(!board)return '';
    return `<details class="community-table community-staff" data-board="staff" data-retain-open="staff"><summary>Команда Норы <span class="community-chevron">⌄</span></summary><div class="community-table-body">${board.staff.length?board.staff.map(p=>row(p,'staff')).join(''):'<p class="sub">Список команды пока пуст.</p>'}<p class="footer-note">Зелёный — сейчас в Норе. Серый — не в сети или активность скрыта.</p></div></details>`;
  }
  let musicUntil=0, musicSending=false;
  const socialIcon=kind=>kind==='telegram'?'<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="m21 3-4 18-6-5-3 3 1-6 9-7-11 6-5-2z"/></svg>':'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor" stroke="none"/></svg>';
  function musicCard(){return `<article class="card community-music"><div class="community-music-top"><span class="eyebrow">Сезон 1 · Bloody Nora</span></div><div class="community-music-art">${window.NoraRecords.art()}</div><h2>Музыкальная пластинка «?» (S1) — dedzytwo</h2><p class="community-music-motto">Старое ≠ бесполезное</p><p class="community-music-copy">Привычные краски в особой палитре — невероятные мэшапы от dedzytwo, начинающего автора из Санкт-Петербурга, теперь в Норе.</p><div class="community-music-socials"><a href="https://t.me/thededzzyDJ" target="_blank" rel="noopener noreferrer">${socialIcon('telegram')}<span>ТГК</span></a><a href="https://www.instagram.com/dedzytwo?exln=MWZ3aXJjcGlvbDlmNg==" target="_blank" rel="noopener noreferrer">${socialIcon('instagram')}<span>ИНСТ</span></a></div><div class="community-music-actions"><button type="button" class="community-music-play" data-music-send aria-label="Отправить песню в чат и в личку"><svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="m8 4 13 8-13 8z"/></svg><span data-music-cooldown></span></button><button type="button" class="community-music-gift" data-record-gift aria-label="Забрать пластинку в игре НОРА">${window.NoraRecords.giftIcon}</button><small>Отправь плейлист в чат или забери пластинку в игру.</small></div></article>`}
  function musicClock(){const button=document.querySelector('[data-music-send]');if(!button)return;const seconds=Math.max(0,Math.ceil((musicUntil-Date.now())/1000));button.disabled=musicSending||seconds>0;button.querySelector('[data-music-cooldown]').textContent=musicSending?'…':seconds?`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`:'';button.setAttribute('aria-label',seconds?`Повторить отправку через ${seconds} секунд`:'Отправить песню в чат и в личку')}
  async function musicStatus(){try{const result=await api('community/music');musicUntil=Math.max(musicUntil,Date.now()+result.retry_after*1000);musicClock()}catch{}}
  async function sendMusic(){if(musicSending||musicUntil>Date.now())return;musicSending=true;musicClock();try{const result=await api('community/music',{});musicUntil=Date.now()+result.retry_after*1000;sheet(`<div class="community-music-sent"><span aria-hidden="true">🎧</span><h2>${esc(result.message)}</h2></div>`)}catch(error){toast(error.message)}finally{musicSending=false;musicClock()}}
  setInterval(musicClock,1000);
  function gameTiles() {
    return `<div class="community-tiles">
      <button type="button" class="community-tile community-games-tile" data-tab="games" aria-label="Игры">
        <span class="community-tile-title" aria-hidden="true"><span class="community-pixel-title">Иг</span><span>ры</span></span>
      </button>
      <button type="button" class="community-tile community-pet-tile" data-tab="pet">
        <span class="community-pet-surface" aria-hidden="true"></span>
        <span class="community-tile-title">Питомец</span>
        <img class="community-gecko" src="/home-art/community-gecko.webp" width="420" height="154" alt="" draggable="false">
      </button>
    </div>`;
  }
  function screen(){return `<div class="community-heading nora-page-heading"><h1>Коммьюнити</h1></div>${gameTiles()}${window.NoraInteractive?.screen('friends')||''}<section id="community-leaders">${leaders()}</section><section id="community-staff">${staff()}</section>${musicCard()}`}
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
      await online();
    }catch{boardFailed=true;const results=$('#community-top-results');if(!board&&results)results.innerHTML=leaderResults()}
    finally{loading=false}
  }
  async function online(){if(tab!=='community'||document.hidden)return;try{const s=await api('community/presence');document.querySelectorAll('[data-staff-online]').forEach(n=>{const on=!!s[n.dataset.staffOnline]?.online;n.classList.toggle('online',on);n.setAttribute('aria-label',on?'В сети в Норе':'Не в сети в Норе')});}catch{document.querySelectorAll('[data-staff-online]').forEach(n=>{n.classList.remove('online');n.setAttribute('aria-label','Статус недоступен')})}}
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
    if(!board||board.revision_day!==day()||Date.now()-lastBoardUpdate>=60000)load();
    else online();
  },15000);
  setInterval(()=>{if(tab==='community'&&!document.hidden)updateClock()},30000);
  async function searchPage(version,offset=0,limit=50){const target=$('#community-search-results');if(!target)return;try{const r=await api('community/people?q='+encodeURIComponent(query)+'&offset='+offset+'&limit='+limit);if(version!==generation||!$('#community-search-results'))return;searchLimit=Math.min(500,Math.max(50,offset+r.items.length));const html=r.items.map(p=>`<button class="invite-person directory-person" data-person-view="${p.id}">${avatar(p)}<span><b>${NoraPrefix(p.prefix)}${esc(p.name)}</b><small>${p.username?'@'+esc(p.username):'Участник Норы'}</small></span><span class="community-online ${p.presence?.online?'online':''}" role="img" aria-label="${p.presence?.online?'В сети в Норе':'Не в сети или активность скрыта'}"></span><span aria-hidden="true">›</span></button>`).join('');const el=$('#community-search-results');if(offset===0)el.innerHTML=html||'<p class="empty">Никого не нашли. Попробуй другое имя.</p>';else el.insertAdjacentHTML('beforeend',html);$('#community-search-count').textContent='Найдено: '+number(r.total);$('#community-search-more')?.remove();if(r.next_offset!==null){el.insertAdjacentHTML('beforeend',`<button class="secondary" id="community-search-more">Показать ещё</button>`);$('#community-search-more').onclick=()=>{$('#community-search-more').remove();searchPage(version,r.next_offset)}}}catch(e){if(version===generation&&$('#community-search-results')){target.innerHTML=`<p class="sub">${esc(e.message)}</p><button class="secondary" id="community-search-retry">Повторить</button>`;$('#community-search-retry').onclick=()=>searchPage(version,offset)}}}
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
