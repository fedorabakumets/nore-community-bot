'use strict';
// The desktop shell never creates an identity or changes server authorization.
window.NoraDesktop = (() => {
  const wide = matchMedia('(min-width: 1050px) and (pointer: fine)');
  const supported = new Set(['home','shop','community','events','lk','wallet','history','notices','friends','pet','commands','staffchat','reputation','admin']);
  const glyphs = {
    home:'M3 10l9-7 9 7v10H3z M9 20v-7h6v7', community:'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M22 21v-2a4 4 0 0 0-3-4 M16 3a4 4 0 0 1 0 8',
    staffchat:'M21 11a8 8 0 0 1-8 8H5l-3 3V11a9 9 0 0 1 19 0z', music:'M9 18V5l12-2v13 M9 9l12-2 M9 18a3 2 0 1 1-6 0 3 2 0 0 1 6 0 M21 16a3 2 0 1 1-6 0 3 2 0 0 1 6 0',
    games:'M6 7h12a4 4 0 0 1 4 4l1 6a3 3 0 0 1-5 2l-3-3H9l-3 3a3 3 0 0 1-5-2l1-6a4 4 0 0 1 4-4z M7 10v6 M4 13h6 M17 12h.1 M20 14h.1',
    pet:'M12 13c-3-4-8 1-8 5 0 3 4 4 8 2 4 2 8 1 8-2 0-4-5-9-8-5z M5 7h.1 M10 4h.1 M14 4h.1 M19 7h.1',
    events:'M3 5h18v16H3z M3 10h18 M7 3v4 M17 3v4', shop:'M4 8h16l1 13H3z M8 9V6a4 4 0 0 1 8 0v3', lk:'M12 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10 M3 22v-2a6 6 0 0 1 6-6h6a6 6 0 0 1 6 6v2', friends:'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M2 21v-2a5 5 0 0 1 5-5h4a5 5 0 0 1 5 5v2 M19 8v6 M16 11h6'
  };
  const icon = key => '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round"><path d="'+glyphs[key]+'"/></svg>';
  const t = value => window.NoraI18n?.t?.(value) || value;
  let left, right, current, route, friends, fetchedAt=0, pending=false, owner=null, requestEpoch=0;
  function node(tag, cls, text) {
    const el=document.createElement(tag); el.className=cls; if(text!==undefined)el.textContent=text; return el;
  }
  function button(key, label, kind='tab') {
    const el=node('button','desktop-nav-item'); el.type='button';
    el.innerHTML=icon(key); el.append(node('span','',t(label)));
    if(kind==='music')el.setAttribute('data-music-library',''); else el.dataset.tab=key;
    return el;
  }
  function setup() {
    if(left)return;
    left=node('aside','desktop-sidebar'); left.id='nora-desktop-left'; left.setAttribute('aria-label','Разделы Норы');
    right=node('aside','desktop-sidebar'); right.id='nora-desktop-right'; right.setAttribute('aria-label','Друзья и события');
    left.hidden=right.hidden=true;
    document.body.append(left,right);
  }
  function buildLeft() {
    const brand=node('div','desktop-brand'); brand.innerHTML='<img src="/intro/nora-home-icon.svg" alt=""><div><strong>НОРА</strong><small>DESKTOP · ALPHA</small></div>';
    const nav=node('div','desktop-nav'); 
    for(const [key,label,kind] of [['home','Главная'],['community','Коммьюнити'],['staffchat','Чат'],['music','Музыка','music'],['friends','Друзья'],['games','Игры'],['pet','Питомец'],['events','События'],['shop','Магазин'],['lk','Профиль']]){
      if(key==='staffchat'&&!current.staff_chat_available)continue;
      const el=button(key,label,kind); 
      if(key===route){el.classList.add('active');el.setAttribute('aria-current','page');}
      if(kind!=='music'&&profileTabLocked(key))el.setAttribute('aria-disabled','true');
      nav.append(el);
    }
    const u=current.user;
    const profile=node('button','desktop-identity');profile.type='button';profile.dataset.tab='lk';
    const avatar=node('span','desktop-avatar',(u.profile_name||u.telegram_name||'?').slice(0,1).toUpperCase());
    const copy=node('span','desktop-identity-copy');copy.append(node('b','',u.profile_name||u.telegram_name||t('Друг')),node('small','',number(u.cookies)+' 🍪'));
    profile.append(avatar,copy);
    left.replaceChildren(brand,nav,profile);
  }
  function buildRight() {
    const top=node('div','desktop-side-heading');top.append(node('h2','','Друзья'));
    const all=node('button','desktop-link','Все');all.type='button';all.dataset.tab='friends';top.append(all);
    const list=node('div','desktop-friends');
    if(current.profile.fill_percent!==100)list.append(node('p','desktop-muted','Заполни профиль, чтобы открыть друзей.'));
    else if(friends===undefined)list.append(node('p','desktop-muted',pending?'Загружаем…':'Список пока недоступен.'));
    else if(!friends.length)list.append(node('p','desktop-muted','Здесь появятся твои друзья.'));
    else {
      list.append(node('p','desktop-muted',friends.filter(p=>p.presence?.online).length+' / '+friends.length+' онлайн'));
      for(const p of friends.slice(0,8)){
        const b=node('button','desktop-friend');b.type='button';b.dataset.personView=String(p.id);
        const av=node('span','desktop-avatar',String(p.name||'?').slice(0,1).toUpperCase());
        const txt=node('span','desktop-friend-copy');txt.append(node('b','',p.name),node('small','',window.NoraPeople?.presenceLine(p.presence)||''));
        const dot=node('i','desktop-presence'+(p.presence?.online?' online':''));
        b.append(av,txt,dot);list.append(b);
      }
    }
    const reload=node('button','desktop-link','Обновить');reload.type='button';reload.disabled=pending||current.profile.fill_percent!==100;reload.onclick=()=>loadFriends(true);
    const events=node('div','desktop-side-heading');events.append(node('h2','','События'));
    const more=node('button','desktop-link','Все');more.type='button';more.dataset.tab='events';events.append(more);
    const next=node('div','desktop-events');
    for(const e of (current.events||[]).slice(0,3)){
      const b=node('button','desktop-event');b.type='button';b.dataset.tab='events';
      b.append(node('span','desktop-event-icon','↗'),node('b','',e.title));next.append(b);
    }
    if(!next.childNodes.length)next.append(node('p','desktop-muted','Новые встречи появятся здесь.'));
    right.replaceChildren(top,list,reload,events,next);
  }
  async function loadFriends(force=false) {
    if(!wide.matches||!document.body.classList.contains('nora-desktop')||document.hidden||current?.profile?.fill_percent!==100||pending||(!force&&Date.now()-fetchedAt<120000))return;
    pending=true;fetchedAt=Date.now();const epoch=++requestEpoch;buildRight();
    try {const r=await api('friends');if(epoch===requestEpoch)friends=Array.isArray(r.friends)?r.friends:[];}
    catch {if(epoch===requestEpoch)friends=undefined;}
    finally {if(epoch===requestEpoch){pending=false;if(document.body.classList.contains('nora-desktop'))buildRight();}}
  }
  function sync(payload, screen) {
    current=payload;route=screen;
    const id=payload?.user?.user_id;
    if(owner!==id){owner=id;friends=undefined;fetchedAt=0;pending=false;requestEpoch++;}
    const active=wide.matches&&!!payload?.profile&&!payload.onboarding&&supported.has(screen);
    document.body.classList.toggle('nora-desktop',active);
    if(!active){if(left)left.hidden=right.hidden=true;return;}
    setup();left.hidden=right.hidden=false;buildLeft();buildRight();void loadFriends();
  }
  wide.addEventListener('change',()=>{if(current)sync(current,route);});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)void loadFriends();});
  return {sync};
})();
