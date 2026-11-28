'use strict';

window.NoraMusicWave = (() => {
  const genres = [
    ['pop', 'Поп', 342, 3], ['hiphop', 'Хип-хоп', 28, 5],
    ['house', 'Хаус', 183, 4], ['electronic', 'Электроника', 248, 6],
    ['rock', 'Рок', 8, 5], ['indie', 'Инди', 155, 3],
    ['rnb', 'R&B', 286, 4], ['chill', 'Чилл', 204, 2],
  ];
  const charts = [['day', 'Сутки', 40], ['week', 'Неделя', 13], ['all', 'Всё время', 318]];
  const featured = ['dedzytwo', 'The Weeknd', 'Billie Eilish', 'Daft Punk', 'Cream Soda'];
  const personal = {key:'personal', title:'Для тебя', hue:282, lobes:3};
  const stationKey = name => name.toLowerCase();
  const makeArtist = name => {
    const key = stationKey(name);
    let hash = 0;
    for (const letter of key) hash = (Math.imul(hash, 31) + letter.codePointAt(0)) >>> 0;
    return {key:'artist:' + key, artist:name, title:name,
      hue:key === 'dedzytwo' ? 351 : hash % 360, lobes:3 + hash % 4};
  };

  function create(root, {icon, select, back, toggle, next}) {
    const {t, html} = NoraI18n;
    root.innerHTML = `
      <header class="music-wave-header">
        <button type="button" data-wave-back aria-label="${html('Назад')}">${icon('arrow')}</button>
        <h2 tabindex="-1">${html('Моя волна')}</h2>
      </header>
      <div class="music-wave-stage">
        <div class="music-wave-orbit" aria-hidden="true"></div>
        <div class="music-wave-orb" aria-hidden="true"><div class="music-wave-fluid"></div></div>
        <button type="button" class="music-wave-play" data-wave-play aria-label="${html('Воспроизвести')}">
          ${icon('play')}${icon('pause')}${icon('loading', 'music-loading')}
        </button>
      </div>
      <div class="music-wave-meta">
        <div><strong data-wave-title></strong><small data-wave-artist></small>
          <p class="music-wave-status" role="status" hidden></p></div>
        <button type="button" data-wave-next aria-label="${html('Следующий трек')}" disabled>${icon('next')}</button>
      </div>
      <div class="music-wave-picker">
        <div class="music-wave-tabs" role="group" aria-label="${html('Настроить волну')}">
          <button type="button" data-wave-personal>${html('Для тебя')}</button>
          <button type="button" data-wave-tab="genres">${html('Жанры')}</button>
          <button type="button" data-wave-tab="charts">${html('Чарты')}</button>
          <button type="button" data-wave-tab="artists">${html('Исполнители')}</button>
        </div>
        <div class="music-wave-options" data-wave-options></div>
        <form class="music-wave-artist-search" hidden>
          <input type="search" minlength="2" maxlength="120" required aria-label="${html('Имя исполнителя')}"
            placeholder="${html('Имя исполнителя')}">
          <button type="submit" aria-label="${html('Найти')}">${icon('search')}</button>
        </form>
      </div>`;

    const orb = root.querySelector('.music-wave-orb');
    const fluid = orb.firstElementChild;
    const title = root.querySelector('[data-wave-title]');
    const byline = root.querySelector('[data-wave-artist]');
    const play = root.querySelector('[data-wave-play]');
    const advance = root.querySelector('[data-wave-next]');
    const status = root.querySelector('.music-wave-status');
    const options = root.querySelector('[data-wave-options]');
    const form = root.querySelector('form');
    const input = form.querySelector('input');
    const motion = matchMedia('(prefers-reduced-motion: reduce)');
    let station = personal, tab = 'genres', artists = featured, choices = [];
    let cover = '', texture = null, pendingTexture = null, frame = 0, last = 0, elapsed = 0, energy = 0;
    let lobes = personal.lobes, targetHue = personal.hue;
    let state = null;

    function paintChoices() {
      const focused = options.contains(document.activeElement)
        ? choices[Number(document.activeElement.dataset.waveChoice)]?.key : null;
      choices = tab === 'genres' ? genres.map(([genre, name, hue, lobes]) =>
        ({key:'genre:' + genre, genre, title:name, hue, lobes})) :
        tab === 'charts' ? charts.map(([period, name, hue]) =>
          ({key:'chart:' + period, period, title:name, display:t('Топ Норы') + ' · ' + t(name), hue, lobes:4})) :
          artists.map(makeArtist);
      options.innerHTML = choices.map(({key, title, artist, hue}, index) =>
        '<button type="button" data-wave-choice="' + index + '" aria-pressed="' + (key === station.key) + '">' +
        '<i aria-hidden="true" style="--wave-choice-hue:' + hue + '"></i>' + (artist ? escapeText(title) : html(title)) +
        '</button>').join('');
      if (focused) options.children[choices.findIndex(choice => choice.key === focused)]?.focus();
      for (const button of root.querySelectorAll('[data-wave-tab]')) {
        button.setAttribute('aria-pressed', String(button.dataset.waveTab === tab));
      }
      root.querySelector('[data-wave-personal]').setAttribute('aria-pressed', String(station.key === personal.key));
      options.setAttribute('aria-label', t(tab === 'charts' ? 'Топ Норы' : tab === 'genres' ? 'Жанры' : 'Исполнители'));
      form.hidden = tab !== 'artists';
    }

    function escapeText(value) {
      const span = document.createElement('span');
      span.textContent = value;
      return span.innerHTML;
    }

    function setArtists(names) {
      const entries = ['dedzytwo', ...(station.artist ? [station.artist] : []), ...names, ...featured];
      const unique = new Map();
      for (const name of entries) {
        const key = stationKey(name);
        if (!unique.has(key)) unique.set(key, name);
      }
      const next = [...unique.values()].slice(0, 10);
      if (next.join('\n') === artists.join('\n')) return;
      artists = next;
      if (tab === 'artists') paintChoices();
    }

    function setStation(value) {
      station = value;
      // Take the shorter route around the hue wheel on station changes.
      targetHue += ((value.hue - targetHue) % 360 + 540) % 360 - 180;
      root.style.setProperty('--wave-hue', targetHue);
      if (!frame) {
        lobes = value.lobes;
        orb.style.setProperty('--wave-shape', shape(elapsed, 0));
      }
      for (const [index, button] of Array.from(options.children).entries()) {
        button.setAttribute('aria-pressed', String(choices[index].key === value.key));
      }
      root.querySelector('[data-wave-personal]').setAttribute('aria-pressed', String(station.key === personal.key));
    }

    function swapTexture(image) {
      for (const old of [...fluid.children]) {
        if (old !== texture) old.remove();
      }
      if (texture) {
        const previous = texture;
        previous.classList.add('music-wave-cover-out');
        previous.addEventListener('animationend', () => previous.remove(), {once:true});
        if (motion.matches) previous.remove();
      }
      texture = image;
      if (image) fluid.append(image);
    }

    function setCover(url) {
      if (cover === url) return;
      cover = url;
      pendingTexture = null;
      if (!url) { swapTexture(null); return; }
      const image = new Image();
      image.alt = '';
      image.referrerPolicy = 'no-referrer';
      image.decoding = 'async';
      image.addEventListener('load', () => {
        if (pendingTexture !== image) return;
        pendingTexture = null;
        swapTexture(image);
      }, {once:true});
      image.addEventListener('error', () => {
        if (pendingTexture !== image) return;
        pendingTexture = null;
        swapTexture(null);
      }, {once:true});
      pendingTexture = image;
      image.src = url;
    }

    const visible = () => !root.hidden && root.isConnected && root.closest('dialog[open]') && !document.hidden;
    const playing = () => Boolean(state && !state.audio.paused && !state.audio.ended && !state.loading);
    function shape(time, pulse) {
      const offset = phase => 50 + (3.4 + 4.3 * pulse) * Math.sin(time + phase * lobes * .63) +
        2.2 * Math.cos(time * .52 - phase * 1.39);
      const [top, bottom, left, right] = [0, 1, 2, 3].map(offset);
      const percentages = (...values) => values.map(value => value.toFixed(1) + '%').join(' ');
      // Opposing radii meet at the tangent, keeping all sides curved as they move.
      return percentages(top, 100 - top, bottom, 100 - bottom) + ' / ' +
        percentages(left, right, 100 - right, 100 - left);
    }

    function draw(now) {
      frame = 0;
      if (!visible() || motion.matches || !playing()) { suspend(); return; }
      frame = requestAnimationFrame(draw);
      const delta = now - last;
      if (delta < 31) return;
      const seconds = Math.min(64, delta) / 1000;
      last = now;
      lobes += (station.lobes - lobes) * (1 - Math.exp(-seconds * 3));
      const index = Math.floor(state.audio.currentTime * 40);
      const drive = (state.beats?.[index] || 0) * .64 + (state.envelope?.[index] || 0) * .36;
      energy += (drive - energy) * (1 - Math.exp(-seconds * (drive > energy ? 17 : 5)));
      elapsed += seconds * (.65 + lobes * .09 + energy * .15);
      orb.style.setProperty('--wave-shape', shape(elapsed, energy));
      orb.style.transform = 'scale(' + (1 + .052 * energy).toFixed(3) + ')';
    }

    function suspend() {
      cancelAnimationFrame(frame);
      frame = 0;
      energy = 0;
      delete root.dataset.waveMoving;
      orb.style.setProperty('--wave-shape', shape(elapsed, 0));
      orb.style.removeProperty('transform');
    }

    function sync(current, {loading = false, canAdvance = false, cover = '', message = ''} = {}) {
      state = current;
      const busy = loading || Boolean(current?.loading);
      const track = current?.track;
      const text = track?.title || (station.artist ? station.title : station.display || t(station.title));
      const artist = track?.artist || '';
      if (title.textContent !== text || byline.textContent !== artist) {
        title.textContent = text;
        byline.textContent = artist;
        if (visible() && !motion.matches) title.parentElement.animate?.([
          {opacity:.55, transform:'translateY(3px)'}, {opacity:1, transform:'translateY(0)'}
        ], {duration:260, easing:'ease-out'});
      }
      byline.hidden = Boolean(message);
      status.hidden = !message;
      const localized = t(message);
      if (status.textContent !== localized) status.textContent = localized;
      if (!busy || cover) setCover(cover);
      const playState = busy ? 'loading' : playing() ? 'playing' : 'idle';
      play.dataset.wavePlayState = playState;
      play.disabled = busy;
      play.setAttribute('aria-label', t(busy ? 'Загружаем трек' : playing() ? 'Пауза' : 'Воспроизвести'));
      advance.disabled = loading || !canAdvance;
      if (visible() && playing() && !motion.matches) {
        root.dataset.waveMoving = '';
        if (!frame) { last = performance.now(); frame = requestAnimationFrame(draw); }
      } else if (frame) suspend();
    }

    root.addEventListener('click', event => {
      const button = event.target.closest('button');
      if (!button) return;
      if (button.hasAttribute('data-wave-back')) { back(); return; }
      if (button.hasAttribute('data-wave-play')) { toggle(); return; }
      if (button.hasAttribute('data-wave-next')) { next(); return; }
      if (button.hasAttribute('data-wave-personal')) { select(personal); return; }
      if (button.dataset.waveTab && tab !== button.dataset.waveTab) {
        tab = button.dataset.waveTab;
        paintChoices();
        if (!motion.matches) options.animate?.([
          {opacity:.35, transform:'translateY(4px)'}, {opacity:1, transform:'translateY(0)'}
        ], {duration:245, easing:'cubic-bezier(.2,.65,.3,1)'});
      }
      const choice = choices[Number(button.dataset.waveChoice)];
      if (choice) select(choice);
    });
    form.addEventListener('submit', event => {
      event.preventDefault();
      const name = input.value.trim().replace(/\s+/g, ' ');
      if (name.length < 2) return;
      input.blur();
      select(makeArtist(name));
    });
    paintChoices();
    return {setStation, setArtists, sync, suspend};
  }

  return {create, personal};
})();
