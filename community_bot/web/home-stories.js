'use strict';

window.NoraStories = (() => {
  const stories = {
    nora: {
      title: "Обновление Норы", label: "Смотреть историю обновления Норы",
      cover: '/intro/nora-update-20261120.jpg',
      poster: '/intro/nora-update-20261120-start.jpg', video: '/intro/nora-update-20261120.mp4',
    },
    dj: {
      title: "DJ Dedzytwo", label: "Смотреть историю DJ Dedzytwo",
      cover: '/intro/dedzytwo-story-cover-20261123.svg',
      poster: '/story/dedzytwo-poster.jpg', video: '/story/dedzytwo.mp4',
    },
    install: {
      title: "Нора на главном экране", label: "История: добавить Нору на экран телефона",
      cover: NoraHomeScreen.icon,
    },
  };
  const slides = [
    {story: 'nora'}, {story: 'dj'},
    {story: 'install', step: 0, seconds: 12}, {story: 'install', step: 1, seconds: 24},
  ];
  const dialog = document.querySelector('#home-story-viewer');
  const stage = dialog.querySelector('.home-story-stage');
  const shade = dialog.querySelector('.home-story-shade');
  const deck = dialog.querySelector('.home-story-deck');
  const heading = dialog.querySelector('#home-story-title');
  const avatar = dialog.querySelector('.home-story-avatar');
  const pauseButton = dialog.querySelector('.home-story-pause');
  const soundButton = dialog.querySelector('.home-story-sound');
  const closeButton = dialog.querySelector('.home-story-close');
  const progress = dialog.querySelector('.home-story-progress');
  const bars = slides.map(() => {
    const track = document.createElement('span');
    track.setAttribute('aria-hidden', 'true');
    return track.appendChild(document.createElement('i'));
  });
  const accessibleProgress = document.createElement('progress');
  accessibleProgress.className = 'sr-only';
  accessibleProgress.max = 1;
  progress.append(...bars.map(bar => bar.parentElement), accessibleProgress);
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const ease = 'cubic-bezier(.2,.72,.22,1)';
  stage.toggleAttribute('data-client-header', ['ios', 'android', 'android_x'].includes(tg?.platform));
  let current, opener, gesture, frame = 0, previousTick = 0;
  let paused = false, muted = false, closing = false;
  let windowMotion = [], slideMotion = [], outgoing;

  // Store views per Telegram account and per content version, not per cover slot.
  const viewKey = 'nora:home-story-views:v1:' + (tg?.initDataUnsafe?.user?.id ?? 'guest');
  const slideKey = entry => {
    const story = stories[entry.story];
    return JSON.stringify([entry.story, story.video || story.cover, story.poster || '', entry.step ?? null]);
  };
  const validKeys = new Set(slides.map(slideKey));
  const seen = new Set();
  try {
    const stored = JSON.parse(localStorage.getItem(viewKey) || '[]');
    if (Array.isArray(stored)) stored.filter(key => validKeys.has(key)).forEach(key => seen.add(key));
  } catch { /* Storage can be unavailable in a webview. */ }
  const viewedStyle = 'background:#77777f;box-shadow:none';
  function isViewed(id) {
    return slides.filter(entry => entry.story === id).every(entry => seen.has(slideKey(entry)));
  }
  function markViewed(index) {
    const entry = slides[index];
    const key = slideKey(entry);
    if (seen.has(key)) return;
    seen.add(key);
    try { localStorage.setItem(viewKey, JSON.stringify([...seen])); } catch {}
    if (isViewed(entry.story)) {
      for (const trigger of document.querySelectorAll('[data-home-story="' + entry.story + '"]')) {
        trigger.classList.add('is-viewed');
        trigger.style.background = '#77777f';
        trigger.style.boxShadow = 'none';
      }
    }
  }

  function triggers() {
    return '<div class="home-stories">' + Object.entries(stories).map(([id, story]) =>
      '<button type="button" class="home-story-trigger' + (isViewed(id) ? ' is-viewed' : '') +
      '" style="' + (isViewed(id) ? viewedStyle : '') + '" data-home-story="' + id +
      '" aria-label="' + NoraI18n.html(story.label) + '" aria-haspopup="dialog" aria-controls="home-story-viewer">' +
      '<img src="' + story.cover + '" alt="" width="52" height="52"></button>'
    ).join('') + NoraI18n.button() + '</div>';
  }

  function coverFor(story) {
    return document.querySelector('#app [data-home-story="' + story + '"]');
  }

  function paintProgress(ratio) {
    if (current.ratio === ratio) return;
    current.ratio = ratio;
    bars[current.index].style.transform = 'scaleX(' + ratio + ')';
    accessibleProgress.value = ratio;
  }

  function playbackAllowed() {
    return dialog.open && !closing && !document.hidden && !paused && !gesture;
  }

  function syncControls() {
    pauseButton.setAttribute('aria-pressed', String(paused));
    pauseButton.setAttribute('aria-label', NoraI18n.t(paused ? "Продолжить историю" : "Приостановить историю"));
    soundButton.setAttribute('aria-pressed', String(muted));
    soundButton.setAttribute('aria-label', NoraI18n.t(muted ? "Включить звук" : "Выключить звук"));
  }

  function duration(slide) {
    return slide.video ? slide.video.duration : slides[slide.index].seconds;
  }

  function tick(now) {
    frame = 0;
    if (!playbackAllowed() || current.failed) return;
    const total = duration(current);
    if (current.video) current.elapsed = current.video.currentTime;
    else if (previousTick) current.elapsed += (now - previousTick) / 1000;
    previousTick = now;
    if (Number.isFinite(total) && total > 0) paintProgress(Math.min(1, current.elapsed / total));
    if (!current.video && current.elapsed >= total) advance(1);
    else if (!current.video?.paused) frame = requestAnimationFrame(tick);
  }

  function stopPlayback() {
    cancelAnimationFrame(frame);
    frame = previousTick = 0;
    if (!current?.video) return;
    current.attempt++;
    current.video.pause();
  }

  async function play(slide) {
    const attempt = ++slide.attempt;
    try {
      await slide.video.play();
    } catch (error) {
      if (slide !== current || attempt !== slide.attempt || !playbackAllowed() || error.name === 'AbortError') return;
      if (error.name === 'NotAllowedError' && !muted) {
        muted = slide.video.muted = true;
        syncControls();
        await play(slide);
      } else {
        fail(slide);
      }
    }
  }

  function resumePlayback() {
    if (!playbackAllowed() || current.failed) return;
    if (!current.video) markViewed(current.index);
    if (current.video?.ended) {
      advance(1);
      return;
    }
    if (current.video?.paused) void play(current);
    if (!frame) frame = requestAnimationFrame(tick);
  }

  function setPaused(value) {
    paused = value;
    syncControls();
    if (paused) stopPlayback();
    else resumePlayback();
  }

  function fail(slide) {
    if (slide !== current || closing) return;
    slide.failed = true;
    slide.error.hidden = false;
    stopPlayback();
  }

  function mountVideo(slide, story) {
    const video = slide.video = document.createElement('video');
    video.playsInline = true;
    video.disablePictureInPicture = true;
    video.disableRemotePlayback = true;
    video.muted = muted;
    video.preload = 'auto';
    video.poster = story.poster;
    video.setAttribute('aria-label', NoraI18n.t(story.title));
    const error = slide.error = document.createElement('p');
    error.className = 'home-story-error';
    error.setAttribute('role', 'status');
    error.hidden = true;
    error.textContent = NoraI18n.t("Не удалось загрузить историю.");
    video.addEventListener('error', () => fail(slide));
    video.addEventListener('playing', () => {
      if (slide === current && playbackAllowed() && !slide.failed) markViewed(slide.index);
    });
    video.addEventListener('ended', () => {
      if (slide === current && playbackAllowed()) advance(1);
    });
    slide.card.append(video, error);
    video.src = story.video;
  }

  function mountArtistAction(slide) {
    const action = document.querySelector('#home-story-dj-action').content.firstElementChild.cloneNode(true);
    const switchAt = 4.35;
    let saving = false;
    let morphTimer;
    const isCurrent = () => slide === current && !closing;
    const label = text => action.setAttribute('aria-label', NoraI18n.t(text));
    label("Поставить лайк профилю @ourcreator");
    action.title = NoraI18n.t("Поставить лайк @ourcreator");
    function showChannel() {
      if (!isCurrent() || action.classList.contains('is-telegram')) return;
      action.classList.add('is-telegram');
      label(action.classList.contains('is-liked')
        ? "Открыть Telegram-канал артиста. Лайк поставлен" : "Открыть Telegram-канал артиста");
      action.title = NoraI18n.t("Перейти в Telegram-канал");
    }
    function showLike(delay) {
      if (!isCurrent()) return;
      action.classList.add('is-liked');
      if (action.classList.contains('is-telegram') || morphTimer) return;
      morphTimer = setTimeout(() => {
        morphTimer = null;
        showChannel();
      }, delay);
    }
    slide.dispose = () => clearTimeout(morphTimer);
    slide.video.addEventListener('timeupdate', () => {
      if (slide.video.currentTime >= switchAt && !saving && !morphTimer) showChannel();
    });
    action.addEventListener('click', async () => {
      if (!isCurrent() || saving) return;
      if (action.classList.contains('is-telegram')) {
        const url = 'https://t.me/thededzzyDJ';
        if (tg?.openTelegramLink) tg.openTelegramLink(url);
        else window.open(url, '_blank', 'noopener,noreferrer');
        return;
      }
      saving = action.disabled = true;
      action.classList.add('is-liked');
      try {
        const result = await api('story/dedzytwo/like', {});
        if (result.liked && isCurrent()) {
          tg?.HapticFeedback?.notificationOccurred?.('success');
          showLike(520);
        }
      } catch (error) {
        if (!isCurrent()) return;
        action.classList.remove('is-liked');
        toast(error.message);
        if (slide.video.currentTime >= switchAt) showChannel();
      } finally {
        saving = action.disabled = false;
      }
    });
    slide.card.append(action);
    api('story/dedzytwo/status').then(result => {
      if (result.liked && !saving) showLike(420);
    }).catch(() => { /* A failed status request does not block the like action. */ });
  }

  function removeSlide(slide) {
    if (!slide) return;
    slide.dispose?.();
    slide.card.remove();
    if (slide.video) {
      slide.video.removeAttribute('src');
      slide.video.load();
    }
  }

  function clearSlideMotion() {
    slideMotion.forEach(animation => animation.cancel());
    slideMotion = [];
    removeSlide(outgoing);
    outgoing = null;
  }

  function animateSlide(previous, direction, drag) {
    if (!previous) return;
    if (reducedMotion.matches) {
      removeSlide(previous);
      return;
    }
    outgoing = previous;
    const amount = Math.min(92, stage.clientWidth * .23);
    const shift = (x, rotation) => 'perspective(900px) translateX(' + x + 'px) rotateY(' + rotation + 'deg)';
    const timing = {duration: 280, easing: ease, fill: 'both'};
    slideMotion = [
      previous.card.animate([
        {transform: shift(drag, 0), opacity: 1},
        {transform: shift(-direction * amount, direction * 16), opacity: 0},
      ], timing),
      current.card.animate([
        {transform: shift(direction * amount + drag, -direction * 16), opacity: .2},
        {transform: shift(0, 0), opacity: 1},
      ], timing),
    ];
    const motion = slideMotion[1];
    motion.onfinish = () => { if (slideMotion[1] === motion) clearSlideMotion(); };
  }

  function show(index, drag = 0) {
    const entry = slides[index];
    const story = stories[entry.story];
    stopPlayback();
    clearSlideMotion();
    const previous = current;
    const moveFocus = previous?.card.contains(document.activeElement) ||
      (!story.video && document.activeElement === soundButton);
    if (previous) previous.card.inert = true;
    const card = document.createElement('div');
    card.className = 'home-story-card';
    current = {index, card, elapsed: 0, attempt: 0};
    const slide = current;
    if (story.video) {
      mountVideo(slide, story);
      if (entry.story === 'dj') mountArtistAction(slide);
    } else {
      if (slides[previous?.index]?.story !== 'install') NoraHomeScreen.reset();
      slide.dispose = NoraHomeScreen.mount(card, entry.step, () => advance(1), close, () => {
        if (slide === current && !closing) setPaused(true);
      });
    }
    deck.append(card);
    heading.textContent = NoraI18n.t(story.title);
    avatar.src = story.cover;
    soundButton.hidden = !story.video;
    bars.forEach((bar, i) => {
      bar.style.transform = 'scaleX(' + Number(i < index) + ')';
      bar.parentElement.classList.toggle('is-current', i === index);
    });
    accessibleProgress.setAttribute('aria-label', NoraI18n.t("Прогресс истории") + ' (' + (index + 1) + '/' + slides.length + ')');
    paintProgress(0);
    if (moveFocus) closeButton.focus({preventScroll: true});
    animateSlide(previous, previous && Math.sign(index - previous.index || -1), drag);
    resumePlayback();
  }

  function advance(direction, drag = 0) {
    if (closing || !current) return;
    const index = current.index + direction;
    if (index >= slides.length) close();
    else show(Math.max(0, index), drag);
  }

  function swipe(direction, drag) {
    const id = slides[current.index].story;
    const groups = Object.keys(stories);
    const neighbor = groups[groups.indexOf(id) + direction];
    if (neighbor) show(slides.findIndex(slide => slide.story === neighbor), drag);
    else if (direction > 0) close();
    else settleDrag();
  }

  const fullFrame = {transform: 'none', clipPath: 'inset(0px round 0px)', opacity: 1};

  function thumbnailFrame(button) {
    const target = button?.getBoundingClientRect();
    const bounds = stage.getBoundingClientRect();
    if (!target?.width || target.bottom <= 0 || target.top >= innerHeight || !bounds.width || !bounds.height) {
      return {...fullFrame, transform: 'translateY(18px) scale(.96)', opacity: 0};
    }
    const size = Math.min(bounds.width, bounds.height);
    const x = target.left + target.width / 2 - (bounds.left + bounds.width / 2);
    const y = target.top + target.height / 2 - (bounds.top + bounds.height / 2);
    const insetY = (bounds.height - size) / 2;
    const insetX = (bounds.width - size) / 2;
    return {
      transform: 'translate(' + x + 'px,' + y + 'px) scale(' + target.width / size + ')',
      clipPath: 'inset(' + insetY + 'px ' + insetX + 'px round ' + size / 2 + 'px)',
      opacity: .65,
    };
  }

  function clearWindowMotion() {
    windowMotion.forEach(animation => animation.cancel());
    windowMotion = [];
  }

  function open(index, trigger) {
    if (dialog.open || index < 0) return;
    opener = trigger;
    muted = paused = false;
    show(index);
    syncControls();
    dialog.showModal();
    window.NoraShop?.syncBack();
    if (!reducedMotion.matches) {
      const timing = {duration: 290, easing: ease};
      windowMotion = [
        stage.animate([thumbnailFrame(trigger), fullFrame], timing),
        shade.animate([{opacity: 0}, {opacity: 1}], timing),
      ];
    }
    resumePlayback();
  }

  function close() {
    if (!dialog.open || closing) return;
    closing = true;
    clearGesture();
    stopPlayback();
    const visible = getComputedStyle(stage);
    const from = {transform: visible.transform, clipPath: visible.clipPath === 'none' ? fullFrame.clipPath : visible.clipPath, opacity: visible.opacity};
    const shadeOpacity = getComputedStyle(shade).opacity;
    clearWindowMotion();
    clearSlideMotion();
    stage.style.transform = deck.style.transform = shade.style.opacity = '';
    if (reducedMotion.matches) {
      finishClose();
      return;
    }
    const cover = coverFor(slides[current.index].story) || opener;
    const timing = {duration: 240, easing: 'cubic-bezier(.42,0,.3,1)', fill: 'forwards'};
    windowMotion = [
      stage.animate([from, {...thumbnailFrame(cover), opacity: 0}], timing),
      shade.animate([{opacity: shadeOpacity}, {opacity: 0}], timing),
    ];
    windowMotion[0].onfinish = finishClose;
  }

  function finishClose() {
    const fallback = current && coverFor(slides[current.index].story);
    const returnFocus = opener?.isConnected ? opener : fallback;
    dialog.close();
    clearWindowMotion();
    removeSlide(current);
    current = opener = null;
    closing = false;
    window.NoraShop?.syncBack();
    returnFocus?.focus({preventScroll: true});
  }

  function clearGesture() {
    if (!gesture) return;
    clearTimeout(gesture.timer);
    gesture = null;
    stage.classList.remove('is-holding');
  }

  function settleDrag() {
    const timing = {duration: 180, easing: ease};
    for (const element of [stage, deck, shade]) {
      const property = element === shade ? 'opacity' : 'transform';
      if (!element.style[property]) continue;
      const from = element.style[property];
      element.style[property] = '';
      if (!reducedMotion.matches) element.animate([{[property]: from}, {[property]: element === shade ? 1 : 'none'}], timing);
    }
    resumePlayback();
  }

  stage.addEventListener('pointerdown', event => {
    if (gesture || closing || !event.isPrimary || event.button !== 0 || event.target.closest('button')) return;
    stage.setPointerCapture(event.pointerId);
    stopPlayback();
    const press = gesture = {
      id: event.pointerId, x: event.clientX, y: event.clientY, time: performance.now(),
      elapsed: current.video?.currentTime ?? current.elapsed, drag: 0,
      scrollable: Boolean(event.target.closest('[data-story-scroll]')),
    };
    press.timer = setTimeout(() => {
      press.holding = true;
      stage.classList.add('is-holding');
    }, 240);
  });

  stage.addEventListener('pointermove', event => {
    const press = gesture;
    if (press?.id !== event.pointerId) return;
    const dx = event.clientX - press.x;
    const dy = event.clientY - press.y;
    const x = Math.abs(dx);
    const y = Math.abs(dy);
    if (press.holding) {
      const total = duration(current);
      if ((x < 8 && !press.scrubbing) || !(total > 0 && Number.isFinite(total))) return;
      press.scrubbing = true;
      current.elapsed = Math.max(0, Math.min(Math.max(0, total - .05), press.elapsed + dx / stage.clientWidth * total));
      if (current.video) current.video.currentTime = current.elapsed;
      paintProgress(current.elapsed / total);
      return;
    }
    if (!press.axis && Math.max(x, y) >= 10) {
      clearTimeout(press.timer);
      press.axis = x > y ? 'x' : 'y';
    }
    if (reducedMotion.matches) return;
    if (press.axis === 'x') {
      press.drag = dx * .42;
      deck.style.transform = 'translateX(' + press.drag + 'px)';
    } else if (!press.scrollable && press.axis === 'y' && dy > 0) {
      const offset = dy * .66;
      stage.style.transform = 'translateY(' + offset + 'px) scale(' + Math.max(.86, 1 - offset / 1500) + ')';
      shade.style.opacity = String(Math.max(.28, 1 - offset / 420));
    } else if (press.axis === 'y') {
      stage.style.transform = shade.style.opacity = '';
    }
  });

  function release(event) {
    const press = gesture;
    if (press?.id !== event.pointerId) return;
    clearGesture();
    if (event.type !== 'pointerup' || press.holding) {
      settleDrag();
      return;
    }
    const dx = event.clientX - press.x;
    const dy = event.clientY - press.y;
    const quick = performance.now() - press.time < 220;
    if (press.axis === 'x' && Math.abs(dx) >= (quick ? 36 : 62)) {
      deck.style.transform = '';
      swipe(dx < 0 ? 1 : -1, press.drag);
    } else if (!press.scrollable && press.axis === 'y' && dy >= (quick ? 48 : 80)) {
      close();
    } else if (!press.axis && Math.max(Math.abs(dx), Math.abs(dy)) < 10) {
      const bounds = stage.getBoundingClientRect();
      advance(event.clientX - bounds.left < bounds.width * .33 ? -1 : 1);
    } else {
      settleDrag();
    }
  }

  // The viewer owns drags on the media surface. Keep native scrolling
  // available in the shortcut instructions when their content overflows.
  stage.addEventListener('touchmove', event => {
    if (gesture && (!gesture.scrollable || gesture.holding || gesture.axis === 'x') && event.cancelable) {
      event.preventDefault();
    }
  }, {passive: false});

  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) stage.addEventListener(type, release);
  stage.addEventListener('contextmenu', event => {
    if (!event.target.closest('button')) event.preventDefault();
  });
  closeButton.addEventListener('click', close);
  shade.addEventListener('click', close);
  pauseButton.addEventListener('click', () => setPaused(!paused));
  soundButton.addEventListener('click', () => {
    if (closing || !current.video) return;
    muted = current.video.muted = !muted;
    syncControls();
  });
  dialog.addEventListener('cancel', event => {
    event.preventDefault();
    close();
  });
  dialog.addEventListener('keydown', event => {
    if (closing || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      advance(event.key === 'ArrowLeft' ? -1 : 1);
    } else if (event.key.toLowerCase() === 'k') {
      event.preventDefault();
      setPaused(!paused);
    }
  });
  for (const button of stage.querySelectorAll('[data-story-step]')) {
    button.addEventListener('click', () => advance(Number(button.dataset.storyStep)));
  }
  document.addEventListener('visibilitychange', () => {
    if (!dialog.open || closing) return;
    if (document.hidden) {
      clearGesture();
      settleDrag();
      stopPlayback();
    } else resumePlayback();
  });
  document.addEventListener('click', event => {
    const trigger = event.target.closest('#app [data-home-story]');
    if (trigger) open(slides.findIndex(slide => slide.story === trigger.dataset.homeStory), trigger);
  });

  return {
    triggers, isOpen: () => dialog.open,
    openInstall: () => open(slides.findIndex(slide => slide.story === 'install'), coverFor('install')),
    back() {
      if (!dialog.open) return false;
      close();
      return true;
    },
  };
})();
