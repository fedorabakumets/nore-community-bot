'use strict';
// Experimental read-only Telegram mirror. No fake "send as user" behavior.
window.NoraStaffChat = (() => {

  let timer = null, loading = false, signature = '', contextId = null, visit = 0, observer = null;
  const cache = new Map();
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
  const msgSignature = m => [m.edited_at || '', m.reply_text || '', m.reply_name || '', m.text || '', m.media_type || '', m.has_thumbnail ? '1' : '0'].join('|');
  const line = m => {
    const id = Number(m.id);
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
    return `<article class="staff-chat-message" data-message-id="${id}">
       ${avatar}<div class="staff-chat-bubble">
         <div class="staff-chat-meta">${who}<time datetime="${esc(m.sent_at)}">${time(m.sent_at)}</time>${m.edited_at?'<span class="staff-chat-edited">изм.</span>':''}${link}</div>
         ${quote}${mediaTile(m)}${body}
       </div>
     </article>`;
  };
  function screen() {
    return `<section class="nora-staff-chat">
      <header class="staff-chat-header">
        <button class="staff-chat-back" type="button" data-tab="community" aria-label="Назад в Коммьюнити">‹</button>
        <div class="staff-chat-heading"><h1>Чат Норы</h1><span><i aria-hidden="true"></i> Только чтение · тест</span></div>
      </header>
      <div id="staff-chat-feed" class="staff-chat-feed" aria-label="Сообщения чата" aria-live="off">
        <p class="staff-chat-empty">Подключаем чат…</p>
      </div>
      <footer class="staff-chat-footer"><span>Сообщения из Telegram · режим просмотра</span><button type="button" class="staff-chat-latest" data-chat-latest hidden>К последним сообщениям ↑</button></footer>
    </section>`;
  }
  async function load() {
    if (tab !== 'staffchat' || document.hidden || loading) return;
    const feed = document.getElementById('staff-chat-feed');
    if (!feed) return;
    loading = true;
    try {
      const result = await api('community/chat');
      const target = document.getElementById('staff-chat-feed');
      if (tab !== 'staffchat' || !target) return;
      const items = Array.isArray(result.items) ? result.items : [];
      const current = items.map(m=>`${m.id}:${m.edited_at||''}`).join('|');
      if (current === signature && target.querySelector('.staff-chat-message')) return;
      const wasAtBottom = target.scrollHeight - target.scrollTop - target.clientHeight < 90;
      const first = !signature;
      signature = current;
      target.innerHTML = items.length
        ? items.map(line).join('')
        : '<p class="staff-chat-empty">Пока здесь нет записанных сообщений. Новые сообщения появятся автоматически.</p>';
      if (first || wasAtBottom) target.scrollTop = target.scrollHeight;
    } catch (error) {
      const target = document.getElementById('staff-chat-feed');
      if (tab === 'staffchat' && target && !target.querySelector('.staff-chat-message'))
        target.innerHTML = `<p class="staff-chat-empty">${esc(error.message || 'Чат недоступен')}</p><button type="button" class="staff-chat-retry" data-staff-chat-retry>Повторить</button>`;
    } finally { loading = false; }
  }
  function mount() {
    if (timer !== null) {clearInterval(timer);timer = null;}
    if (tab !== 'staffchat') return;
    signature = '';
    void load();
    timer = setInterval(load, 3000);
  }
  document.addEventListener('click', event => {
    if (event.target.closest('[data-staff-chat-retry]')) void load();
    const link = event.target.closest('.staff-chat-original');
    if (link && tg?.openTelegramLink) {
      event.preventDefault();
      tg.openTelegramLink(link.href);
    }
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && tab === 'staffchat') void load();
  });
  return {screen,mount};
})();
