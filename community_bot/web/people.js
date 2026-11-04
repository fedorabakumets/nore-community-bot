'use strict';
window.NoraPeople = (() => {
  const session=crypto.randomUUID();
  let seq=0,started=false,heartbeatTimer=null,person=null,avatarURL=null,generation=0,loading=false,privacyRequest=0;
  function presenceLine(p) {
    if(!p?.visible)return 'Активность скрыта';
    if(p.online)return 'В сети в Норе';
    if(!p.last_seen)return 'Ещё не заходил(а) в Нору';
    const minutes=Math.max(1,Math.floor((Date.now()/1000-p.last_seen)/60));
    if(minutes<5)return 'Был(а) недавно';
    if(minutes<60)return 'Был(а) менее часа назад';
    if(minutes<1440)return 'Был(а) сегодня';
    return 'Был(а) давно';
  }
  function beat(active) {
    if(!started||!auth)return;
    fetch('/api/presence',{method:'POST',keepalive:!active,headers:{Authorization:'tma '+auth,'Content-Type':'application/json'},
      body:JSON.stringify({session,seq:++seq,active})}).catch(()=>{});
  }
  function start() {
    if(started)return;
    started=true;beat(!document.hidden);
    heartbeatTimer=setInterval(()=>{if(!document.hidden)beat(true)},20000);
  }
  document.addEventListener('visibilitychange',()=>beat(!document.hidden));
  window.addEventListener('pagehide',()=>beat(false));
  window.addEventListener('pageshow',()=>{if(started&&!document.hidden)beat(true)});
  function discardAvatar(){if(avatarURL){URL.revokeObjectURL(avatarURL);avatarURL=null}}
  function profileHTML(p) {
    const initials=(p.name.match(/[\p{L}\p{N}]/u)?.[0]||'?').toUpperCase();
    const locked=p.private;
    const stats=`<div class="stats"><div class="stat"><span class="eyebrow">Репутация</span><b class="num">${locked?'🔒':number(p.reputation)}</b>${locked?'':`<small>${esc(p.tier)}</small>`}</div><div class="stat"><span class="eyebrow">Печеньки</span><b class="num">${locked?'🔒':number(p.cookies)+' 🍪'}</b></div></div>`;
    return `<div id="person-profile" data-person-id="${p.id}"><span class="eyebrow">Участник Норы</span><div class="profile-heading"><button type="button" class="profile-photo person-photo" data-view-avatar aria-label="Открыть фото профиля" disabled>${esc(initials)}</button><div><h2>${esc(p.name)}</h2><p class="sub">${p.username?'@'+esc(p.username):'Участник сообщества'}</p></div></div>${p.prefix?`<p class="person-role">${NoraPrefix(p.prefix)}</p>`:p.role?`<p class="sub person-role">${esc(p.role)}</p>`:''}${p.hidden?'<section class="card person-locked"><h3>Профиль скрыт</h3><p class="sub">Владелец ограничил просмотр профиля.</p></section>':`<p class="person-presence ${p.presence?.online?'online':''}" title="Это активность в миниапке, не статус Telegram">${esc(p.friend?presenceLine(p.presence):'Активность видна друзьям')}</p>${locked?'<p class="sub">Закрытый профиль</p>':''}${locked?'':`<p class="bio">${esc(p.bio||'Пока без описания.')}</p>`}<p class="sub">Возраст: ${p.age?number(p.age):'не указан'}${locked?'':`<br>Увлечения: ${esc(p.hobbies||'не указаны')}`}</p>`}${stats}<div class="person-actions">${p.friend?`<button class="primary" data-friend-transfer="${p.id}" data-friend-name="${esc(p.name)}">Перевести печеньки</button><button class="secondary" data-friend-play="${p.id}">Пригласить в игру</button>`:`<button class="secondary" data-person-add="${p.id}">Добавить в друзья</button>`}</div></div>`;
  }
  async function avatar(p,version) {
    if(!p.has_avatar||p.hidden)return;
    try {
      const r=await fetch('/api/people/'+p.id+'/avatar',{headers:{Authorization:'tma '+auth}});
      if(!r.ok)return;
      const blob=await r.blob();
      if(version!==generation||!document.querySelector('#person-profile')||!$('#sheet').open)return;
      discardAvatar();avatarURL=URL.createObjectURL(blob);
      const el=document.querySelector('.person-photo');if(el){el.innerHTML=`<img src="${avatarURL}" alt="Фото профиля">`;el.disabled=false;}
    } catch {}
  }
  async function visit(idOrRecipient) {
    if(loading||busy)return;
    if(idOrRecipient===data.user.user_id){$('#sheet').close();tab='lk';NoraShop.tabChanged(tab);render();return}
    loading=true;const version=++generation;discardAvatar();
    try {
      const path=typeof idOrRecipient==='number'?'people/'+idOrRecipient:'people?recipient='+encodeURIComponent(idOrRecipient);
      const p=await api(path);if(version!==generation)return;
      if(p.id===data.user.user_id){$('#sheet').close();tab='lk';NoraShop.tabChanged(tab);render();return}
      person=p;sheet(profileHTML(p));avatar(p,version);
    } catch(e){toast(e.message)}finally{loading=false}
  }
  setInterval(async()=>{
    if(document.hidden||!$('#sheet').open||!document.querySelector('#person-profile')||loading||!person)return;
    const version=generation;
    try {
      const p=await api('people/'+person.id);if(version!==generation||!document.querySelector('#person-profile'))return;
      if(p.role!==person.role||p.hidden!==person.hidden||p.private!==person.private||p.friend!==person.friend||p.has_avatar!==person.has_avatar||JSON.stringify(p.prefix)!==JSON.stringify(person.prefix)){
        discardAvatar();person=p;$('#sheet-content').innerHTML=profileHTML(p);avatar(p,version);
      } else {
        person=p;const el=document.querySelector('.person-presence');
        if(el){el.textContent=presenceLine(p.presence);el.classList.toggle('online',!!p.presence?.online)}
      }
    }catch{discardAvatar();person=null;$('#sheet-content').innerHTML='<h2>Профиль недоступен</h2><p class="sub">Доступ или настройки приватности изменились.</p>'}
  },15000);
  document.addEventListener('close',e=>{if(e.target!==$('#sheet'))return;generation++;privacyRequest++;person=null;discardAvatar()},true);
  document.addEventListener('click',e=>{
    const photo=e.target.closest('[data-view-avatar],#profile-photo');
    const img=photo?.querySelector('img');
    if(!img)return;
    const viewer=document.createElement('dialog');viewer.className='avatar-viewer';
    const full=document.createElement('img');full.src=img.src;full.alt='Фото профиля';
    const close=document.createElement('button');close.type='button';close.textContent='Закрыть';close.className='secondary';
    close.addEventListener('click',()=>viewer.close());
    viewer.addEventListener('click',event=>{if(event.target===viewer)viewer.close()});
    viewer.addEventListener('close',()=>viewer.remove(),{once:true});
    viewer.append(full,close);document.body.append(viewer);viewer.showModal();
  });
  document.addEventListener('click',async e=>{
    const b=e.target.closest('button');if(!b)return;
    if(b.dataset.personView)visit(Number(b.dataset.personView));
    if(b.dataset.personAdd){b.disabled=true;try{const r=await api('friends/action',{action:'request',recipient:b.dataset.personAdd});toast(r.message);b.textContent='Заявка отправлена'}catch(err){toast(err.message);b.disabled=false}}
    if(b.id==='profile-lookup'){const recipient=document.querySelector('#friend-recipient')?.value.trim();if(recipient)visit(recipient);else toast('Укажи точный @username или ID')}
    if(b.hasAttribute('data-privacy-toggle')){await perform('profile/privacy',{hidden:!data.user.profile_private});return}
    if(b.hasAttribute('data-privacy-locked')){sheet('<h2>Закрытый профиль</h2><p class="sub">Купи закрытый профиль в магазине, чтобы скрывать и открывать его в настройках.</p><button class="primary" data-product="private_profile">Посмотреть в магазине</button>');return}
    if(b.hasAttribute('data-presence-settings')||b.hasAttribute('data-lk-privacy')){
      const request=++privacyRequest;
      try{const s=await api('presence');if(request!==privacyRequest)return;sheet(`<h2>Приватность</h2><div class="card"><h3>${data.user.profile_private?'Профиль скрыт':'Профиль открыт'}</h3><p class="sub">${data.privacy_owned?'Скрывай и открывай профиль без повторной покупки. Описание, увлечения, баланс и репутация скрыты от других пользователей.':'Чтобы скрывать профиль, купи «Закрытый профиль» в магазине.'}</p><button class="secondary" ${data.privacy_owned?'data-privacy-toggle':'data-privacy-locked'}>${data.privacy_owned?(data.user.profile_private?'Открыть профиль':'Скрыть профиль'):'🔒 Скрыть профиль'}</button></div><h3 class="lk-presence-title">Видимость активности</h3><p class="sub">Участники видят, когда у тебя открыта Нора. Это не статус во всём Telegram. Закрытый профиль скрывает активность автоматически.</p><label class="presence-choice"><span>Показывать активность в Норе</span><input type="checkbox" id="presence-visible" ${s.hidden?'':'checked'}></label>`)}catch(err){toast(err.message)}
    }
  });
  document.addEventListener('change',async e=>{if(e.target.id!=='presence-visible')return;const el=e.target;el.disabled=true;try{await api('presence',{hidden:!el.checked});toast('Видимость активности сохранена')}catch(err){el.checked=!el.checked;toast(err.message)}finally{el.disabled=false}});
  queueMicrotask(()=>{if(typeof data!=='undefined'&&data?.user)start()});
  return {start,visit,presenceLine};
})();
