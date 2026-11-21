'use strict';
// Experimental read-only Telegram mirror. No fake "send as user" behavior.
window.NoraStaffChat = (() => {
  let timer = null, loading = false, signature = '';
  const mediaLabels = {
    photo: '📷 Фото', video: '🎥 Видео', animation: '🎞 GIF',
    voice: '🎤 Голосовое сообщение', video_note: '◉ Кружочек',
    audio: '🎵 Аудио', document: '📎 Документ',
    sticker: 'Стикер', poll: '📊 Опрос',
    location: '📍 Геопозиция', contact: '👤 Контакт'
  };
  const time = value => {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? '' :
      d.toLocaleTimeString('ru-RU', {hour:'2-digit',minute:'2-digit'});
  };
  const line = m => {
    const name = esc(m.name || 'Участник');
    const initial = esc((m.name || '?').match(/[\p{L}\p{N}]/u)?.[0]?.toUpperCase() || '?');
    const who = Number(m.user_id) > 0
      ? `<button class="staff-chat-author" data-person-view="${m.user_id}" type="button">${name}</button>`
      : `<span class="staff-chat-author">${name}</span>`;
    const avatar = `<span class="staff-chat-avatar" ${Number(m.user_id) > 0 ? `data-person-avatar="${m.user_id}" ${!m.has_avatar?'data-avatar-unavailable':''}` : ''}>${initial}</span>`;
    const reply = m.reply_to_id
      ? `<div class="staff-chat-reply"><b>${esc(m.reply_name || 'Сообщение')}</b><span>${esc((m.reply_text || 'Вложение').slice(0,90))}</span></div>`
      : '';
    const media = m.media_type ? `<div class="staff-chat-media">${esc(mediaLabels[m.media_type] || '📎 Вложение')}</div>` : '';
    const body = m.text ? `<div class="staff-chat-text">${esc(m.text)}</div>` : '';
    const link = m.link ? `<a class="staff-chat-original" href="${esc(m.link)}" target="_blank" rel="noopener noreferrer" aria-label="Открыть сообщение в Telegram">↗</a>` : '';
    return `<article class="staff-chat-message" data-message-id="${m.id}">
       ${avatar}<div class="staff-chat-bubble">
         <div class="staff-chat-meta">${who}<time datetime="${esc(m.sent_at)}">${time(m.sent_at)}</time>${m.edited_at?'<span class="staff-chat-edited">изм.</span>':''}${link}</div>
         ${reply}${media}${body}
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
      <footer class="staff-chat-footer">Сообщения из Telegram · ответы и вложения открываются в оригинальном чате</footer>
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
