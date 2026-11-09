'use strict';
// Shared vector contours keep the face stationary while the three solid backs move.
window.NoraLogo = (() => {
  const outline = 'M123 512 L166 355 Q177 311 217 311 L233 311 L364 311 L376 311 Q417 314 407 355 L398 384 C425 331 478 301 542 301 C608 301 653 340 675 399 L688 351 Q700 312 737 312 L822 312 Q883 312 891 366 Q894 392 882 423 L947 348 Q970 311 1004 311 L1038 311 Q1072 311 1075 351 L1088 516 Q1095 570 1045 570 L1030 570 Q991 570 977 546 Q961 570 926 570 L873 570 Q826 570 815 540 Q803 570 765 570 L701 570 Q662 570 646 546 Q626 570 585 570 L473 570 Q421 570 399 538 Q387 570 347 570 L310 570 Q275 570 266 546 Q252 570 214 570 L164 570 Q115 570 123 512 Z';
  const letters = '<path fill="#fff3e2" d="M123 512 L166 355 Q177 311 217 311 L233 311 Q274 313 264 355 L256 385 Q254 391 261 391 L298 391 Q304 391 306 384 L315 351 Q325 311 364 311 L376 311 Q417 314 407 355 L379 511 Q372 559 335 559 L310 559 Q270 559 279 519 L287 478 Q289 468 279 468 L247 468 Q239 468 237 477 L227 518 Q217 559 180 559 L160 559 Q115 559 123 512 Z"/>'
    + '<path fill="#ff0750" d="M456 559 C411 539 385 502 388 451 C392 370 455 301 542 301 C621 301 679 364 678 438 C678 491 647 536 592 559 C613 530 616 492 607 463 C598 429 574 407 545 406 C513 404 482 423 462 452 C439 485 441 524 456 559 Z"/>'
    + '<path fill="#fff3e2" fill-rule="evenodd" d="M658 529 L688 351 Q700 312 737 312 L822 312 Q883 312 891 366 C898 433 860 486 796 486 L770 486 Q763 486 762 492 L754 533 Q746 559 718 559 L694 559 Q664 559 658 529 Z M779 379 Q772 379 770 387 L765 410 Q762 419 770 419 L786 419 Q808 419 810 395 Q812 379 796 379 Z"/>'
    + '<path fill="#fff3e2" fill-rule="evenodd" d="M839 524 L947 348 Q970 311 1004 311 L1038 311 Q1072 311 1075 351 L1088 516 Q1091 557 1055 559 L1030 559 Q1001 559 1000 521 Q1000 516 995 516 L944 516 Q939 516 937 521 L925 544 Q916 559 896 559 L871 559 Q830 559 839 524 Z M966 440 Q962 450 973 450 L998 450 Q1005 450 1004 442 L1001 400 Q1001 393 996 393 Q990 393 987 399 Z"/>';
  function markup(home = false) {
    return `<svg class="nora-logo${home ? ' nora-logo-home home-wordmark' : ''}" viewBox="100 280 1100 450" role="img" aria-label="Нора" xmlns="http://www.w3.org/2000/svg"><g stroke="#050407" stroke-width="12" stroke-linejoin="round"><path class="nora-logo-layer nora-logo-cyan" fill="#00c8ed" d="${outline}"/><path class="nora-logo-layer nora-logo-pink" fill="#ff09ae" d="${outline}"/><path class="nora-logo-layer nora-logo-yellow" fill="#ffd500" d="${outline}"/><path fill="#050407" d="${outline}"/></g><path fill="#050407" d="M820 300 H990 L855 495 H790 Z"/><g class="nora-logo-face" stroke="#050407" stroke-width="20" stroke-linejoin="round" paint-order="stroke fill">${letters}</g></svg>`;
  }
  function impact(style) {
    if (document.hidden) return;
    const telegram = window.Telegram?.WebApp;
    try {
      if (telegram?.isVersionAtLeast?.('6.1')) telegram.HapticFeedback?.impactOccurred(style);
    } catch { /* Haptics are optional on older clients. */ }
  }
  return {markup, impact};
})();

// API loading continues behind the fixed face; the final layer reveals the ready screen.
window.NoraIntro = (() => {
  const root = document.getElementById('nora-intro');
  const app = document.getElementById('app');
  const nav = document.getElementById('nav');
  const telegram = window.Telegram?.WebApp;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let finished = false, started = false, deadline;
  root.insertAdjacentHTML('afterbegin', NoraLogo.markup());
  function chrome(color) {
    try {
      telegram?.setHeaderColor?.(color);
      telegram?.setBackgroundColor?.(color);
      if (telegram?.isVersionAtLeast?.('7.10')) telegram.setBottomBarColor?.(color);
    } catch { /* Older clients can keep their standard chrome. */ }
  }
  function finish(immediate = false) {
    if (finished) return;
    finished = true;
    clearTimeout(deadline);
    document.removeEventListener('visibilitychange', onVisibility);
    reduced.removeEventListener?.('change', onMotion);
    chrome('#111013');
    app.classList.add('app-enter');
    const remove = () => {
      root.remove();
      for (const element of [app, nav]) {
        element.removeAttribute('inert');
        element.removeAttribute('aria-hidden');
      }
      document.body.classList.remove('intro-playing');
    };
    if (immediate) remove();
    else {
      root.classList.add('intro-leaving');
      setTimeout(remove, 180);
    }
  }
  function ready() {
    if (finished || started) return;
    if (reduced.matches || document.hidden) { finish(true); return; }
    started = true;
    root.classList.add('intro-running');
  }
  function onVisibility() { if (document.hidden) finish(true); }
  function onMotion() { if (reduced.matches) finish(true); }
  root.addEventListener('animationstart', event => {
    if (!finished && event.animationName === 'nora-layer-out') NoraLogo.impact('medium');
  });
  root.addEventListener('animationend', event => {
    if (event.target.classList.contains('nora-logo-cyan')) finish();
  });
  document.addEventListener('visibilitychange', onVisibility);
  reduced.addEventListener?.('change', onMotion);
  // Never trap the user if API loading or animation events stall.
  deadline = setTimeout(() => finish(true), 6500);
  if (!telegram?.initData || reduced.matches || document.hidden) finish(true);
  else requestAnimationFrame(() => { if (!finished) chrome('#050407'); });
  return {finish, ready};
})();
