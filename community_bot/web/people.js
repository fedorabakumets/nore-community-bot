'use strict';
window.NoraPeople = (() => {
  const session=crypto.randomUUID();
  let seq=0,started=false,heartbeatTimer=null,person=null,avatarURL=null,generation=0,loading=false,privacyRequest=0;
  function presenceLine(p) {
    if(!p?.visible)return NoraI18n.t("Активность скрыта");
    if(p.online)return NoraI18n.t("В сети");
    if(!Number.isFinite(p.last_seen)||p.last_seen<=0)return NoraI18n.t("Ещё не был в сети");
    // User-visible status deliberately does not distinguish exact exit from
    // last heartbeat: that distinction describes telemetry, not a person's intent.
    const at=new Date(p.last_seen*1000);
    if(Number.isNaN(at.getTime()))return NoraI18n.t("Время активности недоступно");
    const now=new Date();
    const minutes=Math.max(0,Math.floor((now-at)/60000));
    if(minutes<1)return NoraI18n.t("Был только что");
    if(minutes<60)return NoraI18n.t("Был ")+minutes+' '+plural(minutes,NoraI18n.t("минуту"),NoraI18n.t("минуты"),NoraI18n.t("минут"))+NoraI18n.t(" назад");
    if(at.toDateString()===now.toDateString())return NoraI18n.t("Был в ")+at.toLocaleTimeString(NoraI18n.locale,{hour:'2-digit',minute:'2-digit'});
    const yesterday=new Date(now);
    yesterday.setDate(yesterday.getDate()-1);
    if(at.toDateString()===yesterday.toDateString())return NoraI18n.t("Был в сети вчера");
    const days=Math.round((Date.UTC(now.getFullYear(),now.getMonth(),now.getDate())-
      Date.UTC(at.getFullYear(),at.getMonth(),at.getDate()))/86400000);
    if(days<=7)return NoraI18n.t("Был в сети ")+days+' '+plural(days,NoraI18n.t("день"),NoraI18n.t("дня"),NoraI18n.t("дней"))+NoraI18n.t(" назад");
    return NoraI18n.t("Был в сети давно");
  }
  function beat(active) {
    if(!started||!auth||data?.profile.fill_percent!==100)return;
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
    const field=(label,value)=>`<div class="tg-profile-field"><span>${label}</span><div>${value}</div></div>`;
    const stats=`<div class="tg-profile-fields person-stats">${field(NoraI18n.t("репутация"),locked?'🔒':number(p.reputation)+' / 100 · '+esc(NoraI18n.t(p.tier)))}${field(NoraI18n.t("печеньки"),locked?'🔒':number(p.cookies)+' 🍪')}</div>`;
    return `<div id="person-profile" data-person-id="${p.id}" data-profile-theme="${profileTheme(p)}" tabindex="-1" autofocus><div class="profile-heading"><button type="button" class="profile-photo person-photo" data-view-avatar aria-label="${NoraI18n.html("Открыть фото профиля")}" disabled>${esc(initials)}</button><div><div class="person-name-line"><h2>${esc(p.name)}</h2>${tgkLink(p.tg_channel_url)}</div>${p.hidden?'':`<p class="person-presence ${p.presence?.online?'online':''}" title="${NoraI18n.html("Это активность в миниапке, не статус Telegram")}">${esc(presenceLine(p.presence))}</p>`}<div class="person-profile-meta">${p.prefix?NoraPrefix(p.prefix):p.role?esc(p.role):NoraI18n.t("Участник Норы")}${p.likes==null?'':`<span class="social-like-count" data-person-likes aria-label="${NoraI18n.html("Лайки:")} ${number(p.likes)}">${profileLikeText(p.likes)}</span>`}</div></div></div>${p.hidden?("<section class=\"card person-locked\"><h3>" + NoraI18n.html("Профиль скрыт") + "</h3><p class=\"sub\">" + NoraI18n.html("Владелец ограничил просмотр профиля.") + "</p></section>"):`${NoraProfileTrack.html(p.track, '/api/people/'+p.id+'/track')}${p.music_library_public?NoraProfileTrack.libraryButton(p.id):''}<div class="tg-profile-fields person-details">${p.username?field(NoraI18n.t("имя пользователя"),'@'+esc(p.username)):''}${locked?'':field(NoraI18n.t("о себе"),esc(p.bio||NoraI18n.t("Пока без описания.")))}${field(NoraI18n.t("возраст"),p.age?number(p.age):NoraI18n.t("Не указан"))}${field(NoraI18n.t("город"),esc(p.city||NoraI18n.t("Не указан")))}${locked?'':field(NoraI18n.t("увлечения"),esc(p.hobbies||NoraI18n.t("Не указаны")))}${locked?field(NoraI18n.t("приватность"),NoraI18n.t("Закрытый профиль")):''}</div>`}${p.hidden&&p.username?`<div class="tg-profile-fields person-details">${field(NoraI18n.t("имя пользователя"),'@'+esc(p.username))}</div>`:''}${stats}<div class="person-actions tg-profile-actions">${p.friend?`<button type="button" class="primary" data-friend-transfer="${p.id}" data-friend-name="${esc(p.name)}">${NoraI18n.html("перевести")}</button><button type="button" class="secondary" data-friend-play="${p.id}">${NoraI18n.html("в игру")}</button>`:`<button type="button" class="secondary" data-person-add="${p.id}">${NoraI18n.html("в друзья")}</button>`}</div></div>`;
  }
  async function avatar(p,version) {
    if(!p.has_avatar||p.hidden)return;
    try {
      const r=await fetch('/api/people/'+p.id+'/avatar',{headers:{Authorization:'tma '+auth}});
      if(!r.ok)return;
      const blob=await r.blob();
      if(version!==generation||!document.querySelector('#person-profile')||!$('#sheet').open)return;
      discardAvatar();avatarURL=URL.createObjectURL(blob);
      const el=document.querySelector('.person-photo');if(el){el.innerHTML=`<img src="${avatarURL}" alt="${NoraI18n.html("Фото профиля")}">`;el.disabled=false;}
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
      person=p;sheet(profileHTML(p));
      // Keep dialog autofocus on the profile, not on the first action button.
      $('#person-profile')?.focus({preventScroll:true});avatar(p,version);
    } catch(e){toast(e.message)}finally{loading=false}
  }
  setInterval(async()=>{
    if(document.hidden||!$('#sheet').open||!document.querySelector('#person-profile')||loading||!person)return;
    const version=generation;
    try {
      const p=await api('people/'+person.id);
      const profile=$('#person-profile');
      if(version!==generation||!$('#sheet').open||!profile)return;
      if(p.tg_channel_url!==person.tg_channel_url||p.city!==person.city||p.role!==person.role||p.hidden!==person.hidden||p.private!==person.private||p.friend!==person.friend||p.has_avatar!==person.has_avatar||p.track?.revision!==person.track?.revision||JSON.stringify(p.prefix)!==JSON.stringify(person.prefix)){
        discardAvatar();person=p;$('#sheet-content').innerHTML=profileHTML(p);avatar(p,version);
      } else {
        person=p;
        const theme = profileTheme(p);
        if (profile.dataset.profileTheme !== theme) {
          profile.dataset.profileTheme = theme;
          syncTelegramPalette();
        }
        const likes=document.querySelector('[data-person-likes]');
        if(likes&&p.likes!=null){
          likes.textContent=profileLikeText(p.likes);
          likes.setAttribute('aria-label',NoraI18n.t("Лайки: ")+number(p.likes));
        }
        const el=document.querySelector('.person-presence');
        if(el){el.textContent=presenceLine(p.presence);el.classList.toggle('online',!!p.presence?.online)}
      }
    }catch{discardAvatar();person=null;$('#sheet-content').innerHTML=("<h2>" + NoraI18n.html("Профиль недоступен") + "</h2><p class=\"sub\">" + NoraI18n.html("Доступ или настройки приватности изменились.") + "</p>")}
  },15000);
  document.addEventListener('close',e=>{if(e.target!==$('#sheet'))return;generation++;privacyRequest++;person=null;discardAvatar()},true);
  document.addEventListener('click',e=>{
    const photo=e.target.closest('[data-view-avatar],#profile-photo');
    const img=photo?.querySelector('img');
    if(!img)return;
    const viewer=document.createElement('dialog');viewer.className='avatar-viewer';
    const full=document.createElement('img');full.src=img.src;full.alt=NoraI18n.t("Фото профиля");
    const close=document.createElement('button');close.type='button';close.textContent=NoraI18n.t("Закрыть");close.className='secondary';
    close.addEventListener('click',()=>viewer.close());
    viewer.addEventListener('click',event=>{if(event.target===viewer)viewer.close()});
    viewer.addEventListener('close',()=>viewer.remove(),{once:true});
    viewer.append(full,close);document.body.append(viewer);viewer.showModal();
  });
  document.addEventListener('click',async e=>{
    const b=e.target.closest('button');if(!b)return;
    if(b.dataset.personView)visit(Number(b.dataset.personView));
    if(b.dataset.personAdd){b.disabled=true;try{const r=await api('friends/action',{action:'request',recipient:b.dataset.personAdd});toast(r.message);b.textContent=NoraI18n.t("Заявка отправлена")}catch(err){toast(err.message);b.disabled=false}}
    if(b.id==='profile-lookup'){const recipient=document.querySelector('#friend-recipient')?.value.trim();if(recipient)visit(recipient);else toast(NoraI18n.t("Укажи точный @username или ID"))}
    if(b.hasAttribute('data-privacy-toggle')){await perform('profile/privacy',{hidden:!data.user.profile_private});return}
    if(b.hasAttribute('data-privacy-locked')){sheet(("<h2>" + NoraI18n.html("Закрытый профиль") + "</h2><p class=\"sub\">" + NoraI18n.html("Купи закрытый профиль в магазине, чтобы скрывать и открывать его в настройках.") + "</p><button class=\"primary\" data-product=\"private_profile\">" + NoraI18n.html("Посмотреть в магазине") + "</button>"));return}
    if(b.hasAttribute('data-presence-settings')||b.hasAttribute('data-lk-privacy')){
      const request=++privacyRequest;
      try{const s=await api('presence');if(request!==privacyRequest)return;sheet(`<h2>${NoraI18n.html("Приватность")}</h2><div class="card"><h3>${data.user.profile_private?NoraI18n.t("Профиль скрыт"):NoraI18n.t("Профиль открыт")}</h3><p class="sub">${data.privacy_owned?NoraI18n.t("Скрывай и открывай профиль без повторной покупки. Описание, увлечения, баланс и репутация скрыты от других пользователей."):NoraI18n.t("Чтобы скрывать профиль, купи «Закрытый профиль» в магазине.")}</p><button class="secondary" ${data.privacy_owned?'data-privacy-toggle':'data-privacy-locked'}>${data.privacy_owned?(data.user.profile_private?NoraI18n.t("Открыть профиль"):NoraI18n.t("Скрыть профиль")):NoraI18n.t("🔒 Скрыть профиль")}</button></div><h3 class="lk-presence-title">${NoraI18n.html("Видимость активности")}</h3><p class="sub">${NoraI18n.html("Виден только статус активности в Mini App: время, «вчера» или количество дней. После недели отображается «Был в сети давно». Это не статус Telegram. Это не статус Telegram. Закрытый профиль скрывает активность автоматически.")}</p><label class="presence-choice"><span>${NoraI18n.html("Показывать активность в Норе")}</span><input type="checkbox" id="presence-visible" ${s.hidden?'':'checked'}></label>`)}catch(err){toast(err.message)}
    }
  });
  document.addEventListener('change',async e=>{if(e.target.id!=='presence-visible')return;const el=e.target;el.disabled=true;try{await api('presence',{hidden:!el.checked});toast(NoraI18n.t("Видимость активности сохранена"))}catch(err){el.checked=!el.checked;toast(err.message)}finally{el.disabled=false}});
  queueMicrotask(()=>{if(typeof data!=='undefined'&&data?.user)start()});
  return {start,visit,presenceLine};
})();
