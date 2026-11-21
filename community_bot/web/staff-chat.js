'use strict';
// Staff Telegram community mirror: WebSocket updates and explicitly bot-attributed sends.
window.NoraStaffChat = (() => {

  let timer = null, loading = false, signature = '', contextId = null, visit = 0, observer = null;
  let liveSocket = null, liveReady = false, liveAttempt = 0, liveFailures = 0;
  let retryTimer = null, handshakeTimer = null, heartbeatTimer = null;
  let refreshTimer = null, refreshPending = false, typingTimeout = null;
  let newCount = 0, lastTypingSent = 0;
  const unreadIds = new Set();
  const cache = new Map();
  let draft = '', replyTarget = null, attachment = null, sending = false, emojiOpen = false;
  const maxUpload = 12 * 1024 * 1024;
  const quickEmoji = ['😂','❤️','🔥','👍','🥲','👀','🍪','🎧','🤝','💀'];
  const mediaLabels = {
    photo: 'Фото', video: 'Видео', animation: 'GIF',
    voice: 'Голосовое', video_note: 'Кружочек',
    audio: 'Аудио', document: 'Документ',
    sticker: 'Стикер', poll: 'Опрос',
    location: 'Геопозиция', contact: 'Контакт'
  };
  const time = value => {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? '' :
      d.toLocaleTimeString('ru-RU', {hour:'2-digit',minute:'2-digit'});
  };
  const mediaTile = m => {
    if(!m.media_type)return '';
    const id = Number(m.id);
    const type = esc(m.media_type);
    const playable = ['photo','sticker','video','animation','voice','video_note','audio'].includes(m.media_type);
    if(!playable || !m.has_media)
      return `<div class="staff-chat-media"><span>📎 ${esc(mediaLabels[m.media_type] || 'Вложение')}</span></div>`;
    const autoplay = ['photo','sticker'].includes(m.media_type) || (m.has_thumbnail && ['video','animation','video_note'].includes(m.media_type));
    const symbol = {photo:'▧',sticker:'◈',video:'▶',animation:'▶',video_note:'▶',voice:'♫',audio:'♫'}[m.media_type] || '▷';
    return `<div class="staff-chat-asset" data-chat-asset="${id}" data-chat-type="${type}" data-chat-thumb="${m.has_thumbnail?'1':'0'}" data-chat-auto="${autoplay?'1':'0'}" data-chat-link="${esc(m.link||'')}">
        <button type="button" class="staff-chat-media-action" data-chat-activate="${id}"><span class="staff-chat-media-symbol">${symbol}</span><span>${esc(mediaLabels[m.media_type])}</span></button>
        <div class="staff-chat-media-player" hidden></div>
      </div>`;
  };

  const richRow = m => {
    const blocks = Array.isArray(m.rich) ? m.rich : [];
    if(!blocks.length)return '';
    const id = Number(m.id);
    const nAudio = blocks.filter(block=>block.type==='audio').length;
    const parts = blocks.slice(0,80).map((block,i)=>{
      const type = block.type;
      const text = esc(block.text || '');
      if(type==='heading')return `<h3 class="staff-rich-heading">${text}</h3>`;
      if(type==='text')return `<p class="staff-rich-text">${text}</p>`;
      if(type==='details')return `<p class="staff-rich-detail">${text}</p>`;
      if(type==='photo'){
        if(!Number.isInteger(block.asset))return '<div class="staff-rich-placeholder">Обложка в Telegram</div>';
        return `<div class="staff-rich-cover" data-rich-cover="${id}" data-rich-part="${block.asset}">
          <span>Загружаем обложку…</span></div>`;
      }
      if(type==='audio'){
        const title=esc(block.title||'Аудиотрек');
        const performer=esc(block.performer||'');
        const duration=Number(block.duration)>0?`${Math.floor(Number(block.duration)/60)}:${String(Number(block.duration)%60).padStart(2,'0')}`:'';
        const playable=Number.isInteger(block.asset);
        return `<div class="staff-rich-track">
          <button type="button" class="staff-rich-track-start" data-rich-play="${id}" data-rich-part="${playable?block.asset:'-1'}" ${playable?'':'disabled'} aria-label="Воспроизвести ${title}">▶</button>
          <div class="staff-rich-track-copy"><strong>${title}</strong>${performer?`<span>${performer}</span>`:''}</div>
          ${duration?`<time>${duration}</time>`:''}
          <div class="staff-rich-track-player" hidden></div>
        </div>`;
      }
      if(type==='buttons'){
        return `<div class="staff-rich-buttons">${(block.buttons||[]).slice(0,12).map(btn=>{
          const label=esc(btn.text||'Открыть');
          const url=typeof btn.url==='string' && /^https?:\/\//i.test(btn.url)?esc(btn.url):'';
          return url?`<a href="${url}" data-chat-telegram target="_blank" rel="noopener noreferrer">${label}</a>`:`<span>${label} · в Telegram</span>`;
        }).join('')}</div>`;
      }
      if(['video','animation','voice_note','document'].includes(type))
        return `<div class="staff-rich-placeholder">📎 ${esc(mediaLabels[type]||'Медиа')} · ${m.link?'<span>Открыть в Telegram ↗</span>':''}</div>`;
      return '';
    }).join('');
    return `<section class="staff-rich-card" aria-label="${nAudio?'Музыкальная подборка':'Rich-сообщение'}">
      ${parts}
    </section>`;
  };

  const msgSignature = m => [m.edited_at || '', m.reply_text || '', m.reply_name || '', m.text || '', m.media_type || '', m.has_thumbnail ? '1' : '0', JSON.stringify(m.rich||[])].join('|');
  const line = m => {
    const id = Number(m.id);
    const sent = new Date(m.sent_at);
    const day = Number.isNaN(sent.getTime()) ? '' :
      [sent.getFullYear(),String(sent.getMonth()+1).padStart(2,'0'),String(sent.getDate()).padStart(2,'0')].join('-');
    const dayLabel = Number.isNaN(sent.getTime()) ? '' :
      sent.toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'});
    const name = esc(m.name || 'Участник');
    const initial = esc((m.name || '?').match(/[\p{L}\p{N}]/u)?.[0]?.toUpperCase() || '?');
    const who = Number(m.user_id) > 0
      ? `<button class="staff-chat-author" data-person-view="${m.user_id}" type="button">${name}</button>`
      : `<span class="staff-chat-author">${name}</span>`;
    const avatar = `<span class="staff-chat-avatar" ${Number(m.user_id) > 0 ? `data-person-avatar="${m.user_id}" ${!m.has_avatar?'data-avatar-unavailable':''}` : ''}>${initial}</span>`;
    const quote = m.reply_to_id ? `<button class="staff-chat-reply" type="button" data-chat-reply="${Number(m.reply_to_id)}" data-chat-link="${esc(m.reply_link||'')}">
        <b>${esc(m.reply_name || 'Сообщение')}</b><span>${esc((m.reply_text || mediaLabels[m.reply_media_type] || 'Сообщение').slice(0,90))}</span>
      </button>` : '';
    const body = m.text ? `<div class="staff-chat-text">${esc(m.text)}</div>` : '';
    const link = m.link ? `<a class="staff-chat-original" href="${esc(m.link)}" target="_blank" rel="noopener noreferrer" aria-label="Открыть в Telegram">↗</a>` : '';
    const replyButton = `<button class="staff-chat-answer" type="button" data-chat-answer="${id}" data-chat-name="${name}" data-chat-preview="${esc((m.text || (m.media_type ? mediaLabels[m.media_type] : '') || 'Rich-сообщение').slice(0,140))}" aria-label="Ответить на сообщение">↩</button>`;
    const hideButton = `<button class="staff-chat-hide" type="button" data-chat-hide="${id}" aria-label="Скрыть сообщение из зеркала" title="Скрыть из зеркала">×</button>`;
    return `<article class="staff-chat-message" data-message-id="${id}" data-chat-day="${day}" data-chat-date="${esc(dayLabel)}">
       ${avatar}<div class="staff-chat-bubble">
         <div class="staff-chat-meta">${who}<time datetime="${esc(m.sent_at)}">${time(m.sent_at)}</time>${m.edited_at?'<span class="staff-chat-edited">изм.</span>':''}${link}${replyButton}${hideButton}</div>
         ${quote}${mediaTile(m)}${richRow(m)}${body}
       </div>
     </article>`;
  };
  function screen() {
    return `<section class="nora-staff-chat">
      <header class="staff-chat-header">
        <button class="staff-chat-back" type="button" data-tab="community" aria-label="Назад в Коммьюнити">
          <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m14 5-7 7 7 7"/></svg>
        </button>
        <span class="staff-chat-mark" aria-hidden="true"><span></span></span>
        <div class="staff-chat-heading">
          <h1>Чат Норы</h1>
          <span id="staff-chat-live-status" data-live-state="connecting"><i aria-hidden="true"></i><b>Подключаем…</b><small id="staff-chat-live-count"></small></span>
        </div>
        <span class="staff-chat-team-label">КОМАНДА</span>
      </header>
      <div id="staff-chat-feed" class="staff-chat-feed" aria-label="Сообщения чата" aria-live="off">
        <p class="staff-chat-empty">Подключаем чат…</p>
      </div>
      <div class="staff-chat-activity" aria-live="polite">
        <button type="button" id="staff-chat-new" class="staff-chat-new" data-chat-scroll-new hidden>Новые сообщения ↓</button>
        <div id="staff-chat-typing" class="staff-chat-typing" hidden></div>
        <button type="button" class="staff-chat-latest" data-chat-latest hidden>К последним ↓</button>
      </div>
      <form id="staff-chat-compose" class="staff-chat-compose" autocomplete="off">
        <div class="staff-chat-compose-reply" id="staff-chat-compose-reply" hidden></div>
        <div class="staff-chat-compose-file" id="staff-chat-compose-file" hidden></div>
        <div class="staff-chat-compose-row">
          <button type="button" class="staff-chat-add-file" data-chat-attach aria-label="Прикрепить файл" title="Прикрепить файл">＋</button>
          <input id="staff-chat-file" type="file" accept=".jpg,.jpeg,.png,.webp,.heic,.heif,.gif,.mp4,.mov,.webm,.mp3,.m4a,.ogg,.oga,.opus,.aac,.wav,.pdf,.txt" hidden>
          <textarea id="staff-chat-draft" rows="1" maxlength="3000" placeholder="Сообщение в чат…" aria-label="Сообщение в Telegram-чат"></textarea>
          <button type="button" class="staff-chat-emoji-toggle" data-chat-emoji-toggle aria-label="Эмодзи" title="Эмодзи">☺</button>
          <button type="submit" id="staff-chat-submit" class="staff-chat-submit" aria-label="Отправить в чат" disabled>➤</button>
        </div>
        <div class="staff-chat-emoji-palette" id="staff-chat-emoji-palette" hidden>
          ${quickEmoji.map(emoji=>`<button type="button" data-chat-emoji="${esc(emoji)}" aria-label="Добавить ${esc(emoji)}">${emoji}</button>`).join('')}
        </div>
        <p class="staff-chat-compose-hint"><span aria-hidden="true">●</span> Отправка от бота Норы с подписью автора · до 12 МБ</p>
      </form>
    </section>`;
  }

  const pendingAssets = new Map();
  const mediaCacheBytes = () => [...cache.values()].reduce((sum, value) => sum + value.size, 0);
  function clearAssets() {
    observer?.disconnect(); observer = null;
    for(const asset of cache.values()) URL.revokeObjectURL(asset.url);
    cache.clear();
    pendingAssets.clear();
  }
  async function getAsset(messageId, thumb = false, part = null) {
    const key = messageId + ':' + (part === null ? (thumb ? 'thumb' : 'full') : 'part:'+part);
    if(cache.has(key)) {
      const hit = cache.get(key);
      cache.delete(key); cache.set(key, hit);
      return hit;
    }
    if(pendingAssets.has(key))return pendingAssets.get(key);
    const currentVisit = visit;
    const request = (async() => {
      try {
        const url = '/api/community/chat/media/' + messageId +
          (part !== null ? '?part='+part : (thumb ? '?thumb=1' : ''));
        const response = await fetch(url, {headers:{Authorization:'tma '+auth}});
        if(!response.ok) {
          let payload = {};
          try { payload = await response.json(); } catch {}
          throw new Error(payload.error || 'Файл недоступен');
        }
        const blob = await response.blob();
        if(currentVisit !== visit || tab !== 'staffchat')return null;
        const result = {url:URL.createObjectURL(blob),type:blob.type,size:blob.size};
        cache.set(key, result);
        while(cache.size > 30 || mediaCacheBytes() > 96*1024*1024) {
          const oldest = cache.keys().next().value;
          if(oldest === key || !oldest)break;
          URL.revokeObjectURL(cache.get(oldest).url);
          cache.delete(oldest);
        }
        return result;
      } finally {
        pendingAssets.delete(key);
      }
    })();
    pendingAssets.set(key, request);
    return request;
  }
  function embedMedia(node, asset, thumb) {
    if(!node.isConnected || !asset)return;
    const id = node.dataset.chatAsset;
    const type = node.dataset.chatType;
    const key = id + ':' + (thumb ? 'thumb' : 'full');
    if(node.dataset.chatRendered === key)return;
    const action = node.querySelector('[data-chat-activate]');
    const stage = node.querySelector('.staff-chat-media-player');
    if(!action || !stage)return;
    if(asset.type.startsWith('image/')) {
      const img = new Image();
      img.alt = mediaLabels[type] || 'Вложение';
      img.src = asset.url;
      img.decoding = 'async';
      action.replaceChildren(img);
      action.classList.add('has-preview');
      action.hidden = false; stage.hidden = true; stage.replaceChildren();
      if(thumb && ['video','animation','video_note'].includes(type)) {
        const icon = document.createElement('span');
        icon.className = 'staff-chat-video-play';
        icon.textContent = '▶';
        action.append(icon);
      }
    } else if(asset.type.startsWith('video/') && !thumb) {
      const video = document.createElement('video');
      video.src = asset.url;
      video.playsInline = true; video.preload = 'metadata';
      if(['sticker','animation'].includes(type)) {
        video.muted = true; video.loop = true; video.autoplay = true;
      } else video.controls = true;
      video.className = type === 'video_note' ? 'staff-chat-round-video' : '';
      stage.replaceChildren(video);
      stage.hidden = false; action.hidden = true;
      if(video.autoplay) void video.play().catch(()=>{});
    } else if(asset.type.startsWith('audio/') && !thumb) {
      const audio = document.createElement('audio');
      audio.controls = true; audio.preload = 'metadata'; audio.src = asset.url;
      stage.replaceChildren(audio);
      stage.hidden = false; action.hidden = true;
    } else return;
    node.dataset.chatRendered = key;
  }
  function assetError(node, message) {
    if(!node.isConnected)return;
    const action = node.querySelector('[data-chat-activate]');
    const stage = node.querySelector('.staff-chat-media-player');
    if(!stage || !action)return;
    const url = node.dataset.chatLink;
    stage.innerHTML = `<div class="staff-chat-media-fallback">${esc(message)}</div>`+
      (url ? `<a class="staff-chat-telegram-link" href="${esc(url)}" data-chat-telegram target="_blank" rel="noopener noreferrer">Открыть в Telegram</a>` : '');
    action.hidden = true;stage.hidden = false;
  }
  async function displayAsset(node, thumb=false) {
    if(!node?.isConnected || node.dataset.chatLoading === '1')return;
    const key = node.dataset.chatAsset + ':' + (thumb ? 'thumb':'full');
    if(node.dataset.chatRendered === key)return;
    node.dataset.chatLoading = '1';
    try {
      const asset = await getAsset(node.dataset.chatAsset, thumb);
      if(node.isConnected)embedMedia(node, asset, thumb);
    } catch(error) {
      if(!node.isConnected)return;
      if(thumb)return; // A missing video preview must not block playback.
      if(node.dataset.chatType === 'sticker' && node.dataset.chatThumb === '1') {
        try {
          const preview = await getAsset(node.dataset.chatAsset, true);
          embedMedia(node, preview, true);
          return;
        }catch {}
      }
      assetError(node, error.message || 'Файл недоступен');
    } finally {
      node.dataset.chatLoading = '0';
    }
  }

  async function richCover(node) {
    if(!node?.isConnected || node.dataset.richLoaded)return;
    node.dataset.richLoaded='1';
    const id = Number(node.dataset.richCover), part=Number(node.dataset.richPart);
    try {
      const result=await getAsset(id,false,part);
      if(!node.isConnected)return;
      if(!result?.type.startsWith('image/'))throw Error('Обложка недоступна');
      const image=new Image();
      image.src=result.url;image.alt='Обложка подборки';image.decoding='async';
      node.replaceChildren(image);
    }catch {
      if(node.isConnected)node.textContent='Обложка доступна в Telegram';
    }
  }
  async function richPlay(button) {
    if(!button?.isConnected || button.disabled)return;
    const id=Number(button.dataset.richPlay),part=Number(button.dataset.richPart);
    if(!Number.isInteger(part)||part<0)return;
    const track=button.closest('.staff-rich-track');
    const holder=track?.querySelector('.staff-rich-track-player');
    if(!holder)return;
    button.disabled=true;button.textContent='…';
    try {
      const result=await getAsset(id,false,part);
      if(!button.isConnected || !result)return;
      if(!result.type.startsWith('audio/'))throw Error('Аудио недоступно');
      const player=document.createElement('audio');
      player.controls=true;player.preload='metadata';player.src=result.url;
      player.setAttribute('aria-label','Аудиотрек Норы');
      holder.replaceChildren(player);holder.hidden=false;
      button.textContent='♫';
      void player.play().catch(()=>{});
    }catch(error){
      button.textContent='▶';
      const link=button.closest('.staff-chat-message')?.querySelector('.staff-chat-original');
      holder.innerHTML=`<p class="staff-rich-error">${esc(error.message||'Не удалось открыть аудио')}</p>`+
        (link ? `<a data-chat-telegram href="${esc(link.href)}" target="_blank" rel="noopener noreferrer">Открыть в Telegram ↗</a>`:'');
      holder.hidden=false;
    }finally{if(button.isConnected)button.disabled=false;}
  }

  function hydrateMedia() {
    observer?.disconnect();observer = null;
    const feed = document.getElementById('staff-chat-feed');
    if(!feed)return;
    const assets = [...feed.querySelectorAll('[data-chat-asset][data-chat-auto="1"]')];
    const loadVisible = node => displayAsset(node,
      node.dataset.chatThumb === '1' && ['video','animation','video_note'].includes(node.dataset.chatType));
    if(typeof IntersectionObserver === 'undefined') {
      assets.slice(-12).forEach(loadVisible);
      for(const node of feed.querySelectorAll('[data-rich-cover]:not([data-rich-loaded])'))
        void richCover(node);
      return;
    }
    observer = new IntersectionObserver(entries => {
      for(const entry of entries) {
        if(entry.isIntersecting) {
          observer?.unobserve(entry.target);
          void loadVisible(entry.target);
        }
      }
    }, {root:feed,rootMargin:'90px'});
    assets.forEach(node=>observer.observe(node));
    for(const node of feed.querySelectorAll('[data-rich-cover]:not([data-rich-loaded])'))
      void richCover(node);
  }
  function applyMessages(feed, items, force=false) {
    const existing = new Map([...feed.querySelectorAll('.staff-chat-message')]
      .map(el => [Number(el.dataset.messageId),el]));
    const firstExisting = existing.keys().next().value;
    if(force || !existing.size || (items.length && items[0].id < firstExisting)) {
      feed.innerHTML = items.length ? items.map(line).join('') :
        '<p class="staff-chat-empty">Новых сообщений пока нет. Всё появится автоматически.</p>';
    } else {
      const ids = new Set(items.map(m=>Number(m.id)));
      for(const [id,node] of existing)if(!ids.has(id))node.remove();
      for(const m of items) {
        const old = existing.get(Number(m.id));
        if(!old || !old.isConnected)feed.insertAdjacentHTML('beforeend',line(m));
        else if(old.dataset.chatSig !== msgSignature(m))old.outerHTML = line(m);
      }
    }
    const info = new Map(items.map(m=>[Number(m.id),m]));
    for(const node of feed.querySelectorAll('.staff-chat-message')) {
      const msg = info.get(Number(node.dataset.messageId));
      if(msg)node.dataset.chatSig = msgSignature(msg);
    }
    hydrateMedia();
    decorateDates(feed);
  }
  function decorateDates(feed) {
    // Date headers belong to the scrollable history, not the fixed screen chrome.
    for(const date of feed.querySelectorAll('.staff-chat-day'))date.remove();
    let previous = '';
    for(const message of feed.querySelectorAll('.staff-chat-message')){
      const day=message.dataset.chatDay || '';
      if(day && day!==previous){
        const divider=document.createElement('div');
        divider.className='staff-chat-day';
        divider.textContent=message.dataset.chatDate || '';
        message.before(divider);
      }
      previous=day;
    }
  }
  function focusMessage(id) {
    const feed = document.getElementById('staff-chat-feed');
    if(!feed)return false;
    const item = [...feed.querySelectorAll('.staff-chat-message')]
      .find(el=>Number(el.dataset.messageId)===id);
    if(!item)return false;
    const top = feed.scrollTop + item.getBoundingClientRect().top -
      feed.getBoundingClientRect().top - 26;
    feed.scrollTo({top:Math.max(0,top),behavior:'smooth'});
    item.classList.remove('staff-chat-focus');
    void item.offsetWidth;
    item.classList.add('staff-chat-focus');
    setTimeout(()=>item.classList.remove('staff-chat-focus'),1700);
    return true;
  }
  async function load(force=false) {
    if(tab !== 'staffchat' || document.hidden || loading)return;
    const feed = document.getElementById('staff-chat-feed');
    if(!feed)return;
    const version = visit;
    loading = true;
    try {
      const result = await api('community/chat' +
        (contextId === null ? '' : '?around='+contextId));
      const target = document.getElementById('staff-chat-feed');
      if(tab !== 'staffchat' || version !== visit || !target)return;
      const items = Array.isArray(result.items) ? result.items : [];
      const next = items.map(m=>m.id+':'+msgSignature(m)).join('~');
      if(next === signature && target.querySelector('.staff-chat-message'))return;
      const wasAtBottom = target.scrollHeight - target.scrollTop - target.clientHeight < 95;
      const fresh = !signature || force;
      signature = next;
      applyMessages(target, items, fresh);
      if(contextId !== null)focusMessage(contextId);
      else if(fresh || wasAtBottom)target.scrollTop = target.scrollHeight;
      const latest = document.querySelector('[data-chat-latest]');
      if(latest) latest.hidden = contextId === null;
    } catch(error) {
      const target = document.getElementById('staff-chat-feed');
      if(tab === 'staffchat' && target && !target.querySelector('.staff-chat-message'))
        target.innerHTML = `<p class="staff-chat-empty">${esc(error.message || 'Чат недоступен')}</p><button type="button" class="staff-chat-retry" data-staff-chat-retry>Повторить</button>`;
      else if(contextId !== null)toast(error.message || 'Сообщение недоступно');
    } finally {
      loading=false;
      if(refreshPending && tab==='staffchat' && !document.hidden) {
        refreshPending=false;
        void load();
      }
    }
  }
  async function navigateReply(button) {
    const id = Number(button.dataset.chatReply);
    if(!Number.isSafeInteger(id) || id <= 0)return;
    if(focusMessage(id))return;
    const oldContext = contextId;
    contextId = id;
    signature = '';
    try {
      const result = await api('community/chat?around='+id);
      if(tab !== 'staffchat')return;
      const feed = document.getElementById('staff-chat-feed');
      if(!feed)return;
      applyMessages(feed,result.items || [],true);
      signature = (result.items || []).map(m=>m.id+':'+msgSignature(m)).join('~');
      document.querySelector('[data-chat-latest]').hidden = false;
      focusMessage(id);
    }catch(error) {
      contextId = oldContext;
      const link = button.dataset.chatLink;
      if(link && tg?.openTelegramLink)tg.openTelegramLink(link);
      else toast(error.message || 'Сообщение не найдено');
    }
  }
  function showPhoto(asset) {
    if(!asset || !asset.type.startsWith('image/'))return;
    sheet(`<div class="staff-chat-image-view"><img src="${esc(asset.url)}" alt="Фото из чата Норы"></div>`);
  }

  async function hideEntry(button) {
    if(!button || !button.isConnected)return;
    if(button.dataset.confirm !== '1') {
      button.dataset.confirm='1';
      button.textContent='Скрыть?';
      button.classList.add('confirm');
      button.setAttribute('aria-label','Подтвердить скрытие только из зеркала');
      setTimeout(()=>{
        if(button.isConnected && button.dataset.confirm==='1') {
          button.dataset.confirm='';
          button.textContent='×';
          button.classList.remove('confirm');
          button.setAttribute('aria-label','Скрыть сообщение из зеркала');
        }
      },5000);
      return;
    }
    const messageId=Number(button.dataset.chatHide);
    if(!Number.isSafeInteger(messageId) || messageId <= 0)return;
    button.disabled=true;
    try {
      await api('community/chat/hide',{message_id:messageId});
      const feed=document.getElementById('staff-chat-feed');
      button.closest('.staff-chat-message')?.remove();
      signature='outdated after hide';
      if(feed && !feed.querySelector('.staff-chat-message')) {
        feed.innerHTML='<p class="staff-chat-empty">В сохранённой истории больше нет сообщений.</p>';
      }
      void load();
    } catch(error) {
      button.disabled=false;
      button.dataset.confirm='';
      button.textContent='×';
      button.classList.remove('confirm');
      toast(error.message||'Не удалось скрыть сообщение');
    }
  }


  function composeUpdate() {
    const field = document.getElementById('staff-chat-draft');
    const form = document.getElementById('staff-chat-compose');
    if(!field || !form)return;
    field.maxLength = attachment ? 800 : 3000;
    const send = document.getElementById('staff-chat-submit');
    if(send){
      send.disabled = sending || (!draft.trim() && !attachment) || draft.length > (attachment?800:3000);
      send.textContent = sending ? '…' : '➤';
    }
    const back = document.getElementById('staff-chat-compose-reply');
    if(back){
      back.hidden = !replyTarget;
      back.innerHTML = replyTarget
        ? `<span><b>↩ ${esc(replyTarget.name)}</b><small>${esc(replyTarget.preview)}</small></span><button type="button" data-chat-cancel-reply aria-label="Отменить ответ">×</button>`
        : '';
    }
    const chosen = document.getElementById('staff-chat-compose-file');
    if(chosen){
      chosen.hidden = !attachment;
      chosen.innerHTML = attachment
        ? `<span>📎 ${esc(attachment.name)} · ${(attachment.size/1048576).toFixed(1)} МБ</span><button type="button" data-chat-remove-file aria-label="Убрать вложение">×</button>`
        : '';
    }
    const emoji = document.getElementById('staff-chat-emoji-palette');
    if(emoji)emoji.hidden = !emojiOpen;
    field.style.height = 'auto';
    field.style.height = Math.min(field.scrollHeight, 106) + 'px';
  }
  function prepareComposer() {
    const field = document.getElementById('staff-chat-draft');
    if(!field)return;
    field.value = draft;
    composeUpdate();
  }
  async function sendCompose() {
    if(sending || (!draft.trim() && !attachment))return;
    const text = draft.trim();
    const reply_to = replyTarget?.id || null;
    if(text.length > (attachment ? 800 : 3000)){
      toast('Слишком длинный текст для сообщения с вложением');
      return;
    }
    sending = true;
    composeUpdate();
    try {
      let result;
      if(attachment){
        if(attachment.size > maxUpload)throw new Error('Файл должен быть не больше 12 МБ');
        const form = new FormData();
        form.append('file',attachment,attachment.name);
        form.append('text',text);
        if(reply_to)form.append('reply_to',String(reply_to));
        const response = await fetch('/api/community/chat/upload',{
          method:'POST',headers:{Authorization:'tma '+auth},body:form
        });
        try {result=await response.json();}catch{throw new Error('Нет ответа от сервера Норы')}
        if(!response.ok)throw new Error(result.error || 'Не удалось отправить вложение');
      }else{
        result=await api('community/chat/send',{text,reply_to});
      }
      if(!result?.ok)throw new Error('Telegram не подтвердил отправку');
      draft='';attachment=null;replyTarget=null;emojiOpen=false;contextId=null;
      signature='';
      const file=document.getElementById('staff-chat-file');
      if(file)file.value='';
      prepareComposer();
      void load(true);
    }catch(error){
      toast(error.message || 'Не удалось отправить сообщение');
    }finally{
      sending=false;composeUpdate();
    }
  }
  function selectReply(button) {
    const id=Number(button.dataset.chatAnswer);
    if(!Number.isSafeInteger(id) || id<=0)return;
    replyTarget={
      id,
      name:button.dataset.chatName || 'Сообщение',
      preview:button.dataset.chatPreview || 'Ответ в Telegram'
    };
    composeUpdate();
    document.getElementById('staff-chat-draft')?.focus();
  }


  function connectionStatus(label,state='connecting',online=null) {
    const node=document.getElementById('staff-chat-live-status');
    if(!node)return;
    node.dataset.liveState=state;
    const title=node.querySelector('b'),count=node.querySelector('small');
    if(title)title.textContent=label;
    if(count && online!==null)count.textContent=online>0?` · ${online} в Mini App`:'';
    if(count && state!=='live')count.textContent='';
  }
  function isFeedAtBottom() {
    const node=document.getElementById('staff-chat-feed');
    return !node || node.scrollHeight-node.scrollTop-node.clientHeight<105;
  }
  function updateUnread() {
    const button=document.getElementById('staff-chat-new');
    if(!button)return;
    button.hidden=newCount<1;
    if(newCount>0)button.textContent=`${newCount} новых сообщений ↓`;
  }
  function queueRefresh() {
    if(tab!=='staffchat'||document.hidden)return;
    if(refreshTimer!==null)clearTimeout(refreshTimer);
    refreshTimer=setTimeout(()=>{
      refreshTimer=null;
      if(loading)refreshPending=true;
      else void load();
    },75);
  }
  function startFallback() {
    if(timer!==null||tab!=='staffchat'||document.hidden)return;
    timer=setInterval(()=>{if(tab==='staffchat')void load()},6000);
    void load();
  }
  function stopFallback() {
    if(timer!==null){clearInterval(timer);timer=null;}
  }
  function stopRealtime() {
    liveAttempt++;
    liveReady=false;
    stopFallback();
    for(const id of [retryTimer,handshakeTimer,heartbeatTimer,refreshTimer,typingTimeout]){
      if(id!==null)clearTimeout(id);
    }
    retryTimer=null;handshakeTimer=null;heartbeatTimer=null;
    refreshTimer=null;typingTimeout=null;refreshPending=false;
    if(liveSocket){
      const old=liveSocket;
      liveSocket=null;
      old.onopen=old.onmessage=old.onclose=old.onerror=null;
      try{old.close(1000,'Leaving NORA chat');}catch{}
    }
  }
  function showTyping(name) {
    const node=document.getElementById('staff-chat-typing');
    if(!node||tab!=='staffchat')return;
    node.textContent=name+' печатает из Mini App…';
    node.hidden=false;
    if(typingTimeout!==null)clearTimeout(typingTimeout);
    typingTimeout=setTimeout(()=>{
      typingTimeout=null;
      if(node.isConnected)node.hidden=true;
    },3300);
  }
  function postTyping() {
    if(!draft.trim()||!liveReady||!liveSocket||liveSocket.readyState!==WebSocket.OPEN)return;
    const now=Date.now();
    if(now-lastTypingSent<2500)return;
    lastTypingSent=now;
    try{liveSocket.send(JSON.stringify({type:'typing'}));}catch{}
  }
  function connectLive() {
    if(tab!=='staffchat'||document.hidden)return;
    if(liveSocket && (liveSocket.readyState===WebSocket.CONNECTING || liveSocket.readyState===WebSocket.OPEN))return;
    if(typeof WebSocket==='undefined'||!auth){
      connectionStatus('Режим обновления','fallback');
      startFallback();return;
    }
    const generation=++liveAttempt;
    let socket;
    try{
      const protocol=location.protocol==='https:'?'wss:':'ws:';
      socket=new WebSocket(protocol+'//'+location.host+'/ws/community/chat');
    }catch{
      connectionStatus('Режим обновления','fallback');
      startFallback();return;
    }
    liveSocket=socket;
    liveReady=false;
    connectionStatus(liveFailures?'Переподключаем…':'Подключаем…');
    const valid=()=>generation===liveAttempt && liveSocket===socket && tab==='staffchat';
    const cleanup=()=>{
      if(handshakeTimer!==null){clearTimeout(handshakeTimer);handshakeTimer=null;}
      if(heartbeatTimer!==null){clearInterval(heartbeatTimer);heartbeatTimer=null;}
    };
    handshakeTimer=setTimeout(()=>{
      if(valid()&&!liveReady)socket.close();
    },9000);
    socket.onopen=()=>{
      if(!valid())return;
      try{socket.send(JSON.stringify({type:'auth',init_data:auth}));}catch{socket.close();}
    };
    socket.onmessage=event=>{
      if(!valid())return;
      let payload;
      try{payload=JSON.parse(event.data);}catch{return;}
      if(!payload||typeof payload!=='object')return;
      if(payload.type==='ready'){
        liveReady=true;liveFailures=0;
        cleanup();
        stopFallback();
        connectionStatus('В реальном времени','live',Number(payload.online)||0);
        heartbeatTimer=setInterval(()=>{
          if(valid()&&liveReady&&socket.readyState===WebSocket.OPEN){
            try{socket.send(JSON.stringify({type:'ping'}));}catch{}
          }
        },20000);
        queueRefresh();
      }else if(payload.type==='change'){
        const ids=Array.isArray(payload.ids)?payload.ids.map(Number):[];
        if(payload.operation==='delete'&&contextId!==null&&ids.includes(contextId)){
          contextId=null;signature='';
        }
        if(payload.operation==='message'){
          const feed=document.getElementById('staff-chat-feed');
          const maxShown=feed
            ? Math.max(0,...[...feed.querySelectorAll('[data-message-id]')].map(n=>Number(n.dataset.messageId)||0))
            : 0;
          const incoming=ids.filter(id=>Number.isSafeInteger(id)&&id>maxShown&&!unreadIds.has(id));
          if(incoming.length && (!isFeedAtBottom()||contextId!==null)){
            for(const id of incoming)unreadIds.add(id);
            newCount=unreadIds.size;
            updateUnread();
          }
        }
        queueRefresh();
      }else if(payload.type==='presence'){
        connectionStatus('В реальном времени','live',Number(payload.online)||0);
      }else if(payload.type==='typing'&&typeof payload.name==='string'){
        showTyping(payload.name.slice(0,48));
      }else if(payload.type==='error'&&payload.reason==='access'){
        connectionStatus('Нет доступа','offline');
        socket._noraDenied=true;
      }
    };
    socket.onerror=()=>{if(valid()&&socket.readyState!==WebSocket.CLOSED)socket.close();};
    socket.onclose=()=>{
      if(!valid())return;
      cleanup();
      liveSocket=null;
      liveReady=false;
      if(socket._noraDenied){
        connectionStatus('Нет доступа','offline');return;
      }
      if(document.hidden)return;
      liveFailures=Math.min(liveFailures+1,5);
      connectionStatus('Переподключаем…','fallback');
      startFallback();
      const delay=Math.min(16000,800*2**Math.min(liveFailures,4));
      retryTimer=setTimeout(()=>{retryTimer=null;connectLive()},delay);
    };
  }

  function syncChatViewport() {
    const app = document.getElementById('app');
    if(!app || tab !== 'staffchat' || app.dataset.screen !== 'staffchat')return;
    const viewport = window.visualViewport;
    // iOS keyboard shrinks the visual viewport without reliably resizing 100dvh.
    const height = Math.max(1,Math.round(viewport?.height || window.innerHeight));
    const top = Math.max(0,Math.round(viewport?.offsetTop || 0));
    app.style.setProperty('--staff-chat-viewport-height',height+'px');
    app.style.setProperty('--staff-chat-viewport-top',top+'px');
  }
  function clearChatViewport() {
    const app = document.getElementById('app');
    app?.style.removeProperty('--staff-chat-viewport-height');
    app?.style.removeProperty('--staff-chat-viewport-top');
  }
  function mount() {
    stopRealtime();
    observer?.disconnect();observer = null;
    visit++;
    loading=false;signature='';contextId=null;
    newCount=0;unreadIds.clear();
    if(tab !== 'staffchat'){clearAssets();clearChatViewport();return;}
    syncChatViewport();
    prepareComposer();
    updateUnread();
    void load();
    connectLive();
  }
  window.visualViewport?.addEventListener('resize',syncChatViewport);
  window.visualViewport?.addEventListener('scroll',syncChatViewport);
  window.addEventListener('resize',syncChatViewport);

  document.addEventListener('submit',event=>{
    if(event.target?.id === 'staff-chat-compose'){
      event.preventDefault();
      void sendCompose();
    }
  });
  document.addEventListener('input',event=>{
    if(event.target?.id === 'staff-chat-draft'){
      draft=event.target.value;composeUpdate();postTyping();
    }
  });
  document.addEventListener('change',event=>{
    if(event.target?.id !== 'staff-chat-file')return;
    const selected=event.target.files?.[0];
    if(!selected)return;
    if(selected.size > maxUpload){
      toast('Файл должен быть не больше 12 МБ');
      event.target.value='';return;
    }
    attachment=selected;emojiOpen=false;composeUpdate();
  });

  document.addEventListener('click',event=>{
    if(tab !== 'staffchat')return;

    if(event.target.closest('[data-chat-scroll-new]')){
      const feed=document.getElementById('staff-chat-feed');
      if(contextId!==null){contextId=null;signature='';void load(true);}
      else if(feed)feed.scrollTo({top:feed.scrollHeight,behavior:'smooth'});
      newCount=0;unreadIds.clear();updateUnread();return;
    }
    const answer = event.target.closest('[data-chat-answer]');
    if(answer){selectReply(answer);return;}
    if(event.target.closest('[data-chat-cancel-reply]')){
      replyTarget=null;composeUpdate();return;
    }
    if(event.target.closest('[data-chat-remove-file]')){
      attachment=null;const file=document.getElementById('staff-chat-file');
      if(file)file.value='';composeUpdate();return;
    }
    if(event.target.closest('[data-chat-attach]')){
      document.getElementById('staff-chat-file')?.click();return;
    }
    if(event.target.closest('[data-chat-emoji-toggle]')){
      emojiOpen=!emojiOpen;composeUpdate();return;
    }
    const emojiButton=event.target.closest('[data-chat-emoji]');
    if(emojiButton){
      const symbol=emojiButton.dataset.chatEmoji || '';
      const field=document.getElementById('staff-chat-draft');
      if(field && symbol){
        const start=field.selectionStart,end=field.selectionEnd;
        const allowed=attachment ? 800 : 3000;
        if(draft.length - (end-start) + symbol.length <= allowed){
          draft=draft.slice(0,start)+symbol+draft.slice(end);
          field.value=draft;
          field.focus();
          field.setSelectionRange(start+symbol.length,start+symbol.length);
          composeUpdate();postTyping();
        }
      }
      return;
    }

    const hide=event.target.closest('[data-chat-hide]');
    if(hide){void hideEntry(hide);return;}
    if(event.target.closest('[data-staff-chat-retry]')){signature='';void load(true);}
    if(event.target.closest('[data-chat-latest]')){
      contextId = null;signature = '';
      void load(true);
    }
    const richPlayButton=event.target.closest('[data-rich-play]');
    if(richPlayButton){void richPlay(richPlayButton);return;}
    const reply = event.target.closest('[data-chat-reply]');
    if(reply){void navigateReply(reply);return;}
    const action = event.target.closest('[data-chat-activate]');
    if(action){
      const node = action.closest('[data-chat-asset]');
      if(!node)return;
      const type = node.dataset.chatType;
      const key = node.dataset.chatAsset + ':full';
      const ready = cache.get(key);
      if(ready?.type.startsWith('image/') && node.dataset.chatRendered === key){
        showPhoto(ready);
        return;
      }
      void displayAsset(node,false).then(()=>{
        const loaded = cache.get(key);
        if(type === 'photo' && loaded?.type.startsWith('image/'))showPhoto(loaded);
      });
      return;
    }
    const link = event.target.closest('a.staff-chat-original, a[data-chat-telegram]');
    if(link && tg?.openTelegramLink){
      event.preventDefault();tg.openTelegramLink(link.href);
    }
  });
  document.addEventListener('scroll',event=>{
    if(event.target?.id === 'staff-chat-feed' && newCount>0 && isFeedAtBottom()){
      newCount=0;unreadIds.clear();updateUnread();
    }
  },true);
  document.addEventListener('visibilitychange',()=>{
    if(tab!=='staffchat')return;
    if(document.hidden){stopRealtime();return;}
    void load();
    connectLive();
  });
  window.addEventListener('online',()=>{
    if(tab==='staffchat'&&!document.hidden){
      if(retryTimer!==null){clearTimeout(retryTimer);retryTimer=null;}
      connectLive();
    }
  });
  window.addEventListener('pagehide',()=>{
    clearAssets();stopRealtime();
  });
  window.addEventListener('pageshow',()=>{
    if(tab==='staffchat'&&!document.hidden){void load();connectLive();}
  });
  return {screen,mount};
})();
