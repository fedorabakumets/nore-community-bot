'use strict';
window.NoraCabinet=(()=>{
  let history=null,noticeData=null,noticeLoading=false,pending=false,themePending=false;
  const help={
    fill:[NoraI18n.t("Заполнение профиля"),NoraI18n.t("Пять блоков: имя, дата рождения, увлечения, описание и фото. Все заполнены — 100%. За первое полное заполнение начисляется 10 🍪 один раз; после этого открываются Комьюнити, магазин, события и игры.")],
    cap:[NoraI18n.t("Потолок репутации"),NoraI18n.t("Пока профиль не заполнен полностью, репутация ограничена бронзой — 69. При 100% заполнении доступен полный диапазон до 100. Автоматический рост за активность ограничен 89; до золота помогает поддержка участников.")],
    warnings:[NoraI18n.t("Предупреждения"),NoraI18n.t("Предупреждения выдаёт модерация. 3 предупреждения — мут на 24 часа, 5 — исключение из чата. Автоматические замечания за короткое описание показываются отдельно в боте.")],
    shields:[NoraI18n.t("Щиты от −реп"),NoraI18n.t("Каждый щит поглощает ровно один −реп и исчезает. Срок действия не ограничен.")],
    minus:[NoraI18n.t("Отрицательная репутация"),NoraI18n.t("Любая команда +реп даёт +5, любая команда −реп снимает 10 репутации. Бронза может только поддерживать участников. С серебра доступно понижение репутации. Себе менять репутацию нельзя; одного человека можно отметить до 10 раз в день в пределах общего лимита.")],
    daily:[NoraI18n.t("Дневные действия"),NoraI18n.t("Ниже 50 репутации чат и действия ограничены. Бронза (50–69) — 1 действие, серебро — 3, золото — 5 в день. Лимиты считаются по часовому поясу сообщества.")],
    tier:[NoraI18n.t("Репутация и скидка"),NoraI18n.t("Ниже 50 — ограниченный статус и запрет писать в чат; бронза: 50–69, серебро: 70–89, золото: 90–100. Скидки: 2%, 5%, 10% у соответствующих уровней. +реп даёт +5, −реп снимает 10. Скидка не применяется к билетам мероприятий и пакетам печенек.")],
    starter:[NoraI18n.t("НОРА — СТАРТЕР-ПАК"),NoraI18n.t("Это возвратные 100 🍪 для старта, а не подарок. Полная сумма возврата, комиссия по уровню и срок показаны до получения. При наступлении срока сумма списывается автоматически; недостающее становится долгом. Новый пак недоступен, пока предыдущий не закрыт.")]
  };
  const q=key=>`<button class="stat-help" data-help="${key}" aria-label="${NoraI18n.html("Пояснение:")} ${esc(help[key]?.[0]||key)}">?</button>`;
  function icon(kind){const paths={bell:'M5 17h14l-2-3V9a5 5 0 0 0-10 0v5z M10 20h4',history:'M3 12a9 9 0 1 0 3-7 M3 3v5h5 M12 7v5l3 2',send:'m3 11 18-8-8 18-2-8z M11 13 21 3'};return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[kind]||paths.bell}"/></svg>`}
  function header(){return `<button class="notice-icon ${tab==='notices'?'selected':''}" data-tab="notices" aria-label="${NoraI18n.html("Уведомления")}${data.unread_notices?NoraI18n.t(", непрочитанных ")+data.unread_notices:''}">${icon('bell')}${data.unread_notices?`<span class="notice-badge">${data.unread_notices>99?'99+':number(data.unread_notices)}</span>`:''}</button>`}
  function statRow(label,value,key){return `<p><span>${label} ${q(key)}</span><b>${value}</b></p>`}
  function profileIcon(kind){const paths={gear:'M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1z M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8',camera:'M3 7h4l2-3h6l2 3h4v14H3z M12 10a4 4 0 1 0 0 8 4 4 0 0 0 0-8',edit:'m4 16 12-12 4 4L8 20H4z M14 6l4 4',lock:'M5 10h14v11H5z M8 10V7a4 4 0 0 1 8 0v3',cookie:'M21 12a9 9 0 1 1-9-9 4 4 0 0 0 4 4 4 4 0 0 0 5 5z M8 9h.01 M7 15h.01 M13 17h.01 M12 12h.01',shield:'m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6z',tag:'M3 3h8l10 10-8 8L3 11z M7 7h.01',check:'m4 12 5 5L20 6',close:'m6 6 12 12 M6 18 18 6'};return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[kind]||paths.check}"/></svg>`}
  const medal=()=>Number(data.user.reputation)>=90?'🥇':Number(data.user.reputation)>=70?'🥈':Number(data.user.reputation)>=50?'🥉':'🔞';
  function sheetHeading(title){return `<div class="lk-sheet"><div class="lk-sheet-handle"></div><div class="lk-sheet-heading"><h2>${title}</h2><button data-lk-close aria-label="${NoraI18n.html("Закрыть")}">${profileIcon('close')}</button></div></div>`}
  function profileScreen(u){
    const p=data.profile,name=u.profile_name||u.telegram_name||NoraI18n.t("Друг"),age=Number(u.age);
    const years=plural(age,NoraI18n.t("год"),NoraI18n.t("года"),NoraI18n.t("лет"));
    const hobbies=String(u.hobbies||'').split(/[,;\n]+/).map(s=>s.trim()).filter(Boolean);
    const row=(attrs,art,title,subtitle,badge='',cls='')=>`<button class="lk-row ${cls}" ${attrs}><span class="lk-row-icon">${art}</span><span class="lk-row-copy"><b>${title}</b><small>${subtitle}</small></span>${badge}<span class="lk-chevron" aria-hidden="true">›</span></button>`;
    const field=(label,value)=>`<div class="tg-profile-field"><span>${label}</span><div>${value}</div></div>`;
    const action=(attrs,art,label,value='')=>`<button type="button" class="tg-profile-action" ${attrs} aria-label="${esc(label)}" title="${esc(label)}"><span class="tg-profile-action-icon">${art}</span>${value!==''?`<small>${value}</small>`:''}</button>`;
    return `<section class="lk-screen"><div class="lk-title nora-page-heading"><h1>${NoraI18n.html("Профиль")}</h1></div>
      <section class="lk-identity"><div class="lk-photo-wrap"><button type="button" class="profile-photo" id="profile-photo" aria-label="${NoraI18n.html("Открыть фото профиля")}">${esc((name.match(/[\p{L}\p{N}]/u)?.[0]||'?').toUpperCase())}</button><button id="change-avatar" aria-label="${data.has_avatar?NoraI18n.t("Заменить"):NoraI18n.t("Установить")} ${NoraI18n.html("фото")}" title="${NoraI18n.html("Фото до")} ${AVATAR_MAX_MB} ${NoraI18n.html("МБ")}">${profileIcon('camera')}</button></div>
      <div class="lk-identity-copy"><div class="lk-identity-heading"><h2>${esc(name)}</h2>${tgkLink(u.tg_channel_url)}<button data-lk-settings aria-label="${NoraI18n.html("Настройки профиля")}">${profileIcon('gear')}</button></div><div class="lk-person-meta">${NoraPrefix(p.prefix)||`<span class="lk-role">${esc(NoraI18n.t(p.role))}</span>`}<span class="social-like-count" aria-label="${NoraI18n.html("Лайки:")} ${number(p.likes??0)}">${profileLikeText(p.likes)}</span></div></div>${NoraProfileTrack.html(data.profile_track, '/api/profile/track')}${NoraProfileTrack.libraryButton()}<div class="tg-profile-actions">${action('id="edit-profile"',profileIcon('edit'),NoraI18n.t("изменить"))}${action('data-tab="wallet"',profileIcon('cookie'),NoraI18n.t("кошелёк"),number(u.cookies))}${action('data-lk-reputation',profileIcon('shield'),NoraI18n.t("репутация"),number(u.reputation))}${action('data-presence-settings',profileIcon('lock'),u.profile_private?NoraI18n.t("Приватность: скрыт"):NoraI18n.t("Приватность: открыт"))}</div><div class="tg-profile-fields">${field(NoraI18n.t("о себе"),esc(u.profile_bio||NoraI18n.t("Добавь пару слов о себе.")))}${field(NoraI18n.t("день рождения"),u.birth_date?`<time datetime="${esc(u.birth_date)}">${esc(u.birth_date.split('-').reverse().join('.'))}</time>${age?' · '+number(age)+' '+years:''}`:(age?number(age)+' '+years:NoraI18n.t("Не указана")))}${field(NoraI18n.t("город"),esc(u.city||NoraI18n.t("Не указан")))}${field(NoraI18n.t("увлечения"),hobbies.length?`<div class="lk-hobbies">${hobbies.slice(0,2).map(h=>`<span>${esc(h)}</span>`).join('')}${hobbies.length>2?`<button data-lk-hobbies aria-label="${NoraI18n.html("Все увлечения")}">+${hobbies.length-2}</button>`:''}</div>`:NoraI18n.t("Не указаны"))}</div><input hidden type="file" id="avatar-file" accept="${AVATAR_ACCEPT}"></section><section class="lk-account tg-profile-economy" aria-label="${NoraI18n.html("Репутация и лимиты")}"><button class="lk-summary" data-lk-reputation>${profileIcon('tag')}<span><strong>${esc(NoraI18n.t(p.tier))} ${NoraI18n.html("· скидка")} ${number(p.discount)}%</strong><small>${NoraI18n.html("Осталось")} ${number(p.actions_left)} ${NoraI18n.html("из")} ${number(p.daily_actions)} ${NoraI18n.html("действий")}</small></span><span class="lk-chevron" aria-hidden="true">›</span></button><button class="lk-completion" data-lk-reputation><span class="${p.fill_percent===100?'lk-complete-icon':'lk-pending-icon'}">${profileIcon('check')}</span><span>${NoraI18n.html("Профиль заполнен на")} ${number(p.fill_percent)}%</span><span class="lk-chevron" aria-hidden="true">›</span></button></section><div class="lk-group">${row('data-tab="pet"',navIcon('pet'),NoraI18n.t("Питомец"),data.pet?esc(data.pet.name):NoraI18n.t("Выбрать питомца в магазине"))}${row('data-tab="community"',navIcon('community'),NoraI18n.t("Коммьюнити"),NoraI18n.t("Друзья и команда Норы"))}</div>
      <div class="lk-group lk-settings-group">${row('data-tab="notices"',icon('bell'),NoraI18n.t("Уведомления"),data.unread_notices?`${NoraI18n.html("Непрочитанных:")} <span class="lk-unread-count">${number(data.unread_notices)}</span>`:NoraI18n.t("Новости и настройки"),'',data.unread_notices?'lk-row-glow':'')}${row('data-lk-privacy',profileIcon('lock'),NoraI18n.t("Приватность"),NoraI18n.t("Профиль и активность"))}${data.admin_available?row('data-tab="admin"',profileIcon('shield'),NoraI18n.t("Админ-панель"),NoraI18n.t("Очередь, люди, чат и система"),`<span class="lk-admin-role">${NoraPrefix(p.prefix)||`<span class="lk-role">${esc(NoraI18n.t(p.role))}</span>`}</span>`):''}</div>
      </section>`;
  }
  function reputationSheet(){const u=data.user,p=data.profile;sheet(`${sheetHeading(NoraI18n.t("Репутация и лимиты"))}<section class="lk-reputation"><div class="lk-rep-overview"><span class="lk-medal" aria-hidden="true">${medal()}</span><div><b class="lk-tier">${esc(NoraI18n.t(p.tier))}</b><strong>${number(u.reputation)} / 100</strong><small>${NoraI18n.html("Скидка в магазине")} ${number(p.discount)}%</small></div><progress max="100" value="${Math.min(100,Math.max(0,Number(u.reputation)))}" aria-label="${NoraI18n.html("Репутация")}"></progress></div><div class="lk-limit-list">${statRow(NoraI18n.t("Действий осталось сегодня"),number(p.actions_left)+' / '+number(p.daily_actions),'daily')}${statRow(NoraI18n.t("Запросов к Норе ИИ в день"),number(p.ai_daily_requests),'ai')}${statRow(NoraI18n.t("Потолок репутации"),number(p.reputation_cap),'cap')}${statRow(NoraI18n.t("Предупреждения"),number(u.warnings),'warnings')}${statRow(NoraI18n.t("Щиты от −реп"),number(u.hate_shields),'shields')}${statRow(NoraI18n.t("Можно ставить −реп"),p.can_minus?NoraI18n.t("Да"):NoraI18n.t("Нет"),'minus')}</div><div class="lk-fill"><div><b>${NoraI18n.html("Заполнение профиля")} ${q('fill')}</b><strong>${number(p.fill_percent)}%</strong></div><div class="lk-fill-checks">${p.blocks.map(x=>`<span class="${x.filled?'filled':''}"><i>${x.filled?'✓':'○'}</i> ${esc(NoraI18n.t(x.title))}</span>`).join('')}</div>${p.fill_percent<100?("<button class=\"lk-edit\" id=\"edit-profile\">" + NoraI18n.html("Заполнить профиль") + "</button>"):''}</div><button class="text-btn lk-levels" data-lk-levels>${NoraI18n.html("Все уровни и возможности ›")}</button><p class="footer-note lk-reset">${NoraI18n.html("↻ Обновление лимитов ·")} ${esc(p.timezone==='Europe/Moscow'?NoraI18n.t("Москва"):p.timezone)}</p></section>`)}
  function themePicker() {
    const title = NoraI18n.html("Цвет оформления");
    const selected = profileTheme(data.profile) || 'black';
    const options = Object.entries(profileThemes).map(([theme, label]) =>
      `<button type="button" data-lk-theme="${theme}" aria-pressed="${theme === selected}"${themePending?' disabled':''}><span class="lk-theme-swatch" aria-hidden="true"></span>${NoraI18n.html(label)}</button>`
    ).join('');
    return `<section class="lk-theme-picker"><h3>${title}</h3><p class="sub">${NoraI18n.html("Один цвет для приложения и твоей карточки профиля.")}</p><div class="lk-theme-options" role="group" aria-label="${title}">${options}</div><p class="lk-theme-status" role="status" hidden></p></section>`;
  }
  document.addEventListener('click', async event => {
    const button = event.target.closest('button[data-lk-theme]');
    if (!button || themePending || button.getAttribute('aria-pressed') === 'true') return;
    const status = button.closest('.lk-theme-picker').querySelector('.lk-theme-status');
    const paint = () => {
      const selected = profileTheme(data.profile) || 'black';
      document.querySelectorAll('[data-lk-theme]').forEach(option => {
        option.disabled = themePending;
        option.setAttribute('aria-pressed', String(option.dataset.lkTheme === selected));
      });
    };
    themePending = true;
    status.hidden = true;
    paint();
    try {
      const result = await api('profile/theme', {theme: button.dataset.lkTheme});
      data.profile.theme = result.theme;
      applyProfileTheme(data.profile);
    } catch (error) {
      status.textContent = error.message;
      status.hidden = false;
    } finally {
      themePending = false;
      paint();
      if (button.isConnected && $('#sheet').open) button.focus({preventScroll:true});
    }
  });
  function settingsSheet(){sheet(`${sheetHeading(NoraI18n.t("Настройки профиля"))}${themePicker()}<div class="lk-settings-actions"><button class="secondary" id="edit-profile">${NoraI18n.html("Редактировать профиль")}</button><button class="secondary" data-lk-avatar>${data.has_avatar?NoraI18n.t("Заменить"):NoraI18n.t("Установить")} ${NoraI18n.html("фото")}</button><button class="secondary" data-presence-settings>${NoraI18n.html("Приватность и активность")}</button><button class="secondary" data-music-library>${NoraI18n.html("Мои треки и публичность")}</button><button class="secondary" data-lk-notices>${NoraI18n.html("Уведомления")}</button></div><p class="footer-note">${NoraI18n.html("Фото до")} ${AVATAR_MAX_MB} ${NoraI18n.html("МБ. Подойдут и оригиналы с камеры.")}<br>${NoraI18n.html("Профиль общий с ботом.")}</p>`)}
  function walletScreen() {
    const w = data.wallet, u = data.user;
    return `<button class="text-btn" data-tab="lk">${NoraI18n.html("← Личный кабинет")}</button>
      <h1><em>${NoraI18n.html("Кошелёк")}</em></h1>
      <div class="balance"><small>${NoraI18n.html("Доступно")}</small><strong>${number(u.cookies)} 🍪</strong>
        ${u.cookie_debt ? `<p class="sub">${NoraI18n.html("Просроченный долг ·")} ${number(u.cookie_debt)} 🍪</p>` : ''}
      </div>
      <div class="wallet-actions">
        <button class="primary" id="wallet-topup">${NoraI18n.html("Пополнить")}</button>
        <button class="secondary" id="wallet-transfer">${NoraI18n.html("Перевести")} ${icon('send')}</button>
      </div>
      <section class="wallet-recent" aria-labelledby="wallet-recent-title">
        <h2 id="wallet-recent-title">${NoraI18n.html("Последние операции")}</h2>
        ${data.history.length ? transactionList(data.history) : ("<p class=\"sub\">" + NoraI18n.html("Операций пока нет.") + "</p>")}
        <button class="secondary" data-tab="history">${NoraI18n.html("Вся история")} ${icon('history')}</button>
      </section>
      <section class="card starter-card">
        <h2>${NoraI18n.html("Стартер-пак")} ${q('starter')}</h2>
        ${w.active ? `<p>${NoraI18n.html("К возврату")} <b>${number(w.active.due_amount)} 🍪</b></p>
          <p class="sub">${NoraI18n.html("До")} ${esc(new Date(w.active.due_at).toLocaleString(NoraI18n.locale))}</p>
          <button class="primary" id="wallet-repay">${NoraI18n.html("Вернуть стартер-пак")}</button>`
          : u.cookie_debt ? ("<button class=\"primary\" id=\"wallet-repay\">" + NoraI18n.html("Погасить долг") + "</button>")
          : `<p class="sub">${number(w.principal)} ${NoraI18n.html("🍪 на")} ${number(w.days)} ${plural(w.days,NoraI18n.t("день"),NoraI18n.t("дня"),NoraI18n.t("дней"))} ${NoraI18n.html("· комиссия")} ${number(w.interest_percent)}%<br>
            ${NoraI18n.html("К возврату")} <b>${number(w.repay_amount)} 🍪</b></p>
            <button class="secondary" id="wallet-starter">${NoraI18n.html("Получить с возвратом")}</button>`}
      </section>`;
  }
  const historyFilters = {all:NoraI18n.t("Все"), incoming:NoraI18n.t("Поступления"), outgoing:NoraI18n.t("Списания"), transfers:NoraI18n.t("Переводы")};

  function transactionList(items) {
    const options = {timeZone: data.profile.timezone};
    const dayFormat = new Intl.DateTimeFormat(NoraI18n.locale, {...options, day:'numeric', month:'long', year:'numeric'});
    const timeFormat = new Intl.DateTimeFormat(NoraI18n.locale, {...options, hour:'2-digit', minute:'2-digit'});
    let previousDay;
    return items.map(item => {
      const stamp = new Date(item.date);
      const validDate = Number.isFinite(stamp.getTime());
      const day = validDate ? dayFormat.format(stamp) : NoraI18n.t("Дата неизвестна");
      const heading = day === previousDay ? '' : `<h3 class="wallet-date">${esc(day)}</h3>`;
      previousDay = day;
      const sign = item.amount > 0 ? '+' : item.amount < 0 ? '−' : '';
      return `${heading}<div class="transaction wallet-transaction">
        <span class="tx-icon" aria-hidden="true">${item.amount > 0 ? '↙' : item.amount < 0 ? '↗' : '·'}</span>
        <div class="tx-info">
          <b>${esc(NoraI18n.t(item.label))}</b>
          <span class="wallet-source">${esc(NoraI18n.server(item.source))}</span>
          ${validDate ? `<time datetime="${esc(item.date)}">${esc(timeFormat.format(stamp))}</time>` : ''}
        </div>
        <strong class="${item.amount > 0 ? 'wallet-incoming' : ''}">${sign}${number(Math.abs(item.amount))} 🍪</strong>
      </div>`;
    }).join('');
  }

  function newHistory(direction) {
    const state = {direction, items:[], next:null, loading:true, error:''};
    history = state;
    queueMicrotask(() => loadHistory(state));
  }

  function historyScreen() {
    if (!history) newHistory('all');
    const {direction, items, next, loading, error} = history;
    return `<button class="text-btn" data-tab="wallet">${NoraI18n.html("← Кошелёк")}</button>
      <h1><em>${NoraI18n.html("История операций")}</em></h1>
      <div class="wallet-filters" role="group" aria-label="${NoraI18n.html("Фильтр операций")}">
        ${Object.entries(historyFilters).map(([key,label]) => `
          <button class="secondary" data-history-filter="${key}" aria-pressed="${key === direction}">${label}</button>
        `).join('')}
      </div>
      <section aria-busy="${loading}" aria-label="${NoraI18n.html("Операции кошелька")}">
        ${items.length ? transactionList(items) : !loading && !error ? ("<p class=\"empty\">" + NoraI18n.html("В этой категории пока нет операций.") + "</p>") : ''}
      </section>
      ${loading ? ("<p class=\"sub\" role=\"status\">" + NoraI18n.html("Загружаем операции…") + "</p>") : ''}
      ${error ? `<p class="sub" role="alert">${esc(error)}</p>` : ''}
      ${next || error ? `<button class="secondary wallet-more" id="history-more" ${loading ? 'disabled' : ''}>${error ? NoraI18n.t("Повторить") : NoraI18n.t("Показать ещё")}</button>` : ''}`;
  }

  async function loadHistory(state) {
    if (history !== state || tab !== 'history') return;
    const query = new URLSearchParams({direction:state.direction});
    if (state.next) query.set('before', state.next);
    try {
      const page = await api('wallet/history?' + query);
      state.items.push(...page.items);
      state.next = page.next_before;
    } catch (error) {
      state.error = error.message || NoraI18n.t("История пока недоступна.");
    } finally {
      state.loading = false;
      if (tab === 'history' && history === state) render();
    }
  }

  function syncHistory() {
    if (tab !== 'history') history = null;
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (tab !== 'history' || !button || !history) return;
    const direction = button.dataset.historyFilter;
    if (direction && direction !== history.direction) {
      newHistory(direction);
      render();
    } else if (button.id === 'history-more' && !history.loading) {
      history.loading = true;
      history.error = '';
      render();
      void loadHistory(history);
    }
  });
  function noticesScreen(){if(!noticeData&&!noticeLoading)queueMicrotask(loadNotices);const items=(noticeData?.items||[]).filter(n=>!n.profile_invite||data.profile.fill_percent<100);return `<p class="eyebrow">${NoraI18n.html("Ничего лишнего")}</p><h1><em>${NoraI18n.html("Уведомления")}</em></h1>${noticeLoading?("<p class=\"sub\">" + NoraI18n.html("Проверяем новости…") + "</p>"):''}${noticeData?.birthday_gift_day?`<article class="card notice-item unread"><small>${NoraI18n.html("🎁 Подарок от НОРЫ")}</small><h2>${NoraI18n.html("500 🍪 ждут тебя!")}</h2><p>${NoraI18n.html("Один подарок, общий для бота и мини-приложения.")}</p><button class="primary" data-birthday-claim="${esc(noticeData.birthday_gift_day)}">${NoraI18n.html("Получить подарок")}</button></article>`:''}${(noticeData?.mafia_invites||[]).map(i=>NoraInteractive.invitationCard(i)).join('')}${(noticeData?.sea_invites||[]).map(i=>NoraSea.inviteCard(i)).join('')}<div class="notice-list">${items.length?items.map(n=>`<article class="card notice-item ${n.read?'':'unread'}"><small>${esc(new Date(n.created_at).toLocaleString(NoraI18n.locale))}${n.read?'':NoraI18n.t(" · новое")}</small><p>${esc(n.text)}</p>${n.profile_invite?`<div class="pet-action-row"><button class="primary" data-tab="lk">${NoraI18n.html("Открыть профиль")}</button><button class="secondary" data-dismiss-profile-invite>${NoraI18n.html("Закрыть")}</button></div>`:''}${n.mafia_invite?NoraInteractive.invitationCard(n.mafia_invite):''}${n.sea_invite?NoraSea.inviteCard(n.sea_invite):''}${n.barricade_invite?`<button class="primary" data-tab="barricade" data-barricade-invite="${esc(n.barricade_invite)}">${NoraI18n.html("Посмотреть комнату")}</button>`:''}${n.durak_invite?`<button class="primary" data-tab="durak" data-durak-invite="${esc(n.durak_invite)}">${NoraI18n.html("Посмотреть стол")}</button>`:''}</article>`).join(''):("<p class=\"sub\">" + NoraI18n.html("Пока тихо. Выбери ниже, что тебе интересно.") + "</p>")}</div><h2>${NoraI18n.html("Что присылать")}</h2>${(noticeData?.channels||[]).map(c=>`<section class="card notice-channel"><h3>${esc(c.title)}</h3><p class="sub">${esc(c.description)}</p><label><span>${NoraI18n.html("Получать уведомления")}</span><input type="checkbox" data-notice-channel="${esc(c.id)}" data-notice-field="enabled" ${c.enabled?'checked':''}></label>${c.widget?'':`<label><span>${NoraI18n.html("Собирать в дайджест")}</span><input type="checkbox" data-notice-channel="${esc(c.id)}" data-notice-field="digest" ${c.digest?'checked':''}></label>`}</section>`).join('')}<p class="footer-note">${NoraI18n.html("Настройки общие с ботом. Служебные сообщения модерации и решения по оплатам приходят отдельно.")}</p>`}
  async function loadNotices(){if(noticeLoading)return;noticeLoading=true;try{noticeData=await api('notices');data.unread_notices=noticeData.unread;if(noticeData.unread){noticeData.items.forEach(n=>n.read=true);noticeData.unread=0;data.unread_notices=0;api('notices',{action:'read',through_id:Math.max(0,...noticeData.items.map(n=>n.id))}).catch(()=>{})}}catch(e){toast(e.message);noticeData={items:[],channels:[]}}finally{noticeLoading=false;if(tab==='notices')render()}}
  async function petAction(action,name){if(busy||pending)return;pending=true;const buttons=[...document.querySelectorAll('[data-pet-action],#pet-name-form button')].map(el=>[el,el.disabled]);buttons.forEach(([el])=>el.disabled=true);try{const q=await api('pet/prepare',{action,...(name?{name}:{}),...(action==='return'?{expedition_until:data.pet?.expedition_until}:{})});await perform('pet/action',{token:q.token})}catch(e){toast(e.message)}finally{pending=false;buttons.forEach(([el,disabled])=>{if(el.isConnected)el.disabled=disabled})}}
  async function prepareWallet(action,body={}){if(busy||pending)return;pending=true;try{const q=await api('wallet/prepare',{action,...body});const desc=action==='transfer'?`${NoraI18n.html("Списать")} ${number(q.amount)} 🍪. ${esc(q.recipient)} ${NoraI18n.html("получит")} ${number(q.received)} 🍪.<br>${NoraI18n.html("Комиссия")} ${number(q.percent)}%.`:action==='starter_pack'?`${NoraI18n.html("Получить")} ${number(q.amount)} ${NoraI18n.html("🍪 на")} ${number(q.days)} ${plural(q.days,NoraI18n.t("день"),NoraI18n.t("дня"),NoraI18n.t("дней"))}.<br>${NoraI18n.html("Комиссия")} ${number(q.percent)}${NoraI18n.html("%. Вернуть нужно")} <b>${number(q.due_amount)} 🍪</b>.<br>${NoraI18n.html("По окончании срока сумма списывается, недостающее становится долгом.")}`:`${NoraI18n.t("Вернуть")} ${number(q.amount)} ${NoraI18n.t("🍪 из общего кошелька.")}${q.remaining_debt?NoraI18n.t(" Остаток долга: ")+number(q.remaining_debt)+' 🍪.':''}`;sheet(`<span class="eyebrow">${NoraI18n.html("Проверим условия")}</span><h2>${action==='starter_pack'?NoraI18n.t("НОРА — СТАРТЕР-ПАК"):action==='transfer'?NoraI18n.t("Перевод участнику"):NoraI18n.t("Возврат печенек")}</h2><p class="sub">${desc}</p><button class="primary" id="pay">${action==='starter_pack'?NoraI18n.t("Подтвердить получение с возвратом"):NoraI18n.t("Подтвердить")}</button>`);$('#pay').onclick=()=>perform('wallet/confirm',{token:q.token})}catch(e){toast(e.message)}finally{pending=false}}
  async function transferForm(chosen=null){if(pending||busy)return;pending=true;try{const f=await api('friends');const list=f.friends;const selected=chosen&&list.some(p=>p.id===chosen.id)?chosen.id:null;sheet(`<span class="eyebrow">${NoraI18n.html("Из общего кошелька")}</span><h2>${NoraI18n.html("Перевести печеньки")}</h2><form id="transfer-form"><label>${NoraI18n.html("Получатель")}<select id="transfer-friend" name="friend_id">${list.length?("<option value=\"\">" + NoraI18n.html("Выбери друга") + "</option>"):''}${list.map(p=>`<option value="${p.id}" ${selected===p.id?'selected':''}>${esc(p.name)}${p.username?' · @'+esc(p.username):''}</option>`).join('')}<option value="manual" ${!list.length?'selected':''}>${NoraI18n.html("По нику или ID")}</option></select></label><label id="transfer-recipient-label" ${list.length?'hidden':''}>${NoraI18n.html("Ник или ID")}<input name="recipient" maxlength="40" placeholder="${NoraI18n.html("@username или Telegram ID")}" ${list.length?'disabled':'required'}></label><label>${NoraI18n.html("Сумма")}<input name="amount" type="number" inputmode="numeric" min="1" max="1000000" required></label><p class="sub">${NoraI18n.html("Комиссию и сумму получателя покажем до списания.")}</p><button class="primary" type="submit">${NoraI18n.html("Посмотреть условия")}</button></form>`);const select=$('#transfer-friend'),input=document.querySelector('#transfer-form [name=recipient]');select.onchange=()=>{const manual=select.value==='manual';$('#transfer-recipient-label').hidden=!manual;input.disabled=!manual;input.required=manual};$('#transfer-form').onsubmit=e=>{e.preventDefault();const f=new FormData(e.target);if(select.value===''){toast(NoraI18n.t("Выбери друга или укажи ник / ID"));return}prepareWallet('transfer',{...(select.value==='manual'?{recipient:f.get('recipient')}:{friend_id:Number(select.value)}),amount:Number(f.get('amount'))})}}catch(e){toast(e.message)}finally{pending=false}}

  function rename(){sheet(`<h2>${NoraI18n.html("Как зовут питомца?")}</h2><form id="pet-name-form"><label>${NoraI18n.html("Имя")}<input name="name" value="${esc(data.pet.name)}" maxlength="24" required></label><button class="primary" type="submit">${NoraI18n.html("Сохранить имя")}</button></form>`);$('#pet-name-form').onsubmit=e=>{e.preventDefault();petAction('rename',new FormData(e.target).get('name'))}}
  function showHelp(key){const item=key==='ai'?[NoraI18n.t("Запросы к Норе ИИ"),(data.levels||[]).map(l=>l.label+' — '+l.ai_daily_requests).join(', ')+NoraI18n.t(". Лимит общий для чата и лички и обновляется в полночь по времени сообщества.")]:help[key],back=!!document.querySelector('.lk-reputation');if(item)sheet(`<span class="eyebrow">${NoraI18n.html("Подсказка Норы")}</span><h2>${esc(item[0])}</h2><p class="sub">${esc(item[1])}</p>${back?("<button class=\"secondary\" data-lk-reputation>" + NoraI18n.html("← Репутация и лимиты") + "</button>"):''}`)}
  function parent(t){return window.NoraInteractive?.parent(t)||{lk:'home',wallet:'lk',history:'wallet',notices:'lk',admin:'lk'}[t]||null}
  document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.help)showHelp(b.dataset.help);if(b.hasAttribute('data-lk-reputation'))reputationSheet();if(b.hasAttribute('data-lk-settings'))settingsSheet();if(b.hasAttribute('data-lk-close'))$('#sheet').close();if(b.hasAttribute('data-lk-levels'))showReputation();if(b.hasAttribute('data-lk-avatar')){$('#sheet').close();$('#avatar-file')?.click()}if(b.hasAttribute('data-lk-notices')){$('#sheet').close();tab='notices';render();loadNotices()}if(b.hasAttribute('data-lk-hobbies'))sheet(`${sheetHeading(NoraI18n.t("Увлечения"))}<p class="lk-all-hobbies">${esc(data.user.hobbies)}</p>`);if(b.hasAttribute('data-open-pet-shop')){if(data.profile.fill_percent<100){toast(NoraI18n.t("Заполни профиль на 100% в ЛК"));return}NoraShop.openCategory('pets')}if(b.dataset.petAction)petAction(b.dataset.petAction);if(b.id==='rename-pet')rename();if(b.id==='wallet-topup'){if(data.profile.fill_percent<100){toast(NoraI18n.t("Заполни профиль на 100% в ЛК"));return}NoraShop.openCategory('__cookies')}if(b.id==='wallet-transfer')transferForm();if(b.dataset.friendTransfer)transferForm({id:Number(b.dataset.friendTransfer),name:b.dataset.friendName});if(b.id==='wallet-starter')prepareWallet('starter_pack');if(b.id==='wallet-repay')prepareWallet('repay');if(b.dataset.tab==='notices'){noticeData=null;loadNotices()}});
  document.addEventListener('change',async e=>{const el=e.target;if(!el.dataset.noticeChannel)return;if(pending)return;const c=noticeData.channels.find(c=>c.id===el.dataset.noticeChannel);if(!c)return;pending=true;el.disabled=true;try{await api('notices',{channel:c.id,enabled:el.dataset.noticeField==='enabled'?el.checked:c.enabled,digest:el.dataset.noticeField==='digest'?el.checked:c.digest});await loadNotices()}catch(err){toast(err.message);el.checked=!el.checked}finally{pending=false;el.disabled=false}});
  document.addEventListener('click',async e=>{const button=e.target.closest('[data-birthday-claim]');if(!button||pending)return;pending=true;button.disabled=true;try{const result=await api('notices',{action:'claim_birthday',day:button.dataset.birthdayClaim});toast(result.message);noticeData=null;await loadNotices();data=await api('me');render()}catch(err){toast(err.message);button.disabled=false}finally{pending=false}});
  document.addEventListener('click',async e=>{
    const button=e.target.closest('[data-dismiss-profile-invite]');
    if(!button||pending)return;
    pending=true;button.disabled=true;
    try{await api('notices',{action:'dismiss_profile_invite'});await loadNotices()}
    catch(err){toast(err.message);button.disabled=false}
    finally{pending=false}
  });
  function refreshCurrent(){if(tab==='notices')loadNotices()}
  return {profileScreen,transferForm,reloadNotices:loadNotices,refreshCurrent,syncHistory,header,walletScreen,historyScreen,noticesScreen,parent,showHelp};
})();
