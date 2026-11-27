'use strict';
// Staff Telegram community mirror: WebSocket updates and explicitly bot-attributed sends.
window.NoraStaffChat = (() => {

  let timer = null, loading = false, signature = '', contextId = null, visit = 0, observer = null;
  let liveSocket = null, liveReady = false, liveAttempt = 0, liveFailures = 0;
  let retryTimer = null, handshakeTimer = null, heartbeatTimer = null;
  let refreshTimer = null, refreshPending = false, typingTimeout = null;
  let newCount = 0, lastTypingSent = 0;
  const unreadIds = new Set();
  const reactionSet = ['❤️','😂','🔥','👍','🥲','👀','🍪','🎧','🤝','💀'];
  const reactionBusy = new Set();
  let moderationContext=null, moderationBusy=false;
  let adminAccess=null,adminTarget=null,adminView='home',adminMetric='',adminNewValue=0;
  let adminBusy=false,adminNotice='',adminSelectedId='',adminSourceMessageId=null;
  let confirmationEnabled=true;
  try{confirmationEnabled=localStorage.getItem('nora-staff-chat-confirm')!=='off';}catch{}
  let gesture = null, gestureTimer = null;

  const cache = new Map();
  let draft = '', replyTarget = null, attachments = [], attachmentKind = 'file';
  let sending = false, emojiOpen = false, uploadProgress = 0, uploadXHR = null;
  const delivery = window.NoraStaffDelivery.create({
    getAuth:()=>auth,
    onConfirmed:(restored)=>{
      if(!restored){
        draft='';replyTarget=null;emojiOpen=false;contextId=null;signature='';
        clearUploads();hideSendConfirmation();prepareComposer();void load(true);
      }
      composeUpdate();
    }
  });
  let recorder = null, microphone = null, recordTimer = null, recordStarted = 0;
  let recording = false;
  const previewUrls = new Map();
  const maxUpload = 12 * 1024 * 1024;
  const maxAlbumUpload = 30 * 1024 * 1024;
  const maxAlbumItems = 6;
  const quickEmoji = ['😂','❤️','🔥','👍','🥲','👀','🍪','🎧','🤝','💀'];
  const mediaLabels = {
    photo: NoraI18n.t("Фото"), video: NoraI18n.t("Видео"), animation: 'GIF',
    voice: NoraI18n.t("Голосовое"), video_note: NoraI18n.t("Кружочек"),
    audio: NoraI18n.t("Аудио"), document: NoraI18n.t("Документ"),
    sticker: NoraI18n.t("Стикер"), poll: NoraI18n.t("Опрос"),
    location: NoraI18n.t("Геопозиция"), contact: NoraI18n.t("Контакт")
  };
  const time = value => {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? '' :
      d.toLocaleTimeString(NoraI18n.locale, {hour:'2-digit',minute:'2-digit'});
  };
  const mediaTile = m => {
    if(!m.media_type)return '';
    const id = Number(m.id);
    const type = esc(m.media_type);
    const playable = ['photo','sticker','video','animation','voice','video_note','audio'].includes(m.media_type);
    if(!playable || !m.has_media)
      return `<div class="staff-chat-media"><span>📎 ${esc(mediaLabels[m.media_type] || NoraI18n.t("Вложение"))}</span></div>`;
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
        if(!Number.isInteger(block.asset))return ("<div class=\"staff-rich-placeholder\">" + NoraI18n.html("Обложка в Telegram") + "</div>");
        return `<div class="staff-rich-cover" data-rich-cover="${id}" data-rich-part="${block.asset}">
          <span>${NoraI18n.html("Загружаем обложку…")}</span></div>`;
      }
      if(type==='audio'){
        const title=esc(block.title||NoraI18n.t("Аудиотрек"));
        const performer=esc(block.performer||'');
        const duration=Number(block.duration)>0?`${Math.floor(Number(block.duration)/60)}:${String(Number(block.duration)%60).padStart(2,'0')}`:'';
        const playable=Number.isInteger(block.asset);
        return `<div class="staff-rich-track">
          <button type="button" class="staff-rich-track-start" data-rich-play="${id}" data-rich-part="${playable?block.asset:'-1'}" ${playable?'':'disabled'} aria-label="${NoraI18n.html("Воспроизвести")} ${title}">▶</button>
          <div class="staff-rich-track-copy"><strong>${title}</strong>${performer?`<span>${performer}</span>`:''}</div>
          ${duration?`<time>${duration}</time>`:''}
          <div class="staff-rich-track-player" hidden></div>
        </div>`;
      }
      if(type==='buttons'){
        return `<div class="staff-rich-buttons">${(block.buttons||[]).slice(0,12).map(btn=>{
          const label=esc(btn.text||NoraI18n.t("Открыть"));
          const url=typeof btn.url==='string' && /^https?:\/\//i.test(btn.url)?esc(btn.url):'';
          return url?`<a href="${url}" data-chat-telegram target="_blank" rel="noopener noreferrer">${label}</a>`:`<span>${label} ${NoraI18n.html("· в Telegram")}</span>`;
        }).join('')}</div>`;
      }
      if(['video','animation','voice_note','document'].includes(type))
        return `<div class="staff-rich-placeholder">📎 ${esc(mediaLabels[type]||NoraI18n.t("Медиа"))} · ${m.link?("<span>" + NoraI18n.html("Открыть в Telegram ↗") + "</span>"):''}</div>`;
      return '';
    }).join('');
    return `<section class="staff-rich-card" aria-label="${nAudio?NoraI18n.t("Музыкальная подборка"):NoraI18n.t("Rich-сообщение")}">
      ${parts}
    </section>`;
  };

  const msgSignature = m => [m.edited_at || '', m.reply_text || '', m.reply_name || '', m.text || '', m.media_type || '', m.has_thumbnail ? '1' : '0', JSON.stringify(m.rich||[]), JSON.stringify(m.reactions||[]),
    JSON.stringify((m.album||[]).map(photo=>[photo.id,photo.media_type,photo.has_thumbnail]))].join('|');
  function groupAlbums(items){
    const result=[], seen=new Set();
    for(const m of items){
      const key=String(m.media_group_id||'');
      if(key && ['photo','video'].includes(m.media_type)){
        if(seen.has(key))continue;
        const group=items.filter(other=>other.media_group_id===key && ['photo','video'].includes(other.media_type));
        seen.add(key);
        if(group.length>1){result.push({...m,album:group});continue;}
      }
      result.push(m);
    }
    return result;
  }
  const reactionMarkup = (reactions,id) => (Array.isArray(reactions) ? reactions : [])
    .filter(item=>reactionSet.includes(item.emoji) && Number(item.count)>0)
    .map(item=>`<button type="button" class="staff-chat-react-chip${item.mine?' is-mine':''}"
       data-chat-react="${id}" data-chat-emoji-value="${esc(item.emoji)}"
       aria-pressed="${item.mine?'true':'false'}" aria-label="${esc(item.emoji)}: ${Number(item.count)} ${NoraI18n.html("реакций")}">${esc(item.emoji)} <span>${Math.max(0,Number(item.count)||0)}</span></button>`)
    .join('');
  const reactionPicker = id => `<div class="staff-chat-reaction-picker" data-chat-picker hidden role="group" aria-label="${NoraI18n.html("Реакции Норы")}">
    ${reactionSet.map(emoji=>`<button type="button" data-chat-react="${id}" data-chat-emoji-value="${esc(emoji)}" title="${NoraI18n.html("Реакция")} ${esc(emoji)}">${esc(emoji)}</button>`).join('')}
  </div>`;

  const line = m => {
    const id = Number(m.id);
    const sent = new Date(m.sent_at);
    const day = Number.isNaN(sent.getTime()) ? '' :
      [sent.getFullYear(),String(sent.getMonth()+1).padStart(2,'0'),String(sent.getDate()).padStart(2,'0')].join('-');
    const dayLabel = Number.isNaN(sent.getTime()) ? '' :
      sent.toLocaleDateString(NoraI18n.locale,{day:'numeric',month:'long',year:'numeric'});
    const name = esc(m.name || NoraI18n.t("Участник"));
    const initial = esc((m.name || '?').match(/[\p{L}\p{N}]/u)?.[0]?.toUpperCase() || '?');
    const who = Number(m.user_id) > 0
      ? `<button class="staff-chat-author" data-person-view="${m.user_id}" type="button">${name}</button>`
      : `<span class="staff-chat-author">${name}</span>`;
    const avatar = `<span class="staff-chat-avatar" ${Number(m.user_id) > 0 ? `data-person-avatar="${m.user_id}" ${!m.has_avatar?'data-avatar-unavailable':''}` : ''}>${initial}</span>`;
    const quote = m.reply_to_id ? `<button class="staff-chat-reply" type="button" data-chat-reply="${Number(m.reply_to_id)}" data-chat-link="${esc(m.reply_link||'')}">
        <b>${esc(m.reply_name || NoraI18n.t("Сообщение"))}</b><span>${esc((m.reply_text || mediaLabels[m.reply_media_type] || NoraI18n.t("Сообщение")).slice(0,90))}</span>
      </button>` : '';
    const body = m.text ? `<div class="staff-chat-text">${esc(m.text)}</div>` : '';
    const media = m.album?.length>1
      ? `<div class="staff-chat-album-grid" aria-label="${NoraI18n.html("Альбом из")} ${m.album.length} ${NoraI18n.html("файлов")}">${m.album.map(mediaTile).join('')}</div>`
      : mediaTile(m);
    const link = m.link ? `<a class="staff-chat-original" href="${esc(m.link)}" target="_blank" rel="noopener noreferrer" aria-label="${NoraI18n.html("Открыть в Telegram")}">↗</a>` : '';
    const replyButton = `<button class="staff-chat-answer" type="button" data-chat-answer="${id}" data-chat-name="${name}" data-chat-preview="${esc((m.text || (m.media_type ? mediaLabels[m.media_type] : '') || NoraI18n.t("Rich-сообщение")).slice(0,140))}" aria-label="${NoraI18n.html("Ответить на сообщение")}">↩</button>`;
    const hideButton = `<button class="staff-chat-hide" type="button" data-chat-hide="${id}" aria-label="${NoraI18n.html("Скрыть сообщение из зеркала")}" title="${NoraI18n.html("Скрыть из зеркала")}">×</button>`;
    const more = `<button type="button" class="staff-chat-more" data-chat-more="${id}" aria-label="${NoraI18n.html("Действия с сообщением")}" aria-expanded="false" title="${NoraI18n.html("Действия")}">•••</button>`;
    const actions = `<div class="staff-chat-actions" data-chat-menu hidden>
      <button type="button" class="staff-chat-react-open" data-chat-react-open="${id}" aria-label="${NoraI18n.html("Поставить реакцию")}" title="${NoraI18n.html("Реакция")}">☺</button>
      ${replyButton}
      <button type="button" class="staff-chat-copy" data-chat-copy="${id}" aria-label="${NoraI18n.html("Копировать текст")}" title="${NoraI18n.html("Копировать")}">⧉</button>
      <button type="button" class="staff-chat-mod-trigger" data-chat-mod-message="${id}" title="${NoraI18n.html("Модерация")}" aria-label="${NoraI18n.html("Модерация сообщения")}">🛡</button>
      <button type="button" class="staff-chat-admin-message-trigger" data-chat-admin-message="${id}" title="${NoraI18n.html("Админка сообщения")}" aria-label="${NoraI18n.html("Админка сообщения")}">⚙</button>
      ${link}${hideButton}</div>`;
    return `<article class="staff-chat-message" data-message-id="${id}" data-chat-user-id="${Number(m.user_id)||0}" data-chat-day="${day}" data-chat-date="${esc(dayLabel)}">
       ${avatar}<div class="staff-chat-bubble">
         <div class="staff-chat-meta">${who}<time datetime="${esc(m.sent_at)}">${time(m.sent_at)}</time>${m.edited_at?("<span class=\"staff-chat-edited\">" + NoraI18n.html("изм.") + "</span>"):''}${more}</div>
         ${actions}
         ${quote}${media}${richRow(m)}${body}
         <div class="staff-chat-reactions" data-chat-reactions="${id}">${reactionMarkup(m.reactions,id)}</div>
         ${reactionPicker(id)}
       </div>
     </article>`;
  };
  function screen() {
    return `<section class="nora-staff-chat">
      <header class="staff-chat-header">
        <button class="staff-chat-back" type="button" data-tab="community" aria-label="${NoraI18n.html("Назад в Коммьюнити")}">
          <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m14 5-7 7 7 7"/></svg>
        </button>
        <span class="staff-chat-mark" aria-hidden="true"><span></span></span>
        <div class="staff-chat-heading">
          <h1>${NoraI18n.html("Чат Норы")}</h1>
          <span id="staff-chat-live-status" data-live-state="connecting"><i aria-hidden="true"></i><b>${NoraI18n.html("Подключаем…")}</b><small id="staff-chat-live-count"></small></span>
        </div>
        <span class="staff-chat-team-label">${NoraI18n.html("КОМАНДА")}</span>
      </header>
      <div id="staff-chat-feed" class="staff-chat-feed" aria-label="${NoraI18n.html("Сообщения чата")}" aria-live="off">
        <p class="staff-chat-empty">${NoraI18n.html("Подключаем чат…")}</p>
      </div>
      <div class="staff-chat-activity" aria-live="polite">
        <button type="button" id="staff-chat-new" class="staff-chat-new" data-chat-scroll-new hidden>${NoraI18n.html("Новые сообщения ↓")}</button>
        <div id="staff-chat-typing" class="staff-chat-typing" hidden></div>
        <button type="button" class="staff-chat-latest" data-chat-latest hidden>${NoraI18n.html("К последним ↓")}</button>
      </div>
      <form id="staff-chat-compose" class="staff-chat-compose" autocomplete="off">
        <div class="staff-chat-compose-reply" id="staff-chat-compose-reply" hidden></div>
        <div class="staff-chat-compose-file" id="staff-chat-compose-file" hidden></div>
        <div id="staff-chat-delivery" class="staff-chat-delivery" role="status" hidden></div>
        <div id="staff-chat-send-confirm" class="staff-chat-send-confirm" hidden></div>
        <div class="staff-chat-record-status" id="staff-chat-record-status" hidden aria-live="polite"></div>
        <div class="staff-chat-compose-row">
          <button type="button" class="staff-chat-add-file" data-chat-attach aria-label="${NoraI18n.html("Прикрепить файл")}" title="${NoraI18n.html("Прикрепить файл")}">＋</button>
          <input id="staff-chat-file" type="file" multiple accept=".jpg,.jpeg,.png,.webp,.heic,.heif,.gif,.mp4,.mov,.webm,.mp3,.m4a,.ogg,.oga,.opus,.aac,.wav,.pdf,.txt" hidden>
          <textarea id="staff-chat-draft" rows="1" maxlength="3000" placeholder="${NoraI18n.html("Сообщение в чат…")}" aria-label="${NoraI18n.html("Сообщение в Telegram-чат")}"></textarea>
          <button type="button" class="staff-chat-record-toggle" data-chat-record aria-label="${NoraI18n.html("Записать голосовое")}" title="${NoraI18n.html("Голосовое")}">🎙</button>
          <button type="button" class="staff-chat-emoji-toggle" data-chat-emoji-toggle aria-label="${NoraI18n.html("Эмодзи")}" title="${NoraI18n.html("Эмодзи")}">☺</button>
          <button type="submit" id="staff-chat-submit" class="staff-chat-submit" aria-label="${NoraI18n.html("Отправить в чат")}" disabled>➤</button>
        </div>
        <div class="staff-chat-emoji-palette" id="staff-chat-emoji-palette" hidden>
          ${quickEmoji.map(emoji=>`<button type="button" data-chat-emoji="${esc(emoji)}" aria-label="${NoraI18n.html("Добавить")} ${esc(emoji)}">${emoji}</button>`).join('')}
        </div>
        <p class="staff-chat-compose-hint"><span aria-hidden="true">●</span> ${NoraI18n.html("От имени бота Норы с подписью автора · 12 МБ на файл, альбом до 30 МБ")}</p>
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
          throw new Error(NoraI18n.server(payload.error) || NoraI18n.t("Файл недоступен"));
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
      img.alt = mediaLabels[type] || NoraI18n.t("Вложение");
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
      audio.preload = 'metadata'; audio.src = asset.url;
      if(type==='voice'){
        const wrapper=document.createElement('div');
        wrapper.className='staff-chat-voice-player';
        wrapper.innerHTML=("<button class=\"staff-chat-voice-play\" type=\"button\" data-chat-voice-play aria-label=\"" + NoraI18n.html("Воспроизвести голосовое") + "\">▶</button>")+
          '<div class="staff-chat-voice-body"><div class="staff-chat-voice-wave" aria-hidden="true">'+
          Array.from({length:24},(_,i)=>'<span style="height:'+
            (8+Math.abs(Math.sin(i*1.73)*Math.cos(i*.52))*17)+'px"></span>').join('')+
          ("</div><input class=\"staff-chat-voice-progress\" type=\"range\" min=\"0\" max=\"100\" value=\"0\" step=\".1\" aria-label=\"" + NoraI18n.html("Позиция голосового") + "\">")+
          '<time class="staff-chat-voice-time">0:00</time></div>'+
          ("<button type=\"button\" class=\"staff-chat-voice-speed\" data-chat-voice-speed aria-label=\"" + NoraI18n.html("Скорость воспроизведения") + "\">1×</button>");
        wrapper.append(audio);
        const format=seconds=>{
          if(!Number.isFinite(seconds)||seconds<0)return '0:00';
          return Math.floor(seconds/60)+':'+String(Math.floor(seconds%60)).padStart(2,'0');
        };
        const update=()=>{
          const progress=wrapper.querySelector('.staff-chat-voice-progress');
          const label=wrapper.querySelector('.staff-chat-voice-time');
          const play=wrapper.querySelector('.staff-chat-voice-play');
          const duration=Number.isFinite(audio.duration)?audio.duration:0;
          if(progress)progress.value=duration>0?String(audio.currentTime/duration*100):'0';
          if(label)label.textContent=format(audio.currentTime)+' / '+format(duration);
          if(play){play.textContent=audio.paused?'▶':'Ⅱ';play.setAttribute('aria-label',audio.paused?NoraI18n.t("Воспроизвести"):NoraI18n.t("Приостановить"));}
        };
        for(const event of ['loadedmetadata','durationchange','timeupdate','play','pause','ended'])audio.addEventListener(event,update);
        stage.replaceChildren(wrapper);
        update();
      }else{
        audio.controls=true;
        stage.replaceChildren(audio);
      }
      stage.hidden=false;action.hidden=true;
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
      (url ? `<a class="staff-chat-telegram-link" href="${esc(url)}" data-chat-telegram target="_blank" rel="noopener noreferrer">${NoraI18n.html("Открыть в Telegram")}</a>` : '');
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
      assetError(node, error.message || NoraI18n.t("Файл недоступен"));
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
      if(!result?.type.startsWith('image/'))throw Error(NoraI18n.t("Обложка недоступна"));
      const image=new Image();
      image.src=result.url;image.alt=NoraI18n.t("Обложка подборки");image.decoding='async';
      node.replaceChildren(image);
    }catch {
      if(node.isConnected)node.textContent=NoraI18n.t("Обложка доступна в Telegram");
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
      if(!result.type.startsWith('audio/'))throw Error(NoraI18n.t("Аудио недоступно"));
      const player=document.createElement('audio');
      player.controls=true;player.preload='metadata';player.src=result.url;
      player.setAttribute('aria-label',NoraI18n.t("Аудиотрек Норы"));
      holder.replaceChildren(player);holder.hidden=false;
      button.textContent='♫';
      void player.play().catch(()=>{});
    }catch(error){
      button.textContent='▶';
      const link=button.closest('.staff-chat-message')?.querySelector('.staff-chat-original');
      holder.innerHTML=`<p class="staff-rich-error">${esc(error.message||NoraI18n.t("Не удалось открыть аудио"))}</p>`+
        (link ? `<a data-chat-telegram href="${esc(link.href)}" target="_blank" rel="noopener noreferrer">${NoraI18n.html("Открыть в Telegram ↗")}</a>`:'');
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
    items=groupAlbums(items);
    const existing = new Map([...feed.querySelectorAll('.staff-chat-message')]
      .map(el => [Number(el.dataset.messageId),el]));
    const firstExisting = existing.keys().next().value;
    if(force || !existing.size || (items.length && items[0].id < firstExisting)) {
      feed.innerHTML = items.length ? items.map(line).join('') :
        ("<p class=\"staff-chat-empty\">" + NoraI18n.html("Новых сообщений пока нет. Всё появится автоматически.") + "</p>");
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
        target.innerHTML = `<p class="staff-chat-empty">${esc(error.message || NoraI18n.t("Чат недоступен"))}</p><button type="button" class="staff-chat-retry" data-staff-chat-retry>${NoraI18n.html("Повторить")}</button>`;
      else if(contextId !== null)toast(error.message || NoraI18n.t("Сообщение недоступно"));
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
      else toast(error.message || NoraI18n.t("Сообщение не найдено"));
    }
  }
  function showPhoto(asset) {
    if(!asset || !asset.type.startsWith('image/'))return;
    sheet(`<div class="staff-chat-image-view"><img src="${esc(asset.url)}" alt="${NoraI18n.html("Фото из чата Норы")}"></div>`);
  }

  async function hideEntry(button) {
    if(!button || !button.isConnected)return;
    if(button.dataset.confirm !== '1') {
      button.dataset.confirm='1';
      button.textContent=NoraI18n.t("Скрыть?");
      button.classList.add('confirm');
      button.setAttribute('aria-label',NoraI18n.t("Подтвердить скрытие только из зеркала"));
      setTimeout(()=>{
        if(button.isConnected && button.dataset.confirm==='1') {
          button.dataset.confirm='';
          button.textContent='×';
          button.classList.remove('confirm');
          button.setAttribute('aria-label',NoraI18n.t("Скрыть сообщение из зеркала"));
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
        feed.innerHTML=("<p class=\"staff-chat-empty\">" + NoraI18n.html("В сохранённой истории больше нет сообщений.") + "</p>");
      }
      void load();
    } catch(error) {
      button.disabled=false;
      button.dataset.confirm='';
      button.textContent='×';
      button.classList.remove('confirm');
      toast(error.message||NoraI18n.t("Не удалось скрыть сообщение"));
    }
  }



  const isPhotoUpload = file => /\.(jpe?g|png)$/i.test(file.name);
  function uploadUrl(file) {
    if(!previewUrls.has(file))previewUrls.set(file,URL.createObjectURL(file));
    return previewUrls.get(file);
  }
  function forgetUpload(file) {
    const url=previewUrls.get(file);
    if(url)URL.revokeObjectURL(url);
    previewUrls.delete(file);
  }
  function clearUploads() {
    for(const file of attachments)forgetUpload(file);
    attachments=[];
    attachmentKind='file';
    const field=document.getElementById('staff-chat-file');
    if(field)field.value='';
  }
  function chooseFiles(files) {
    if(sending || recording)return;
    const chosen=[...files];
    if(!chosen.length)return;
    if(attachmentKind==='voice')clearUploads();
    const combined=[...attachments,...chosen];
    if(combined.length>maxAlbumItems) {
      toast(NoraI18n.t("В одном альбоме не больше 6 файлов"));return;
    }
    if(combined.some(file=>file.size>maxUpload || file.size<=0)){
      toast(NoraI18n.t("Размер каждого файла должен быть от 1 байта до 12 МБ"));return;
    }
    if(combined.reduce((size,file)=>size+file.size,0)>maxAlbumUpload){
      toast(NoraI18n.t("Общий размер альбома не больше 30 МБ"));return;
    }
    if(combined.length>1&&!combined.every(isPhotoUpload)){
      toast(NoraI18n.t("Несколько файлов можно отправить только альбомом JPG/PNG"));return;
    }
    attachments=combined;
    attachmentKind='file';
    emojiOpen=false;composeUpdate();
  }
  function recordStatus() {
    const status=document.getElementById('staff-chat-record-status');
    if(!status)return;
    status.hidden=!recording;
    if(!recording){status.replaceChildren();return;}
    const seconds=Math.min(120,Math.floor((Date.now()-recordStarted)/1000));
    status.innerHTML='<span class="staff-chat-record-dot" aria-hidden="true"></span>'+
      ("<span>" + NoraI18n.html("Запись голосового ·") + " ")+Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0')+'</span>'+
      ("<button type=\"button\" data-chat-record-cancel aria-label=\"" + NoraI18n.html("Отменить запись") + "\">" + NoraI18n.html("Отменить") + "</button>")+
      ("<button type=\"button\" data-chat-record-stop>" + NoraI18n.html("Готово") + "</button>");
  }
  function stopRecording(discard=false) {
    if(!recorder)return;
    if(recordTimer!==null){clearInterval(recordTimer);recordTimer=null;}
    const active=recorder;
    if(discard)active._noraDiscard=true;
    recording=false;
    recordStatus();
    composeUpdate();
    if(active.state!=='inactive')active.stop();
    else{microphone?.getTracks().forEach(track=>track.stop());microphone=null;recorder=null;}
  }
  async function toggleRecording() {
    if(sending)return;
    if(recording){stopRecording();return;}
    if(recorder)return; // Wait for the previous onstop before starting again.
    if(!navigator.mediaDevices?.getUserMedia||typeof MediaRecorder==='undefined'){
      toast(NoraI18n.t("Запись голоса недоступна в этом Telegram WebView"));return;
    }
    let stream;
    try{
      stream=await navigator.mediaDevices.getUserMedia({
        audio:{echoCancellation:true,noiseSuppression:true,channelCount:1}
      });
      if(tab!=='staffchat'){stream.getTracks().forEach(track=>track.stop());return;}
      const choices=['audio/mp4','audio/ogg;codecs=opus','audio/webm;codecs=opus','audio/webm'];
      const mime=choices.find(type=>MediaRecorder.isTypeSupported(type));
      const options=mime?{mimeType:mime,audioBitsPerSecond:64000}:{audioBitsPerSecond:64000};
      const active=new MediaRecorder(stream,options);
      const chunks=[];
      microphone=stream;recorder=active;
      active.ondataavailable=event=>{if(event.data?.size)chunks.push(event.data);};
      active.onerror=()=>{
        toast(NoraI18n.t("Не удалось записать голосовое"));
        stopRecording(true);
      };
      active.onstop=()=>{
        const discard=!!active._noraDiscard;
        stream.getTracks().forEach(track=>track.stop());
        if(recorder===active)recorder=null;
        if(microphone===stream)microphone=null;
        if(discard || tab!=='staffchat')return;
        const actual=active.mimeType||mime||'audio/webm';
        const extension=actual.includes('mp4')?'m4a':actual.includes('ogg')?'ogg':'webm';
        const clip=new File(chunks,'nora-voice.'+extension,{type:actual});
        if(clip.size>maxUpload||!clip.size){
          toast(NoraI18n.t("Голосовое пустое или превышает 12 МБ"));return;
        }
        clearUploads();
        attachments=[clip];attachmentKind='voice';
        composeUpdate();
      };
      active.start(400);
      recording=true;recordStarted=Date.now();
      recordStatus();
      recordTimer=setInterval(()=>{
        recordStatus();
        if(Date.now()-recordStarted>=120000)stopRecording();
      },250);
      composeUpdate();
      tg?.HapticFeedback?.impactOccurred?.('medium');
    }catch(error){
      stream?.getTracks().forEach(track=>track.stop());
      recording=false;recorder=null;microphone=null;
      toast(error?.name==='NotAllowedError'?NoraI18n.t("Разреши доступ к микрофону в Telegram"):
        NoraI18n.t("Не удалось включить микрофон"));
      recordStatus();composeUpdate();
    }
  }
  function composeUpdate() {
    const field=document.getElementById('staff-chat-draft');
    const form=document.getElementById('staff-chat-compose');
    if(!field||!form)return;
    field.maxLength=attachments.length?800:3000;
    const send=document.getElementById('staff-chat-submit');
    if(send){
      send.disabled=sending||recording||delivery.pending||(!draft.trim()&&!attachments.length)||
        draft.length>(attachments.length?800:3000);
      send.textContent=sending?(uploadProgress?uploadProgress+'%':'…'):'➤';
    }
    const microphoneButton=form.querySelector('[data-chat-record]');
    if(microphoneButton){
      microphoneButton.disabled=sending||delivery.pending;
      microphoneButton.classList.toggle('is-recording',recording);
      microphoneButton.textContent=recording?'■':'🎙';
      microphoneButton.setAttribute('aria-label',recording?NoraI18n.t("Завершить запись"):NoraI18n.t("Записать голосовое"));
    }
    field.disabled=sending||delivery.pending;
    const attachButton=form.querySelector('[data-chat-attach]');
    if(attachButton)attachButton.disabled=sending||delivery.pending;
    const emojiButton=form.querySelector('[data-chat-emoji-toggle]');
    if(emojiButton)emojiButton.disabled=sending||delivery.pending;
    delivery.render();
    const back=document.getElementById('staff-chat-compose-reply');
    if(back){
      back.hidden=!replyTarget;
      back.innerHTML=replyTarget
        ? '<span><b>↩ '+esc(replyTarget.name)+'</b><small>'+esc(replyTarget.preview)+
          ("</small></span><button type=\"button\" data-chat-cancel-reply aria-label=\"" + NoraI18n.html("Отменить ответ") + "\">×</button>")
        : '';
    }
    const chosen=document.getElementById('staff-chat-compose-file');
    if(chosen){
      chosen.hidden=!attachments.length;
      if(attachments.length){
        const cards=attachments.map((file,index)=>{
          const label=esc(file.name),src=esc(uploadUrl(file));
          const media=attachmentKind==='voice'
            ? '<audio controls preload="metadata" src="'+src+(NoraI18n.html("\" aria-label=\"Прослушать голосовое\">") + "</audio>")
            : file.type.startsWith('image/') || isPhotoUpload(file)
              ? '<img src="'+src+'" alt="'+label+'" loading="lazy">'
              : file.type.startsWith('video/') && file.size<=maxUpload
                ? '<video src="'+src+'" muted playsinline preload="metadata"></video>'
                : '<span class="staff-chat-preview-symbol">📎</span>';
          return '<div class="staff-chat-preview-item">'+media+
            '<span title="'+label+'">'+(attachmentKind==='voice'?NoraI18n.t("Голосовое"):label)+'</span>'+
            '<button type="button" data-chat-remove-file="'+index+'" '+(sending?'disabled':'')+
            NoraI18n.t(" aria-label=\"Убрать ")+label+'">×</button></div>';
        }).join('');
        const size=(attachments.reduce((total,file)=>total+file.size,0)/1048576).toFixed(1);
        chosen.innerHTML='<div class="staff-chat-preview-header"><span>'+
          (attachmentKind==='voice'?NoraI18n.t("🎤 Голосовое"):
            attachments.length>1?NoraI18n.t("▧ Альбом · ")+attachments.length+NoraI18n.t(" фото"):NoraI18n.t("Вложение"))+
          ' · '+size+(" " + NoraI18n.html("МБ") + "</span>")+(sending?'<b>'+(uploadProgress?uploadProgress+'%':NoraI18n.t("Отправка…"))+'</b>':'')+
          '</div><div class="staff-chat-preview-grid">'+cards+'</div>';
      }else chosen.replaceChildren();
    }
    const emoji=document.getElementById('staff-chat-emoji-palette');
    if(emoji)emoji.hidden=!emojiOpen;
    field.style.height='auto';
    field.style.height=Math.min(field.scrollHeight,106)+'px';
  }
  function prepareComposer() {
    const field=document.getElementById('staff-chat-draft');
    if(!field)return;
    field.value=draft;
    composeUpdate();recordStatus();
  }
  function uploadForm(form){
    return new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();
      uploadXHR=xhr;
      xhr.open('POST','/api/community/chat/upload',true);
      xhr.timeout=120000;
      xhr.setRequestHeader('Authorization','tma '+auth);
      xhr.upload.onprogress=event=>{
        if(!event.lengthComputable)return;
        uploadProgress=Math.min(99,Math.round(100*event.loaded/event.total));
        composeUpdate();
      };
      xhr.onload=()=>{
        if(uploadXHR===xhr)uploadXHR=null;
        let response;
        try{response=JSON.parse(xhr.responseText)}catch{
          reject(new Error(NoraI18n.t("Нет ответа от сервера Норы")));return;
        }
        if(xhr.status<200||xhr.status>=300){
          reject(new Error(response.error||NoraI18n.t("Не удалось отправить вложение")));return;
        }
        resolve(response);
      };
      xhr.onerror=()=>{
        if(uploadXHR===xhr)uploadXHR=null;
        reject(new Error(NoraI18n.t("Нет связи с сервером. Перед повтором проверь чат")));
      };
      xhr.onabort=()=>{
        if(uploadXHR===xhr)uploadXHR=null;
        reject(new Error(NoraI18n.t("Отправка прервана. Проверь чат перед повтором")));
      };
      xhr.ontimeout=()=>{
        if(uploadXHR===xhr)uploadXHR=null;
        reject(new Error(NoraI18n.t("Превышено время отправки. Проверяем результат.")));
      };
      xhr.send(form);
    });
  }

  function hideSendConfirmation(){
    const node=document.getElementById('staff-chat-send-confirm');
    if(node){node.hidden=true;node.replaceChildren();}
  }
  function showSendConfirmation(text){
    const node=document.getElementById('staff-chat-send-confirm');
    if(!node)return;
    node.innerHTML=("<b>" + NoraI18n.html("Отправить сообщение?") + "</b>")+
      ("<small>" + NoraI18n.html("От имени бота, с именем автора и без кнопок"))+
      (attachments.length?NoraI18n.t(" · вложений: ")+attachments.length:'')+'</small>'+
      (text?'<p>'+esc(text.slice(0,240))+'</p>':'')+
      ("<div class=\"staff-chat-send-controls\"><button type=\"button\" data-chat-send-back>" + NoraI18n.html("Назад") + "</button>")+
      ("<button type=\"button\" data-chat-send-confirm>" + NoraI18n.html("Отправить") + "</button></div>");
    node.hidden=false;
  }
  async function sendCompose(skipConfirm=false) {
    if(sending||delivery.pending||recording||(!draft.trim()&&!attachments.length))return;
    const text=draft.trim(),reply_to=replyTarget?.id||null;
    if(text.length>(attachments.length?800:3000)){
      toast(NoraI18n.t("Слишком длинный текст для сообщения с вложением"));return;
    }
    if(confirmationEnabled&&!skipConfirm){showSendConfirmation(text);return;}
    hideSendConfirmation();
    const operationId=delivery.begin();
    if(!operationId)return;
    sending=true;uploadProgress=0;composeUpdate();
    try{
      let result;
      if(attachments.length){
        const size=attachments.reduce((sum,file)=>sum+file.size,0);
        if(attachments.some(file=>file.size>maxUpload)||size>maxAlbumUpload){
          throw new Error(NoraI18n.t("Один файл до 12 МБ, альбом до 30 МБ"));
        }
        const form=new FormData();
        for(const file of attachments)form.append('file',file,file.name);
        form.append('text',text);
        form.append('kind',attachmentKind);
        form.append('operation_id',operationId);
        if(reply_to)form.append('reply_to',String(reply_to));
        result=await uploadForm(form);
      }else result=await api('community/chat/send',{text,reply_to,operation_id:operationId});
      if(!delivery.acknowledge(result))await delivery.check();
    }catch(error){
      await delivery.check();
      if(delivery.pending)toast(NoraI18n.t("Статус отправки неизвестен. Проверь Telegram."));
      else if(error?.message)toast(error.message);
    }finally{
      sending=false;uploadProgress=0;composeUpdate();
    }
  }
  function selectReply(button) {
    const id=Number(button.dataset.chatAnswer);
    if(!Number.isSafeInteger(id) || id<=0)return;
    replyTarget={
      id,
      name:button.dataset.chatName || NoraI18n.t("Сообщение"),
      preview:button.dataset.chatPreview || NoraI18n.t("Ответ в Telegram")
    };
    hideSendConfirmation();
    composeUpdate();
    document.getElementById('staff-chat-draft')?.focus();
  }



  function closeChatPickers(except=null) {
    for(const node of document.querySelectorAll('#staff-chat-feed [data-chat-picker]:not([hidden])')){
      if(node!==except)node.hidden=true;
    }
  }
  function openReactionPicker(article) {
    if(!article || tab!=='staffchat')return;
    const picker=article.querySelector('[data-chat-picker]');
    if(!picker)return;
    const opened=!picker.hidden;
    closeChatPickers();
    for(const menu of document.querySelectorAll('#staff-chat-feed [data-chat-menu]:not([hidden])')){
      menu.hidden=true;
      menu.closest('.staff-chat-message')?.querySelector('[data-chat-more]')?.setAttribute('aria-expanded','false');
    }
    picker.hidden=opened;
    if(!opened){
      const reacted=[...article.querySelectorAll('.staff-chat-react-chip[aria-pressed="true"]')]
        .map(x=>x.dataset.chatEmojiValue);
      for(const button of picker.querySelectorAll('[data-chat-react]')){
        button.setAttribute('aria-pressed',String(reacted.includes(button.dataset.chatEmojiValue)));
      }
      if(typeof tg!=='undefined')tg?.HapticFeedback?.selectionChanged?.();
    }
  }
  function updateReactionChips(id,reactions) {
    const article=[...document.querySelectorAll('#staff-chat-feed .staff-chat-message')]
      .find(node=>Number(node.dataset.messageId)===id);
    if(!article)return;
    const container=article.querySelector('[data-chat-reactions]');
    if(container)container.innerHTML=reactionMarkup(reactions,id);
    for(const btn of article.querySelectorAll('[data-chat-picker] [data-chat-react]')){
      const selected=(reactions||[]).some(item=>item.emoji===btn.dataset.chatEmojiValue&&item.mine);
      btn.setAttribute('aria-pressed',String(selected));
    }
  }
  async function setChatReaction(button) {
    const id=Number(button.dataset.chatReact);
    const emoji=button.dataset.chatEmojiValue;
    if(!Number.isSafeInteger(id)||id<=0||!reactionSet.includes(emoji)||reactionBusy.has(id))return;
    const article=button.closest('.staff-chat-message');
    const own=article&&[...article.querySelectorAll('.staff-chat-react-chip[aria-pressed="true"]')]
      .some(x=>x.dataset.chatEmojiValue===emoji);
    reactionBusy.add(id);
    try{
      const result=await api('community/chat/reaction',{message_id:id,emoji,active:!own});
      if(!result?.ok)throw new Error(NoraI18n.t("Реакция не сохранилась"));
      updateReactionChips(id,result.reactions);
      const picker=article?.querySelector('[data-chat-picker]');
      if(picker)picker.hidden=true;
      tg?.HapticFeedback?.impactOccurred?.('light');
      queueRefresh();
    }catch(error){
      toast(error.message||NoraI18n.t("Не удалось изменить реакцию"));
    }finally{
      reactionBusy.delete(id);
    }
  }
  async function copyChatMessage(article) {
    if(!article)return;
    const text=article.querySelector('.staff-chat-text')?.textContent?.trim() ||
      [...article.querySelectorAll('.staff-rich-text,.staff-rich-heading')]
        .map(node=>node.textContent).join('\n').trim();
    if(!text){toast(NoraI18n.t("В сообщении нет текста для копирования"));return;}
    let copied=false;
    try{
      if(navigator.clipboard?.writeText){
        await navigator.clipboard.writeText(text);
        copied=true;
      }
    }catch{}
    if(!copied){
      const field=document.createElement('textarea');
      field.value=text;
      field.style.cssText='position:fixed;left:-9999px;top:0;opacity:0';
      document.body.append(field);field.select();
      try{copied=document.execCommand('copy')}catch{}
      field.remove();
    }
    toast(copied?NoraI18n.t("Текст скопирован"):NoraI18n.t("Не удалось скопировать текст"));
    if(copied)tg?.HapticFeedback?.notificationOccurred?.('success');
  }
  function cancelChatGesture() {
    if(gestureTimer!==null){clearTimeout(gestureTimer);gestureTimer=null;}
    gesture=null;
  }

  function connectionStatus(label,state='connecting',online=null) {
    const node=document.getElementById('staff-chat-live-status');
    if(!node)return;
    node.dataset.liveState=state;
    const title=node.querySelector('b'),count=node.querySelector('small');
    if(title)title.textContent=label;
    if(count && online!==null)count.textContent=online>0?` · ${online} ${NoraI18n.t("в Mini App")}`:'';
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
    if(newCount>0)button.textContent=`${newCount} ${NoraI18n.t("новых сообщений ↓")}`;
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
    node.textContent=name+NoraI18n.t(" печатает из Mini App…");
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
      connectionStatus(NoraI18n.t("Режим обновления"),'fallback');
      startFallback();return;
    }
    const generation=++liveAttempt;
    let socket;
    try{
      const protocol=location.protocol==='https:'?'wss:':'ws:';
      socket=new WebSocket(protocol+'//'+location.host+'/ws/community/chat');
    }catch{
      connectionStatus(NoraI18n.t("Режим обновления"),'fallback');
      startFallback();return;
    }
    liveSocket=socket;
    liveReady=false;
    connectionStatus(liveFailures?NoraI18n.t("Переподключаем…"):NoraI18n.t("Подключаем…"));
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
        connectionStatus(NoraI18n.t("В реальном времени"),'live',Number(payload.online)||0);
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
        connectionStatus(NoraI18n.t("В реальном времени"),'live',Number(payload.online)||0);
      }else if(payload.type==='typing'&&typeof payload.name==='string'){
        showTyping(payload.name.slice(0,48));
      }else if(payload.type==='error'&&payload.reason==='access'){
        connectionStatus(NoraI18n.t("Нет доступа"),'offline');
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
        connectionStatus(NoraI18n.t("Нет доступа"),'offline');return;
      }
      if(document.hidden)return;
      liveFailures=Math.min(liveFailures+1,5);
      connectionStatus(NoraI18n.t("Переподключаем…"),'fallback');
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


  // All authorization and permission/rank checks occur again in the server endpoints.
  const adminStats=[
    {key:'cookies',title:NoraI18n.t("🍪 Печеньки"),minimum:0,maximum:1000000,permission:'can_cookies'},
    {key:'reputation',title:NoraI18n.t("⭐ Репутация"),minimum:-20,maximum:100,permission:'can_profile'},
    {key:'likes',title:NoraI18n.t("💜 Лайки"),minimum:0,maximum:1000000,permission:'can_likes'}
  ];
  function activeAdminStat(){return adminStats.find(item=>item.key===adminMetric);}
  function closeChatAdmin(){
    document.querySelector('#staff-chat-feed [data-chat-admin-panel]')?.remove();
    adminSourceMessageId=null;
  }
  function recentChatAuthors(){
    const seen=new Set(),out=[];
    for(const item of [...document.querySelectorAll('#staff-chat-feed [data-chat-user-id]')].reverse()){
      const id=Number(item.dataset.chatUserId);
      if(!Number.isSafeInteger(id)||id<=0||seen.has(id))continue;
      seen.add(id);
      out.push({id,name:(item.querySelector('.staff-chat-author')?.textContent||String(id)).slice(0,50)});
      if(out.length>=30)break;
    }
    return out;
  }
  function renderChatAdmin(){
    const node=document.querySelector('#staff-chat-feed [data-chat-admin-panel]');
    if(!node||!node.isConnected||!adminAccess)return;
    const header=("<header class=\"staff-chat-admin-heading\"><b>" + NoraI18n.html("⚙ Управление сообщением") + "</b>")+
      ("<button type=\"button\" data-chat-admin-close aria-label=\"" + NoraI18n.html("Закрыть окно") + "\">×</button></header>");
    let view='';
    if(adminView==='home'){
      view=("<label class=\"staff-chat-admin-switch\"><span><b>" + NoraI18n.html("Подтверждать отправку") + "</b>")+
        ("<small>" + NoraI18n.html("Выключи, чтобы отправлять сразу") + "</small></span>")+
        '<input type="checkbox" role="switch" data-chat-confirm-toggle '+
        (confirmationEnabled?'checked':'')+'></label>';
      if(adminAccess.can_cookies||adminAccess.can_profile){
        view+='<form id="staff-chat-admin-search" class="staff-chat-admin-form">'+
          ("<label for=\"staff-chat-admin-user\">" + NoraI18n.html("Управление участником") + "</label>")+
          ("<select id=\"staff-chat-admin-user\"><option value=\"\">" + NoraI18n.html("Выбери из чата…") + "</option>")+
          recentChatAuthors().map(person=>'<option value="'+person.id+'">'+
            esc(person.name)+' · '+person.id+'</option>').join('')+'</select>'+
          '<div class="staff-chat-admin-row"><input id="staff-chat-admin-id" type="text" '+
          NoraI18n.t("inputmode=\"numeric\" maxlength=\"12\" pattern=\"[0-9]{1,12}\" placeholder=\"Или Telegram ID\" value=\"")+
          esc(adminSelectedId)+("\" required><button type=\"submit\">" + NoraI18n.html("Найти") + "</button></div></form>");
      }else view+=("<p class=\"staff-chat-admin-muted\">" + NoraI18n.html("Для изменения показателей нужны права администратора.") + "</p>");
      view+=("<button type=\"button\" class=\"staff-chat-admin-subtle\" data-chat-mod-log>" + NoraI18n.html("☷ Журнал модерации") + "</button>");
    }else if(adminView==='person'&&adminTarget){
      view=("<button class=\"staff-chat-admin-back\" type=\"button\" data-chat-admin-back>" + NoraI18n.html("‹ К выбору участника") + "</button>")+
        '<div class="staff-chat-admin-person"><b>'+esc(adminTarget.name)+'</b>'+
        '<small>Telegram ID '+adminTarget.id+'</small></div>'+
        '<div class="staff-chat-admin-stats">'+adminStats.map(stat=>
          '<button type="button" data-chat-admin-stat="'+stat.key+'" '+
          (adminAccess[stat.permission]?'':'disabled')+'><span>'+stat.title+'</span>'+
          '<b>'+Number(adminTarget[stat.key]).toLocaleString(NoraI18n.locale)+'</b><span>›</span></button>'
        ).join('')+'</div>'+
        ("<label class=\"staff-chat-admin-switch\"><span><b>" + NoraI18n.html("Подтверждать отправку") + "</b><small>" + NoraI18n.html("Настройка чата") + "</small></span>")+
        '<input type="checkbox" role="switch" data-chat-confirm-toggle '+(confirmationEnabled?'checked':'')+'></label>'+
        ("<button type=\"button\" class=\"staff-chat-admin-subtle\" data-chat-mod-log>" + NoraI18n.html("☷ Журнал модерации") + "</button>");
    }else if(adminView==='edit'&&adminTarget){
      const stat=activeAdminStat();
      view=("<button class=\"staff-chat-admin-back\" type=\"button\" data-chat-admin-back>" + NoraI18n.html("‹ К показателям") + "</button>")+
        '<form id="staff-chat-admin-edit" class="staff-chat-admin-form">'+
        '<label for="staff-chat-admin-value">'+stat.title+' · '+esc(adminTarget.name)+'</label>'+
        '<input id="staff-chat-admin-value" type="number" step="1" min="'+stat.minimum+
        '" max="'+stat.maximum+'" value="'+Number(adminTarget[stat.key])+'" required>'+
        ("<small>" + NoraI18n.html("Сейчас:") + " ")+Number(adminTarget[stat.key]).toLocaleString(NoraI18n.locale)+'</small>'+
        ("<button type=\"submit\">" + NoraI18n.html("Продолжить") + "</button></form>");
    }else if(adminView==='confirm'&&adminTarget){
      const stat=activeAdminStat();
      view=("<button class=\"staff-chat-admin-back\" type=\"button\" data-chat-admin-back>" + NoraI18n.html("‹ Изменить число") + "</button>")+
        ("<p class=\"staff-chat-admin-summary\">" + NoraI18n.html("Подтверди изменение") + " ")+stat.title+
        (" " + NoraI18n.html("для") + " <b>")+esc(adminTarget.name)+'</b>: <b>'+
        Number(adminTarget[stat.key]).toLocaleString(NoraI18n.locale)+
        ' → '+Number(adminNewValue).toLocaleString(NoraI18n.locale)+'</b></p>'+
        '<button class="staff-chat-admin-primary" type="button" data-chat-admin-save '+
        (adminBusy?'disabled':'')+'>'+(adminBusy?NoraI18n.t("Сохраняем…"):NoraI18n.t("Подтвердить изменение"))+'</button>';
    }
    node.innerHTML=header+'<div class="staff-chat-admin-content">'+
      (adminNotice?'<p class="staff-chat-admin-notice">'+esc(adminNotice)+'</p>':'')+
      view+'</div>';
  }
  async function initChatAdmin(){
    try{
      const access=await api('community/chat/admin');
      if(tab==='staffchat')adminAccess=access;
    }catch{
      if(tab==='staffchat'){adminAccess=null;closeChatAdmin();}
    }
  }
  async function openChatAdminFromMessage(article){
    if(!article||tab!=='staffchat')return;
    const messageId=Number(article.dataset.messageId);
    if(!Number.isSafeInteger(messageId)||messageId<=0)return;
    if(adminSourceMessageId===messageId&&article.querySelector('[data-chat-admin-panel]')){
      closeChatAdmin();return;
    }
    closeChatAdmin();
    if(!adminAccess)await initChatAdmin();
    if(!adminAccess?.can_open||tab!=='staffchat'||!article.isConnected){
      toast(NoraI18n.t("Админка сообщений недоступна"));return;
    }
    const menu=article.querySelector('[data-chat-menu]');
    if(menu)menu.hidden=true;
    article.querySelector('[data-chat-more]')?.setAttribute('aria-expanded','false');
    const bubble=article.querySelector('.staff-chat-bubble');
    if(!bubble)return;
    adminSourceMessageId=messageId;
    adminTarget=null;
    adminView='home';adminNotice='';
    const node=document.createElement('section');
    node.className='staff-chat-admin-panel';
    node.dataset.chatAdminPanel=String(messageId);
    node.setAttribute('aria-label',NoraI18n.t("Управление сообщением №")+messageId);
    if(menu)menu.insertAdjacentElement('afterend',node);
    else bubble.prepend(node);
    const uid=Number(article.dataset.chatUserId);
    adminSelectedId=Number.isSafeInteger(uid)&&uid>0?String(uid):'';
    renderChatAdmin();
    if(adminSelectedId&&(adminAccess.can_cookies||adminAccess.can_profile)){
      await lookupChatAdminUser(adminSelectedId);
    }
  }
  async function lookupChatAdminUser(raw){
    const id=String(raw||'').trim();
    if(adminBusy)return;
    if(!/^[0-9]{1,12}$/.test(id)||Number(id)<=0){
      adminNotice=NoraI18n.t("Укажи корректный Telegram ID");renderChatAdmin();return;
    }
    const sourceId=adminSourceMessageId;
    adminSelectedId=id;adminBusy=true;adminNotice=NoraI18n.t("Загружаем профиль…");renderChatAdmin();
    try{
      const data=await api('community/chat/admin?target_id='+encodeURIComponent(id));
      if(tab!=='staffchat'||adminSourceMessageId!==sourceId)return;
      adminTarget=data.target;adminView='person';adminNotice='';
    }catch(error){if(adminSourceMessageId===sourceId){adminView='home';adminNotice=error.message||NoraI18n.t("Не удалось открыть профиль");}}
    finally{adminBusy=false;if(tab==='staffchat'&&adminSourceMessageId===sourceId)renderChatAdmin();}
  }
  function prepareChatAdminValue(){
    const stat=activeAdminStat(),field=document.getElementById('staff-chat-admin-value');
    if(!stat||!field||!adminTarget)return;
    const value=Number(field.value);
    if(!field.value.trim()||!Number.isSafeInteger(value)||value<stat.minimum||value>stat.maximum){
      adminNotice=NoraI18n.t("Допустимо целое число от ")+stat.minimum+NoraI18n.t(" до ")+stat.maximum;
      renderChatAdmin();return;
    }
    if(value===Number(adminTarget[stat.key])){
      adminNotice=NoraI18n.t("Значение уже установлено");renderChatAdmin();return;
    }
    adminNewValue=value;adminView='confirm';adminNotice='';renderChatAdmin();
  }
  async function saveChatAdminValue(){
    const stat=activeAdminStat();
    if(!stat||!adminAccess?.[stat.permission]||!adminTarget||adminBusy)return;
    adminBusy=true;adminNotice='';renderChatAdmin();
    try{
      const result=await api('community/chat/admin',{
        target_id:Number(adminTarget.id),metric:stat.key,value:adminNewValue,
        expected:Number(adminTarget[stat.key]),confirmed:true
      });
      if(tab!=='staffchat')return;
      adminTarget=result.target;adminView='person';adminNotice=NoraI18n.t("Показатель сохранён");
      tg?.HapticFeedback?.notificationOccurred?.('success');
    }catch(error){adminNotice=error.message||NoraI18n.t("Изменение не сохранено");}
    finally{adminBusy=false;if(tab==='staffchat')renderChatAdmin();}
  }

  function moderationTitle(name) {
    return ("<header class=\"nora-staff-mod-head\"><span>🛡</span><div><small>" + NoraI18n.html("МОДЕРАЦИЯ НОРЫ") + "</small><h3>")+esc(name)+'</h3></div></header>';
  }
  function moderationCloseButton() {
    return ("<button type=\"button\" class=\"nora-staff-mod-close\" data-chat-mod-close>" + NoraI18n.html("Закрыть") + "</button>");
  }
  function moderationError(message) {
    sheet('<section class="nora-staff-mod">'+moderationTitle(NoraI18n.t("Ошибка"))+
      '<p class="nora-staff-mod-warning">'+esc(message)+'</p>'+moderationCloseButton()+'</section>');
  }
  function moderationMenu(info) {
    moderationContext=info;
    const buttons=(info.actions||[]).map(action=>
      '<button type="button" data-chat-mod-action="'+esc(action.id)+'">'+
      esc(action.label)+' <span aria-hidden="true">›</span></button>').join('');
    sheet('<section class="nora-staff-mod">'+moderationTitle(info.target_name || NoraI18n.t("Сообщение"))+
      ("<div class=\"nora-staff-mod-meta\">" + NoraI18n.html("Сообщение №"))+Number(info.message_id)+
      (info.target_id?' · '+Number(info.warnings||0)+NoraI18n.t(" предупреждений"):NoraI18n.t(" · автор недоступен"))+'</div>'+
      (buttons?'<div class="nora-staff-mod-actions">'+buttons+'</div>':
        ("<p class=\"nora-staff-mod-warning\">" + NoraI18n.html("Нет прав для действий с этим участником или сообщение не содержит доступного автора.") + "</p>"))+
      ("<p class=\"nora-staff-mod-footnote\">" + NoraI18n.html("Права проверяются сервером перед каждым действием. Удаление из Telegram отличается от скрытия в Норе.") + "</p>")+
      moderationCloseButton()+'</section>');
  }
  async function openModeration(id) {
    if(!Number.isSafeInteger(id)||id<=0||tab!=='staffchat')return;
    sheet('<section class="nora-staff-mod">'+moderationTitle(NoraI18n.t("Проверка прав…"))+'</section>');
    try{
      const info=await api('community/chat/moderation?message_id='+id);
      if(tab==='staffchat')moderationMenu(info);
    }catch(error){moderationError(error.message||NoraI18n.t("Не удалось открыть модерацию"));}
  }
  function moderationConfirm(action) {
    const info=moderationContext;
    if(!info||(info.actions||[]).every(entry=>entry.id!==action))return;
    const label=info.actions.find(entry=>entry.id===action).label;
    const needsDuration=action==='ban'||action==='mute';
    const durations=needsDuration
      ? ("<label class=\"nora-staff-mod-label\">" + NoraI18n.html("Срок") + "<select id=\"staff-chat-mod-duration\">")+
        (action==='ban'
          ? ("<option value=\"1d\">" + NoraI18n.html("1 день") + "</option><option value=\"7d\" selected>" + NoraI18n.html("7 дней") + "</option><option value=\"forever\">" + NoraI18n.html("Навсегда") + "</option>")
          : ("<option value=\"10m\">" + NoraI18n.html("10 минут") + "</option><option value=\"1h\" selected>" + NoraI18n.html("1 час") + "</option><option value=\"12h\">" + NoraI18n.html("12 часов") + "</option><option value=\"1d\">" + NoraI18n.html("1 день") + "</option><option value=\"7d\">" + NoraI18n.html("7 дней") + "</option>"))+
        '</select></label>' : '';
    const risk=action==='ban'
      ? NoraI18n.t("Бан в основном чате сбрасывает профиль и прогресс по существующим правилам Норы. Действие потенциально необратимо.")
      : action==='kick'
        ? NoraI18n.t("Участник будет исключён из чата Telegram. Он сможет вступить повторно.")
        : action==='delete'
          ? NoraI18n.t("Сообщение будет удалено из Telegram и зеркала Норы для всех.")
          : action==='warn'
            ? NoraI18n.t("Предупреждение влияет на счётчик пользователя. На установленных порогах действует автоматическая лесенка наказаний.")
            : NoraI18n.t("Действие изменит реальное состояние участника в Telegram или Норе.");
    sheet('<section class="nora-staff-mod" data-chat-mod-confirm="'+esc(action)+'">'+
      moderationTitle(label)+("<p>" + NoraI18n.html("Участник:") + " <b>")+esc(info.target_name)+'</b></p>'+
      '<div class="nora-staff-mod-warning">'+esc(risk)+'</div>'+
      durations+
      ("<label class=\"nora-staff-mod-label\">" + NoraI18n.html("Причина") + "<textarea id=\"staff-chat-mod-reason\" rows=\"3\" maxlength=\"250\" placeholder=\"" + NoraI18n.html("Напиши причину, минимум 3 символа") + "\" required></textarea></label>")+
      '<div class="nora-staff-mod-confirm-row">'+
      ("<button type=\"button\" data-chat-mod-back>" + NoraI18n.html("Назад") + "</button>")+
      '<button type="button" class="nora-staff-mod-danger" data-chat-mod-execute="'+esc(action)+(NoraI18n.html("\">Подтвердить") + "</button>")+
      '</div></section>');
  }
  function moderationOpId() {
    if(window.crypto?.randomUUID)return window.crypto.randomUUID();
    const bytes=new Uint8Array(16);
    if(window.crypto?.getRandomValues)window.crypto.getRandomValues(bytes);
    else throw Error(NoraI18n.t("Безопасное подтверждение недоступно на этом устройстве"));
    bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
    const hex=[...bytes].map(x=>x.toString(16).padStart(2,'0')).join('');
    return hex.slice(0,8)+'-'+hex.slice(8,12)+'-'+hex.slice(12,16)+'-'+hex.slice(16,20)+'-'+hex.slice(20);
  }
  async function executeModeration(action) {
    const info=moderationContext;
    if(moderationBusy||!info||!(info.actions||[]).some(x=>x.id===action))return;
    const reason=document.getElementById('staff-chat-mod-reason')?.value?.trim()||'';
    const duration=document.getElementById('staff-chat-mod-duration')?.value||'';
    if(reason.length<3||reason.length>250){toast(NoraI18n.t("Укажи причину: 3–250 символов"));return;}
    let opId;
    try{opId=moderationOpId();}catch(error){toast(error.message);return;}
    moderationBusy=true;
    const button=document.querySelector('[data-chat-mod-execute]');
    if(button){button.disabled=true;button.textContent=NoraI18n.t("Выполняем…");}
    let confirmed=false;
    try{
      const result=await api('community/chat/moderation',{
        message_id:Number(info.message_id),action,reason,duration,
        operation_id:opId,confirmed:true
      });
      confirmed=!!result.ok && result.state==='sent';
    }catch(error){
      // The operation may have reached Telegram despite the HTTP error.
      // Never issue the same action using another key automatically.
      try{
        const receipt=await api('community/chat/delivery/'+opId);
        confirmed=receipt.state==='sent';
      }catch{}
      if(!confirmed){
        moderationError(NoraI18n.t("Telegram мог применить действие, но ответ не подтвердился. Проверь журнал и сам чат. Не повторяй наказание вслепую."));
        moderationBusy=false;
        return;
      }
    }finally{
      moderationBusy=false;
    }
    if(confirmed){
      moderationContext=null;
      sheet('<section class="nora-staff-mod">'+moderationTitle(NoraI18n.t("Готово"))+
        ("<p class=\"nora-staff-mod-success\">" + NoraI18n.html("Действие подтверждено. Запись добавлена в журнал Норы.") + "</p>")+
        ("<button type=\"button\" data-chat-mod-log>" + NoraI18n.html("Открыть журнал") + "</button>")+
        moderationCloseButton()+'</section>');
      signature='';void load(true);
      tg?.HapticFeedback?.notificationOccurred?.('success');
    }
  }
  async function openModerationLog() {
    sheet('<section class="nora-staff-mod">'+moderationTitle(NoraI18n.t("Журнал действий"))+
      ("<p>" + NoraI18n.html("Загружаем записи…") + "</p></section>"));
    try{
      const result=await api('community/chat/moderation/logs');
      if(tab!=='staffchat')return;
      const items=Array.isArray(result.items)?result.items:[];
      const entries=items.slice(0,30).map(item=>
        '<article class="nora-staff-mod-entry"><div><b>'+esc(item.action||NoraI18n.t("Действие"))+
        '</b><time>'+esc(item.created_at||'')+'</time></div>'+
        '<small>'+esc(item.actor||'')+' → '+esc(item.target||'')+'</small>'+
        '<p>'+esc(item.reason||item.details||NoraI18n.t("Без причины"))+'</p></article>').join('');
      sheet('<section class="nora-staff-mod">'+moderationTitle(NoraI18n.t("Журнал действий"))+
        '<p class="nora-staff-mod-footnote">'+
        (result.scope==='all'?NoraI18n.t("Последние действия команды"):NoraI18n.t("Только твои последние действия"))+
        '</p><div class="nora-staff-mod-entries">'+
        (entries||("<p>" + NoraI18n.html("Записей пока нет.") + "</p>"))+'</div>'+
        moderationCloseButton()+'</section>');
    }catch(error){moderationError(error.message||NoraI18n.t("Не удалось загрузить журнал"));}
  }

  function mount() {
    cancelChatGesture();
    reactionBusy.clear();
    stopRealtime();
    observer?.disconnect();observer = null;
    visit++;
    loading=false;signature='';contextId=null;
    newCount=0;unreadIds.clear();
    if(tab !== 'staffchat'){
      adminAccess=null;adminTarget=null;closeChatAdmin();
      if(recorder)stopRecording(true);
      clearUploads();
      clearAssets();clearChatViewport();return;
    }
    syncChatViewport();
    prepareComposer();
    void initChatAdmin();
    delivery.restore();
    updateUnread();
    void load();
    connectLive();
    if(delivery.pending)void delivery.check();
  }
  window.visualViewport?.addEventListener('resize',syncChatViewport);
  window.visualViewport?.addEventListener('scroll',syncChatViewport);
  window.addEventListener('resize',syncChatViewport);

  document.addEventListener('submit',event=>{
    if(event.target?.id === 'staff-chat-compose'){
      event.preventDefault();
      void sendCompose();
    }else if(event.target?.id==='staff-chat-admin-search'){
      event.preventDefault();
      void lookupChatAdminUser(document.getElementById('staff-chat-admin-id')?.value);
    }else if(event.target?.id==='staff-chat-admin-edit'){
      event.preventDefault();
      prepareChatAdminValue();
    }
  });
  document.addEventListener('input',event=>{
    if(tab==='staffchat' && event.target?.matches?.('.staff-chat-voice-progress')){
      const audio=event.target.closest('.staff-chat-voice-player')?.querySelector('audio');
      if(audio && Number.isFinite(audio.duration)){
        audio.currentTime=audio.duration*Number(event.target.value)/100;
      }
      return;
    }
    if(event.target?.id === 'staff-chat-draft'){
      draft=event.target.value;hideSendConfirmation();composeUpdate();postTyping();
    }
  });
  document.addEventListener('change',event=>{
    if(event.target?.matches?.('[data-chat-confirm-toggle]')){
      confirmationEnabled=!!event.target.checked;
      try{localStorage.setItem('nora-staff-chat-confirm',confirmationEnabled?'on':'off');}catch{}
      if(!confirmationEnabled)hideSendConfirmation();
      return;
    }
    if(event.target?.id==='staff-chat-admin-user'){
      const input=document.getElementById('staff-chat-admin-id');
      if(input&&event.target.value)input.value=event.target.value;
      return;
    }
    if(event.target?.id !== 'staff-chat-file')return;
    const selected=[...(event.target.files||[])];
    if(!selected.length)return;
    chooseFiles(selected);hideSendConfirmation();
    event.target.value='';
  });

  document.addEventListener('click',event=>{
    if(tab !== 'staffchat')return;
    const fromMessage=event.target.closest('[data-chat-admin-message]');
    if(fromMessage){void openChatAdminFromMessage(fromMessage.closest('.staff-chat-message'));return;}
    if(event.target.closest('[data-chat-admin-close]')){closeChatAdmin();return;}
    if(event.target.closest('[data-chat-send-back]')){hideSendConfirmation();return;}
    if(event.target.closest('[data-chat-send-confirm]')){void sendCompose(true);return;}
    const editStat=event.target.closest('[data-chat-admin-stat]');
    if(editStat&&adminTarget){
      const spec=adminStats.find(s=>s.key===editStat.dataset.chatAdminStat);
      if(!spec||!adminAccess?.[spec.permission])return;
      adminMetric=spec.key;adminView='edit';adminNotice='';renderChatAdmin();return;
    }
    if(event.target.closest('[data-chat-admin-back]')){
      adminView=adminView==='confirm'?'edit':adminView==='edit'?'person':'home';
      adminNotice='';renderChatAdmin();return;
    }
    if(event.target.closest('[data-chat-admin-save]')){void saveChatAdminValue();return;}
    const adminNode=document.querySelector('#staff-chat-feed [data-chat-admin-panel]');
    if(adminNode&&!event.target.closest('[data-chat-admin-panel]')&&!event.target.closest('[data-chat-more]'))closeChatAdmin();
    if(event.target.closest('[data-chat-mod-close]')){
      document.getElementById('sheet')?.close();return;
    }
    if(event.target.closest('[data-chat-mod-log]')){closeChatAdmin();void openModerationLog();return;}
    const modMessage=event.target.closest('[data-chat-mod-message]');
    if(modMessage){void openModeration(Number(modMessage.dataset.chatModMessage));return;}
    const modAction=event.target.closest('[data-chat-mod-action]');
    if(modAction){moderationConfirm(modAction.dataset.chatModAction);return;}
    if(event.target.closest('[data-chat-mod-back]')){
      if(moderationContext)moderationMenu(moderationContext);
      return;
    }
    const modExecute=event.target.closest('[data-chat-mod-execute]');
    if(modExecute){void executeModeration(modExecute.dataset.chatModExecute);return;}

    if(event.target.closest('[data-chat-check-delivery]')){
      void delivery.check();return;
    }
    if(event.target.closest('[data-chat-reset-delivery]')){
      if(delivery.reset())composeUpdate();
      return;
    }
    if(event.target.closest('[data-chat-scroll-new]')){
      const feed=document.getElementById('staff-chat-feed');
      if(contextId!==null){contextId=null;signature='';void load(true);}
      else if(feed)feed.scrollTo({top:feed.scrollHeight,behavior:'smooth'});
      newCount=0;unreadIds.clear();updateUnread();return;
    }
    const voicePlay=event.target.closest('[data-chat-voice-play]');
    if(voicePlay){
      const audio=voicePlay.closest('.staff-chat-voice-player')?.querySelector('audio');
      if(audio){
        if(audio.paused)void audio.play().catch(()=>toast(NoraI18n.t("Не удалось воспроизвести голосовое")));
        else audio.pause();
      }
      return;
    }
    const voiceSpeed=event.target.closest('[data-chat-voice-speed]');
    if(voiceSpeed){
      const audio=voiceSpeed.closest('.staff-chat-voice-player')?.querySelector('audio');
      if(audio){
        audio.playbackRate=audio.playbackRate===1?1.5:audio.playbackRate===1.5?2:1;
        voiceSpeed.textContent=audio.playbackRate+'×';
      }
      return;
    }
    const reactButton=event.target.closest('[data-chat-react]');
    if(reactButton){void setChatReaction(reactButton);return;}
    const reactionOpen=event.target.closest('[data-chat-react-open]');
    if(reactionOpen){
      openReactionPicker(reactionOpen.closest('.staff-chat-message'));
      return;
    }
    const copyButton=event.target.closest('[data-chat-copy]');
    if(copyButton){
      void copyChatMessage(copyButton.closest('.staff-chat-message'));
      copyButton.closest('[data-chat-menu]')?.setAttribute('hidden','');
      return;
    }
    const more = event.target.closest('[data-chat-more]');
    if(more){
      closeChatPickers();
      closeChatAdmin();
      const menu=more.closest('.staff-chat-message')?.querySelector('[data-chat-menu]');
      if(!menu)return;
      const opened=!menu.hidden;
      for(const other of document.querySelectorAll('#staff-chat-feed [data-chat-menu]:not([hidden])')){
        other.hidden=true;
        other.closest('.staff-chat-message')?.querySelector('[data-chat-more]')?.setAttribute('aria-expanded','false');
      }
      menu.hidden=opened;
      more.setAttribute('aria-expanded',String(!opened));
      return;
    }
    const answer = event.target.closest('[data-chat-answer]');
    if(answer){selectReply(answer);return;}
    if(event.target.closest('[data-chat-cancel-reply]')){
      replyTarget=null;hideSendConfirmation();composeUpdate();return;
    }
    const remove=event.target.closest('[data-chat-remove-file]');
    if(remove){
      if(sending)return;
      const index=Number(remove.dataset.chatRemoveFile);
      if(Number.isSafeInteger(index)&&index>=0&&index<attachments.length){
        forgetUpload(attachments[index]);
        attachments.splice(index,1);
        if(!attachments.length)attachmentKind='file';
        hideSendConfirmation();
        composeUpdate();
      }
      return;
    }
    if(event.target.closest('[data-chat-record-stop]')){stopRecording();return;}
    if(event.target.closest('[data-chat-record-cancel]')){stopRecording(true);return;}
    if(event.target.closest('[data-chat-record]')){void toggleRecording();return;}
    if(event.target.closest('[data-chat-attach]')){
      if(!recording&&!sending)document.getElementById('staff-chat-file')?.click();return;
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
        const allowed=attachments.length ? 800 : 3000;
        if(draft.length - (end-start) + symbol.length <= allowed){
          draft=draft.slice(0,start)+symbol+draft.slice(end);
          field.value=draft;
          field.focus();
          field.setSelectionRange(start+symbol.length,start+symbol.length);
          hideSendConfirmation();composeUpdate();postTyping();
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

  // Touch gestures are scoped to the message content, never to media controls.
  document.addEventListener('pointerdown',event=>{
    if(tab!=='staffchat'||event.pointerType==='mouse'||event.button!==0)return;
    if(event.target.closest('button,a,input,textarea,video,audio,[data-chat-picker]'))return;
    const bubble=event.target.closest('#staff-chat-feed .staff-chat-bubble');
    if(!bubble)return;
    cancelChatGesture();
    const article=bubble.closest('.staff-chat-message');
    if(!article)return;
    gesture={
      article,bubble,id:event.pointerId,x:event.clientX,y:event.clientY,
      moved:false,fired:false
    };
    gestureTimer=setTimeout(()=>{
      gestureTimer=null;
      if(gesture && !gesture.moved && gesture.article.isConnected){
        gesture.fired=true;
        openReactionPicker(gesture.article);
      }
    },480);
  },{passive:true});
  document.addEventListener('pointermove',event=>{
    if(!gesture||gesture.id!==event.pointerId)return;
    const dx=event.clientX-gesture.x,dy=event.clientY-gesture.y;
    if(Math.abs(dx)>16||Math.abs(dy)>13){
      gesture.moved=true;
      if(gestureTimer!==null){clearTimeout(gestureTimer);gestureTimer=null;}
    }
    if(dx>30&&Math.abs(dy)<32&&gesture.bubble.isConnected){
      gesture.bubble.classList.add('staff-chat-swiping');
    }else{
      gesture.bubble.classList.remove('staff-chat-swiping');
    }
  },{passive:true});
  document.addEventListener('pointerup',event=>{
    if(!gesture||gesture.id!==event.pointerId)return;
    const current=gesture;
    const dx=event.clientX-current.x,dy=event.clientY-current.y;
    current.bubble.classList.remove('staff-chat-swiping');
    cancelChatGesture();
    if(!current.fired&&dx>=65&&Math.abs(dy)<42&&current.article.isConnected){
      const answer=current.article.querySelector('[data-chat-answer]');
      if(answer){closeChatPickers();selectReply(answer);tg?.HapticFeedback?.impactOccurred?.('light');}
    }
  },{passive:true});
  document.addEventListener('pointercancel',()=>{
    if(gesture)gesture.bubble.classList.remove('staff-chat-swiping');
    cancelChatGesture();
  },{passive:true});
  document.addEventListener('contextmenu',event=>{
    if(tab!=='staffchat')return;
    if(event.target.closest('button,a,input,textarea,video,audio'))return;
    const article=event.target.closest('#staff-chat-feed .staff-chat-message');
    if(!article)return;
    event.preventDefault();
    openReactionPicker(article);
  });

  document.addEventListener('scroll',event=>{
    if(event.target?.id === 'staff-chat-feed' && newCount>0 && isFeedAtBottom()){
      newCount=0;unreadIds.clear();updateUnread();
    }
  },true);
  document.addEventListener('visibilitychange',()=>{
    if(tab!=='staffchat')return;
    if(document.hidden){if(recorder)stopRecording(true);stopRealtime();return;}
    void load();connectLive();
    if(delivery.pending)void delivery.check();
  });
  window.addEventListener('online',()=>{
    if(tab==='staffchat'&&!document.hidden){
      if(retryTimer!==null){clearTimeout(retryTimer);retryTimer=null;}
      connectLive();
      if(delivery.pending)void delivery.check();
    }
  });
  window.addEventListener('pagehide',()=>{
    if(recorder)stopRecording(true);
    clearUploads();clearAssets();stopRealtime();
  });
  window.addEventListener('pageshow',()=>{
    if(tab==='staffchat'&&!document.hidden){
      void load();connectLive();
      delivery.restore();
      if(delivery.pending)void delivery.check();
    }
  });
  return {screen,mount};
})();
