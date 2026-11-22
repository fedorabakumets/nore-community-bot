'use strict';
// Shared, explicitly selected city control: no free-text value is submitted.
window.NoraCity = (() => {
  function mount(form, original = '') {
    const input = form?.querySelector('input[name="city"]');
    if (!input) return;
    const list = document.createElement('div');
    list.className = 'city-suggestions';
    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-label', 'Подходящие города');
    list.hidden = true;
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');
    input.after(list);
    const feedback = document.createElement('small');
    feedback.className = 'city-picker-feedback';
    feedback.textContent = 'Начни вводить город и выбери подходящий вариант.';
    list.after(feedback);
    let seq = 0;
    let timer;
    function options(items) {
      list.replaceChildren();
      if (!items.length) {
        const empty = document.createElement('p');
        empty.className = 'sub';
        empty.textContent = 'Совпадений нет. Попробуй другое написание.';
        list.append(empty);
      }
      for (const city of items) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'city-suggestion-option';
        button.setAttribute('role', 'option');
        button.dataset.cityId = city.id;
        const name = document.createElement('b');
        name.textContent = city.name;
        const meta = document.createElement('small');
        meta.textContent = [city.region, city.country].filter(Boolean).join(' · ');
        button.append(name, meta);
        button.addEventListener('click', () => {
          ++seq;
          clearTimeout(timer);
          input.value = city.name;
          input.dataset.cityId = city.id;
          input.setAttribute('aria-expanded', 'false');
          feedback.textContent = '✓ Выбран город: ' + city.name;
          list.hidden = true;
        });
        list.append(button);
      }
      list.hidden = false;
      input.setAttribute('aria-expanded', 'true');
    }
    async function search(value) {
      const thisSeq = ++seq;
      try {
        const result = await api('cities' + (value.length >= 2 ? '?q=' + encodeURIComponent(value) : ''));
        if (thisSeq !== seq || !form.isConnected) return;
        options(result.items || []);
      } catch (err) {
        if (thisSeq !== seq || !form.isConnected) return;
        list.hidden = true;
        feedback.textContent = err.message || 'Не удалось загрузить города';
      }
    }
    input.addEventListener('input', () => {
      ++seq; // Immediately reject results for the previous input, before debounce.
      list.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      input.dataset.cityId = '';
      feedback.textContent = 'Выбери город из подсказок.';
      clearTimeout(timer);
      if (input.value.trim().length === 1) {
        list.hidden = true;
        return;
      }
      timer = setTimeout(() => search(input.value.trim()), 260);
    });
    input.addEventListener('focus', () => {
      if (list.hidden && !input.dataset.cityId) search(input.value.trim());
    });
    input.addEventListener('keydown', event => {
      if (event.key === 'Escape') { list.hidden = true; input.setAttribute('aria-expanded', 'false'); }
      if (event.key === 'ArrowDown' && !list.hidden) {
        event.preventDefault();
        list.querySelector('button')?.focus();
      }
    });
    list.addEventListener('keydown', event => {
      const buttons = [...list.querySelectorAll('button')], current = buttons.indexOf(document.activeElement);
      if (event.key === 'ArrowDown' && current < buttons.length - 1) { event.preventDefault(); buttons[current+1].focus(); }
      if (event.key === 'ArrowUp') { event.preventDefault(); if (current > 0) buttons[current-1].focus(); else input.focus(); }
      if (event.key === 'Escape') { event.preventDefault(); list.hidden = true; input.focus(); }
    });
    const controller = new AbortController();
    document.addEventListener('pointerdown', event => {
      if (!form.isConnected) return;
      if (event.target !== input && !list.contains(event.target)) {
        list.hidden = true;
        input.setAttribute('aria-expanded', 'false');
      }
    }, {signal:controller.signal});
    const observer = new MutationObserver(() => {
      if (!form.isConnected) { controller.abort(); observer.disconnect(); clearTimeout(timer); }
    });
    observer.observe(form.closest('dialog') || document.querySelector('#app') || document.body, {childList:true, subtree:true});
    if (original) feedback.textContent = 'Изменяешь город? Выбери новое значение из подсказок.';
  }
  function choice(form, original = '') {
    const input = form?.querySelector('input[name="city"]');
    if (!input) throw Error('Поле города не найдено');
    if (input.dataset.cityId) return input.dataset.cityId;
    if (original && original === input.value.trim()) return null;
    input.focus();
    throw Error('Выбери настоящий город из предложенного списка');
  }
  return {mount, choice};
})();
