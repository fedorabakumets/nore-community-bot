'use strict';
window.NoraIncognito = (() => {
  let panel, feed, form, input, error, title, subtitle, lobby, tools, finder;
  let state = 'idle', session = null, cursor = 0, timer = null, busy = false, epoch = 0;
  let lastTyping = 0, pending = null, previousFocus = null, recent = null;
  let activeRequest = null, acting = false, confirmation = null, gesture = null, pressTimer = null;
  let selectedMessage = null, ended = false, fullHeight = 0;
  const tr = value => window.NoraI18n?.t(value) || value;
  const icons = {
    back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 5-7 7 7 7"/></svg>',
    more: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="19" cy="12" r="1.7"/></svg>',
    mask: '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 20c4-9 10-11 18-6 8-5 14-3 18 6l-4 10c-3 7-10 5-14-1-4 6-11 8-14 1z"/><path d="M12 23q5-5 10 0m4 0q5-5 10 0"/></svg>',
    send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5m-6 6 6-6 6 6"/></svg>',
    next: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m17 3 4 4-4 4M3 7h4l10 10h4m-4-4 4 4-4 4M3 17h4l3-3m4-4 3-3h4"/></svg>'
  };
  const $i = s => panel.querySelector(s);
  function haptic(type='light') {
    try { tg?.HapticFeedback?.impactOccurred(type); } catch {}
  }
  function create() {
    panel = document.createElement('dialog');
    panel.id = 'nora-incognito';
    panel.className = 'incognito-panel';
    panel.setAttribute('aria-label','Инкогнито');
    panel.innerHTML = `<header class="incognito-header"><button type="button" class="incognito-round" data-inc="close" aria-label="Назад">${icons.back}</button><div class="incognito-heading"><strong>Инкогнито</strong><small data-inc-status>Анонимный чат · 18+</small></div><button type="button" class="incognito-round" data-inc="menu" aria-label="Действия" hidden>${icons.more}</button></header>
      <section class="incognito-lobby"><div class="incognito-orbit"><i></i><i></i><i></i><div class="incognito-symbol">${icons.mask}</div></div><h1 data-inc-title>Кто-то незнакомый.</h1><p data-inc-copy>Ни имён, ни профилей.<br>Только вы и разговор.</p><button class="incognito-primary" data-inc="find">Найти собеседника</button><small>Только текст. Не отправляй личные данные.<br>После завершения последние сообщения доступны для жалобы 15 минут.</small><button type="button" class="incognito-recent" data-inc="recent-report" hidden>Пожаловаться на последнего собеседника</button></section>
      <div class="incognito-feed" role="log" aria-live="polite" hidden></div>
      <div class="incognito-error" role="status" hidden></div>
      <form class="incognito-compose" hidden><textarea rows="1" maxlength="2000" placeholder="Сообщение" aria-label="Сообщение"></textarea><button type="submit" aria-label="Отправить">${icons.send}</button></form>
      <div class="incognito-tools" hidden><button type="button" data-inc="next">${icons.next} Следующий</button><button type="button" data-inc="end">Завершить</button></div>
      <div class="incognito-menu" hidden><button data-inc="block" type="button">Заблокировать</button><button data-inc="report" type="button">Пожаловаться и заблокировать</button><button data-inc="menu" type="button">Отмена</button></div>
      <div class="incognito-message-menu" hidden><button data-inc="copy" type="button">Копировать</button><button data-inc="report" type="button">Пожаловаться</button><button data-inc="dismiss-message" type="button">Отмена</button></div>
      <div class="incognito-confirm" hidden><div class="incognito-confirm-card" role="alertdialog" aria-modal="true" aria-labelledby="incognito-confirm-title"><strong id="incognito-confirm-title"></strong><p></p><div><button type="button" data-inc-confirm="no">Отмена</button><button type="button" data-inc-confirm="yes">Подтвердить</button></div></div></div>`;
    // Translate only trusted UI text, never messages.
    const walker=document.createTreeWalker(panel,NodeFilter.SHOW_TEXT);
    while(walker.nextNode()){const node=walker.currentNode;if(node.nodeValue.trim())node.nodeValue=tr(node.nodeValue);}
    panel.querySelectorAll('[aria-label],[placeholder]').forEach(el=>{
      for(const key of ['aria-label','placeholder'])if(el.hasAttribute(key))el.setAttribute(key,tr(el.getAttribute(key)));
    });
    document.body.append(panel);
    feed=$i('.incognito-feed');form=$i('form');input=$i('textarea');error=$i('.incognito-error');
    title=$i('[data-inc-title]');subtitle=$i('[data-inc-status]');lobby=$i('.incognito-lobby');
    tools=$i('.incognito-tools');finder=$i('[data-inc="find"]');
    panel.addEventListener('click', e => {
      const choice=e.target.closest('[data-inc-confirm]');
      if(choice){finishConfirm(choice.dataset.incConfirm==='yes');return;}
      const button=e.target.closest('[data-inc]'); if(!button)return;
      void action(button.dataset.inc);
    });
    form.addEventListener('submit', e => {e.preventDefault();void send();});
    input.addEventListener('input', () => {
      input.style.height='auto';input.style.height=Math.min(input.scrollHeight,105)+'px';syncSend();
      if(state==='matched' && input.value.trim() && Date.now()-lastTyping>3000 && !busy && !acting) {
        lastTyping=Date.now();void request('typing',{session,after:cursor});
      }
    });
    panel.addEventListener('cancel', e=>{e.preventDefault();if(confirmation)finishConfirm(false);else void action('close');});
    const header=$i('.incognito-header');
    header.addEventListener('touchstart',e=>{if(e.touches.length===1&&!e.target.closest('button'))gesture={x:e.touches[0].clientX,y:e.touches[0].clientY};},{passive:true});
    header.addEventListener('touchend',e=>{if(!gesture)return;const p=e.changedTouches[0];const dy=p.clientY-gesture.y,dx=p.clientX-gesture.x;gesture=null;if(dy>72&&Math.abs(dx)<dy*.65)void action('close');},{passive:true});
    header.addEventListener('touchcancel',()=>{gesture=null;});
    feed.addEventListener('contextmenu',e=>{const bubble=e.target.closest('.incognito-bubble');if(bubble){e.preventDefault();messageMenu(bubble);}});
    feed.addEventListener('pointerdown',e=>{const bubble=e.target.closest('.incognito-bubble');if(!bubble)return;const x=e.clientX,y=e.clientY;clearTimeout(pressTimer);pressTimer=setTimeout(()=>messageMenu(bubble),550);gesture={x,y,press:true};});
    feed.addEventListener('pointermove',e=>{if(gesture?.press&&Math.hypot(e.clientX-gesture.x,e.clientY-gesture.y)>10)clearTimeout(pressTimer);});
    for(const name of ['pointerup','pointercancel','pointerleave'])feed.addEventListener(name,()=>{clearTimeout(pressTimer);gesture=null;});
    window.visualViewport?.addEventListener('resize',syncViewport);
    window.visualViewport?.addEventListener('scroll',syncViewport);
    window.addEventListener('resize',syncViewport);
    tg?.onEvent?.('safeAreaChanged',syncViewport);tg?.onEvent?.('contentSafeAreaChanged',syncViewport);
    panel.addEventListener('close', () => {
      clearTimeout(timer);clearTimeout(pressTimer);epoch++;finishConfirm(false);document.body.classList.remove('incognito-open');previousFocus?.focus?.({preventScroll:true});
    });
  }
  function syncViewport(){
    if(!panel?.open)return;
    const v=window.visualViewport,h=Math.round(v?.height||window.innerHeight),top=Math.round(v?.offsetTop||0);
    fullHeight=Math.max(fullHeight,h);panel.style.setProperty('--inc-viewport-height',h+'px');panel.style.setProperty('--inc-viewport-top',top+'px');
    panel.style.setProperty('--inc-controls',tg?.isFullscreen||tg?.initData?'56px':'0px');
    panel.dataset.keyboard=String(fullHeight-h>120);
    if(document.activeElement===input&&feed.scrollHeight-feed.scrollTop-feed.clientHeight<140)feed.scrollTop=feed.scrollHeight;
  }
  function syncSend(){form.querySelector('button[type="submit"]').disabled=!input.value.trim()||state!=='matched'||acting;}
  function showError(message='') {error.textContent=tr(message);error.hidden=!message;}
  function resetFeed(){feed.replaceChildren();const note=document.createElement('div');note.className='incognito-note';note.textContent=tr('Ваши личности скрыты');feed.append(note);}
  function finishConfirm(answer){if(!confirmation)return;const resolve=confirmation;confirmation=null;$i('.incognito-confirm').hidden=true;resolve(answer);}
  function confirmAction(heading,copy){
    if(confirmation)return Promise.resolve(false);
    input.blur();const box=$i('.incognito-confirm');box.querySelector('strong').textContent=tr(heading);box.querySelector('p').textContent=tr(copy);box.hidden=false;
    return new Promise(resolve=>{confirmation=resolve;});
  }
  function messageMenu(bubble){if(!bubble.isConnected||state!=='matched'||acting||confirmation)return;selectedMessage=bubble.querySelector('span').textContent;$i('.incognito-message-menu').hidden=false;$i('.incognito-menu').hidden=true;haptic();}
  function dismissMessage(){selectedMessage=null;$i('.incognito-message-menu').hidden=true;}
  function refreshView(old) {
    const matched=state==='matched', searching=state==='searching';
    panel.dataset.state=state;
    lobby.hidden=matched;feed.hidden=!matched;form.hidden=!matched;tools.hidden=!matched;
    $i('[data-inc="menu"]').hidden=!matched;
    if(!matched) {$i('.incognito-menu').hidden=true;dismissMessage();}
    $i('[data-inc="recent-report"]').hidden=!recent||matched;
    finder.textContent=tr(searching?'Отменить поиск':ended?'Найти нового':'Найти собеседника');
    title.textContent=tr(searching?'Ищем собеседника…':ended?'Диалог завершён.':'Кто-то незнакомый.');
    $i('[data-inc-copy]').textContent=tr(searching?'Кто-то тоже ищет разговор.':ended?'Можно начать новый разговор.':'Ни имён, ни профилей. Только вы и разговор.');
    subtitle.textContent=tr(matched?'Незнакомец':searching?'Поиск собеседника':'Анонимный чат · 18+');
    subtitle.dataset.online='false';subtitle.dataset.typing='false';syncSend();
    if(matched && old!=='matched') haptic('medium');
  }
  function accept(result) {
    const old=state;
    if(result.session!==session) {
      session=result.session;cursor=0;resetFeed();input.value='';input.style.height='auto';pending=null;dismissMessage();
      if(!session)input.blur();
    }
    if(result.state==='idle'&&old==='matched')ended=true;
    else if(result.state!=='idle')ended=false;
    state=result.state;recent=result.recent||null;refreshView(old);
    if(state==='matched') {
      subtitle.textContent=tr(result.typing?'печатает':result.online?'Незнакомец · в сети':'Незнакомец');
      subtitle.dataset.typing=String(!!result.typing);subtitle.dataset.online=String(!!result.online);
      const nearEnd=feed.scrollHeight-feed.scrollTop-feed.clientHeight<100;
      for(const msg of result.messages||[]) {
        if(msg.id<=cursor)continue;
        cursor=msg.id;
        const bubble=document.createElement('article');bubble.className='incognito-bubble'+(msg.mine?' mine':'');
        const text=document.createElement('span');text.textContent=msg.text;
        const time=document.createElement('time');time.textContent=new Date(msg.created_at*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
        bubble.append(text,time);feed.append(bubble);
      }
      if(nearEnd || old!=='matched')feed.scrollTop=feed.scrollHeight;
    }
    return result;
  }
  function schedule(delay=1800) {
    clearTimeout(timer);
    if(panel?.open && !document.hidden && state!=='idle'&&!acting)timer=setTimeout(()=>void request('status',{after:cursor}),delay);
  }
  function request(name,data={},quiet=false){
    if(busy||!panel?.open)return Promise.resolve(null);
    const run=performRequest(name,data,quiet);activeRequest=run;
    void run.finally(()=>{if(activeRequest===run)activeRequest=null;});return run;
  }
  async function performRequest(name, data, quiet) {
    clearTimeout(timer);busy=true;const current=epoch;
    if(!quiet && name!=='status' && name!=='typing')showError();
    try {
      const result=await api('incognito/'+name,data);
      if(current!==epoch || !panel.open)return null;
      accept(result);if(name==='status')showError();
      return result;
    } catch(e) {
      if(current===epoch && panel.open) {
        showError(e.message || 'Не удалось подключиться');
        if(e.status===403){state='idle';session=null;cursor=0;resetFeed();input.value='';pending=null;refreshView('idle');}
      }
      return null;
    } finally {busy=false;if(current===epoch)schedule();}
  }
  async function send() {
    const text=input.value.trim();
    if(!text || state!=='matched' || acting)return;
    const target=session;acting=true;clearTimeout(timer);syncSend();
    try{
    if(activeRequest)await activeRequest;
    if(state!=='matched'||session!==target)return;
    if(!pending || pending.text!==text || pending.session!==session) {
      const bytes=crypto.getRandomValues(new Uint8Array(16));
      pending={session, text, client_id:Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('')};
    }
    const result=await request('send',{...pending,after:cursor});
    if(result){if(input.value.trim()===text){input.value='';input.style.height='auto';}pending=null;haptic();}
    }finally{acting=false;syncSend();schedule();}
  }
  async function action(name) {
    if(confirmation)return;
    if(name==='dismiss-message'){dismissMessage();return;}
    if(name==='copy'){
      try{await navigator.clipboard.writeText(selectedMessage||'');haptic();}catch{showError('Не удалось скопировать сообщение');}
      dismissMessage();return;
    }
    if(name==='menu'){dismissMessage();$i('.incognito-menu').hidden=!$i('.incognito-menu').hidden;return;}
    if(acting)return;
    const target=session,previousState=state,reportTarget=recent;
    acting=true;clearTimeout(timer);syncSend();
    try{
      if(activeRequest)await activeRequest;
      if(!panel.open)return;
      if(name==='close'){
        if(state==='matched'&&!await confirmAction('Завершить диалог?','Переписка исчезнет из чата.'))return;
        if(state!=='idle'&&!await request('end',{session}))return;
        panel.close();return;
      }
      if(name==='find'){
        if(previousState==='searching'&&state==='matched')return;
        haptic();await request(state==='searching'?'end':'join',{session,after:cursor});return;
      }
      if(name==='recent-report'){
        if(reportTarget&&await confirmAction('Пожаловаться?','Последние сообщения будут переданы модераторам. Собеседник будет заблокирован.'))await request('report',{session:reportTarget});
        return;
      }
      if(session!==target||state!=='matched')return;
      const prompts={
        next:['Найти другого собеседника?','Текущий диалог завершится.'],
        end:['Завершить диалог?','Переписка исчезнет из чата.'],
        block:['Заблокировать собеседника?','Вы больше не встретитесь в Инкогнито.'],
        report:['Пожаловаться?','Последние сообщения будут переданы модераторам. Собеседник будет заблокирован.']
      };
      if(!prompts[name])return;
      dismissMessage();$i('.incognito-menu').hidden=true;
      if(!await confirmAction(...prompts[name]))return;
      haptic();await request(name,{session:target});
    }finally{acting=false;syncSend();schedule();}
  }
  function open() {
    if(!panel)create();
    if(panel.open)return;
    previousFocus=document.activeElement;
    state='idle';session=null;recent=null;cursor=0;ended=false;resetFeed();input.value='';pending=null;showError();refreshView('idle');
    document.body.classList.add('incognito-open');fullHeight=0;panel.showModal();syncViewport();void request('status');
  }
  document.addEventListener('click',e=>{if(e.target.closest('[data-incognito-open]')){e.preventDefault();open();}});
  document.addEventListener('visibilitychange',()=>{if(document.hidden){clearTimeout(timer);}else if(panel?.open&&!acting){syncViewport();void request('status',{after:cursor});}});
  return {open, isOpen:()=>!!panel?.open};
})();
