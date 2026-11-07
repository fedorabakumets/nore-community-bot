'use strict';
// Workspace design informed by Unslop by Damir Sokolovsky, CC BY 4.0.
// https://github.com/heydamir/unslop
window.NoraAdmin = (() => {
  let panel = null, loading = false, working = false, error = '', mediaURLs = [];
  let draft = emptyDraft(), directoryQuery = '', menuOpen = false, focusAfter = '';
  const expandedPeople = new Set();
  const expanded = new Set(['profile', 'wallet', 'roles', 'actions', 'settings', 'permissions', 'directory', 'community', 'protection', 'perm_people', 'reports', 'tools', 'catalog', 'storefront', 'prefix_color', 'prefix_emoji']);
  const groups = {profile:'Профиль', wallet:'Печеньки и баланс', moderation:'Репутация и модерация',
    roles:'Роль и права', permissions:'Разрешения роли', settings:'Настройки',
    prefix_color:'Цвет префикса', prefix_emoji:'Символ префикса', directory:'Участники', actions:'Действия', danger:'Опасные действия',
    community:'Возможности сообщества', protection:'Защита чата', automation:'Автоматизация',
    perm_people:'Участники и модерация', perm_content:'Чат и публикации', perm_system:'Инструменты и доступ',
    reports:'Отчёты и история', tools:'Инструменты Норы', catalog:'Каталог', storefront:'Витрина и оформление'};
  const formLabels = {role_name:['Новая роль','Название роли','Настроить префикс'], search:['Найти участника','Имя, @username или Telegram ID','Найти'],
    cookies:['Установить баланс','Новый баланс','Сохранить баланс'],
    add_cookies:['Начислить печеньки','Количество печенек','Начислить'],
    rep:['Репутация','Новое значение репутации','Сохранить'],
    name:['Имя участника','Новое имя','Сохранить имя'], age:['Возраст','Возраст','Сохранить'],
    warnings:['Предупреждения','Количество предупреждений','Сохранить'],
    note:['Заметка модератора','Заметка','Сохранить заметку'], avatar:['Аватар','Подпись к вложению','Загрузить'],
    clear_name:['Очистить имя','Введи ОЧИСТИТЬ для подтверждения','Очистить имя'],
    clear_bio:['Очистить описание','Введи ОЧИСТИТЬ для подтверждения','Очистить описание']};
  const paths = {overview:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
    people:'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M17 4a4 4 0 0 1 0 7 M22 21v-2a4 4 0 0 0-3-4',
    queue:'M4 4h16v16H4z M4 14h5l2 3h2l2-3h5', content:'M4 21V4h16v17l-4-3-4 3-4-3z M8 8h8 M8 12h6',
    events:'M4 5h16v16H4z M4 10h16 M8 2v5 M16 2v5', shop:'M4 8h16v13H4z M8 8V5a4 4 0 0 1 8 0v3',
    settings:'M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6',
    system:'M3 5h18v14H3z M8 23h8 M12 19v4 M6 9l3 3-3 3 M12 15h5',
    arrow:'m9 5 7 7-7 7', search:'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M15 15l6 6',
    refresh:'M20 7A9 9 0 1 0 21 14 M20 2v6h-6', back:'m14 5-7 7 7 7', check:'m5 12 4 4 10-10'};
  function icon(key) { return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[key] || paths.arrow}"/></svg>`; }
  function emptyDraft() { return {text:'', format:'plain', kind:'auto', file:null}; }
  function redraw() { if (tab === 'admin') render(); }
  function clearMedia() { for (const url of mediaURLs) URL.revokeObjectURL(url); mediaURLs = []; }
  function show(next, keepDraft = false) {
    clearMedia(); if (!keepDraft) draft = emptyDraft(); panel = next; error = '';
    for (const notice of next.notices || []) toast(notice);
    if (next.exit) { tab = 'lk'; render(); } else redraw();
  }
  async function load(reset = false) {
    if (working || loading) return;
    loading = true; error = ''; redraw();
    try { show(await api(reset ? 'admin/reset' : 'admin', reset ? {} : undefined), !reset); }
    catch (e) { error = e.message; } finally { loading = false; redraw(); }
  }
  function canLeave() {
    return !(panel?.draft || draft.text || draft.file) || confirm('Закрыть текущую форму и перейти в другой раздел? Несохранённые данные будут потеряны.');
  }
  async function act(action, navigation = false) {
    if (working || loading || !panel || (navigation && !canLeave())) return;
    working = true; error = ''; menuOpen = false;
    focusAfter = navigation ? 'heading' : focusAfter; redraw();
    try { show(await api('admin/action', {action, version:panel.version})); }
    catch (e) { error = e.message; toast(e.message); } finally { working = false; redraw(); }
  }
  function disabled() { return working || loading ? 'disabled' : ''; }
  function navButton(item, active = false) {
    return `<button class="adm-nav-item ${active ? 'is-active' : ''}" data-adm-go="${esc(item.action)}" ${active ? 'aria-current="page"' : ''} ${disabled()}>${icon(item.id)}<span>${esc(item.title)}</span>${icon('arrow')}</button>`;
  }
  function toolButton(item, count) {
    return `<button class="adm-tool" data-adm-go="${esc(item.action)}" ${disabled()}><span><b>${esc(item.title)}</b><small>${esc(item.description)}</small></span>${count === undefined ? '' : `<strong class="adm-count">${number(count)}</strong>`}${icon('arrow')}</button>`;
  }
  function overview(workspace) {
    const queue = workspace.tools.filter(t => t.section === 'queue');
    return `<div class="adm-overview"><section class="adm-priority"><div class="adm-section-title"><h2>Требуют внимания</h2><span>Сейчас</span></div><p class="adm-muted">Новые обращения и незавершённые задачи сообщества</p><div class="adm-tool-list">${queue.map(t => toolButton(t, workspace.counts[t.id])).join('')}</div></section><section class="adm-section-list"><h2>Рабочие разделы</h2>${workspace.navigation.filter(n => !['overview','queue'].includes(n.id)).map(n => toolButton(n)).join('')}</section></div>`;
  }
  function searchForm() {
    return `<form id="adm-search" class="adm-search" role="search"><label for="adm-search-query">Найти участника</label><div>${icon('search')}<input id="adm-search-query" type="search" autocomplete="off" placeholder="Имя, @username или ID" value="${esc(directoryQuery)}" ${disabled()}><button type="submit" ${disabled()}>Найти</button></div><small>Поиск по всему сообществу</small></form>`;
  }
  function hub(workspace) {
    const section = workspace.section;
    const tools = workspace.tools.filter(t => t.section === section);
    // These screens are rendered as purpose-built workspaces, rather than Telegram keyboard rows.
    if (section === 'people') return `${searchForm()}<div class="adm-section-title"><h2>Управление участниками</h2></div><div class="adm-tool-list">${tools.filter(t => t.id !== 'search').map(t => toolButton(t)).join('')}</div>`;
    if (section === 'queue') return `<div class="adm-tool-list">${tools.map(t => toolButton(t, workspace.counts[t.id])).join('')}</div>`;
    if (section === 'content') return `<div class="adm-section-title"><h2>Сообщения и публикации</h2></div><div class="adm-tool-list">${tools.map(t => toolButton(t)).join('')}</div>`;
    return null;
  }
  function button(b) {
    const label = b.label || b.text;
    const classes = `adm-control ${b.group === 'danger' || b.style === 'danger' ? 'is-danger' : ''}`;
    if (b.tab) return `<button class="${classes}" data-tab="${esc(b.tab)}">${esc(label)}</button>`;
    if (b.url) return `<a class="${classes}" href="${esc(b.url)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`;
    if (b.kind === 'choice') {
      const color=['red','orange','gold','green','blue','purple','pink'].includes(b.prefix_color)?b.prefix_color:'';
      return `<button type="button" class="adm-prefix-choice ${b.checked?'is-selected':''}" aria-pressed="${Boolean(b.checked)}" data-admin-action="${esc(b.action)}" data-control-label="${esc(label)}" ${disabled()}>${color?`<i class="role-prefix--${color}" aria-hidden="true"></i>`:''}${NoraPrefixSymbol(b.prefix_emoji)}<span>${esc(label)}</span>${b.checked?'<b aria-hidden="true">✓</b>':''}</button>`;
    }
    if (b.kind === 'toggle') return `<button type="button" class="adm-toggle" role="switch" aria-checked="${Boolean(b.checked)}" aria-label="${esc(label)}" data-admin-action="${esc(b.action)}" data-control-label="${esc(label)}" ${disabled()}><span><span>${esc(label)}</span>${b.description ? `<small>${esc(b.description)}</small>` : ''}</span><small>${b.checked ? 'Включено' : 'Выключено'}</small><i aria-hidden="true"></i></button>`;
    if (b.kind === 'user') {
      const person = b.person, name = person?.name || label;
      const open = person && expandedPeople.has(String(person.id)), infoId = `adm-identity-${b.action}`;
      return `<div class="adm-person-row" ${person ? `data-adm-person-row="${esc(person.id)}"` : ''}><button class="adm-person" data-admin-action="${esc(b.action)}" data-control-label="${esc(name)}" ${disabled()}>${avatar(person, name)}<span>${NoraPrefix(person?.prefix)}${esc(name)}</span>${icon('arrow')}</button>${person ? `<button type="button" class="adm-person-info" data-adm-identity="${esc(person.id)}" aria-label="Контакты ${esc(name)}: username и Telegram ID" aria-expanded="${Boolean(open)}" aria-controls="${esc(infoId)}">@ / ID${icon('arrow')}</button><div class="adm-person-contact" id="${esc(infoId)}" ${open ? '' : 'hidden'}><span>${person.username ? `@${esc(person.username)}` : 'Без @username'}</span><span>Telegram ID: <b>${esc(person.id)}</b></span></div>` : ''}</div>`;
    }
    return `<button class="${classes}" data-admin-action="${esc(b.action)}" data-control-label="${esc(label)}" ${disabled()}>${esc(label)}${b.kind === 'link' ? icon('arrow') : ''}</button>`;
  }
  function avatar(person, name, large = false) {
    return `<span class="${large ? 'adm-member-avatar' : 'adm-avatar'} person-avatar" ${person ? `data-person-avatar="${esc(person.id)}" ${person.has_avatar ? '' : 'data-avatar-unavailable'}` : ''} aria-hidden="true">${esc(Array.from(name)[0] || 'Н')}</span>`;
  }
  function controls(buttons) {
    const flat = buttons.flat(), back = flat.filter(b => b.kind === 'back');
    const buckets = new Map();
    for (const b of flat.filter(b => b.kind !== 'back')) {
      const key = b.group || 'actions'; if (!buckets.has(key)) buckets.set(key, []); buckets.get(key).push(b);
    }
    const order = ['profile','wallet','roles','moderation','directory','community','protection','automation','perm_people','perm_content','perm_system','permissions','catalog','storefront','reports','tools','settings','prefix_color','prefix_emoji','actions','danger'];
    return Array.from(buckets).sort((a,b) => order.indexOf(a[0]) - order.indexOf(b[0])).map(([key, list]) => `<details class="adm-group ${key === 'danger' ? 'adm-danger-group' : ''}" data-adm-group="${key}" ${expanded.has(key) ? 'open' : ''}><summary><span>${groups[key] || 'Действия'}</span><small>${list.length}</small>${icon('arrow')}</summary><div class="adm-group-body ${key === 'directory' ? 'adm-directory' : ''}">${list.map(button).join('')}</div></details>`).join('') + (back.length ? `<div class="adm-back-actions">${back.map(button).join('')}</div>` : '');
  }
  function media(m) {
    if (!m) return '';
    if (m.url) return `<a class="adm-file" href="${esc(m.url)}" target="_blank" rel="noopener noreferrer">Открыть вложение ↗</a>`;
    return `<div class="adm-media" data-admin-media="${esc(m.id)}" data-kind="${esc(m.kind)}"><span class="adm-muted">Загружаем вложение…</span></div>`;
  }
  function card(c) {
    const member = c.member;
    const summary = member ? `<div class="adm-member"><div class="adm-member-title">${avatar(member, member.name, true)}<div><h2>${esc(member.name)}</h2><p>${NoraPrefix(member.prefix)||esc(member.role)}${member.username ? ` · @${esc(member.username)}` : ''}</p><small>ID ${esc(member.id)}${member.age ? ` · ${number(member.age)} ${plural(member.age,'год','года','лет')}` : ''}</small></div></div><dl class="adm-member-stats"><div><dt>Печеньки</dt><dd>${number(member.cookies)}</dd></div><div><dt>Репутация</dt><dd>${number(member.reputation)}</dd><small>Щиты: ${number(member.hate_shields)}</small></div><div><dt>Нарушения</dt><dd>${number(member.warnings)}</dd></div></dl>${member.moderator_note ? `<p class="adm-member-note"><b>Заметка модератора</b>${esc(member.moderator_note)}</p>` : ''}</div>` : c.html && c.layout !== 'features' && !panel?.workspace?.prefix_preview ? `<div class="admin-copy adm-copy">${c.html}</div>` : '';
    return `<section class="adm-card">${media(c.media)}${summary}${controls(c.buttons)}</section>`;
  }
  function composer() {
    const kind = panel.workspace?.form_kind || '', labels = formLabels[kind] || ['Заполнить форму','Текст или подпись к вложению','Продолжить'];
    const numeric = ['cookies','add_cookies','rep','age','warnings'].includes(kind);
    return `<section class="adm-composer"><div class="adm-section-title"><h2>${labels[0]}</h2><span>Не сохранено</span></div><form id="admin-input"><label for="admin-text">${labels[1]}</label>${numeric ? `<input id="admin-text" type="number" step="1" ${kind === 'rep' ? 'min="-20" max="100"' : kind === 'age' ? 'min="14" max="120"' : kind === 'warnings' ? 'min="0"' : `min="${kind === 'cookies' ? 0 : 1}" max="1000000"`} value="${esc(draft.text)}" ${disabled()}>` : `<textarea id="admin-text" rows="${kind === 'search' ? 2 : 5}" maxlength="4096" placeholder="${labels[1]}" ${disabled()}>${esc(draft.text)}</textarea>`}${numeric || kind === 'role_name' || kind === 'search' || kind.startsWith('clear_') ? '' : `<details class="adm-attachments"><summary>Форматирование и вложения${draft.file ? ' · файл выбран' : ''}</summary><div class="adm-formatting"><label><input type="checkbox" id="admin-html" ${draft.format === 'html' ? 'checked' : ''}> HTML-форматирование</label><button type="button" data-admin-format="b" aria-label="Жирный текст">Ж</button><button type="button" data-admin-format="i" aria-label="Курсив">К</button><button type="button" data-admin-format="blockquote">Цитата</button></div><label for="admin-file">Вложение</label><input type="file" id="admin-file" ${disabled()}>${draft.file ? `<p class="adm-muted">Выбран файл: ${esc(draft.file.name)} <button type="button" data-adm-remove-file>Убрать</button></p>` : ''}<label for="admin-kind">Тип вложения</label><select id="admin-kind" ${disabled()}>${[['auto','Определить по файлу'],['photo','Фотография'],['video','Видео'],['animation','GIF / анимация'],['document','Документ'],['audio','Аудио'],['voice','Голосовое OGG']].map(([value,title]) => `<option value="${value}" ${draft.kind === value ? 'selected' : ''}>${title}</option>`).join('')}</select><p class="adm-muted">До 20 МБ. Файл сохранится в личном диалоге с Норой. Публикация выполняется отдельным действием.</p></details>`}<div class="adm-form-actions"><button class="adm-primary" type="submit" ${disabled()}>${working ? 'Сохраняем…' : labels[2]}</button><button class="adm-quiet" type="button" data-adm-cancel ${disabled()}>Отменить</button></div></form></section>`;
  }
  function renderPanel() {
    if (!panel && !loading && !error) queueMicrotask(() => load());
    const w = panel?.workspace, section = w?.navigation.find(n => n.id === w.section);
    let content = '';
    if (w) {
      if (w.screen === 'admin:panel') content = overview(w);
      else if (['admin:people','admin:queue','admin:chatroom'].includes(w.screen) && !panel.form && !(w.section === 'settings')) content = hub(w) ?? panel.cards.map(card).join('');
      else content = `${w.section === 'people' && !panel.form && (w.screen === 'admin:search' || panel.cards.some(c => c.buttons.flat().some(b => b.kind === 'user'))) ? searchForm() : ''}${panel.cards.map(card).join('')}`;
    } else if (panel) content = panel.cards.map(card).join('');
    const sectionTools = w?.tools.filter(t => t.section === w.section && t.id !== 'search') || [];
    const shortcuts = w && w.section !== 'overview' && sectionTools.length > 1 ? `<div class="adm-section-tools" aria-label="Инструменты раздела">${sectionTools.map(t => `<button class="${t.current ? 'is-active' : ''}" data-adm-go="${esc(t.action)}" ${t.current ? 'aria-current="page"' : ''} ${disabled()}>${esc(t.title)}</button>`).join('')}</div>` : '';
    return `<div class="adm-workspace" aria-busy="${working || loading}"><aside class="adm-sidebar"><div class="adm-brand"><span>Нора<span class="adm-brand-dot">.</span></span><small>Панель команды</small></div><button class="adm-menu-button" aria-expanded="${menuOpen}" aria-controls="adm-navigation" data-adm-menu>${icon(w?.section || 'overview')}<span>${esc(section?.title || 'Разделы панели')}</span>${icon('arrow')}</button><nav id="adm-navigation" class="adm-navigation ${menuOpen ? 'is-open' : ''}" aria-label="Управление Норой">${(w?.navigation || []).map(n => navButton(n, n.id === w.section)).join('')}</nav><button class="adm-return" data-tab="lk">${icon('back')}<span>Личный кабинет</span></button></aside><div class="adm-main"><header class="adm-header"><div><p>Управление сообществом</p><h1 id="adm-heading" tabindex="-1">${esc(section?.title || 'Админ-панель')}</h1><span>${esc(section?.description || 'Рабочее пространство команды Норы')}</span></div><button class="adm-refresh" data-admin-refresh aria-label="Обновить текущий экран" title="Обновить" ${disabled()}>${icon('refresh')}</button></header>${error ? `<div class="adm-error" role="alert">${esc(error)}<button data-admin-refresh ${disabled()}>Обновить экран</button></div>` : ''}${loading && !panel ? '<div class="adm-loading" role="status">Открываем панель команды…</div>' : ''}<div class="adm-content">${shortcuts}${w?.prefix_preview?`<div class="adm-prefix-preview"><small>Так будет выглядеть префикс</small><p>${NoraPrefix(w.prefix_preview)||'<span class="sub">Без плашки</span>'} Имя участника</p></div>`:''}${content}${panel?.form ? composer() : ''}</div>${working ? '<p class="adm-progress" role="status">Выполняем действие…</p>' : ''}</div></div>`;
  }
  async function search(e) {
    e.preventDefault(); if (working || loading) return;
    const query = $('#adm-search-query').value.trim(); directoryQuery = query;
    if (query.length < 2 && !/^\d+$/.test(query)) { toast('Введи имя, @username или Telegram ID'); return; }
    const target = panel.workspace.tools.find(t => t.id === 'search'); if (!target) return;
    working = true; error = ''; redraw();
    try {
      const form = await api('admin/action', {action:target.action, version:panel.version});
      show(form);
      if (!form.form) throw Error('Поиск недоступен. Обнови панель');
      show(await api('admin/input', {form:form.form, version:form.version, text:query}));
      focusAfter = 'heading';
    } catch (e) { error = e.message; } finally { working = false; redraw(); }
  }
  async function submit(e) {
    e.preventDefault(); if (working || loading || !panel?.form) return;
    draft.text = $('#admin-text').value;
    const {text, file, format} = draft;
    if (!text.trim() && !file) { toast('Заполни поле или выбери файл'); return; }
    if (file && file.size > 20 * 1024 * 1024) { toast('Файл должен быть не больше 20 МБ'); return; }
    let kind = draft.kind;
    if (kind === 'auto' && file) kind = file.type.startsWith('image/') ? (file.type === 'image/gif' ? 'animation' : 'photo') : file.type.startsWith('video/') ? 'video' : file.type.startsWith('audio/') ? 'audio' : 'document';
    const body = {form:panel.form, version:panel.version, text, format};
    working = true; error = ''; redraw();
    try {
      let next;
      if (file) {
        const r = await fetch('/api/admin/upload', {method:'POST', headers:{Authorization:'tma ' + auth,
          'Content-Type':'application/octet-stream', 'X-Admin-Form':body.form, 'X-Admin-Version':body.version,
          'X-Admin-Caption':encodeURIComponent(text), 'X-Admin-Format':format, 'X-Admin-Media':kind}, body:file});
        next = await r.json(); if (!r.ok) throw Error(next.error || 'Не удалось загрузить вложение');
      } else next = await api('admin/input', body);
      // Validation errors from existing handlers keep the same form open and retain the input.
      show(next, next.state === panel.state && next.workspace?.form_kind === panel.workspace?.form_kind);
      focusAfter = next.form ? 'input' : 'heading';
    } catch (e) { error = e.message; toast(e.message); } finally { working = false; redraw(); }
  }
  function mount() {
    const form = $('#admin-input'); if (form) form.onsubmit = submit;
    const find = $('#adm-search'); if (find) find.onsubmit = search;
    for (const details of document.querySelectorAll('[data-adm-group]')) details.ontoggle = () => {
      if (!details.isConnected) return;
      if (details.open) expanded.add(details.dataset.admGroup); else expanded.delete(details.dataset.admGroup);
    };
    for (const holder of document.querySelectorAll('[data-admin-media]')) loadMedia(holder);
    if (!working && !loading && focusAfter) {
      const target = focusAfter === 'input' ? $('#admin-text') : focusAfter === 'heading' ? $('#adm-heading') :
        Array.from(document.querySelectorAll('[data-control-label]')).find(el => el.dataset.controlLabel === focusAfter);
      target?.focus({preventScroll:true}); focusAfter = '';
    }
  }
  async function loadMedia(holder) {
    if (holder.dataset.started) return; holder.dataset.started = '1';
    try {
      const r = await fetch('/api/admin/media/' + encodeURIComponent(holder.dataset.adminMedia), {headers:{Authorization:'tma ' + auth}});
      if (!r.ok) throw Error('Вложение недоступно');
      const blob = await r.blob(), url = URL.createObjectURL(blob), kind = holder.dataset.kind;
      if (!holder.isConnected) { URL.revokeObjectURL(url); return; } mediaURLs.push(url);
      let child;
      if (['photo','sticker'].includes(kind)) { child = document.createElement('img'); child.alt = 'Вложение'; }
      else if (['video','video_note','animation','audio','voice'].includes(kind)) {
        child = document.createElement(['video','video_note','animation'].includes(kind) ? 'video' : 'audio'); child.controls = true; child.preload = 'metadata';
      } else { child = document.createElement('a'); child.href = url; child.download = 'nora-attachment'; child.textContent = 'Скачать вложение'; child.className = 'adm-file'; }
      if (child.tagName !== 'A') child.src = url; holder.replaceChildren(child);
    } catch { holder.textContent = 'Не удалось открыть вложение. Обнови панель.'; }
  }
  document.addEventListener('input', e => {
    if (e.target.id === 'admin-text') draft.text = e.target.value;
    if (e.target.id === 'adm-search-query') directoryQuery = e.target.value;
  });
  document.addEventListener('change', e => {
    if (e.target.id === 'admin-html') draft.format = e.target.checked ? 'html' : 'plain';
    if (e.target.id === 'admin-kind') draft.kind = e.target.value;
    if (e.target.id === 'admin-file') {
      const file = e.target.files[0] || null;
      if (file && file.size > 20 * 1024 * 1024) { toast('Файл должен быть не больше 20 МБ'); e.target.value = ''; return; }
      draft.file = file;
    }
  });
  document.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.admIdentity) {
      const id = b.dataset.admIdentity, open = !expandedPeople.has(id);
      if (open) expandedPeople.add(id); else expandedPeople.delete(id);
      for (const row of document.querySelectorAll(`[data-adm-person-row="${id}"]`)) {
        row.querySelector('.adm-person-info').setAttribute('aria-expanded', String(open));
        row.querySelector('.adm-person-contact').hidden = !open;
      }
    }
    if (b.dataset.adminAction) { focusAfter = b.dataset.controlLabel || 'heading'; act(b.dataset.adminAction); }
    if (b.dataset.admGo) act(b.dataset.admGo, true);
    if (b.hasAttribute('data-admin-refresh')) load();
    if (b.hasAttribute('data-adm-menu')) { menuOpen = !menuOpen; redraw(); }
    if (b.hasAttribute('data-adm-cancel') && canLeave()) {
      const item = panel.workspace.navigation.find(n => n.id === panel.workspace.section);
      if (item) act(item.action); else load(true);
    }
    if (b.hasAttribute('data-adm-remove-file')) { draft.file = null; redraw(); }
    if (b.dataset.adminFormat) {
      const input = $('#admin-text'), tag = b.dataset.adminFormat; if (!input) return;
      const a = input.selectionStart, z = input.selectionEnd;
      input.setRangeText(`<${tag}>${input.value.slice(a,z)}</${tag}>`, a, z, 'select');
      draft.text = input.value; draft.format = 'html'; $('#admin-html').checked = true; input.focus();
    }
  });
  return {render:renderPanel, mount};
})();
