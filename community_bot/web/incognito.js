'use strict';
window.NoraIncognito = (() => {
  let panel, feed, form, input, error, title, subtitle, lobby, tools, finder;
  let state = 'idle', session = null, cursor = 0, timer = null, busy = false, epoch = 0;
  let lastTyping = 0, pending = null, previousFocus = null;
  const icons = {
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
    panel.innerHTML = `<header class="incognito-header"><button type="button" class="incognito-round" data-inc="close" aria-label="Назад">‹</button><div class="incognito-heading"><strong>Инкогнито</strong><small data-inc-status>Анонимный чат · 18+</small></div><button type="button" class="incognito-round" data-inc="menu" aria-label="Действия" hidden>···</button></header>
      <section class="incognito-lobby"><div class="incognito-orbit"><i></i><i></i><i></i><div class="incognito-symbol">${icons.mask}</div></div><h1 data-inc-title>Кто-то незнакомый.</h1><p data-inc-copy>Ни имён, ни профилей.<br>Только вы и разговор.</p><button class="incognito-primary" data-inc="find">Найти собеседника</button><small>Только текст. Не отправляй личные данные.</small></section>
      <div class="incognito-feed" role="log" aria-live="polite" hidden></div>
      <div class="incognito-error" role="status" hidden></div>
      <form class="incognito-compose" hidden><textarea rows="1" maxlength="2000" placeholder="Сообщение" aria-label="Сообщение"></textarea><button type="submit" aria-label="Отправить">${icons.send}</button></form>
      <div class="incognito-tools" hidden><button type="button" data-inc="next">${icons.next} Следующий</button><button type="button" data-inc="end">Завершить</button></div>
      <div class="incognito-menu" hidden><button data-inc="block" type="button">Заблокировать</button><button data-inc="report" type="button">Пожаловаться и заблокировать</button><button data-inc="menu" type="button">Отмена</button></div>`;
    document.body.append(panel);
    feed=$i('.incognito-feed');form=$i('form');input=$i('textarea');error=$i('.incognito-error');
    title=$i('[data-inc-title]');subtitle=$i('[data-inc-status]');lobby=$i('.incognito-lobby');
    tools=$i('.incognito-tools');finder=$i('[data-inc="find"]');
    panel.addEventListener('click', e => {
      const button=e.target.closest('[data-inc]'); if(!button)return;
      void action(button.dataset.inc);
    });
    form.addEventListener('submit', e => {e.preventDefault();void send();});
    input.addEventListener('input', () => {
      input.style.height='auto';input.style.height=Math.min(input.scrollHeight,105)+'px';
      if(state==='matched' && input.value.trim() && Date.now()-lastTyping>3000 && !busy) {
        lastTyping=Date.now();void request('typing',{session,after:cursor});
      }
    });
    panel.addEventListener('cancel', e=>{e.preventDefault();void action('close');});
    panel.addEventListener('close', () => {
      clearTimeout(timer);epoch++;document.body.classList.remove('incognito-open');previousFocus?.focus?.({preventScroll:true});
    });
  }
  function showError(message='') {error.textContent=message;error.hidden=!message;}
  function refreshView(old) {
    const matched=state==='matched', searching=state==='searching';
    panel.dataset.state=state;
    lobby.hidden=matched;feed.hidden=!matched;form.hidden=!matched;tools.hidden=!matched;
    $i('[data-inc="menu"]').hidden=!matched;
    if(!matched) $i('.incognito-menu').hidden=true;
    finder.textContent=searching?'Отменить поиск':'Найти собеседника';
    title.textContent=searching?'Ищем собеседника…':old==='matched'?'Диалог завершён.':'Кто-то незнакомый.';
    $i('[data-inc-copy]').textContent=searching?'Кто-то тоже ищет разговор.':old==='matched'?'Можно начать новый разговор.':'Ни имён, ни профилей. Только вы и разговор.';
    subtitle.textContent=matched?'Незнакомец':searching?'Поиск собеседника':'Анонимный чат · 18+';
    if(matched && old!=='matched') haptic('medium');
  }
  function accept(result) {
    const old=state;
    if(result.session!==session) {
      session=result.session;cursor=0;feed.replaceChildren();input.value='';input.style.height='auto';pending=null;
    }
    state=result.state;refreshView(old);
    if(state==='matched') {
      subtitle.textContent=result.typing?'печатает…':result.online?'Незнакомец · в сети':'Незнакомец';
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
    if(panel?.open && !document.hidden && state!=='idle')timer=setTimeout(()=>void request('status',{after:cursor}),delay);
  }
  async function request(name, data={}, quiet=false) {
    if(busy || !panel?.open)return null;
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
        if(e.status===403){state='idle';session=null;cursor=0;feed.replaceChildren();input.value='';pending=null;refreshView('idle');}
      }
      return null;
    } finally {busy=false;if(current===epoch)schedule();}
  }
  async function send() {
    const text=input.value.trim();
    if(!text || state!=='matched' || busy)return;
    if(!pending || pending.text!==text || pending.session!==session) {
      const bytes=crypto.getRandomValues(new Uint8Array(16));
      pending={session, text, client_id:Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('')};
    }
    const result=await request('send',{...pending,after:cursor});
    if(result){input.value='';input.style.height='auto';pending=null;haptic();}
  }
  async function action(name) {
    if(name==='menu'){$i('.incognito-menu').hidden=!$i('.incognito-menu').hidden;return;}
    if(busy){showError('Подожди, выполняется запрос');return;}
    if(name==='close') {
      if(state==='matched'&&!window.confirm('Завершить анонимный диалог?'))return;
      if(state!=='idle' && !await request('end',{session}))return;
      panel.close();return;
    }
    if(name==='find'){haptic();await request(state==='searching'?'end':'join',{session,after:cursor});return;}
    if(name==='report'&&!window.confirm('Отправить последние 12 сообщений модераторам и заблокировать собеседника?'))return;
    if(name==='block'&&!window.confirm('Заблокировать собеседника?'))return;
    if(name==='end'&&!window.confirm('Завершить диалог?'))return;
    if(['next','end','block','report'].includes(name)){
      $i('.incognito-menu').hidden=true;haptic();await request(name,{session});
    }
  }
  function open() {
    if(!panel)create();
    if(panel.open)return;
    previousFocus=document.activeElement;
    state='idle';session=null;cursor=0;feed.replaceChildren();input.value='';pending=null;showError();refreshView('idle');
    document.body.classList.add('incognito-open');panel.showModal();void request('status');
  }
  document.addEventListener('click',e=>{if(e.target.closest('[data-incognito-open]')){e.preventDefault();open();}});
  document.addEventListener('visibilitychange',()=>{if(document.hidden){clearTimeout(timer);}else if(panel?.open){void request('status',{after:cursor});}});
  return {open, isOpen:()=>!!panel?.open};
})();
