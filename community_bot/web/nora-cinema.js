'use strict';
window.NoraCinema = (() => {
  const entrance = {x: 10.8, z: -.3};
  const rows = [-4, -2.3];
  const columns = [10.8, 9.5, 12.1, 8.2, 13.4];
  const seats = rows.flatMap(z => columns.map(x => ({x, z})));
  let youtubePromise;

  function loadYouTube() {
    if (window.YT?.Player) return Promise.resolve(window.YT);
    if (!youtubePromise) {
      youtubePromise = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = 'https://www.youtube.com/iframe_api';
        script.referrerPolicy = 'strict-origin-when-cross-origin';
        const timeout = setTimeout(fail, 15000);
        function fail() {
          clearTimeout(timeout);
          script.remove();
          youtubePromise = null;
          delete window.onYouTubeIframeAPIReady;
          reject(new Error('YouTube сейчас недоступен.'));
        }
        script.onerror = fail;
        window.onYouTubeIframeAPIReady = () => {
          clearTimeout(timeout);
          delete window.onYouTubeIframeAPIReady;
          resolve(window.YT);
        };
        document.head.append(script);
      });
    }
    return youtubePromise;
  }

  function mount(root, reset, sessionId, clock, chatOpen, onExit) {
    root.insertAdjacentHTML('beforeend',
      '<button type="button" class="nora-cinema-open" hidden>Кинотеатр</button>' +
      '<section class="nora-cinema" aria-label="Кинотеатр" hidden>' +
      '<header><h2>Кинотеатр</h2><button type="button" data-chat>Чат</button>' +
      '<button type="button" data-exit>Выйти из зала</button></header>' +
      '<div class="nora-cinema-media" hidden></div>' +
      '<p role="status" data-note>Ищем свободное место…</p>' +
      '<button type="button" data-watch hidden>Смотреть</button>' +
      '<details hidden><summary>Выбрать видео</summary><form>' +
      '<label>Ссылка на YouTube или MP4<input name="url" type="url" placeholder="https://" maxlength="2048"></label>' +
      '<label>Видео из Telegram<select name="clip"><option value="">Выбери ролик</option></select></label>' +
      '<button type="button" data-clips>Обновить список</button>' +
      '<button type="submit">Начать сеанс</button></form></details>' +
      '<div class="nora-cinema-controls" hidden><button type="button" data-toggle>Пауза для всех</button>' +
      '<button type="button" data-back aria-label="Назад на 30 секунд">−30 с</button>' +
      '<button type="button" data-forward aria-label="Вперёд на 30 секунд">+30 с</button>' +
      '<input type="range" min="0" max="1" value="0" aria-label="Перемотка сеанса" disabled>' +
      '<button type="button" data-stop>Завершить</button></div></section>');
    const opener = root.querySelector('.nora-cinema-open');
    const panel = root.querySelector('.nora-cinema');
    const media = panel.querySelector('.nora-cinema-media');
    const note = panel.querySelector('[data-note]');
    const watch = panel.querySelector('[data-watch]');
    const form = panel.querySelector('form');
    const picker = panel.querySelector('details');
    const controls = panel.querySelector('.nora-cinema-controls');
    const range = controls.querySelector('input');
    const toggle = controls.querySelector('[data-toggle]');
    const exit = panel.querySelector('[data-exit]');
    const life = new AbortController();
    let visible = false;
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.intersectionRatio >= .55;
      if (visible) sync(performance.now(), true);
    }, {threshold: .55});
    observer.observe(media);
    const on = (target, name, handler) => target.addEventListener(name, handler, {signal: life.signal});
    let active = false, seat = null, revision = '?', show = null, moderator = false;
    let watched = false, autoplayBlocked = false, playerError = '', busy = false, seeking = false;
    let video = null, youtube = null, ready = false, version = 0, lastSync = 0, lastReply = 0, loadAt = 0;
    let pendingRevision = null, warned = false;

    function desired(now) {
      return show ? show.position + (show.playing ? Math.max(0, (clock(now) - show.changed) / 1000) : 0) : 0;
    }

    function request(params = {}) {
      const query = new URLSearchParams({session: sessionId() || '', ...params});
      return api('nora-game/cinema?' + query, undefined, AbortSignal.timeout(7000));
    }

    function clearPlayer() {
      version++;
      const oldPlayer = youtube;
      youtube = null;
      ready = false;
      if (oldPlayer) oldPlayer.destroy();
      if (video) {
        video.pause();
        video.removeAttribute('src');
        video.load();
        video = null;
      }
      media.replaceChildren();
      media.hidden = true;
      autoplayBlocked = false;
      playerError = '';
      warned = false;
    }

    function render() {
      const connected = seat !== null;
      const leading = !!show && (show.host || moderator);
      picker.hidden = !connected || !!show && !leading;
      controls.hidden = !connected || !leading;
      toggle.textContent = show?.playing ? 'Пауза для всех' : 'Продолжить для всех';
      watch.hidden = !connected || !show || watched && !autoplayBlocked && !playerError;
      watch.textContent = playerError ? 'Попробовать снова' : autoplayBlocked ? 'Включить видео' : 'Смотреть';
      if (playerError) note.textContent = playerError;
      else if (!connected) note.textContent = lastReply ? 'Зал заполнен. Место освободится, когда кто-нибудь выйдет.' :
        'Ищем свободное место…';
      else if (!show) note.textContent = 'Сеанс ещё не начался. Выбери, что будем смотреть.';
      else if (autoplayBlocked && show.kind === 'youtube') note.textContent = 'Нажми ▶ в плеере YouTube, чтобы подключиться.';
      else if (autoplayBlocked) note.textContent = 'Нажми «Включить видео», чтобы подключиться со звуком.';
      else if (show.playing) note.textContent = leading ? 'Ты управляешь сеансом.' : 'Общий сеанс идёт.';
      else note.textContent = 'Общая пауза.';
      if (autoplayBlocked && show?.kind === 'youtube') watch.hidden = true;
    }

    function fail(message) {
      playerError = message;
      render();
    }

    async function clips() {
      const current = sessionId();
      try {
        const result = await request();
        if (!active || current !== sessionId()) return;
        moderator = result.moderator;
        const select = form.elements.clip;
        const selected = select.value;
        select.replaceChildren(new Option('Выбери ролик', ''));
        for (const clip of result.clips) select.add(new Option(clip.label, clip.id));
        if (result.clips.some(clip => clip.id === selected)) select.value = selected;
        render();
      } catch (error) {
        if (active && current === sessionId()) note.textContent = error.message;
      }
    }

    async function command(action, fields = {}) {
      if (busy || seat === null || pendingRevision === revision) return;
      busy = true;
      const session = sessionId();
      const sentRevision = revision;
      try {
        await api('nora-game/cinema', {session, revision, action, ...fields}, AbortSignal.timeout(7000));
        if (!active || session !== sessionId()) return;
        if (action === 'start') {
          picker.open = false;
          form.reset();
        }
        if (revision === sentRevision) pendingRevision = sentRevision;
      } catch (error) {
        if (active && session === sessionId()) note.textContent = error.message;
      } finally {
        busy = false;
      }
    }

    async function openPlayer() {
      if (!active || !show) return;
      clearPlayer();
      watched = true;
      loadAt = performance.now();
      const current = version;
      const {kind, id, source} = show;
      media.hidden = false;
      render();
      try {
        if (kind === 'youtube') {
          const YT = await loadYouTube();
          if (current !== version) return;
          const iframe = document.createElement('iframe');
          const params = new URLSearchParams({enablejsapi: '1', playsinline: '1', origin: location.origin});
          iframe.title = 'Плеер YouTube';
          iframe.allow = 'autoplay; encrypted-media; fullscreen; picture-in-picture';
          iframe.allowFullscreen = true;
          iframe.referrerPolicy = 'strict-origin-when-cross-origin';
          iframe.src = 'https://www.youtube.com/embed/' + source + '?' + params;
          media.replaceChildren(iframe);
          youtube = new YT.Player(iframe, {events: {
            onReady() {
              if (current !== version) return;
              ready = true;
              sync(performance.now(), true);
            },
            onStateChange(event) {
              if (current !== version || event.data !== 1) return;
              if (autoplayBlocked) {
                autoplayBlocked = false;
                render();
              }
            },
            onAutoplayBlocked() {
              if (current !== version) return;
              autoplayBlocked = true;
              render();
            },
            onError() {
              if (current === version) fail('Ролик YouTube не открывается в этом плеере.');
            },
          }});
        } else {
          const url = kind === 'telegram' ? (await request({show: id})).url : source;
          if (current !== version) return;
          const element = document.createElement('video');
          video = element;
          video.playsInline = true;
          video.controls = true;
          video.preload = 'metadata';
          video.referrerPolicy = 'no-referrer';
          video.addEventListener('loadedmetadata', () => {
            if (current !== version) return;
            ready = true;
            sync(performance.now(), true);
          });
          video.addEventListener('error', () => {
            if (current === version) fail('Видео не загрузилось. Проверь формат MP4 и доступность файла.');
          });
          video.addEventListener('play', () => {
            if (current === version && autoplayBlocked) {
              autoplayBlocked = false;
              render();
            }
          });
          media.replaceChildren(video);
          video.src = url;
          if (show.playing) playVideo();
        }
      } catch (error) {
        if (current === version) fail(error.message);
      }
    }

    function playVideo() {
      const element = video;
      element?.play().catch(error => {
        if (video !== element || error.name !== 'NotAllowedError') return;
        autoplayBlocked = true;
        render();
      });
    }

    function pauseLocal() {
      if (video && !video.paused) video.pause();
      if (ready && youtube?.getPlayerState() === 1) youtube.pauseVideo();
    }

    function sync(now, force = false) {
      if (!active || !show || now - lastReply > 8000 || document.hidden || chatOpen() || !visible) {
        pauseLocal();
        return;
      }
      if (!watched || playerError) return;
      if (!ready) {
        if (now - loadAt > 21000) fail('Плеер не ответил. Можно попробовать ещё раз.');
        return;
      }
      if (!force && now - lastSync < 900) return;
      lastSync = now;
      const duration = video?.duration ?? youtube?.getDuration() ?? 0;
      const validDuration = Number.isFinite(duration) && duration > 0;
      const at = validDuration ? Math.min(duration, desired(now)) : desired(now);
      const ended = validDuration && at >= duration;
      range.disabled = !validDuration;
      if (validDuration && !seeking && document.activeElement !== range) {
        range.max = String(Math.ceil(duration));
        range.value = String(at);
      }
      if (ended && show.host && !warned) {
        warned = true;
        void command('stop');
      }
      const playing = show.playing && !ended;
      const position = video?.currentTime ?? youtube.getCurrentTime();
      if (video?.seeking || youtube?.getPlayerState() === 3) {
        if (!playing) pauseLocal();
        return;
      }
      const tolerance = force ? .12 : playing ? (video ? .65 : 2) : .25;
      if (!autoplayBlocked && Math.abs(position - at) > tolerance) {
        if (video) video.currentTime = at;
        else youtube.seekTo(at, true);
      }
      if (playing && !autoplayBlocked) {
        if (video?.paused) playVideo();
        if (youtube && youtube.getPlayerState() !== 1) youtube.playVideo();
      } else if (!playing) pauseLocal();
    }

    function receive(payload) {
      if (!active || !payload) return;
      const firstReply = lastReply === 0;
      const previousSeat = seat;
      lastReply = performance.now();
      const firstSeat = seat === null && payload.seat !== null;
      seat = payload.seat;
      if (seat === null) {
        if (!firstReply && previousSeat === null) return;
        clearPlayer();
        watched = false;
        revision = '?';
        show = null;
        render();
        return;
      }
      if ('show' in payload) {
        const changed = payload.show?.id !== show?.id;
        show = payload.show;
        revision = payload.revision;
        pendingRevision = null;
        warned = false;
        if (changed) {
          const keepWatching = watched && !!show;
          clearPlayer();
          watched = false;
          if (keepWatching) void openPlayer();
        }
        render();
        sync(lastReply, true);
      }
      if (firstSeat) void clips();
    }

    function leave() {
      if (active) onExit();
      active = false;
      watched = false;
      seat = null;
      revision = '?';
      pendingRevision = null;
      show = null;
      lastReply = 0;
      moderator = false;
      picker.open = false;
      form.reset();
      clearPlayer();
      panel.hidden = true;
      root.classList?.remove('nora-cinema-active');
      reset();
    }

    function enter() {
      if (active || opener.hidden) return;
      active = true;
      panel.hidden = false;
      root.classList?.add('nora-cinema-active');
      reset();
      render();
      exit.focus();
    }

    on(opener, 'click', enter);
    on(exit, 'click', () => {
      leave();
      opener.focus();
    });
    on(panel.querySelector('[data-chat]'), 'click', () => root.querySelector('.nora-chat-open')?.click());
    on(panel.querySelector('[data-clips]'), 'click', clips);
    on(watch, 'click', () => {
      if (video && autoplayBlocked && !playerError) {
        autoplayBlocked = false;
        render();
        playVideo();
      } else void openPlayer();
    });
    on(form, 'submit', event => {
      event.preventDefault();
      const url = form.elements.url.value.trim();
      const clip = form.elements.clip.value;
      if (url || clip) void command('start', url ? {url} : {clip});
      else note.textContent = 'Вставь ссылку или выбери видео из Telegram.';
    });
    on(toggle, 'click', () => command('toggle'));
    on(controls.querySelector('[data-stop]'), 'click', () => command('stop'));
    for (const [name, delta] of [['back', -30], ['forward', 30]]) {
      on(controls.querySelector('[data-' + name + ']'), 'click', () => {
        const duration = video?.duration ?? youtube?.getDuration() ?? 86400;
        const position = Math.max(0, desired(performance.now()) + delta);
        void command('seek', {position: Math.min(duration || 86400, position)});
      });
    }
    on(range, 'pointerdown', () => {seeking = true;});
    for (const event of ['pointerup', 'pointercancel', 'blur']) on(range, event, () => {seeking = false;});
    on(range, 'change', () => {
      seeking = false;
      void command('seek', {position: Number(range.value)});
    });
    on(document, 'visibilitychange', () => {
      if (document.hidden) {
        pauseLocal();
        revision = '?';
      }
    });

    return {
      active: () => active,
      seat: () => seats[seat] ?? null,
      revision: () => revision,
      setAvailable(available) {
        if (opener.hidden === available) opener.hidden = !available;
      },
      enter, receive, sync,
      dispose() {
        leave();
        life.abort();
        observer.disconnect();
        panel.remove();
        opener.remove();
      },
    };
  }

  return {mount, entrance, seats};
})();
