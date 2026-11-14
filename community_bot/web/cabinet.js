'use strict';
window.NoraCabinet=(()=>{
  let history=null,noticeData=null,noticeLoading=false,pending=false;
  const help={
    fill:['Заполнение профиля','Пять блоков: имя, дата рождения, увлечения, описание и фото. Все заполнены — 100%. За первое полное заполнение начисляется 10 🍪 один раз; после этого открываются Комьюнити, магазин, события и игры.'],
    cap:['Потолок репутации','Пока профиль не заполнен полностью, репутация ограничена бронзой — 69. При 100% заполнении доступен полный диапазон до 100. Автоматический рост за активность ограничен 89; до золота помогает поддержка участников.'],
    warnings:['Предупреждения','Предупреждения выдаёт модерация. 3 предупреждения — мут на 24 часа, 5 — исключение из чата. Автоматические замечания за короткое описание показываются отдельно в боте.'],
    shields:['Щиты от −реп','Один щит поглощает одно отрицательное действие с репутацией и расходуется. Плащ иммунитета защищает в течение времени. Щит и плащ доступны в магазине.'],
    minus:['Отрицательная репутация','Бронза может только поддерживать участников. С серебра доступно понижение репутации. Себе менять репутацию нельзя; одного человека можно отметить до 10 раз в день в пределах общего лимита.'],
    daily:['Дневные действия','Бронза — 1 действие, серебро — 3, золото — 5 в день. Ограничения ниже порога репутации могут отключать взаимодействия. Лимиты считаются по часовому поясу сообщества.'],
    immunity:['Иммунитет','Плащ защищает от отрицательных оценок до указанного времени. При повторной покупке время продлевается. Предупреждения и решения модераторов он не отменяет.'],
    tier:['Репутация и скидка','Бронза: до 69, серебро: 70–89, золото: 90–100. Скидки: 2%, 5%, 10%. Скидка не применяется к билетам мероприятий и пакетам печенек. Нажми на репутацию на главной, чтобы увидеть все уровни.'],
    starter:['НОРА — СТАРТЕР-ПАК','Это возвратные 100 🍪 для старта, а не подарок. Полная сумма возврата, комиссия по уровню и срок показаны до получения. При наступлении срока сумма списывается автоматически; недостающее становится долгом. Новый пак недоступен, пока предыдущий не закрыт.']
  };
  const q=key=>`<button class="stat-help" data-help="${key}" aria-label="Пояснение: ${esc(help[key]?.[0]||key)}">?</button>`;
  function icon(kind){const paths={bell:'M5 17h14l-2-3V9a5 5 0 0 0-10 0v5z M10 20h4',history:'M3 12a9 9 0 1 0 3-7 M3 3v5h5 M12 7v5l3 2',send:'m3 11 18-8-8 18-2-8z M11 13 21 3'};return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[kind]||paths.bell}"/></svg>`}
  function header(){return `<button class="notice-icon ${tab==='notices'?'selected':''}" data-tab="notices" aria-label="Уведомления${data.unread_notices?', непрочитанных '+data.unread_notices:''}">${icon('bell')}${data.unread_notices?`<span class="notice-badge">${data.unread_notices>99?'99+':number(data.unread_notices)}</span>`:''}</button>`}
  function statRow(label,value,key){return `<p><span>${label} ${q(key)}</span><b>${value}</b></p>`}
  function profileIcon(kind){const paths={gear:'M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1z M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8',camera:'M3 7h4l2-3h6l2 3h4v14H3z M12 10a4 4 0 1 0 0 8 4 4 0 0 0 0-8',edit:'m4 16 12-12 4 4L8 20H4z M14 6l4 4',lock:'M5 10h14v11H5z M8 10V7a4 4 0 0 1 8 0v3',shield:'m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6z',tag:'M3 3h8l10 10-8 8L3 11z M7 7h.01',check:'m4 12 5 5L20 6',close:'m6 6 12 12 M6 18 18 6'};return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[kind]||paths.check}"/></svg>`}
  const medal=()=>Number(data.user.reputation)>=90?'🥇':Number(data.user.reputation)>=70?'🥈':'🥉';
  function sheetHeading(title){return `<div class="lk-sheet"><div class="lk-sheet-handle"></div><div class="lk-sheet-heading"><h2>${title}</h2><button data-lk-close aria-label="Закрыть">${profileIcon('close')}</button></div></div>`}
  function profileScreen(u){
    const p=data.profile,name=u.profile_name||u.telegram_name||'Друг',age=Number(u.age),last=age%100;
    const years=last>=11&&last<=14?'лет':age%10===1?'год':age%10>=2&&age%10<=4?'года':'лет';
    const hobbies=String(u.hobbies||'').split(/[,;\n]+/).map(s=>s.trim()).filter(Boolean);
    const row=(attrs,art,title,subtitle,badge='',cls='')=>`<button class="lk-row ${cls}" ${attrs}><span class="lk-row-icon">${art}</span><span class="lk-row-copy"><b>${title}</b><small>${subtitle}</small></span>${badge}<span class="lk-chevron" aria-hidden="true">›</span></button>`;
    return `<section class="lk-screen"><p class="eyebrow season-label">Сезон 1 · Bloody Nora</p><div class="lk-title"><h1>Профиль</h1></div>
      <section class="lk-identity"><div class="lk-photo-wrap"><button type="button" class="profile-photo" id="profile-photo" aria-label="Открыть фото профиля">${esc((name.match(/[\p{L}\p{N}]/u)?.[0]||'?').toUpperCase())}</button><button id="change-avatar" aria-label="${data.has_avatar?'Заменить':'Установить'} фото" title="Фото до 5 МБ">${profileIcon('camera')}</button></div>
      <div class="lk-identity-copy"><div class="lk-identity-heading"><h2>${esc(name)}</h2><button data-lk-settings aria-label="Настройки профиля">${profileIcon('gear')}</button></div><div class="lk-person-meta">${NoraPrefix(p.prefix)||`<span class="lk-role">${esc(p.role)}</span>`}<span>${age?number(age)+' '+years:'Дата рождения не указана'}</span>${u.birth_date?`<time class="lk-birth-date" datetime="${esc(u.birth_date)}">${esc(u.birth_date.split('-').reverse().join('.'))}</time>`:''}</div><p class="lk-bio">${esc(u.profile_bio||'Добавь пару слов о себе.')}</p><div class="lk-hobbies">${hobbies.slice(0,2).map(h=>`<span>${esc(h)}</span>`).join('')}${hobbies.length>2?`<button data-lk-hobbies aria-label="Все увлечения">+${hobbies.length-2}</button>`:''}</div><button class="lk-privacy-pill" data-presence-settings>${profileIcon('lock')}${u.profile_private?'Профиль скрыт':'Профиль открыт'}</button><button class="lk-edit" id="edit-profile">${profileIcon('edit')}Редактировать</button></div><input hidden type="file" id="avatar-file" accept="image/jpeg,image/png,image/webp"></section>
      <div class="lk-tiles"><button class="lk-tile" data-tab="wallet"><span class="lk-tile-art" aria-hidden="true">🍪</span><span><small>Кошелёк</small><b class="${Number(u.cookies)===0?'red-number':''}">${number(u.cookies)} <span aria-hidden="true">🍪</span></b></span><span class="lk-chevron" aria-hidden="true">›</span></button><button class="lk-tile" data-lk-reputation><span class="lk-tile-art" aria-hidden="true">${medal()}</span><span><small>Репутация</small><em>${esc(p.tier)}</em><b class="${Number(u.reputation)<70?'red-number':''}">${number(u.reputation)}<small> / 100</small></b></span><span class="lk-chevron" aria-hidden="true">›</span></button></div>
      <button class="lk-summary" data-lk-reputation>${profileIcon('tag')}<span>Скидка ${number(p.discount)}% · Осталось ${number(p.actions_left)} из ${number(p.daily_actions)} действий</span></button>
      <div class="lk-group">${row('data-tab="pet"',navIcon('pet'),'Питомец',data.pet?esc(data.pet.name):'Выбрать питомца в магазине')}${row('data-tab="community"',navIcon('community'),'Коммьюнити','Друзья и команда Норы')}</div>
      <div class="lk-group lk-settings-group">${row('data-tab="notices"',icon('bell'),'Уведомления',data.unread_notices?`Непрочитанных: <span class="lk-unread-count">${number(data.unread_notices)}</span>`:'Новости и настройки','',data.unread_notices?'lk-row-glow':'')}${row('data-lk-privacy',profileIcon('lock'),'Приватность','Профиль и активность')}${data.admin_available?row('data-tab="admin"',profileIcon('shield'),'Админ-панель','Очередь, люди, чат и система',`<span class="lk-admin-role">${NoraPrefix(p.prefix)||`<span class="lk-role">${esc(p.role)}</span>`}</span>`):''}</div>
      <button class="lk-completion" data-lk-reputation><span class="${p.fill_percent===100?'lk-complete-icon':'lk-pending-icon'}">${profileIcon('check')}</span><span>Профиль заполнен на ${number(p.fill_percent)}%</span><span class="lk-chevron" aria-hidden="true">›</span></button></section>`;
  }
  function reputationSheet(){const u=data.user,p=data.profile;sheet(`${sheetHeading('Репутация и лимиты')}<section class="lk-reputation"><div class="lk-rep-overview"><span class="lk-medal" aria-hidden="true">${medal()}</span><div><b class="lk-tier">${esc(p.tier)}</b><strong>${number(u.reputation)} / 100</strong><small>Скидка в магазине ${number(p.discount)}%</small></div><progress max="100" value="${Math.min(100,Math.max(0,Number(u.reputation)))}" aria-label="Репутация"></progress></div><div class="lk-limit-list">${statRow('Действий осталось сегодня',number(p.actions_left)+' / '+number(p.daily_actions),'daily')}${statRow('Потолок репутации',number(p.reputation_cap),'cap')}${statRow('Предупреждения',number(u.warnings),'warnings')}${statRow('Щиты от −реп',number(u.hate_shields),'shields')}${statRow('Можно ставить −реп',p.can_minus?'Да':'Нет','minus')}${u.hate_immunity_until?statRow('Иммунитет до',esc(new Date(u.hate_immunity_until).toLocaleString('ru-RU',{timeZone:p.timezone})),'immunity'):''}</div><div class="lk-fill"><div><b>Заполнение профиля ${q('fill')}</b><strong>${number(p.fill_percent)}%</strong></div><div class="lk-fill-checks">${p.blocks.map(x=>`<span class="${x.filled?'filled':''}"><i>${x.filled?'✓':'○'}</i> ${esc(x.title)}</span>`).join('')}</div>${p.fill_percent<100?'<button class="lk-edit" id="edit-profile">Заполнить профиль</button>':''}</div><button class="text-btn lk-levels" data-lk-levels>Все уровни и возможности ›</button><p class="footer-note lk-reset">↻ Обновление лимитов · ${esc(p.timezone==='Europe/Moscow'?'Москва':p.timezone)}</p></section>`)}
  function settingsSheet(){sheet(`${sheetHeading('Настройки профиля')}<div class="lk-settings-actions"><button class="secondary" id="edit-profile">Редактировать профиль</button><button class="secondary" data-lk-avatar>${data.has_avatar?'Заменить':'Установить'} фото</button><button class="secondary" data-presence-settings>Приватность и активность</button><button class="secondary" data-lk-notices>Уведомления</button></div><p class="footer-note">Фото до 5 МБ · JPG, PNG или WebP.<br>Профиль общий с ботом.</p>`)}
  function walletScreen() {
    const w = data.wallet, u = data.user;
    return `<button class="text-btn" data-tab="lk">← Личный кабинет</button>
      <h1><em>Кошелёк</em></h1>
      <div class="balance"><small>Доступно</small><strong>${number(u.cookies)} 🍪</strong>
        ${u.cookie_debt ? `<p class="sub">Просроченный долг · ${number(u.cookie_debt)} 🍪</p>` : ''}
      </div>
      <div class="wallet-actions">
        <button class="primary" id="wallet-topup">Пополнить</button>
        <button class="secondary" id="wallet-transfer">Перевести ${icon('send')}</button>
      </div>
      <section class="wallet-recent" aria-labelledby="wallet-recent-title">
        <h2 id="wallet-recent-title">Последние операции</h2>
        ${data.history.length ? transactionList(data.history) : '<p class="sub">Операций пока нет.</p>'}
        <button class="secondary" data-tab="history">Вся история ${icon('history')}</button>
      </section>
      <section class="card starter-card">
        <h2>Стартер-пак ${q('starter')}</h2>
        ${w.active ? `<p>К возврату <b>${number(w.active.due_amount)} 🍪</b></p>
          <p class="sub">До ${esc(new Date(w.active.due_at).toLocaleString('ru-RU'))}</p>
          <button class="primary" id="wallet-repay">Вернуть стартер-пак</button>`
          : u.cookie_debt ? '<button class="primary" id="wallet-repay">Погасить долг</button>'
          : `<p class="sub">${number(w.principal)} 🍪 на ${number(w.days)} ${plural(w.days,'день','дня','дней')} · комиссия ${number(w.interest_percent)}%<br>
            К возврату <b>${number(w.repay_amount)} 🍪</b></p>
            <button class="secondary" id="wallet-starter">Получить с возвратом</button>`}
      </section>`;
  }
  const historyFilters = {all:'Все', incoming:'Поступления', outgoing:'Списания', transfers:'Переводы'};

  function transactionList(items) {
    const options = {timeZone: data.profile.timezone};
    const dayFormat = new Intl.DateTimeFormat('ru-RU', {...options, day:'numeric', month:'long', year:'numeric'});
    const timeFormat = new Intl.DateTimeFormat('ru-RU', {...options, hour:'2-digit', minute:'2-digit'});
    let previousDay;
    return items.map(item => {
      const stamp = new Date(item.date);
      const validDate = Number.isFinite(stamp.getTime());
      const day = validDate ? dayFormat.format(stamp) : 'Дата неизвестна';
      const heading = day === previousDay ? '' : `<h3 class="wallet-date">${esc(day)}</h3>`;
      previousDay = day;
      const sign = item.amount > 0 ? '+' : item.amount < 0 ? '−' : '';
      return `${heading}<div class="transaction wallet-transaction">
        <span class="tx-icon" aria-hidden="true">${item.amount > 0 ? '↙' : item.amount < 0 ? '↗' : '·'}</span>
        <div class="tx-info">
          <b>${esc(item.label)}</b>
          <span class="wallet-source">${esc(item.source)}</span>
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
    return `<button class="text-btn" data-tab="wallet">← Кошелёк</button>
      <h1><em>История операций</em></h1>
      <div class="wallet-filters" role="group" aria-label="Фильтр операций">
        ${Object.entries(historyFilters).map(([key,label]) => `
          <button class="secondary" data-history-filter="${key}" aria-pressed="${key === direction}">${label}</button>
        `).join('')}
      </div>
      <section aria-busy="${loading}" aria-label="Операции кошелька">
        ${items.length ? transactionList(items) : !loading && !error ? '<p class="empty">В этой категории пока нет операций.</p>' : ''}
      </section>
      ${loading ? '<p class="sub" role="status">Загружаем операции…</p>' : ''}
      ${error ? `<p class="sub" role="alert">${esc(error)}</p>` : ''}
      ${next || error ? `<button class="secondary wallet-more" id="history-more" ${loading ? 'disabled' : ''}>${error ? 'Повторить' : 'Показать ещё'}</button>` : ''}`;
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
      state.error = error.message || 'История пока недоступна.';
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
  function noticesScreen(){if(!noticeData&&!noticeLoading)queueMicrotask(loadNotices);const items=(noticeData?.items||[]).filter(n=>!n.profile_invite||data.profile.fill_percent<100);return `<p class="eyebrow">Ничего лишнего</p><h1><em>Уведомления</em></h1>${noticeLoading?'<p class="sub">Проверяем новости…</p>':''}${noticeData?.birthday_gift_day?`<article class="card notice-item unread"><small>🎁 Подарок от НОРЫ</small><h2>500 🍪 ждут тебя!</h2><p>Один подарок, общий для бота и мини-приложения.</p><button class="primary" data-birthday-claim="${esc(noticeData.birthday_gift_day)}">Получить подарок</button></article>`:''}${(noticeData?.mafia_invites||[]).map(i=>NoraInteractive.invitationCard(i)).join('')}${(noticeData?.sea_invites||[]).map(i=>NoraSea.inviteCard(i)).join('')}<div class="notice-list">${items.length?items.map(n=>`<article class="card notice-item ${n.read?'':'unread'}"><small>${esc(new Date(n.created_at).toLocaleString('ru-RU'))}${n.read?'':' · новое'}</small><p>${esc(n.text)}</p>${n.profile_invite?`<div class="pet-action-row"><button class="primary" data-tab="lk">Открыть профиль</button><button class="secondary" data-dismiss-profile-invite>Закрыть</button></div>`:''}${n.mafia_invite?NoraInteractive.invitationCard(n.mafia_invite):''}${n.sea_invite?NoraSea.inviteCard(n.sea_invite):''}</article>`).join(''):'<p class="sub">Пока тихо. Выбери ниже, что тебе интересно.</p>'}</div><h2>Что присылать</h2>${(noticeData?.channels||[]).map(c=>`<section class="card notice-channel"><h3>${esc(c.title)}</h3><p class="sub">${esc(c.description)}</p><label><span>Получать уведомления</span><input type="checkbox" data-notice-channel="${esc(c.id)}" data-notice-field="enabled" ${c.enabled?'checked':''}></label>${c.widget?'':`<label><span>Собирать в дайджест</span><input type="checkbox" data-notice-channel="${esc(c.id)}" data-notice-field="digest" ${c.digest?'checked':''}></label>`}</section>`).join('')}<p class="footer-note">Настройки общие с ботом. Служебные сообщения модерации и решения по оплатам приходят отдельно.</p>`}
  async function loadNotices(){if(noticeLoading)return;noticeLoading=true;try{noticeData=await api('notices');data.unread_notices=noticeData.unread;if(noticeData.unread){noticeData.items.forEach(n=>n.read=true);noticeData.unread=0;data.unread_notices=0;api('notices',{action:'read',through_id:Math.max(0,...noticeData.items.map(n=>n.id))}).catch(()=>{})}}catch(e){toast(e.message);noticeData={items:[],channels:[]}}finally{noticeLoading=false;if(tab==='notices')render()}}
  async function petAction(action,name){if(busy||pending)return;pending=true;const buttons=[...document.querySelectorAll('[data-pet-action],#pet-name-form button')].map(el=>[el,el.disabled]);buttons.forEach(([el])=>el.disabled=true);try{const q=await api('pet/prepare',{action,...(name?{name}:{})});await perform('pet/action',{token:q.token})}catch(e){toast(e.message)}finally{pending=false;buttons.forEach(([el,disabled])=>{if(el.isConnected)el.disabled=disabled})}}
  async function prepareWallet(action,body={}){if(busy||pending)return;pending=true;try{const q=await api('wallet/prepare',{action,...body});const desc=action==='transfer'?`Списать ${number(q.amount)} 🍪. ${esc(q.recipient)} получит ${number(q.received)} 🍪.<br>Комиссия ${number(q.percent)}%.`:action==='starter_pack'?`Получить ${number(q.amount)} 🍪 на ${number(q.days)} ${plural(q.days,'день','дня','дней')}.<br>Комиссия ${number(q.percent)}%. Вернуть нужно <b>${number(q.due_amount)} 🍪</b>.<br>По окончании срока сумма списывается, недостающее становится долгом.`:`Вернуть ${number(q.amount)} 🍪 из общего кошелька.${q.remaining_debt?' Остаток долга: '+number(q.remaining_debt)+' 🍪.':''}`;sheet(`<span class="eyebrow">Проверим условия</span><h2>${action==='starter_pack'?'НОРА — СТАРТЕР-ПАК':action==='transfer'?'Перевод участнику':'Возврат печенек'}</h2><p class="sub">${desc}</p><button class="primary" id="pay">${action==='starter_pack'?'Подтвердить получение с возвратом':'Подтвердить'}</button>`);$('#pay').onclick=()=>perform('wallet/confirm',{token:q.token})}catch(e){toast(e.message)}finally{pending=false}}
  async function transferForm(chosen=null){if(pending||busy)return;pending=true;try{const f=await api('friends');const list=f.friends;const selected=chosen&&list.some(p=>p.id===chosen.id)?chosen.id:null;sheet(`<span class="eyebrow">Из общего кошелька</span><h2>Перевести печеньки</h2><form id="transfer-form"><label>Получатель<select id="transfer-friend" name="friend_id">${list.length?'<option value="">Выбери друга</option>':''}${list.map(p=>`<option value="${p.id}" ${selected===p.id?'selected':''}>${esc(p.name)}${p.username?' · @'+esc(p.username):''}</option>`).join('')}<option value="manual" ${!list.length?'selected':''}>По нику или ID</option></select></label><label id="transfer-recipient-label" ${list.length?'hidden':''}>Ник или ID<input name="recipient" maxlength="40" placeholder="@username или Telegram ID" ${list.length?'disabled':'required'}></label><label>Сумма<input name="amount" type="number" inputmode="numeric" min="1" max="1000000" required></label><p class="sub">Комиссию и сумму получателя покажем до списания.</p><button class="primary" type="submit">Посмотреть условия</button></form>`);const select=$('#transfer-friend'),input=document.querySelector('#transfer-form [name=recipient]');select.onchange=()=>{const manual=select.value==='manual';$('#transfer-recipient-label').hidden=!manual;input.disabled=!manual;input.required=manual};$('#transfer-form').onsubmit=e=>{e.preventDefault();const f=new FormData(e.target);if(select.value===''){toast('Выбери друга или укажи ник / ID');return}prepareWallet('transfer',{...(select.value==='manual'?{recipient:f.get('recipient')}:{friend_id:Number(select.value)}),amount:Number(f.get('amount'))})}}catch(e){toast(e.message)}finally{pending=false}}

  function rename(){sheet(`<h2>Как зовут питомца?</h2><form id="pet-name-form"><label>Имя<input name="name" value="${esc(data.pet.name)}" maxlength="24" required></label><button class="primary" type="submit">Сохранить имя</button></form>`);$('#pet-name-form').onsubmit=e=>{e.preventDefault();petAction('rename',new FormData(e.target).get('name'))}}
  function showHelp(key){const item=help[key],back=!!document.querySelector('.lk-reputation');if(item)sheet(`<span class="eyebrow">Подсказка Норы</span><h2>${esc(item[0])}</h2><p class="sub">${esc(item[1])}</p>${back?'<button class="secondary" data-lk-reputation>← Репутация и лимиты</button>':''}`)}
  function parent(t){return window.NoraInteractive?.parent(t)||{lk:'home',wallet:'lk',history:'wallet',notices:'lk',admin:'lk'}[t]||null}
  document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.help)showHelp(b.dataset.help);if(b.hasAttribute('data-lk-reputation'))reputationSheet();if(b.hasAttribute('data-lk-settings'))settingsSheet();if(b.hasAttribute('data-lk-close'))$('#sheet').close();if(b.hasAttribute('data-lk-levels'))showReputation();if(b.hasAttribute('data-lk-avatar')){$('#sheet').close();$('#avatar-file')?.click()}if(b.hasAttribute('data-lk-notices')){$('#sheet').close();tab='notices';render();loadNotices()}if(b.hasAttribute('data-lk-hobbies'))sheet(`${sheetHeading('Увлечения')}<p class="lk-all-hobbies">${esc(data.user.hobbies)}</p>`);if(b.hasAttribute('data-open-pet-shop')){if(data.profile.fill_percent<100){toast('Заполни профиль на 100% в ЛК');return}NoraShop.openCategory('pets')}if(b.dataset.petAction)petAction(b.dataset.petAction);if(b.id==='rename-pet')rename();if(b.id==='wallet-topup'){if(data.profile.fill_percent<100){toast('Заполни профиль на 100% в ЛК');return}NoraShop.openCategory('__cookies')}if(b.id==='wallet-transfer')transferForm();if(b.dataset.friendTransfer)transferForm({id:Number(b.dataset.friendTransfer),name:b.dataset.friendName});if(b.id==='wallet-starter')prepareWallet('starter_pack');if(b.id==='wallet-repay')prepareWallet('repay');if(b.dataset.tab==='notices'){noticeData=null;loadNotices()}});
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
  window.addEventListener('popstate',()=>{const next=window.NoraShop?.route().view;if(data&&['lk','pet','wallet','history','notices','admin'].includes(next)){tab=next;render();NoraShop.syncBack()}});
  function refreshCurrent(){if(tab==='notices')loadNotices()}
  return {profileScreen,transferForm,reloadNotices:loadNotices,refreshCurrent,syncHistory,header,walletScreen,historyScreen,noticesScreen,parent,showHelp};
})();
