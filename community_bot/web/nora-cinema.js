'use strict';
window.NoraCinema = (() => {
  const room = 'cinema', title = 'Кинотеатр';
  const surfaceWidth = 640, surfaceHeight = 360;
  let youtubePromise;

  async function load() {
    const response = await fetch('/nora-cinema.json?v=cinema-hall');
    if (!response.ok) throw Error('Не удалось загрузить кинотеатр');
    return response.json();
  }

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

  function mount(root, T, layout, {reset, sessionId, clock, onSeatChange}) {
    root.insertAdjacentHTML('beforeend', '<div class="nora-cinema-viewport" inert aria-hidden="true"><div class="nora-cinema-media" hidden></div></div>' +
      '<div class="nora-cinema-tools" hidden><button type="button" data-projector>Проектор</button>' +
      '<button type="button" data-audio hidden>Включить звук</button></div>' +
      '<dialog class="nora-cinema" aria-label="Проектор кинотеатра"><header><h2>Проектор</h2>' +
      '<button type="button" data-close autofocus>Закрыть</button></header>' +
      '<p role="status" data-note></p>' +
      '<details hidden><summary>Выбрать видео</summary><form>' +
      '<label>Ссылка на YouTube или MP4<input name="url" type="url" placeholder="https://" maxlength="2048"></label>' +
      '<label>Видео из Telegram<select name="clip"><option value="">Выбери ролик</option></select></label>' +
      '<button type="button" data-clips>Обновить список</button>' +
      '<button type="submit">Начать сеанс</button></form></details>' +
      '<button type="button" data-retry hidden>Перезагрузить плеер</button>' +
      '<div class="nora-cinema-controls" hidden><button type="button" data-toggle>Пауза для всех</button>' +
      '<button type="button" data-back aria-label="Назад на 30 секунд">−30 с</button>' +
      '<button type="button" data-forward aria-label="Вперёд на 30 секунд">+30 с</button>' +
      '<input type="range" min="0" max="1" value="0" aria-label="Перемотка сеанса" disabled>' +
      '<button type="button" data-stop>Завершить</button></div></dialog>');
    const tools = root.querySelector('.nora-cinema-tools');
    const opener = tools.querySelector('[data-projector]');
    const audio = tools.querySelector('[data-audio]');
    const panel = root.querySelector('.nora-cinema');
    const close = panel.querySelector('[data-close]');
    const viewport = root.querySelector('.nora-cinema-viewport');
    const media = viewport.querySelector('.nora-cinema-media');
    const note = panel.querySelector('[data-note]');
    const retry = panel.querySelector('[data-retry]');
    const form = panel.querySelector('form');
    const picker = panel.querySelector('details');
    const controls = panel.querySelector('.nora-cinema-controls');
    const range = controls.querySelector('input');
    const toggle = controls.querySelector('[data-toggle]');
    const life = new AbortController();
    const on = (target, name, handler) => target.addEventListener(name, handler, {signal: life.signal});
    const {screen, seats, seatReach} = layout;
    const plane = new T.Matrix4();
    let homeRoom=null, homeOwner=false;
    function setScreen(surface){
      plane.makeScale(surface.width/surfaceWidth,-surface.height/surfaceHeight,1)
        .setPosition(surface.x-surface.width/2,surface.y+surface.height/2,surface.z);
      projectedWidth=0;
    }
    const transform = new T.Matrix4();
    const lastTransform = new T.Matrix4();
    let projectedWidth = 0, projectedHeight = 0;
    let active = false, seat = null, requestedSeat = null, occupied = [], revision = '?', show = null;
    let moderator = false, soundEnabled = false, autoplayBlocked = false, playerError = '', busy = false, seeking = false;
    let video = null, youtube = null, ready = false, version = 0, lastSync = 0, lastReply = 0, loadAt = 0;
    let pendingRevision = null, warned = false;

    function desired(now) {
      return show ? show.position + (show.playing ? Math.max(0, (clock(now) - show.changed) / 1000) : 0) : 0;
    }

    function request(params = {}) {
      const query = new URLSearchParams({session: sessionId() || '', ...(homeRoom?{room:homeRoom}:{}), ...params});
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
      projectedWidth = 0;
      range.disabled = true;
    }

    function render() {
      const connected = revision !== '?';
      const leading = !!show && (homeRoom ? homeOwner : show.host || moderator);
      picker.hidden = !connected || (homeRoom && !homeOwner) || !!show && !leading;
      controls.hidden = !connected || !leading;
      toggle.textContent = show?.playing ? 'Пауза для всех' : 'Продолжить для всех';
      retry.hidden = !playerError;
      audio.hidden = !show || !ready || !!playerError;
      const audioLabel = autoplayBlocked ? 'Включить видео' : soundEnabled ? 'Выключить звук' : 'Включить звук';
      audio.textContent = autoplayBlocked ? 'Пуск' : 'Звук';
      audio.setAttribute('aria-label', audioLabel);
      audio.setAttribute('aria-pressed', String(soundEnabled));
      if (playerError) note.textContent = playerError;
      else if (!connected) note.textContent = 'Подключаем проектор…';
      else if (!show) note.textContent = 'Экран свободен. Выбери видео для сеанса.';
      else if (!show.playing) note.textContent = 'Общая пауза.';
      else note.textContent = leading ? 'Ты управляешь сеансом.' : 'Идёт общий сеанс.';
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
        if (active && current === sessionId() && panel.open) note.textContent = error.message;
      }
    }

    async function command(action, fields = {}) {
      if (busy || !active || revision === '?' || pendingRevision === revision) return;
      busy = true;
      const session = sessionId();
      const sentRevision = revision;
      try {
        await api('nora-game/cinema', {session, revision, action, ...(homeRoom?{room:homeRoom}:{}), ...fields}, AbortSignal.timeout(7000));
        if (!active || session !== sessionId()) return;
        if (action === 'start') {
          picker.open = false;
          form.reset();
          panel.close();
        }
        if (revision === sentRevision) pendingRevision = sentRevision;
      } catch (error) {
        if (active && session === sessionId()) note.textContent = error.message;
      } finally {
        busy = false;
      }
    }

    function markReady() {
      ready = true;
      render();
      sync(performance.now(), true);
    }

    async function openPlayer() {
      clearPlayer();
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
          const params = new URLSearchParams({enablejsapi: '1', playsinline: '1', controls: '0', disablekb: '1', fs: '0', origin: location.origin});
          iframe.title = 'Плеер YouTube на экране зала';
          iframe.tabIndex = -1;
          iframe.allow = 'autoplay; encrypted-media';
          iframe.referrerPolicy = 'strict-origin-when-cross-origin';
          iframe.src = 'https://www.youtube.com/embed/' + source + '?' + params;
          media.replaceChildren(iframe);
          youtube = new YT.Player(iframe, {events: {
            onReady(event) {
              if (current !== version) return;
              if (!soundEnabled) event.target.mute();
              markReady();
            },
            onStateChange(event) {
              if (current !== version || event.data !== 1) return;
              if (autoplayBlocked) {
                autoplayBlocked = false;
                render();
              }
              if (!show?.playing || document.hidden) event.target.pauseVideo();
            },
            onAutoplayBlocked() {
              if (current !== version) return;
              if (soundEnabled) {
                soundEnabled = false;
                youtube.mute();
                if (show?.playing && !document.hidden) youtube.playVideo();
              } else autoplayBlocked = true;
              render();
            },
            onError() {
              if (current === version) fail('Ролик YouTube недоступен во встроенном плеере.');
            },
          }});
        } else {
          const url = kind === 'telegram' ? (await request({show: id})).url : source;
          if (current !== version) return;
          const element = document.createElement('video');
          video = element;
          video.playsInline = true;
          video.muted = !soundEnabled;
          video.preload = 'auto';
          video.addEventListener('loadedmetadata', () => {
            if (current === version) markReady();
          });
          video.addEventListener('error', () => {
            if (current === version) fail('Видео не загрузилось. Проверь формат MP4 и доступность файла.');
          });
          media.replaceChildren(video);
          video.src = url;
        }
      } catch (error) {
        if (current === version) fail(error.message);
      }
    }

    function playVideo() {
      const element = video;
      element.play().catch(error => {
        if (video !== element || error.name !== 'NotAllowedError') return;
        if (soundEnabled) {
          soundEnabled = false;
          element.muted = true;
          playVideo();
        } else autoplayBlocked = true;
        render();
      });
    }

    function pauseLocal() {
      if (video && !video.paused) video.pause();
      if (ready && youtube && [1, 3].includes(youtube.getPlayerState())) youtube.pauseVideo();
    }

    function sync(now, force = false) {
      if (!active || !show || now - lastReply > 8000 || document.hidden) {
        pauseLocal();
        return;
      }
      if (playerError) return;
      if (!ready) {
        if (now - loadAt > 21000) fail('Плеер не ответил. Можно попробовать ещё раз.');
        return;
      }
      if (!force && now - lastSync < 700) return;
      lastSync = now;
      const duration = video?.duration ?? youtube?.getDuration() ?? 0;
      const validDuration = Number.isFinite(duration) && duration > 0;
      const at = validDuration ? Math.min(duration, desired(now)) : desired(now);
      const ended = validDuration && at >= duration;
      if (range.disabled === validDuration) range.disabled = !validDuration;
      if (panel.open && validDuration && !seeking && document.activeElement !== range) {
        range.max = String(Math.ceil(duration));
        range.value = String(at);
      }
      if (ended && (homeRoom?homeOwner:show.host) && !warned) {
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
      const playerState = youtube?.getPlayerState();
      if (!autoplayBlocked && Math.abs(position - at) > tolerance) {
        if (video) video.currentTime = at;
        else youtube.seekTo(at, true);
      }
      if (playing && !autoplayBlocked) {
        if (video?.paused) playVideo();
        if (youtube && playerState !== 1) youtube.playVideo();
      } else if (!playing) pauseLocal();
    }

    // The 3D wall masks this native media layer, including chairs and avatars in front.
    // Only the camera changes its projection. Decoded frames never pass through JavaScript.
    function project(camera, width, height) {
      if (!active || media.hidden || !width || !height) return false;
      const showing = !playerError && (video ? video.readyState >= 2 : ready);
      if (!showing) return false;
      transform.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse).multiply(plane);
      const m = transform.elements;
      const previous = lastTransform.elements;
      if (width === projectedWidth && height === projectedHeight &&
          m.every((value, i) => Math.abs(value - previous[i]) < 0.000001)) return true;

      projectedWidth = width;
      projectedHeight = height;
      lastTransform.copy(transform);
      const css = [];
      for (const i of [0, 4, 8, 12]) {
        if (i === 8) css.push(0, 0, 1, 0);
        else css.push((m[i] + m[i + 3]) * width / 2, (m[i + 3] - m[i + 1]) * height / 2, 0, m[i + 3]);
      }
      media.style.transform = 'matrix3d(' + css.join(',') + ')';
      return true;
    }

    function receive(payload) {
      if (!active || !payload) return;
      lastReply = performance.now();
      occupied = payload.occupied ?? [];
      if (payload.requestedSeat === requestedSeat && seat !== payload.seat) {
        const previous = seat;
        seat = payload.seat;
        root.classList.toggle('nora-cinema-seated', seat !== null);
        onSeatChange(seats[previous], seats[seat]);
      }
      if (payload.requestedSeat === requestedSeat) requestedSeat = seat;
      if (!('show' in payload)) return;
      const changed = payload.show?.id !== show?.id;
      show = payload.show;
      revision = payload.revision;
      pendingRevision = null;
      warned = false;
      if (changed) {
        if (show) void openPlayer();
        else clearPlayer();
      }
      render();
      sync(lastReply, true);
    }

    function leave() {
      active = false;
      seat = requestedSeat = null;
      occupied = [];
      revision = '?';
      pendingRevision = null;
      show = null;
      lastReply = 0;
      moderator = false;
      soundEnabled = false;
      picker.open = false;
      form.reset();
      if (panel.open) panel.close();
      clearPlayer();
      tools.hidden = true;
      root.classList.remove('nora-cinema-room', 'nora-cinema-seated','nora-tv-room');
      homeRoom=null;homeOwner=false;opener.hidden=false;
    }

    function enter(room=null,surface=screen,owner=false) {
      homeRoom=room;homeOwner=owner;setScreen(surface);
      opener.hidden=!!room;
      panel.querySelector('h2').textContent=room?'Телевизор':'Проектор';
      panel.setAttribute('aria-label',room?'Домашний телевизор':'Проектор кинотеатра');
      active = true;
      tools.hidden = false;
      root.classList.add(room?'nora-tv-room':'nora-cinema-room');
      render();
    }

    on(opener, 'click', () => {
      reset();
      panel.showModal();
      close.focus({preventScroll:true});
      void clips();
    });
    on(close, 'click', () => panel.close());
    on(panel, 'close', () => {
      reset();
      if (active) opener.focus({preventScroll:true});
    });
    on(audio, 'click', () => {
      soundEnabled = autoplayBlocked || !soundEnabled;
      autoplayBlocked = false;
      if (video) {
        video.muted = !soundEnabled;
        if (show?.playing) playVideo();
      }
      if (ready && youtube) {
        if (soundEnabled) youtube.unMute();
        else youtube.mute();
        if (show?.playing) youtube.playVideo();
      }
      render();
    });
    on(retry, 'click', () => {if (show) void openPlayer();});
    on(panel.querySelector('[data-clips]'), 'click', clips);
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
      seat: () => seats[seat],
      requestSeat(index) {requestedSeat = index;},
      movementLocked: () => seat !== null || requestedSeat !== seat,
      nearbySeat(position, accepts = () => true) {
        let best = null, distance = seatReach;
        for (const [index, [x, z]] of seats.entries()) {
          const gap = Math.hypot(x - position.x, z - position.z);
          if (gap < distance && !occupied.includes(index) && accepts(index)) {
            best = index;
            distance = gap;
          }
        }
        return best;
      },
      panelOpen: () => panel.open,
      packet: () => ({cinema: revision, seat: requestedSeat}),
      openPanel:()=>opener.click(), enter, leave, receive, project, sync,
      dispose() {
        leave();
        life.abort();
        tools.remove();
        panel.remove();
        viewport.remove();
      },
    };
  }

  return {load, room, title, mount};
})();
