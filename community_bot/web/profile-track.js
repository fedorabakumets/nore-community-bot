'use strict';
window.NoraProfileTrack = (() => {
  let active = null;

  function clock(seconds) {
    const total = Math.floor(Number(seconds) || 0);
    return Math.floor(total / 60) + ':' + String(total % 60).padStart(2, '0');
  }

  function html(track, endpoint) {
    if (!track) return '';
    const src = endpoint + '?v=' + encodeURIComponent(track.revision);
    return `<section class="profile-track" data-track-src="${esc(src)}" aria-label="Трек профиля">
      <button type="button" class="profile-track-toggle" data-track-toggle aria-label="Включить трек"></button>
      <div class="profile-track-copy">
        <strong title="${esc(track.title)}">${esc(track.title)}</strong>
        ${track.artist ? `<small>${esc(track.artist)}</small>` : ''}
      </div>
      <div class="profile-track-timeline">
        <span data-track-time>0:00</span>
        <input type="range" min="0" max="1" step="0.001" value="0" data-track-seek aria-label="Позиция в треке" disabled>
        <span data-track-duration>${clock(track.duration)}</span>
      </div>
    </section>`;
  }

  function paint(state) {
    const { audio, element, loading } = state;
    const playing = !audio.paused && !audio.ended;
    const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
    const seek = element.querySelector('[data-track-seek]');
    const current = audio.currentTime || 0;
    seek.value = duration ? current / duration : 0;
    seek.disabled = !duration;
    seek.style.setProperty('--track-progress', (Number(seek.value) * 100) + '%');
    seek.setAttribute('aria-valuetext', clock(current));
    element.querySelector('[data-track-time]').textContent = clock(current);
    if (duration) element.querySelector('[data-track-duration]').textContent = clock(duration);
    element.dataset.playing = String(playing);
    element.dataset.loading = String(loading);
    const play = element.querySelector('[data-track-toggle]');
    play.disabled = loading;
    play.setAttribute('aria-label', loading ? 'Загружаем трек' : playing ? 'Поставить на паузу' : 'Включить трек');
  }

  function stop() {
    const state = active;
    if (!state) return;
    active = null;
    state.controller.abort();
    state.audio.pause();
    state.audio.removeAttribute('src');
    state.audio.load();
    state.loading = false;
    paint(state);
    if (state.url) URL.revokeObjectURL(state.url);
  }

  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-track-toggle]');
    if (!button) return;
    const element = button.closest('[data-track-src]');
    if (active?.element !== element) {
      stop();
      const audio = new Audio();
      active = { audio, element, src: element.dataset.trackSrc, controller: new AbortController(), loading: true };
      const state = active;
      for (const name of ['loadedmetadata', 'timeupdate', 'play', 'pause', 'ended']) {
        audio.addEventListener(name, () => { if (active === state) paint(state); });
      }
      audio.addEventListener('error', () => {
        if (active === state) {
          stop();
          toast('Не удалось воспроизвести трек');
        }
      });
      paint(state);
      try {
        const response = await fetch(state.src, {
          headers: { Authorization: 'tma ' + auth }, signal: state.controller.signal,
        });
        if (!response.ok) throw new Error();
        const blob = await response.blob();
        if (active !== state) return;
        state.url = URL.createObjectURL(blob);
        audio.src = state.url;
      } catch {
        if (active === state) {
          stop();
          toast('Трек сейчас недоступен');
        }
        return;
      }
      state.loading = false;
      paint(state);
    }
    const state = active;
    if (!state || state.loading) return;
    if (!state.audio.paused) {
      state.audio.pause();
      return;
    }
    try {
      await state.audio.play();
    } catch (error) {
      if (active !== state) return;
      if (error.name === 'NotAllowedError') toast('Нажми «Включить трек» ещё раз');
      else {
        stop();
        toast('Не удалось воспроизвести трек');
      }
    }
  });

  document.addEventListener('input', event => {
    const seek = event.target;
    if (!seek.matches('[data-track-seek]') || active?.element !== seek.closest('[data-track-src]')) return;
    const { audio } = active;
    if (Number.isFinite(audio.duration)) {
      audio.currentTime = Number(seek.value) * audio.duration;
      paint(active);
    }
  });

  // The cabinet refreshes its markup periodically. Keep playback if the same track is still on screen.
  const observer = new MutationObserver(() => {
    if (!active || active.element.isConnected) return;
    const replacement = Array.from(document.querySelectorAll('[data-track-src]'))
      .find(element => element.dataset.trackSrc === active.src && !element.closest('dialog:not([open])'));
    if (!replacement) stop();
    else {
      active.element = replacement;
      paint(active);
    }
  });
  for (const id of ['app', 'sheet-content']) {
    observer.observe(document.getElementById(id), { childList: true, subtree: true });
  }
  document.addEventListener('close', event => {
    if (active && event.target.contains(active.element)) stop();
  }, true);
  window.addEventListener('pagehide', stop);
  return { html };
})();
