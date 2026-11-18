'use strict';
window.NoraChat = (() => {
  const colors = ['#f6bf80', '#90d9e5', '#f0a9ca', '#bfdb90', '#c6b7fe',
    '#ffab9e', '#99d9ba', '#ffe090', '#abc9ff', '#eeb4f7'];
  const roomNames = {
    lobby:'Лобби', cinema:'Кинотеатр', observatory:'Воспоминание', tavern:'Твоя Нора', forest:'Твоя Нора',
  };
  const clock = new Intl.DateTimeFormat('ru', {hour:'2-digit', minute:'2-digit'});

  function speech(T, text, color) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const font = '15px NoraCraft, monospace';
    ctx.font = font;
    const lines = [''];
    const chars = Array.from(text);
    for (let i = 0; i < chars.length; i++) {
      const last = lines.length - 1;
      if (ctx.measureText(lines[last] + chars[i]).width <= 182) {
        lines[last] += chars[i];
      } else if (lines.length < 3) {
        const space = lines[last].lastIndexOf(' ');
        if (space > 0) {
          lines.push(lines[last].slice(space + 1) + chars[i]);
          lines[last] = lines[last].slice(0, space);
        } else {
          lines.push(chars[i].trimStart());
        }
      } else {
        const line = Array.from(lines[last].trimEnd());
        while (ctx.measureText(line.join('') + '…').width > 182) line.pop();
        lines[last] = line.join('').trimEnd() + '…';
        break;
      }
    }
    canvas.width = Math.ceil(Math.max(...lines.map(line => ctx.measureText(line).width))) + 20;
    canvas.height = lines.length * 20 + 19;
    const {width, height} = canvas;
    const center = Math.floor(width / 2);
    ctx.fillStyle = color;
    ctx.fillRect(3, 0, width - 6, height - 7);
    ctx.fillRect(0, 3, width, height - 13);
    ctx.fillRect(center - 5, height - 8, 10, 4);
    ctx.fillRect(center - 2, height - 4, 4, 4);
    ctx.fillStyle = '#181822';
    ctx.fillRect(3, 3, width - 6, height - 13);
    ctx.fillStyle = '#fff0db';
    ctx.font = font;
    ctx.textBaseline = 'top';
    lines.forEach((line, i) => ctx.fillText(line, 10, 6 + i * 20));
    const texture = new T.CanvasTexture(canvas);
    texture.colorSpace = T.SRGBColorSpace;
    texture.minFilter = texture.magFilter = T.NearestFilter;
    const sprite = new T.Sprite(new T.SpriteMaterial({map:texture, depthWrite:false, fog:false, transparent:true}));
    sprite.center.set(.5, 0);
    sprite.position.y = 6.12;
    sprite.scale.set(width / 33, height / 33, 1);
    return sprite;
  }

  function mount(root, T, player, findAvatar, reset, location) {
    root.insertAdjacentHTML('beforeend', `
      <button type="button" class="nora-chat-open" aria-controls="nora-chat" aria-expanded="false">Чат<span hidden aria-hidden="true"></span></button>
      <aside class="nora-chat-mini" aria-label="Последние сообщения" hidden><ol></ol></aside>
      <dialog class="nora-chat" id="nora-chat" aria-labelledby="nora-chat-title">
        <div class="nora-chat-panel">
          <div class="nora-chat-top">
            <h2 id="nora-chat-title">Лобби</h2>
            <div class="nora-chat-tools">
              <button type="button" class="nora-chat-telegram" aria-label="Связь с Telegram"
                aria-pressed="false" title="Связь с Telegram"></button>
            <button type="button" class="nora-chat-close" aria-label="Закрыть чат" autofocus>×</button></div>
          </div>
          <div class="nora-chat-feed" role="log" aria-label="Сообщения" tabindex="0">
            <ol></ol><div class="nora-chat-empty">Загрузка сообщений…</div>
          </div>
          <form class="nora-chat-form">
            <div class="nora-chat-draft-quote" hidden>
              <span></span><button type="button" aria-label="Отменить ответ">×</button>
            </div>
            <div class="nora-chat-status" role="status">Только этот игровой чат.</div>
            <div class="nora-chat-compose">
              <input name="message" aria-label="Сообщение" placeholder="Написать в чат…" maxlength="240" required autocomplete="off" enterkeyhint="send" disabled>
              <button type="submit" disabled>Отправить</button>
            </div>
          </form>
        </div>
      </dialog>`);
    const opener = root.querySelector('.nora-chat-open');
    const dot = opener.querySelector('span');
    const dialog = root.querySelector('.nora-chat');
    const close = dialog.querySelector('.nora-chat-close');
    const title = dialog.querySelector('#nora-chat-title');
    const telegramToggle = dialog.querySelector('.nora-chat-telegram');
    const draftQuote = dialog.querySelector('.nora-chat-draft-quote');
    const draftDetails = draftQuote.querySelector('span');
    const preview = root.querySelector('.nora-chat-mini');
    const previewLog = preview.querySelector('ol');
    const toggle = root.querySelector('#nora-chat-preview-setting');
    let showMini = true;
    try { showMini = localStorage.getItem('nora-chat-preview') !== 'off'; } catch (_) {}
    if (toggle) toggle.checked = showMini;
    const feed = dialog.querySelector('.nora-chat-feed');
    const log = feed.querySelector('ol');
    const empty = feed.querySelector('.nora-chat-empty');
    const status = dialog.querySelector('.nora-chat-status');
    const form = dialog.querySelector('form');
    const input = form.elements.message;
    const send = form.querySelector('button[type="submit"]');
    const controls = new AbortController();
    const listen = (el, event, fn) => el?.addEventListener(event, fn, {signal:controls.signal});
    const viewport = window.visualViewport;
    const signal = (ms, ...extra) => AbortSignal.any?.([controls.signal, AbortSignal.timeout(ms), ...extra]) || controls.signal;
    const rows = new Map(), bubbles = new Map();
    let revision = '', timer, stopped = false, polling = false, online = false, sending = false;
    let pollRequest, previewTimer;
    let previewLines = [];
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let shownStatus = '', currentRoom = location(), telegram = false, view = 0, replyTo = null;
    title.textContent = roomNames[currentRoom];
    document.fonts?.load('15px NoraCraft').catch(() => {});

    function updateForm() {
      input.disabled = !online;
      send.disabled = !online || sending || !input.value.trim();
      const message = shownStatus || (telegram ? 'В игре и в группе Telegram.' : 'Только этот игровой чат.');
      if (status.textContent !== message) status.textContent = message;
    }
    function selectReply(line) {
      replyTo = line;
      draftQuote.hidden = !line;
      draftDetails.textContent = line ? line.author + ' · ' + line.text : '';
    }

    function changeView() {
      view++;
      pollRequest?.abort();
      revision = '';
      online = false;
      shownStatus = '';
      title.textContent = roomNames[currentRoom];
      dot.hidden = true;
      updateFeed([]);
      for (const key of bubbles.keys()) clearBubble(key);
      empty.textContent = 'Подключаем чат…';
      updateForm();
      void poll();
    }

    listen(telegramToggle, 'click', () => {
      telegram = !telegram;
      telegramToggle.setAttribute('aria-pressed', String(telegram));
      if (!telegram && replyTo?.source === 'telegram') selectReply(null);
      changeView();
    });
    listen(draftQuote.querySelector('button'), 'click', () => selectReply(null));

    function syncViewport() {
      if (!viewport) return;
      dialog.style.setProperty('--chat-viewport', viewport.height + 'px');
      dialog.style.setProperty('--chat-keyboard', Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop) + 'px');
    }
    listen(toggle, 'change', () => {
      showMini = toggle.checked;
      renderPreview();
      try { localStorage.setItem('nora-chat-preview', showMini ? 'on' : 'off'); } catch (_) {}
    });
    listen(viewport, 'resize', syncViewport);
    listen(viewport, 'scroll', syncViewport);
    listen(opener, 'click', () => {
      reset();
      syncViewport();
      dialog.showModal();
      close.focus({preventScroll:true});
      opener.setAttribute('aria-expanded', 'true');
      dot.hidden = true;
      feed.scrollTop = feed.scrollHeight;
      if (!online) void poll();
    });
    listen(dialog, 'close', () => {
      opener.setAttribute('aria-expanded','false');
      if (!stopped) opener.focus({preventScroll:true});
      reset();
    });
    listen(close, 'click', () => dialog.close());
    listen(input, 'input', () => {
      if (online) shownStatus = '';
      updateForm();
    });
    listen(form, 'submit', async event => {
      event.preventDefault();
      const draft = input.value, text = draft.trim();
      if (!online || sending || !text) return;
      sending = true;
      const target = replyTo, sentView = view;
      shownStatus = 'Отправляем…';
      updateForm();
      try {
        await api('nora-game/chat', {text, location:currentRoom, telegram, replyTo:target?.id}, signal(15000));
        if (view === sentView) {
          if (input.value === draft) input.value = '';
          if (replyTo === target) selectReply(null);
          shownStatus = '';
          void poll();
        }
      } catch (error) {
        if (view === sentView) shownStatus = error.message || 'Не удалось отправить сообщение.';
      } finally {
        sending = false;
        if (!stopped) updateForm();
      }
    });

    function authorName(line) {
      const author = document.createElement('b');
      author.textContent = line.author;
      author.dir = 'auto';
      author.style.color = colors[line.color];
      return author;
    }

    function renderPreview() {
      clearTimeout(previewTimer);
      const now = Date.now();
      previewLines = previewLines.filter(entry => entry.until > now);
      const active = showMini ? previewLines : [];
      const latest = active.map(({line, until}) => {
        const row = document.createElement('li');
        const message = document.createElement('span');
        message.dir = 'auto';
        message.textContent = line.text;
        row.append(authorName(line), ' · ', message);
        if (!reducedMotion.matches) {
          const remaining = until - now, fadeMs = 800;
          row.animate?.([{opacity:Math.min(1, remaining / fadeMs)}, {opacity:0}], {
            delay:Math.max(0, remaining - fadeMs), duration:Math.min(remaining, fadeMs), fill:'forwards',
          });
        }
        return row;
      });
      previewLog.replaceChildren(...latest);
      preview.hidden = !latest.length;
      if (active.length) {
        const expiry = Math.min(...active.map(entry => entry.until));
        previewTimer = setTimeout(renderPreview, expiry - now);
      }
    }

    function append(line) {
      const row = document.createElement('li');
      const meta = document.createElement('div');
      const author = authorName(line);
      const origin = document.createElement('small');
      const time = document.createElement('time');
      const message = document.createElement('p');
      const date = new Date(line.time);
      origin.textContent = line.source === 'game' ? 'Игра' : 'Telegram';
      origin.dataset.source = line.source;
      time.dateTime = date.toISOString();
      time.textContent = clock.format(date);
      message.textContent = line.text;
      message.dir = 'auto';
      const reply = document.createElement('button');
      reply.type = 'button';
      reply.className = 'nora-chat-reply';
      reply.setAttribute('aria-label', 'Ответить · ' + line.author);
      reply.title = 'Ответить';
      reply.onclick = () => { selectReply(line); input.focus(); };
      meta.append(author, origin, time, reply);
      row.append(meta);
      if (line.quote) {
        const quote = document.createElement('blockquote');
        quote.className = 'nora-chat-quote';
        quote.textContent = line.quote.author + ' · ' + line.quote.text;
        row.append(quote);
      }
      row.append(message);
      log.append(row);
      rows.set(line.id, row);
    }

    function updateFeed(messages) {
      const now = Date.now();
      previewLines = messages.filter(line => line.previewMs > 0).slice(-3)
        .map(line => ({line, until:now + line.previewMs}));
      renderPreview();
      const bottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 28;
      const first = [...log.children].find(row => row.offsetTop + row.offsetHeight > feed.scrollTop);
      const offset = first ? first.offsetTop - feed.scrollTop : 0;
      const ids = new Set(messages.map(line => line.id));
      for (const [id, row] of rows) {
        if (!ids.has(id)) {
          row.remove();
          rows.delete(id);
        }
      }
      for (const line of messages) {
        if (rows.has(line.id)) continue;
        append(line);
        if (!dialog.open && !line.mine && line.bubbleMs > 0) dot.hidden = false;
        if ((line.avatar || line.mine) && line.bubbleMs > 0) {
          const key = line.mine ? player : line.avatar;
          clearBubble(key);
          bubbles.set(key, {line, expires:performance.now() + line.bubbleMs, sprite:null});
        }
      }
      if (bottom) feed.scrollTop = feed.scrollHeight;
      else if (first?.isConnected) feed.scrollTop = first.offsetTop - offset;
      empty.hidden = rows.size > 0;
      empty.textContent = 'Здесь появятся сообщения этого чата.';
    }

    function clearBubble(key) {
      const bubble = bubbles.get(key);
      for (const sprite of [bubble?.sprite, bubble?.quote]) {
        if (!sprite) continue;
        sprite.removeFromParent();
        sprite.material.map.dispose();
        sprite.material.dispose();
      }
      bubbles.delete(key);
    }

    async function poll() {
      if (stopped || polling || document.hidden) return;
      clearTimeout(timer);
      polling = true;
      const polledView = view;
      pollRequest = new AbortController();
      const params = new URLSearchParams({after:revision, location:currentRoom, telegram:telegram?'1':'0'});
      try {
        const result = await api('nora-game/chat?' + params, undefined, signal(7000, pollRequest.signal));
        if (stopped || polledView !== view) return;
        if (!online && !sending) shownStatus = '';
        online = true;
        revision = result.revision;
        if (result.messages) updateFeed(result.messages);
      } catch (error) {
        if (stopped || polledView !== view) return;
        revision = '';
        online = false;
        updateFeed([]);
        for (const key of bubbles.keys()) clearBubble(key);
        dot.hidden = true;
        empty.textContent = '';
        shownStatus = error.message || 'Связь с чатом потеряна.';
      } finally {
        polling = false;
        pollRequest = null;
        if (!stopped) {
          updateForm();
          const delay = polledView !== view ? 0 : online ? 1400 : currentRoom === 'cinema' || currentRoom === 'observatory' ? 950 : 5000;
          timer = setTimeout(poll, delay);
        }
      }
    }
    listen(document, 'visibilitychange', () => {
      if (document.hidden) return;
      renderPreview();
      void poll();
    });
    void poll();

    return {
      preview,
      panelOpen: () => dialog.open,
      update(now) {
        const room = location();
        if (room !== currentRoom) {
          currentRoom = room;
          input.value = '';
          selectReply(null);
          changeView();
        }
        for (const [key, bubble] of bubbles) {
          const left = bubble.expires - now;
          if (left <= 0) {
            clearBubble(key);
            continue;
          }
          const avatar = key === player ? player : findAvatar(key);
          if (!avatar) {
            bubble.sprite?.removeFromParent();
            bubble.quote?.removeFromParent();
            continue;
          }
          if (!bubble.sprite) {
            bubble.sprite = speech(T, bubble.line.text, colors[bubble.line.color]);
            if (bubble.line.quote) {
              const quote = bubble.line.quote;
              bubble.quote = speech(T, quote.author + ' · ' + quote.text, '#a9a2b1');
              bubble.quote.scale.multiplyScalar(.78);
              bubble.quote.position.y += bubble.sprite.scale.y + .10;
            }
          }
          const fade = Math.min(1, left / 450);
          if (bubble.sprite.parent !== avatar) avatar.add(bubble.sprite);
          bubble.sprite.material.opacity = fade;
          if (bubble.quote) {
            if (bubble.quote.parent !== avatar) avatar.add(bubble.quote);
            bubble.quote.material.opacity = fade * .62;
          }
        }
      },
      dispose() {
        stopped = true;
        clearTimeout(timer);
        clearTimeout(previewTimer);
        controls.abort();
        if (dialog.open) dialog.close();
        for (const key of bubbles.keys()) clearBubble(key);
        dialog.remove();
        opener.remove();
        preview.remove();
      },
    };
  }

  return {mount};
})();
