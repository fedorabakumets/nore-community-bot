
'use strict';

window.NoraI18n = (() => {
  const preference = 'nora-miniapp-language';
  const switched = history.state?.noraLanguageSwitch === true;
  let saved;
  try { saved = localStorage.getItem(preference); } catch { /* Storage can be blocked in a WebView. */ }
  const selected = switched ? history.state?.noraLanguage : saved || history.state?.noraLanguage;
  const language = selected === 'en' ? 'en' : 'ru';
  document.documentElement.lang = language;
  if (switched) {
    const state = {...history.state};
    delete state.noraLanguageSwitch;
    history.replaceState(state, '');
  }

  function t(value) {
    if (language !== 'en' || typeof value !== 'string') return value;
    const key = value.trim();
    const translations = window.NoraEnglish;
    const translated = translations && (Object.hasOwn(translations, value) ? translations[value] :
      Object.hasOwn(translations, key) ? translations[key] : undefined);
    return typeof translated === 'string' ? value.replace(key, () => translated) : value;
  }

  function html(value) {
    const translated = t(value);
    if (translated === value) return value;
    return translated.replace(/[&<>"']/g, char => ({
      '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;',
    })[char]);
  }

  const serverPatterns = [
    [/^Обязательная ставка (\d+)$/, 'Blind bet $1'],
    [/^(.+) забирает банк$/, '$1 takes the pot'],
    [/^(.+) выигрывает банк$/, '$1 wins the pot'],
    [/^Всё (\d+)$/, 'All in $1'],
    [/^Уравнял (\d+)$/, 'Called $1'],
    [/^Повысил до (\d+)$/, 'Raised to $1'],
    [/^Ставка (\d+)$/, 'Bet $1'],
    [/^Фото должно быть не больше (\d+) МБ$/, 'The photo must be $1 MB or smaller'],
    [/^Для входа нужно (\d+) печенек, на балансе (\d+)$/, 'You need $1 cookies to join. Your balance is $2.'],
    [/^Не хватает печенек на ставку (\d+) 🍪$/, 'You need $1 🍪 to place this bet.'],
    [/^Перевод выполнен: получателю (\d+) 🍪$/, 'Transfer complete. The recipient received $1 🍪.'],
    [/^Мероприятие удалено из актуальных\. Возвращено (\d+) 🍪$/, 'Event removed. Refunded $1 🍪.'],
    [/^Проигрыватель будет доступен через (\d+) сек\.$/, 'The player will be available in $1 seconds.'],
  ];

  function server(value) {
    if (language === 'en' && typeof value === 'string') {
      const field = value.match(/^Заполни поле «([^»]+)» \(до (\d+) символов\)\.$/);
      if (field) return 'Enter ' + t(field[1]) + ' (up to ' + field[2] + ' characters).';
    }
    const formatted = t(value);
    if (language !== 'en' || typeof value !== 'string' || formatted !== value) return formatted;
    for (const [pattern, message] of serverPatterns) {
      if (pattern.test(value)) return value.replace(pattern, message);
    }
    return value;
  }

  function toggle() {
    const next = language === 'ru' ? 'en' : 'ru';
    try { localStorage.setItem(preference, next); } catch { /* History keeps the choice for this reload. */ }
    history.replaceState({...history.state, noraLanguage: next, noraLanguageSwitch: true}, '');
    location.reload();
  }

  function button() {
    const english = language === 'ru';
    return '<button type="button" class="nora-language" data-language-switch aria-label="' +
      (english ? 'Switch to English' : 'Переключить на русский') +
      '"><span aria-hidden="true">🌐</span><span lang="' + (english ? 'en">English' : 'ru">Русский') +
      '</span></button>';
  }

  document.addEventListener('click', event => {
    const control = event.target.closest('button[data-language-switch]');
    if (!control) return;
    control.disabled = true;
    toggle();
  });

  function translateShell() {
    if (language !== 'en') return;
    document.title = t(document.title);
    const attributes = ['aria-label', 'title', 'alt', 'placeholder'];
    for (const element of document.body.querySelectorAll(attributes.map(name => '[' + name + ']').join(','))) {
      for (const name of attributes) {
        if (element.hasAttribute(name)) element.setAttribute(name, t(element.getAttribute(name)));
      }
    }
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (!node.parentElement.closest('script, style')) node.nodeValue = t(node.nodeValue);
    }
  }

  return {language, locale: language === 'en' ? 'en-US' : 'ru-RU', switched, t, html, server, button, translateShell};
})();
NoraI18n.translateShell();
