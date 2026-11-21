'use strict';
// Telegram creates a real Mini App shortcut using the bot's profile icon.
// This is deliberately not a PWA install: the Telegram client owns the shortcut.
window.NoraHomeScreen = (() => {
  const app = window.Telegram?.WebApp;
  const deepLink = 'nora_home_screen';
  const isMobile = ['ios', 'android'].includes(app?.platform) ||
    /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  const supported = !!(isMobile && app?.isVersionAtLeast?.('8.0') &&
    typeof app?.addToHomeScreen === 'function');
  const icon = '/intro/nora-logo-ru.jpg';
  let dialog, page = 0, status = 'unknown', requested = false, opener;

  function ensure() {
    if (dialog) return;
    dialog = document.createElement('dialog');
    dialog.className = 'nora-install-story';
    dialog.setAttribute('aria-label', 'Установить Нору на главный экран');
    dialog.innerHTML = `<div class="nora-install-panel">
      <div class="nora-install-top"><span>НОРА <i>•</i> ИСТОРИЯ</span>
        <button type="button" class="nora-install-x" data-install-close aria-label="Закрыть">✕</button></div>
      <div class="nora-install-progress" aria-hidden="true"><b></b><b></b><b></b></div>
      <div class="nora-install-content" aria-live="polite"></div>
      <div class="nora-install-actions"><button type="button" class="nora-install-cta"></button>
        <button type="button" class="nora-install-back" hidden>← Назад</button></div>
    </div>`;
    document.body.append(dialog);
    dialog.querySelector('[data-install-close]').addEventListener('click', close);
    dialog.querySelector('.nora-install-back').addEventListener('click', () => show(Math.max(0, page - 1)));
    dialog.querySelector('.nora-install-cta').addEventListener('click', primaryAction);
    dialog.addEventListener('click', e => { if (e.target === dialog) close(); });
    dialog.addEventListener('close', () => {
      if (opener?.isConnected) opener.focus();
      opener = null;
    });
    if (supported) {
      app?.onEvent?.('homeScreenAdded', () => { status = 'added'; show(2); });
      app?.onEvent?.('homeScreenChecked', event => {
        if (event && typeof event.status === 'string') updateStatus(event.status);
      });
    }
  }

  function updateStatus(next) {
    if (!['unsupported', 'unknown', 'added', 'missed'].includes(next)) return;
    status = next;
    if (dialog?.open && (page === 1 || page === 2)) show(page);
  }

  function check() {
    if (!supported || typeof app.checkHomeScreenStatus !== 'function') return;
    try { app.checkHomeScreenStatus(updateStatus); } catch { status = 'unsupported'; }
  }

  function show(next) {
    page = next;
    const content = dialog.querySelector('.nora-install-content');
    const action = dialog.querySelector('.nora-install-cta');
    const back = dialog.querySelector('.nora-install-back');
    const title = `<span class="nora-install-kicker">НА ГЛАВНЫЙ ЭКРАН</span>`;
    if (page === 0) {
      content.innerHTML = `<div class="nora-install-icon"><img src="${icon}" alt="Логотип Норы"></div>
        ${title}<h2>Нора всегда<br><em>под рукой.</em></h2>
        <p>Открывай игры, профиль и коммьюнити прямо с экрана телефона. Один значок, один тап.</p>
        <div class="nora-install-footnote">Без App Store и Google Play. Ярлык создаёт сам Telegram.</div>`;
      action.textContent = 'Показать как →';
      back.hidden = true;
    } else if (page === 1) {
      const unavailable = !supported || status === 'unsupported';
      content.innerHTML = `<div class="nora-install-icon nora-install-icon-small"><img src="${icon}" alt="Логотип Норы"></div>
        ${title}<h2>Добавь <em>иконку.</em></h2>
        <div class="nora-install-steps">
          <div><b>01</b><span>Открой Нору в Telegram на iPhone или Android.</span></div>
          <div><b>02</b><span>${unavailable ? 'Обнови Telegram до актуальной версии и открой эту историю снова.' :
            'Нажми кнопку ниже и подтверди системный запрос Telegram.'}</span></div>
          <div><b>03</b><span>Найди значок Норы на главном экране. Он будет открывать Mini App.</span></div>
        </div>
        ${unavailable ? '<p class="nora-install-hint">На этом устройстве Telegram не поддерживает создание ярлыка. Открой Нору в мобильном приложении Telegram.</p>' :
          '<p class="nora-install-hint">Изображение ярлыка берётся из аватара бота Норы в Telegram.</p>'}`;
      action.textContent = status === 'added' ? 'Уже на экране ✓' :
        unavailable ? 'Понятно' : '📲 Добавить Нору на экран';
      back.hidden = false;
      action.disabled = status === 'added';
    } else {
      content.innerHTML = `<div class="nora-install-icon"><img src="${icon}" alt="Логотип Норы"></div>
        ${title}<h2>${status === 'added' ? 'Нора теперь <em>рядом.</em>' : 'Проверь <em>свой экран.</em>'}</h2>
        <p>${status === 'added' ? 'Telegram подтвердил добавление ярлыка. Найди значок Норы на главном экране телефона.' :
          'Подтверди запрос Telegram. Некоторые устройства не сообщают приложению, появился ли ярлык. Проверь главный экран вручную.'}</p>
        <div class="nora-install-footnote">Нажатие на ярлык открывает Нору через Telegram.</div>`;
      action.textContent = 'Готово';
      action.disabled = false;
      back.hidden = false;
    }
    dialog.querySelectorAll('.nora-install-progress b').forEach((bar, i) => {
      bar.classList.toggle('active', i <= page);
    });
  }

  function primaryAction() {
    if (page === 0) { show(1); return; }
    if (page === 2 || !supported || status === 'unsupported') { close(); return; }
    if (status === 'added') { show(2); return; }
    try {
      requested = true;
      app.addToHomeScreen();  // Must be called directly from a user gesture.
      show(2);
    } catch {
      requested = false;
      status = 'unsupported';
      show(1);
    }
  }

  function open(trigger) {
    ensure();
    if (dialog.open) return;
    opener = trigger || document.activeElement;
    page = 0;
    requested = false;
    status = supported ? 'unknown' : 'unsupported';
    show(0);
    dialog.showModal();
    check();
  }

  function close() {
    if (dialog?.open) dialog.close();
  }

  document.addEventListener('click', e => {
    const button = e.target.closest('[data-home-install]');
    if (button) open(button);
  });

  return { open, close, deepLink };
})();
