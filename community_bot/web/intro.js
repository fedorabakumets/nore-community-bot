'use strict';
// One opening sequence per document. API loading and authentication continue underneath.
window.NoraIntro = (() => {
  const root = document.getElementById('nora-intro');
  const video = document.getElementById('nora-intro-video');
  const skip = document.getElementById('nora-intro-skip');
  const app = document.getElementById('app');
  const nav = document.getElementById('nav');
  const telegram = window.Telegram?.WebApp;
  let finished = false, deadline = null, showSkip = null;
  function chrome(color) {
    try {
      telegram?.setHeaderColor?.(color);
      telegram?.setBackgroundColor?.(color);
      if (telegram?.isVersionAtLeast?.('7.10')) telegram.setBottomBarColor?.(color);
    } catch { /* Older Telegram clients can keep their standard chrome. */ }
  }
  function finish(immediate = false) {
    if (finished) return;
    finished = true;
    clearTimeout(deadline);
    clearTimeout(showSkip);
    video.pause();
    video.removeAttribute('src');
    video.load();
    chrome('#101011');
    const remove = () => {
      root.remove();
      app.removeAttribute('inert');
      app.removeAttribute('aria-hidden');
      nav.removeAttribute('inert');
      nav.removeAttribute('aria-hidden');
      document.body.classList.remove('intro-playing');
    };
    if (immediate) remove();
    else {
      root.classList.add('intro-leaving');
      setTimeout(remove, 180);
    }
  }
  skip.addEventListener('click', () => finish());
  video.addEventListener('ended', () => finish(), {once:true});
  video.addEventListener('error', () => finish(true), {once:true});
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) finish(true);
  });
  if (!telegram?.initData || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    finish(true);
  } else {
    // Hard stop covers stalled downloads and WebViews that never dispatch a media error.
    deadline = setTimeout(() => finish(true), 8000);
    showSkip = setTimeout(() => { skip.hidden = false; }, 900);
    requestAnimationFrame(() => { if (!finished) chrome('#000000'); });
    video.muted = true;
    const playback = video.play();
    playback?.catch(() => finish(true));
  }
  return {finish};
})();
