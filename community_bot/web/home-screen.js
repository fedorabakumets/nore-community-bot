'use strict';

// Telegram owns the shortcut and uses the bot's profile icon.
window.NoraHomeScreen = (() => {
  const app = window.Telegram?.WebApp;
  const isMobile = ['ios', 'android'].includes(app?.platform) ||
    /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  const supported = !!(isMobile && app?.isVersionAtLeast?.('8.0') &&
    typeof app?.addToHomeScreen === 'function');
  const icon = '/intro/nora-home-icon.svg';
  let status, requested, active;

  function reset() {
    status = supported ? 'unknown' : 'unsupported';
    requested = false;
  }

  function updateStatus(next) {
    if (!active || !['unsupported', 'unknown', 'added', 'missed'].includes(next)) return;
    status = next;
    if (active.page > 0) render(active);
  }

  if (supported) {
    app.onEvent?.('homeScreenAdded', () => {
      if (!active || !requested) return;
      status = 'added';
      active.page = 2;
      render(active);
      active.pause();
    });
    app.onEvent?.('homeScreenChecked', event => updateStatus(event?.status));
  }

  function render({page, content, action}) {
    action.disabled = false;
    if (page === 0) {
      content.innerHTML = `<div class="nora-install-icon"><img src="${icon}" alt="${NoraI18n.html("Иконка Норы")}"></div>
        <h2>${NoraI18n.html("Нора всегда")}<br><em>${NoraI18n.html("под рукой.")}</em></h2>
        <p>${NoraI18n.html("Открывай игры, профиль и коммьюнити прямо с экрана телефона. Один значок, один тап.")}</p>
        <div class="nora-install-footnote">${NoraI18n.html("Без App Store и Google Play. Ярлык создаёт сам Telegram.")}</div>`;
      action.textContent = NoraI18n.t("Показать как →");
    } else if (page === 1) {
      const unavailable = !supported || status === 'unsupported';
      content.innerHTML = `<div class="nora-install-icon nora-install-icon-small"><img src="${icon}" alt="${NoraI18n.html("Иконка Норы")}"></div>
        <h2>${NoraI18n.html("Добавь")} <em>${NoraI18n.html("иконку.")}</em></h2>
        <div class="nora-install-steps">
          <div><b>01</b><span>${NoraI18n.html("Открой Нору в Telegram на iPhone или Android.")}</span></div>
          <div><b>02</b><span>${unavailable ? NoraI18n.t("Обнови Telegram до актуальной версии и открой эту историю снова.") :
            NoraI18n.t("Нажми кнопку ниже и подтверди системный запрос Telegram.")}</span></div>
          <div><b>03</b><span>${NoraI18n.html("Найди значок Норы на главном экране. Он будет открывать Mini App.")}</span></div>
        </div>
        ${unavailable ? ("<p class=\"nora-install-hint\">" + NoraI18n.html("На этом устройстве Telegram не поддерживает создание ярлыка. Открой Нору в мобильном приложении Telegram.") + "</p>") :
          ("<p class=\"nora-install-hint\">" + NoraI18n.html("Изображение ярлыка берётся из аватара бота Норы в Telegram.") + "</p>")}`;
      action.textContent = status === 'added' ? NoraI18n.t("Уже на экране ✓") :
        unavailable ? NoraI18n.t("Понятно") : NoraI18n.t("📲 Добавить Нору на экран");
      action.disabled = status === 'added';
    } else {
      content.innerHTML = `<div class="nora-install-icon"><img src="${icon}" alt="${NoraI18n.html("Иконка Норы")}"></div>
        <h2>${status === 'added' ? (NoraI18n.html("Нора теперь") + " <em>" + NoraI18n.html("рядом.") + "</em>") : (NoraI18n.html("Проверь") + " <em>" + NoraI18n.html("свой экран.") + "</em>")}</h2>
        <p>${status === 'added' ? NoraI18n.t("Telegram подтвердил добавление ярлыка. Найди значок Норы на главном экране телефона.") :
          NoraI18n.t("Подтверди запрос Telegram. Некоторые устройства не сообщают приложению, появился ли ярлык. Проверь главный экран вручную.")}</p>
        <div class="nora-install-footnote">${NoraI18n.html("Нажатие на ярлык открывает Нору через Telegram.")}</div>`;
      action.textContent = NoraI18n.t("Готово");
    }
    content.scrollTop = 0;
    syncScroll(content);
  }

  function syncScroll(content) {
    const scrollable = content.clientHeight > 0 && content.scrollHeight > content.clientHeight;
    content.toggleAttribute('data-story-scroll', scrollable);
    if (scrollable) content.tabIndex = 0;
    else content.removeAttribute('tabindex');
  }

  function mount(card, step, next, close, pause) {
    card.innerHTML = '<div class="nora-install-panel">' +
      '<div class="nora-install-content" aria-live="polite"></div>' +
      '<div class="nora-install-actions"><button type="button" class="nora-install-cta"></button></div></div>';
    const view = active = {
      page: step,
      content: card.querySelector('.nora-install-content'),
      action: card.querySelector('.nora-install-cta'),
      pause,
    };
    render(view);
    const resize = new ResizeObserver(() => syncScroll(view.content));
    resize.observe(view.content);
    view.action.addEventListener('click', () => {
      if (view !== active) return;
      if (view.page === 0) { next(); return; }
      if (view.page === 2 || !supported || status === 'unsupported') { close(); return; }
      try {
        requested = true;
        // This call must remain within the button's user gesture.
        app.addToHomeScreen();
        view.page = 2;
        render(view);
        pause();
      } catch {
        requested = false;
        updateStatus('unsupported');
      }
    });
    if (step === 0 && supported && typeof app.checkHomeScreenStatus === 'function') {
      try { app.checkHomeScreenStatus(updateStatus); } catch { status = 'unsupported'; }
    }
    return () => {
      resize.disconnect();
      if (active === view) active = null;
    };
  }

  return { icon, mount, reset, open: () => window.NoraStories.openInstall() };
})();
