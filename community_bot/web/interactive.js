"use strict";
window.NoraInteractive = (() => {
  const views = new Set(["interactive", "games", "friends", "mafia", "rocket"]);
  const liveViews = new Set(["friends", "mafia", "rocket"]);
  const state = { friends: null, mafia: null, rocket: null };
  const fetching = {},
    loadedAt = {},
    errors = {},
    epochs = {};
  let activeView = "",
    pending = false,
    pollTimer = null,
    frame = 0,
    clock = { mafia: 0, rocket: 0 },
    clockAt = { mafia: 0, rocket: 0 };
  let roleOpen = false,
    roomSeen = "",
    chatChannel = "public",
    roomFocus = null,
    retryAction = null,
    lastRoundId = "",
    lastRocketResult = null;
  const drafts = {
    friend: "",
    room: "",
    chat: "",
    bet: "10",
    auto: "2.00",
    autoOn: true,
  };
  const roleNames = {
    mafia: "Мафия",
    detective: "Комиссар",
    doctor: "Доктор",
    civilian: "Мирный житель",
  };
  const phaseNames = {
    lobby: "Собираемся",
    night: "Город засыпает",
    discussion: "Город просыпается",
    vote: "Время решения",
    finished: "Партия завершена",
  };
  const glyphs = {
    game: "M6 7h12c3 0 4 4 4 8s-2 4-4 1l-2-2H8l-2 2c-2 3-4 3-4-1S3 7 6 7z M7 9v5 M4.5 11.5h5 M16 10h.01 M19 13h.01",
    friends:
      "M8 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M1 21v-2a7 7 0 0 1 14 0v2 M17 4a4 4 0 0 1 0 8 M18 16a5 5 0 0 1 5 5",
    mafia:
      "M3 12c2-6 5-8 9-8s7 2 9 8v5c-2 3-5 4-9 4s-7-1-9-4z M3 12l7 3-2 3-5-2 M21 12l-7 3 2 3 5-2 M10 20l2-4 2 4",
    rocket:
      "M9 15 5 19 M7 13l-4-1 5-5 4 1 M11 17l1 4 5-5-1-4 M7 13C10 6 14 3 21 3c0 7-3 11-10 14z M15 7a2 2 0 1 0 0 4 2 2 0 0 0 0-4 M5 16l-2 5 5-2",
    moon: "M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11z M18 3v4 M16 5h4",
    sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M19 5l-2 2 M7 17l-2 2",
    eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6",
    arrow: "M5 19 19 5 M5 5h14v14",
    shield: "M12 3 21 7v6c0 5-9 9-9 9s-9-4-9-9V7z M8 12l3 3 5-6",
  };
  function icon(name) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${glyphs[name] || glyphs.game}"/></svg>`;
  }
  function initials(name) {
    return esc(
      String(name || "?")
        .match(/[\p{L}\p{N}]/u)?.[0]
        ?.toUpperCase() || "?",
    );
  }
  function go(view) {
    if (!views.has(view) && view !== "pet" && view !== "lk" && view !== "community") return;
    tab = view;
    NoraShop.tabChanged(view);
    render();
    window.scrollTo(0, 0);
  }
  function parent(view) {
    return (
      {
        pet: "interactive",
        games: "interactive",
        mafia: "games",
        rocket: "games",
        friends: "community",
      }[view] || null
    );
  }
  function badge(text, red = false) {
    return `<span class="play-badge ${red ? "accent" : ""}">${esc(text)}</span>`;
  }
  function back(view, label) {
    return `<button class="text-btn play-back" data-tab="${view}">← ${label}</button>`;
  }
  function errorBox(view) {
    return errors[view]
      ? `<div class="play-connection" role="status">${esc(errors[view])}<button class="text-btn" data-game-retry="${view}">Обновить</button></div>`
      : "";
  }
  function interactiveScreen() {
    return `${mafiaInvites()}<p class="eyebrow">У каждого свой способ</p><h1>Побудем<br><em>вместе.</em></h1><p class="sub play-intro">Заботься, играй, собирай своих.</p><button class="play-hero pet-hero" data-tab="pet"><span class="play-hero-copy"><span class="eyebrow">Твой маленький спутник</span><strong>Тамагочи<span>.</span></strong><span class="play-hero-description">${data.pet ? esc(data.pet.name) + " ждёт тебя. Забота, походы и маленькие находки." : "Заведи питомца. Заботься о нём и отправляй за приключениями."}</span><span class="play-hero-cta">${data.pet ? "К питомцу" : "Знакомиться"} ${icon("arrow")}</span></span><span class="play-hero-art pet-orbit">${NoraShop.svg("pets")}<i></i><i></i><i></i></span></button><button class="play-hero games-hero" data-tab="games"><span class="play-hero-copy"><span class="eyebrow">Один или всей компанией</span><strong>Игры<span>.</span></strong><span class="play-hero-description">У города есть тайны.<br>У ракеты — свой предел.</span><span class="play-hero-cta">Выбрать игру ${icon("arrow")}</span></span><span class="play-hero-art">${icon("game")}<span class="art-plus">+</span></span></button><button class="play-friends-link" data-tab="friends">${icon("friends")}<span>Свои всегда рядом<small>Добавляй друзей и зови играть</small></span>${icon("arrow")}</button>`;
  }
  function gamesScreen() {
    return `${back("interactive", "Интерактив")}${mafiaInvites()}<p class="eyebrow">Есть время на ещё одну?</p><h1>Давай<br><em>сыграем.</em></h1><button class="play-hero mafia-hero" data-tab="mafia"><span class="play-hero-copy"><span class="play-tags">${badge("5–12 человек")}${badge("Бесплатно", true)}</span><strong>Мафия<span>.</span></strong><span class="play-hero-description">Ночь скрывает роли.<br>Днём решают люди.</span><span class="play-hero-cta">Собрать своих ${icon("arrow")}</span></span><span class="play-hero-art">${icon("mafia")}</span></button><button class="play-hero rocket-hero" data-tab="rocket"><span class="play-hero-copy"><span class="play-tags">${badge("Соло")}${badge("18+ · 🍪")}</span><strong>Ракетка<span>.</span></strong><span class="play-hero-description">Поймай свой момент.<br>Забери до срыва.</span><span class="play-hero-cta">На старт ${icon("arrow")}</span></span><span class="play-hero-art">${icon("rocket")}</span></button><p class="footer-note">Мафия — командная игра без ставок.<br>В Ракетке печеньки можно потерять.</p>`;
  }
  function friendRow(person, section) {
    const actions = {
      friends: [
        ["remove", "Удалить"],
        ["block", "Заблокировать"],
      ],
      incoming: [
        ["accept", "Принять"],
        ["decline", "Отклонить"],
        ["block", "Заблокировать"],
      ],
      outgoing: [["cancel", "Отозвать"]],
      blocked: [["unblock", "Разблокировать"]],
    }[section];
    return `<article class="friend-row"><div class="friend-person"><button class="person-visit" data-person-view="${person.id}" aria-label="Открыть профиль ${esc(person.name)}"><span class="person-avatar" data-person-avatar="${person.id}" ${person.has_avatar===false?"data-avatar-unavailable":""}>${initials(person.name)}</span><span><b>${esc(person.name)}</b><small>${person.username ? "@" + esc(person.username) : "Участник Норы"}</small>${section==='friends'?`<small class="person-presence ${person.presence?.online?'online':''}">${esc(window.NoraPeople?.presenceLine(person.presence)||'')}</small>`:''}</span></button>${section === "friends" && person.available !== false ? `<button class="icon-button" data-friend-play="${person.id}" aria-label="Пригласить ${esc(person.name)} в игру">${icon("game")}</button>` : ""}</div><div class="friend-row-actions">${section==='friends'?`<button class="text-btn" data-friend-transfer="${person.id}" data-friend-name="${esc(person.name)}">Перевести 🍪</button>`:''}${actions.map(([action, label]) => `<button class="${action === "accept" ? "friend-accept" : "text-btn"}" data-friend-action="${action}" data-person-id="${person.id}" ${pending ? "disabled" : ""}>${label}</button>`).join("")}</div></article>`;
  }
  function friendsScreen() {
    const f = state.friends;
    return `${tab === "community" ? "" : back("community", "Коммьюнити")}<div class="play-title-row"><div><p class="eyebrow">Близкие по духу</p><h2>Друзья<em>.</em></h2></div><span class="play-title-icon">${icon("friends")}</span></div><p class="sub">Добавь участника Норы. Когда он примет заявку, сможете взаимодействовать друг с другом.</p>${errorBox("friends")}<button class="secondary community-find" data-community-search>⌕ Найти участников</button>${!f ? '<div class="empty">Загружаем друзей…</div>' : ""}${f?.incoming?.length ? `<section class="friend-section"><h2>Зовут дружить ${badge(f.incoming.length, true)}</h2>${f.incoming.map((p) => friendRow(p, "incoming")).join("")}</section>` : ""}<section class="friend-section"><h2>Друзья ${badge(f?.friends?.length || 0)}</h2>${f?.friends?.length ? f.friends.map((p) => friendRow(p, "friends")).join("") : '<div class="card empty">Список пока пуст.<br>Начни с одного знакомого имени.</div>'}</section>${f?.outgoing?.length ? `<section class="friend-section"><h2>Ждём ответа</h2>${f.outgoing.map((p) => friendRow(p, "outgoing")).join("")}</section>` : ""}${f?.blocked?.length ? `<details class="play-details" data-detail="blocked"><summary>Заблокированные · ${f.blocked.length}</summary>${f.blocked.map((p) => friendRow(p, "blocked")).join("")}</details>` : ""}`;
  }
  function roleExplanation(role) {
    return (
      state.mafia?.rules?.roles?.find((r) => r.id === role)?.description ||
      {
        civilian:
          "Слушай, сопоставляй и голосуй. Найдите всю мафию, пока она не сравнялась числом с городом.",
        mafia:
          "Вы знакомы с союзниками. Ночью договоритесь о цели, днём не выдавайте себя.",
        doctor:
          "Ночью защити одного игрока. Себя можно спасти один раз; одну цель нельзя лечить две ночи подряд.",
        detective:
          "Каждую ночь проверяй одного игрока. Результат проверки увидишь только ты.",
      }[role] ||
      ""
    );
  }
  function mafiaRules() {
    const rules = state.mafia?.rules;
    return `<details class="play-details" data-detail="mafia-rules"><summary>Как устроена «Мафия» ${icon("shield")}</summary><p class="sub">${rules?.min_players || 5}–${rules?.max_players || 12} человек. Участие бесплатное — печеньки не списываются и не разыгрываются.</p>${(rules?.roles || Object.keys(roleNames).map((id) => ({ id, name: roleNames[id], description: roleExplanation(id) }))).map((r) => `<div class="rule-row"><b>${esc(r.name)}</b><p>${esc(r.description)}</p></div>`).join("")}${(
      rules?.sections || [
        {
          title: "Ночь → обсуждение → голосование",
          text: "На ночь отводится 60 секунд, на обсуждение — 90, на голосование — 45. Таймер работает на сервере, даже если миниапка закрыта.",
        },
        {
          title: "Победа",
          text: "Город побеждает, когда мафии не осталось. Мафия побеждает, когда сравнялась с городом по числу живых игроков.",
        },
      ]
    ).map(
      (r) =>
        `<div class="rule-row"><b>${esc(r.title)}</b><p>${esc(r.text)}</p></div>`,
    )}</details>`;
  }
  function invitationCard(i) {
    return `<section class="card mafia-invite"><span class="eyebrow">Друг приглашает в «Мафию»</span><h3>${esc(i.title)}</h3><p class="sub">${esc(i.sender_name)} зовёт тебя в комнату · ${number(i.players_count)} за столом</p><div class="pet-action-row"><button class="primary" data-mafia-respond="yes" data-room-id="${esc(i.room_id)}" ${pending ? "disabled" : ""}>Принять</button><button class="secondary" data-mafia-respond="no" data-room-id="${esc(i.room_id)}" ${pending ? "disabled" : ""}>Отклонить</button></div></section>`;
  }
  function roomControls(r) {
    if (!['lobby','active'].includes(r.status) || r.self.left) return '';
    return `<section class="card mafia-room-controls"><button class="secondary" data-mafia-action="leave">Выйти из комнаты</button>${r.host_id === r.self.id ? '<button class="secondary danger-action" data-mafia-action="cancel">Выйти и удалить комнату</button>' : ''}</section>`;
  }
  function mafiaInvites() {
    return (state.mafia?.invites || []).map(invitationCard).join('');
  }

  function mafiaHome() {
    const m = state.mafia;
    return `${back("games", "Игры")}<div class="play-title-row"><div><p class="eyebrow">Бесплатно · 5–12 человек</p><h1>В городе<br><em>неспокойно.</em></h1></div><span class="play-title-icon">${icon("mafia")}</span></div><p class="sub">Кто-то уже знает больше, чем говорит.<br>Собери друзей и проверь свою интуицию.</p>${errorBox("mafia")}${m && !m.enabled ? '<p class="game-restricted">Новые игры временно выключены администрацией.</p>' : ""}${mafiaInvites()}<section class="card mafia-create"><span class="eyebrow">Твой стол, твоя компания</span><h2>Начнём с приглашения.</h2><p class="sub">Создай комнату, позови друзей. Партия начнётся, когда все будут готовы.</p><button class="primary" id="mafia-create" ${pending || !m || !m.enabled ? "disabled" : ""}>Создать комнату</button><button class="secondary" data-tab="friends">Найти своих</button></section>${mafiaRules()}${m?.recent?.length ? `<details class="play-details" data-detail="mafia-recent"><summary>Прошлые партии · ${m.recent.length}</summary>${m.recent.map((r) => `<button class="mafia-recent" data-mafia-history="${esc(r.id)}"><span><b>${esc(r.title)}</b><small>${winnerLabel(r.winner, r.status)}</small></span>${icon("arrow")}</button>`).join("")}</details>` : ""}`;
  }
  function winnerLabel(winner, status) {
    if (status === "cancelled") return "Комната закрыта";
    return (
      {
        town: "Победил город",
        civilian: "Победил город",
        civilians: "Победил город",
        mafia: "Победила мафия",
        draw: "Ничья",
      }[winner] || "Партия завершена"
    );
  }
  function players(room) {
    return `<div class="mafia-players">${room.players.map((p) => `<div class="mafia-player ${!p.alive && room.status !== "lobby" ? "out" : ""} ${p.id === room.self.id ? "you" : ""}"><span class="person-avatar" data-person-avatar="${p.id}" ${p.has_avatar===false?"data-avatar-unavailable":""}>${initials(p.name)}${p.id === room.host_id ? '<i class="host-dot" title="Создатель комнаты"></i>' : ""}</span><b>${esc(p.name)}</b><small>${p.left ? "Вышел" : room.status === "lobby" ? (p.ready ? "Готов" : "Собирается") : p.role ? esc(roleNames[p.role] || p.role) : p.alive ? "В игре" : "Выбыл"}${p.id === room.self.id ? " · ты" : ""}</small>${p.voted && room.phase === "vote" ? '<span class="player-voted" aria-label="Голос принят">✓</span>' : ""}</div>`).join("")}</div>`;
  }
  function roleCard(room) {
    if (!room.self.role) return "";
    return `<button class="mafia-role ${roleOpen ? "revealed" : ""}" id="mafia-role" aria-expanded="${roleOpen}"><span class="role-symbol">${icon(roleOpen && room.self.role === "doctor" ? "shield" : "eye")}</span><span><small>${roleOpen ? "Твоя тайная роль" : "Только для тебя"}</small><b>${roleOpen ? esc(roleNames[room.self.role] || room.self.role) : "Нажми, чтобы узнать роль"}</b>${roleOpen ? `<span>${esc(roleExplanation(room.self.role))}</span>` : "<span>Не показывай экран другим игрокам</span>"}</span></button>`;
  }
  function actionPanel(room) {
    if (room.self.left)
      return '<p class="phase-hint">Ты покинул эту комнату. Вернись к списку, чтобы создать новую.</p>';
    if (room.status === "lobby")
      return `<div class="mafia-lobby-actions"><button class="${room.self.ready ? "secondary" : "primary"}" data-mafia-action="ready" ${pending ? "disabled" : ""}>${room.self.ready ? "Я пока не готов" : "Я готов"}</button>${room.inviteable ? '<button class="secondary" id="mafia-invite">Пригласить друзей</button>' : ""}${room.host_id === room.self.id ? `<button class="primary mafia-start" data-mafia-action="start" ${pending || room.players.filter((p) => !p.left).length < (state.mafia.rules.min_players || 5) || room.players.some((p) => !p.left && !p.ready) ? "disabled" : ""}>Начать партию</button><p class="footer-note">Нужно минимум ${state.mafia.rules.min_players || 5} ${plural(state.mafia.rules.min_players || 5, "игрок", "игрока", "игроков")}. Каждый нажимает «Я готов».</p>` : ""}</div>`;
    if (room.status !== "active") return "";
    if (!room.self.alive)
      return '<section class="card game-observer"><b>Ты наблюдаешь за городом.</b><p class="sub">Роли ещё скрыты. Обсуждать партию можно с другими выбывшими в отдельном чате.</p></section>';
    const available = room.available_targets || [];
    if (room.phase === "discussion")
      return '<p class="phase-hint">Время слушать и убеждать. Голосование откроется после обсуждения.</p>';
    if (room.phase === "night" && !available.length)
      return `<p class="phase-hint">${room.self.role === "civilian" ? "Город спит. Твой ход — на дневном обсуждении." : "Сейчас нет доступных целей. Ждём рассвета."}</p>`;
    if (!["night", "vote"].includes(room.phase)) return "";
    const target =
      room.phase === "vote" ? room.self.vote_target : room.self.night_target;
    const selected =
      room.phase === "vote" ? room.self.voted : room.self.night_target !== null;
    const verb =
      room.phase === "vote"
        ? "Кого подозреваешь?"
        : {
            mafia: "Цель этой ночи",
            doctor: "Кого защитить?",
            detective: "Кого проверить?",
          }[room.self.role] || "Ночной ход";
    return `<section class="card mafia-targets"><span class="eyebrow">${selected ? "Твой выбор принят" : "Твой ход"}</span><h3>${verb}</h3><div class="target-grid">${room.players
      .filter((p) => available.includes(p.id))
      .map(
        (p) =>
          `<button class="target-button ${selected && target === p.id ? "chosen" : ""}" data-mafia-target="${p.id}" data-target-action="${room.phase === "vote" ? "vote" : "night"}" ${pending ? "disabled" : ""}><span class="person-avatar" data-person-avatar="${p.id}" ${p.has_avatar===false?"data-avatar-unavailable":""}>${initials(p.name)}</span><span>${esc(p.name)}${p.id === room.self.id ? " · ты" : ""}</span>${selected && target === p.id ? "<b>✓</b>" : ""}</button>`,
      )
      .join(
        "",
      )}${room.phase === "vote" ? `<button class="target-button target-skip ${room.self.voted && target === null ? "chosen" : ""}" data-mafia-target="skip" data-target-action="vote" ${pending ? "disabled" : ""}>Никого не исключать ${room.self.voted && target === null ? "✓" : ""}</button>` : ""}</div><p class="sub">${room.phase === "vote" ? "Выбор можно изменить до конца голосования." : "Выбор можно изменить до рассвета."}</p></section>`;
  }
  function chatOptions(room) {
    if (room.self.left) return [];
    if (room.status === "lobby") return ["public"];
    if (room.status !== "active") return ["public"];
    if (!room.self.alive) return ["ghost"];
    if (room.phase === "night")
      return room.self.role === "mafia" ? ["mafia"] : [];
    return ["public"];
  }
  function chat(room) {
    const options = chatOptions(room);
    if (options.length && !options.includes(chatChannel))
      chatChannel = options[0];
    const shown = room.messages.filter((m) => m.channel === chatChannel);
    return `<section class="card mafia-chat"><div class="row"><h3>${chatChannel === "mafia" ? "Тайный чат мафии" : chatChannel === "ghost" ? "Чат выбывших" : "Голос города"}</h3><span class="chat-privacy">${chatChannel === "public" ? "Участники комнаты" : "Только своя команда"}</span></div>${!options.length && room.status === "active" ? '<p class="sub">Ночью общий чат молчит. Вернёмся к обсуждению на рассвете.</p>' : ""}<div class="mafia-chat-log" id="mafia-chat-log" role="log" aria-live="polite">${shown.length ? shown.map((m) => `<article class="chat-message ${m.user_id === room.self.id ? "mine" : ""}"><span><b>${esc(m.name)}</b><time>${esc(new Date(m.at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }))}</time></span><p>${esc(m.text)}</p></article>`).join("") : '<p class="chat-empty">Здесь пока тихо.</p>'}</div>${options.length && room.status !== "finished" && room.status !== "cancelled" ? `<form id="mafia-chat-form"><label class="sr-only" for="mafia-chat-input">Сообщение в ${chatChannel === "mafia" ? "тайный чат" : chatChannel === "ghost" ? "чат выбывших" : "общий чат"}</label><div class="inline-form"><input id="mafia-chat-input" name="message" maxlength="500" autocomplete="off" placeholder="Слово тебе…" required value="${esc(drafts.chat)}"><button class="primary" type="submit" aria-label="Отправить сообщение" ${pending ? "disabled" : ""}>↑</button></div></form>` : ""}</section>`;
  }
  function mafiaRoom() {
    const r = state.mafia.room;
    const isDone = ["finished", "cancelled"].includes(r.status);
    const alive = r.players.filter((p) => p.alive && !p.left).length;
    return `${back("games", "Игры")}<div class="mafia-room-heading"><div><p class="eyebrow">Мафия · бесплатно</p><h1>${esc(r.title)}<em>.</em></h1></div><button class="icon-button" id="mafia-rules" aria-label="Правила мафии">?</button></div>${errorBox("mafia")}<section class="phase-banner phase-${esc(r.phase)}"><span class="phase-symbol">${icon(r.phase === "night" ? "moon" : isDone ? "shield" : "sun")}</span><div><span class="eyebrow">${r.phase === "lobby" ? `${r.players.filter((p) => !p.left).length} / ${state.mafia.rules.max_players || 12} за столом` : isDone ? "До следующей встречи" : `Круг ${number(r.round)} · живы ${alive} / ${r.players.length}`}</span><h2>${isDone ? winnerLabel(r.winner, r.status) : phaseNames[r.phase] || esc(r.phase)}</h2></div>${!isDone && r.deadline ? '<span class="phase-timer" id="mafia-timer" aria-label="Оставшееся время">—</span>' : ""}</section>${roomControls(r)}${roleCard(r)}${players(r)}${actionPanel(r)}${r.self.investigations?.length ? `<details class="play-details private-results" data-detail="investigations"><summary>Твои проверки · ${r.self.investigations.length}</summary>${r.self.investigations.map((p) => `<p><b>${esc(p.name)}</b> — ${p.mafia ? "мафия" : "не мафия"}<small>Ночь ${number(p.round)}</small></p>`).join("")}</details>` : ""}${chat(r)}${r.timeline?.length ? `<details class="play-details" data-detail="timeline"><summary>Что случилось в городе</summary><ol class="mafia-timeline">${r.timeline.map((item) => `<li>${esc(item.text)}</li>`).join("")}</ol></details>` : ""}${isDone ? `<button class="primary" id="mafia-new">Собрать новую партию</button><button class="secondary" id="mafia-current">К текущей комнате</button>` : ""}`;
  }
  function mafiaScreen() {
    return state.mafia?.room ? mafiaRoom() : mafiaHome();
  }
  function rocketBoard(round) {
    const flying = round && ["countdown", "flying"].includes(round.status);
    const final = round && !flying;
    return `<section class="rocket-board ${final && round.status === "crashed" ? "rocket-crashed" : ""}" aria-label="Полёт ракеты"><div class="flight-grid"></div><div class="flight-heading"><span class="eyebrow" id="rocket-flight-label">${!round ? "Готовность к запуску" : round.status === "countdown" ? "Обратный отсчёт" : round.status === "flying" ? "В полёте" : round.status === "crashed" ? "Полёт окончен" : "Печеньки забраны"}</span><strong id="rocket-multiplier">${final ? "×" + Number(round.cashout_multiplier || round.proof?.crash_multiplier || 1).toFixed(2) : "×1.00"}</strong><span class="flight-caption" id="rocket-flight-caption">${!round ? "Твой момент где-то впереди." : flying ? "Успей забрать до срыва." : round.status === "crashed" ? "Ставка не вернулась." : "Выплата уже в общем кошельке."}</span></div><svg class="rocket-graph" viewBox="0 0 340 200" aria-hidden="true"><defs><linearGradient id="flight-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#f32843" stop-opacity=".28"/><stop offset="100%" stop-color="#f32843" stop-opacity="0"/></linearGradient></defs><path id="rocket-area" fill="url(#flight-fill)" d="M22 176H318V176Z"/><path id="rocket-path" d="M22 176Q70 176 90 165" fill="none" stroke="#f32843" stroke-width="3" stroke-linecap="round"/><g id="rocket-ship" transform="translate(90 165)"><circle r="17" fill="#f3284318"/><path d="M-9 7-5-6 9-13 9 1-4 9z" fill="#f7f5f1"/><circle cx="3" cy="-5" r="3" fill="#f32843"/><path d="m-8 9-5 5 7-2" stroke="#f32843" stroke-width="3" stroke-linecap="round"/></g><text x="22" y="196">СТАРТ</text><text x="290" y="196">×10</text></svg><span class="rocket-server-note">Расчёт на сервере</span></section>`;
  }
  function rocketScreen() {
    const s = state.rocket,
      r = s?.round || lastRocketResult,
      live = r && ["countdown", "flying"].includes(r.status);
    return `${back("games", "Игры")}<div class="play-title-row"><div><p class="eyebrow">Соло · 18+</p><h1>Ракетка<em>.</em></h1></div><span class="rocket-balance"><small>В кошельке</small><b>${number(s?.balance ?? data.user.cookies)} 🍪</b></span></div>${errorBox("rocket")}${rocketBoard(r)}${live ? `<section class="card flight-controls"><div class="flight-stake"><span>В полёте <b>${number(r.bet)} 🍪</b></span><span>Автовыход <b>${r.auto_cashout ? "×" + Number(r.auto_cashout).toFixed(2) : "выключен"}</b></span></div><button class="primary rocket-cashout" id="rocket-cashout" ${pending || r.status === "countdown" ? "disabled" : ""}>${r.status === "countdown" ? "Готовимся к запуску…" : "Забрать"}</button><p class="footer-note">Выплата включает ставку. Сумма определяется в момент получения запроса сервером.</p></section>` : `${r ? `<section class="rocket-result ${r.status === "crashed" ? "lost" : "won"}" role="status"><div><small>${r.status === "crashed" ? "Срыв на ×" + Number(r.proof?.crash_multiplier || r.current_multiplier || 1).toFixed(2) : "Выход на ×" + Number(r.cashout_multiplier || 1).toFixed(2)}</small><b>${r.status === "crashed" ? "−" + number(r.bet) : "+" + number((r.payout || 0) - r.bet)} 🍪</b></div><p>Ставка ${number(r.bet)} 🍪 · выплата ${number(r.payout || 0)} 🍪</p></section>` : ""}<form id="rocket-bet-form" class="card rocket-form"><div class="row"><h3>Твой запуск</h3><span class="sub">1–100 🍪</span></div><label for="rocket-bet">Ставка в печеньках</label><input id="rocket-bet" name="bet" type="number" inputmode="numeric" min="1" max="100" step="1" value="${esc(drafts.bet)}" required><div class="stake-chips">${[5, 10, 25, 50, 100].map((n) => `<button type="button" data-rocket-stake="${n}" class="${Number(drafts.bet) === n ? "selected" : ""}">${n}</button>`).join("")}</div><label class="auto-toggle" for="rocket-auto-on"><span>Забрать автоматически<small>Сработает, даже если закроешь миниапку</small></span><input id="rocket-auto-on" type="checkbox" ${drafts.autoOn ? "checked" : ""}></label><label for="rocket-auto" ${drafts.autoOn ? "" : "hidden"} id="rocket-auto-label">На множителе<input id="rocket-auto" name="auto" type="number" inputmode="decimal" min="1.1" max="10" step="0.01" value="${esc(drafts.auto)}" ${drafts.autoOn ? "required" : "disabled"}></label>${s && !s.eligible ? `<p class="game-restricted">${esc(s.reason || "Ставки сейчас недоступны")}</p>` : ""}<button class="primary" type="submit" ${pending || !s?.eligible ? "disabled" : ""}>Проверить запуск</button><p class="footer-note">Списание — после подтверждения.<br>Срыв раньше твоего выхода означает потерю ставки.</p></form>`}<details class="play-details" data-detail="rocket-rules"><summary>Как летит ракета</summary><div class="rule-row"><b>Одна ставка — один полёт</b><p>Ставка от 1 до 100 печенек. После трёхсекундного отсчёта множитель растёт. Нажми «Забрать» до срыва: выплата = ставка × множитель, с округлением вниз.</p></div><div class="rule-row"><b>Автовыход — до запуска</b><p>Можно заранее выбрать множитель от ×1.10 до ×10.00. Он сохраняется на сервере и сработает без открытой миниапки. При достижении ×10 выплата автоматическая, если ракета не сорвалась раньше.</p></div><div class="rule-row"><b>Понятные условия</b><p>Точка срыва случайна и фиксируется до полёта. Теоретический возврат — не выше 97%, округление выплат его уменьшает. Каждый полёт независим. Предыдущие результаты ничего не предсказывают.</p></div><div class="rule-row"><b>Связь и результат</b><p>Анимация показывает приблизительный текущий множитель. Ручной выход принимается по времени сервера. При потере связи полёт продолжается; без автовыхода ставка может быть потеряна. Доступно с 18 лет, при заполненном профиле, без открытого стартер-пака и просроченного долга.</p></div></details>${rocketHistory()}${r ? `<details class="play-details" data-detail="rocket-proof"><summary>Проверка этого полёта</summary><p class="sub">SHA-256 фиксируется до запуска. После завершения открывается исходное значение для проверки результата.</p><label class="proof-label">Отпечаток<code>${esc(r.commitment || "—")}</code></label>${r.proof ? `<label class="proof-label">Исходное значение<code>${esc(r.proof.seed)}</code></label><p class="sub">Точка срыва: ×${Number(r.proof.crash_multiplier).toFixed(2)}<br>${esc(r.proof.algorithm || "")}</p>` : '<p class="sub">Исходное значение скрыто до завершения полёта.</p>'}</details>` : ""}`;
  }
  function rocketHistory() {
    const h = state.rocket?.history || [];
    return `<details class="play-details" data-detail="rocket-history"><summary>Твои последние полёты · ${h.length}</summary>${h.length ? h.map((r) => `<div class="flight-history"><span><b>×${Number(r.cashout_multiplier || r.proof?.crash_multiplier || r.current_multiplier || 1).toFixed(2)}</b><small>${r.status === "crashed" ? "Срыв" : "Забрано"} · ставка ${number(r.bet)}</small></span><strong class="${r.status === "crashed" ? "red-number" : ""}">${r.status === "crashed" ? "−" + number(r.bet) : "+" + number((r.payout || 0) - r.bet)} 🍪</strong></div>`).join("") : '<p class="sub">Первый полёт ещё впереди.</p>'}</details>`;
  }
  function screen(view) {
    const body = {
      interactive: interactiveScreen,
      games: gamesScreen,
      friends: friendsScreen,
      mafia: mafiaScreen,
      rocket: rocketScreen,
    }[view];
    return `<div id="interactive-content" data-interactive-view="${view}">${body ? body() : ""}</div>`;
  }
  function now(kind) {
    return (
      (clock[kind] || Date.now()) +
      (performance.now() - (clockAt[kind] || performance.now()))
    );
  }
  function updateClock(kind, payload) {
    clock[kind] =
      kind === "mafia"
        ? payload.server_now
        : Number(payload.server_time) * 1000;
    clockAt[kind] = performance.now();
  }
  function patch() {
    const el = $("#interactive-content");
    const view = tab === "community" ? "friends" : tab;
    if (!el || !views.has(view) || el.dataset.interactiveView !== view) return;
    const focused = document.activeElement,
      focusId = focused?.id,
      selection = focused?.selectionStart;
    const open = [...el.querySelectorAll("details[open]")].map(
      (n) => n.dataset.detail,
    );
    const log = $("#mafia-chat-log"),
      atBottom =
        !log || log.scrollHeight - log.scrollTop - log.clientHeight < 40,
      scroll = log?.scrollTop || 0;
    const y = window.scrollY;
    el.outerHTML = screen(view);
    for (const key of open) {
      const node = $(`[data-detail="${key}"]`);
      if (node) node.open = true;
    }
    if (focusId) {
      const node = document.getElementById(focusId);
      if (node) {
        node.focus({ preventScroll: true });
        try {
          if (selection !== null && selection !== undefined)
            node.setSelectionRange(selection, selection);
        } catch {}
      }
    }
    const next = $("#mafia-chat-log");
    if (next) next.scrollTop = atBottom ? next.scrollHeight : scroll;
    window.scrollTo(0, y);
    updateFrame();
  }
  function acceptSnapshot(view, payload) {
    state[view] = payload;
    if (view === "rocket") {
      updateClock(view, payload);
      if (Number.isFinite(payload.balance)) {
        data.user.cookies = payload.balance;
      }
      if (payload.round) {
        lastRoundId = payload.round.id;
        if (!["countdown", "flying"].includes(payload.round.status))
          lastRocketResult = payload.round;
        else lastRocketResult = null;
      } else if (lastRoundId) {
        const terminal = payload.history?.find((r) => r.id === lastRoundId);
        if (terminal) lastRocketResult = terminal;
      }
    }
    if (view === "mafia") {
      updateClock(view, payload);
      const room = payload.room?.id || "";
      roomFocus = room || null;
      if (room !== roomSeen) {
        roomSeen = room;
        roleOpen = false;
        drafts.chat = "";
        chatChannel = "public";
      }
    }
    loadedAt[view] = performance.now();
    delete errors[view];
  }
  async function load(view, force = false, roomId = undefined) {
    if (!liveViews.has(view) || !auth || !data) return;
    if (fetching[view]) {
      await fetching[view];
      if (!force) return;
    }
    if (!force && performance.now() - (loadedAt[view] || 0) < 1800) return;
    const epoch = epochs[view] || 0;
    const selectedRoom = roomId === undefined ? roomFocus : roomId;
    const request = (async () => {
      try {
        const response = await api(
          view +
            (view === "mafia" && selectedRoom
              ? "?room_id=" + encodeURIComponent(selectedRoom)
              : ""),
        );
        if (epoch !== (epochs[view] || 0)) return;
        acceptSnapshot(view, response);
        if (tab === view || (view === "friends" && tab === "community") || (view === "mafia" && ["games", "interactive"].includes(tab))) patch();
      } catch (e) {
        if (epoch !== (epochs[view] || 0)) return;
        errors[view] = "Связь прервалась. " + e.message;
        if (tab === view || (view === "friends" && tab === "community") || (view === "mafia" && ["games", "interactive"].includes(tab))) patch();
      }
    })();
    fetching[view] = request;
    try {
      await request;
    } finally {
      if (fetching[view] === request) delete fetching[view];
    }
  }
  function updateFrame() {
    if (tab === "mafia") {
      const r = state.mafia?.room,
        t = $("#mafia-timer");
      if (t && r?.deadline) {
        const seconds = Math.max(
          0,
          Math.ceil((r.deadline - now("mafia")) / 1000),
        );
        t.textContent =
          seconds >= 60
            ? Math.floor(seconds / 60) +
              ":" +
              String(seconds % 60).padStart(2, "0")
            : String(seconds) + "с";
        t.classList.toggle("urgent", seconds < 10);
      }
    }
    if (tab !== "rocket") return;
    const r = state.rocket?.round || lastRocketResult;
    const s = state.rocket;
    let multiplier = 1,
      progress = 0.12;
    if (r) {
      const live = ["countdown", "flying"].includes(r.status);
      if (live) {
        const seconds = now("rocket") / 1000 - r.starts_at;
        const countdown = Math.max(0, Math.ceil(-seconds));
        multiplier = Math.min(
          s.rules.max_multiplier,
          Math.exp(Math.max(0, seconds) * s.rules.growth_rate),
        );
        progress = Math.min(
          0.96,
          0.12 +
            (Math.log(multiplier) / Math.log(s.rules.max_multiplier)) * 0.84,
        );
        if ($("#rocket-flight-label"))
          $("#rocket-flight-label").textContent = countdown
            ? "До старта " + countdown + "…"
            : "В полёте";
        if ($("#rocket-multiplier"))
          $("#rocket-multiplier").textContent = countdown
            ? String(countdown)
            : "×" + multiplier.toFixed(2);
        const button = $("#rocket-cashout");
        if (button) {
          button.disabled =
            pending || countdown > 0 || r.status === "countdown";
          button.textContent = countdown
            ? "До старта " + countdown + "…"
            : "Забрать ≈ " + number(Math.floor(r.bet * multiplier)) + " 🍪";
        }
      } else {
        multiplier = Number(
          r.cashout_multiplier || r.proof?.crash_multiplier || 1,
        );
        progress = Math.min(
          0.96,
          0.12 + (Math.log(Math.max(1, multiplier)) / Math.log(10)) * 0.84,
        );
      }
    }
    const x = 22 + progress * 286,
      y = 176 - progress * progress * 146;
    const path = `M22 176 Q${22 + (x - 22) * 0.57} 176 ${x} ${y}`;
    $("#rocket-path")?.setAttribute("d", path);
    $("#rocket-area")?.setAttribute("d", path + ` L${x} 176 Z`);
    $("#rocket-ship")?.setAttribute("transform", `translate(${x} ${y})`);
    if (r?.status === "crashed" && $("#rocket-ship"))
      $("#rocket-ship").style.opacity = ".2";
  }
  function animation() {
    cancelAnimationFrame(frame);
    if (document.hidden || !["rocket", "mafia"].includes(tab)) return;
    updateFrame();
    frame = requestAnimationFrame(animation);
  }
  function mount() {
    if (activeView !== tab) {
      activeView = tab;
      clearTimeout(pollTimer);
      cancelAnimationFrame(frame);
      if (tab !== "mafia") roleOpen = false;
      if (tab !== "mafia") roomFocus = null;
      if (tab === "community") load("friends", true);
      if (liveViews.has(tab)) load(tab, true);
      if (["games", "interactive"].includes(tab)) load("mafia", true, null);
      if (tab === "mafia" && !state.friends) load("friends", true);
    }
    if (["mafia", "rocket"].includes(tab)) animation();
    schedule();
  }
  function schedule() {
    clearTimeout(pollTimer);
    if (document.hidden || !(liveViews.has(tab) || ["games", "interactive", "community"].includes(tab))) return;
    const interval =
      tab === "rocket" && state.rocket?.round
        ? 900
        : tab === "mafia"
          ? 1800
          : 10000;
    pollTimer = setTimeout(async () => {
      if (!pending && !document.hidden && !$("#sheet").open)
        await load(tab === "community" ? "friends" : ["games", "interactive"].includes(tab) ? "mafia" : tab, true);
      schedule();
    }, interval);
  }
  function refreshCurrent() {
    if (liveViews.has(tab) || ["games", "interactive", "community"].includes(tab)) {
      load(tab === "community" ? "friends" : ["games", "interactive"].includes(tab) ? "mafia" : tab, true);
      return true;
    }
    return false;
  }
  async function performAction(
    view,
    path,
    body,
    { close = false, quiet = false } = {},
  ) {
    if (pending || busy) return null;
    pending = true;
    epochs[view] = (epochs[view] || 0) + 1;
    const controls = [
      ...document.querySelectorAll(
        "#interactive-content button,#sheet-content button",
      ),
    ].map((b) => [b, b.disabled]);
    controls.forEach(([b]) => (b.disabled = true));
    try {
      const response = await api(path, body);
      if (view === "mafia") acceptSnapshot(view, response);
      if (view === "rocket") {
        acceptSnapshot(view, { ...state.rocket, ...response });
        await load("rocket", true);
      }
      if (close) $("#sheet").close();
      if (response.message && !quiet) toast(response.message);
      if (view === "friends") await load("friends", true);
      if (tab === view || (view === "friends" && tab === "community") || (view === "mafia" && ["games", "interactive"].includes(tab))) patch();
      return response;
    } catch (e) {
      toast(e.message);
      await load(view, true);
      return null;
    } finally {
      pending = false;
      controls.forEach(([b, disabled]) => {
        if (b.isConnected) b.disabled = disabled;
      });
      if (tab === view || (view === "friends" && tab === "community") || (view === "mafia" && ["games", "interactive"].includes(tab))) patch();
      schedule();
    }
  }
  async function mafiaAction(action, extra = {}, opts = {}) {
    const r = state.mafia?.room;
    const body = {
      action,
      ...(r ? { room_id: r.id, phase_token: r.phase_token } : {}),
      ...extra,
    };
    const key = JSON.stringify(body);
    if (retryAction?.key !== key)
      retryAction = { key, id: crypto.randomUUID() };
    const response = await performAction(
      "mafia",
      "mafia/action",
      { request_id: retryAction.id, ...body },
      opts,
    );
    if (response) retryAction = null;
    return response;
  }
  function findFriend(id) {
    const f = state.friends;
    return (
      f &&
      [...f.friends, ...f.incoming, ...f.outgoing, ...f.blocked].find(
        (p) => p.id === id,
      )
    );
  }
  function friendAction(action, id) {
    const person = findFriend(id);
    if (!person) return;
    const send = () =>
      performAction(
        "friends",
        "friends/action",
        {
          action,
          target_id: id,
          ...(person.token ? { token: person.token } : {}),
        },
        { close: true },
      );
    if (["remove", "block"].includes(action)) {
      sheet(
        `<h2>${action === "block" ? "Заблокировать" : "Удалить из друзей"}?</h2><p class="sub">${esc(person.name)}${action === "block" ? " не сможет присылать заявки и приглашения. Разблокировать можно в этом разделе." : " исчезнет из списка. Чтобы снова дружить, понадобится новая заявка."}</p><button class="primary" id="friend-confirm">${action === "block" ? "Заблокировать" : "Удалить"}</button>`,
      );
      $("#friend-confirm").onclick = send;
    } else send();
  }
  function createRoom() {
    sheet(
      '<span class="eyebrow">Своя компания</span><h2>Новая комната</h2><form id="mafia-create-form"><label for="mafia-room-title">Название<input id="mafia-room-title" name="title" maxlength="60" placeholder="Вечер в Норе" value="' +
        esc(drafts.room) +
        '"></label><p class="sub">5–12 игроков, без ставок. Пригласи друзей, дождись готовности каждого и начинайте.</p><button class="primary" type="submit">Создать комнату</button></form>',
    );
  }
  async function inviteFriends(preselect = null) {
    await load("friends", true);
    const r = state.mafia?.room;
    if (!r || r.status !== "lobby") {
      toast("Сначала создай комнату «Мафии»");
      go("mafia");
      return;
    }
    const list = (state.friends?.friends || []).filter(
      (p) => p.available !== false && !r.players.some((x) => x.id === p.id),
    );
    sheet(
      `<span class="eyebrow">Собираем своих</span><h2>Позвать в «Мафию»</h2><p class="sub">${esc(r.title)} · ${r.players.length} / 12 игроков</p>${list.length ? list.map((p) => `<button class="invite-person ${p.id === preselect ? "preselected" : ""}" data-invite-person="${p.id}"><span class="person-avatar" data-person-avatar="${p.id}" ${p.has_avatar===false?"data-avatar-unavailable":""}>${initials(p.name)}</span><span><b>${esc(p.name)}</b><small>Пригласить в комнату</small></span>${icon("arrow")}</button>`).join("") : '<p class="sub">Все доступные друзья уже за столом или список пока пуст.</p>'}<button class="secondary" id="friends-from-invite">Добавить друзей</button>`,
    );
  }
  async function rocketPrepare(form) {
    if (pending || busy) return;
    pending = true;
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      const q = await api("rocket/prepare", {
        bet: Number(drafts.bet),
        auto_cashout: drafts.autoOn ? Number(drafts.auto) : null,
      });
      sheet(
        `<span class="eyebrow">До запуска — одно решение</span><h2>Отправляем<br>ракету?</h2><div class="amount">${number(q.bet)} 🍪</div><p class="sub">Эта сумма спишется из кошелька при запуске. Срыв до выхода — потеря всей ставки.</p><div class="quote-facts"><span>Автовыход<b>${q.auto_cashout ? "×" + Number(q.auto_cashout).toFixed(2) : "Выключен"}</b></span><span>Отсчёт<b>3 секунды</b></span></div><button class="primary" id="rocket-confirm">Списать ${number(q.bet)} 🍪 и запустить</button>`,
      );
      $("#rocket-confirm").onclick = () =>
        performAction(
          "rocket",
          "rocket/launch",
          { token: q.token },
          { close: true },
        );
    } catch (e) {
      toast(e.message);
    } finally {
      pending = false;
      if (button.isConnected) button.disabled = false;
    }
  }
  document.addEventListener("input", (e) => {
    const id = e.target.id;
    if (id === "friend-recipient") drafts.friend = e.target.value;
    if (id === "mafia-room-title") drafts.room = e.target.value;
    if (id === "mafia-chat-input") drafts.chat = e.target.value;
    if (id === "rocket-bet") drafts.bet = e.target.value;
    if (id === "rocket-auto") drafts.auto = e.target.value;
  });
  document.addEventListener("change", (e) => {
    if (e.target.id === "rocket-auto-on") {
      drafts.autoOn = e.target.checked;
      $("#rocket-auto-label").hidden = !drafts.autoOn;
      $("#rocket-auto").disabled = !drafts.autoOn;
      $("#rocket-auto").required = drafts.autoOn;
    }
  });
  document.addEventListener("submit", async (e) => {
    const id = e.target.id;
    if (
      ![
        "friend-add-form",
        "mafia-create-form",
        "mafia-chat-form",
        "rocket-bet-form",
      ].includes(id)
    )
      return;
    e.preventDefault();
    if (id === "friend-add-form") {
      const result = await performAction("friends", "friends/action", {
        action: "request",
        recipient: drafts.friend.trim(),
      });
      if (result) {
        drafts.friend = "";
        patch();
      }
    }
    if (id === "mafia-create-form") {
      const result = await mafiaAction(
        "create",
        { title: drafts.room.trim() || "Вечер в Норе" },
        { close: true },
      );
      if (result) {
        drafts.room = "";
        go("mafia");
      }
    }
    if (id === "mafia-chat-form") {
      const text = drafts.chat.trim();
      if (!text) return;
      const result = await mafiaAction(
        "chat",
        { channel: chatChannel, text },
        { quiet: true },
      );
      if (result) {
        drafts.chat = "";
        patch();
      }
    }
    if (id === "rocket-bet-form") rocketPrepare(e.target);
  });
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.gameRetry) load(b.dataset.gameRetry, true);
    if (b.dataset.friendAction)
      friendAction(b.dataset.friendAction, Number(b.dataset.personId));
    if (b.dataset.friendPlay) {
      await load("mafia", true);
      go("mafia");
      if (state.mafia?.room?.status === "lobby")
        inviteFriends(Number(b.dataset.friendPlay));
      else if (!state.mafia?.room) createRoom();
      else toast("Заверши текущую партию, чтобы пригласить друзей");
    }
    if (b.id === "mafia-create" || b.id === "mafia-new") createRoom();
    if (b.id === "mafia-current") {
      roomFocus = null;
      load("mafia", true, null);
    }
    if (b.id === "mafia-role") {
      roleOpen = !roleOpen;
      patch();
    }
    if (b.id === "mafia-invite") inviteFriends();
    if (b.id === "friends-from-invite") {
      $("#sheet").close();
      go("friends");
    }
    if (b.dataset.invitePerson) {
      const result = await mafiaAction("invite", {
        user_id: Number(b.dataset.invitePerson),
      });
      if (result && b.isConnected) {
        b.disabled = true;
        b.innerHTML = "<span>Приглашение отправлено ✓</span>";
      }
    }
    if (b.dataset.mafiaRespond) {
      const result = await mafiaAction("respond", {
        room_id: b.dataset.roomId, accept: b.dataset.mafiaRespond === "yes",
      });
      if (tab === 'notices') await window.NoraCabinet?.reloadNotices();
      if (result && b.dataset.mafiaRespond === 'yes') go('mafia');
    }
    if (b.dataset.mafiaHistory) load("mafia", true, b.dataset.mafiaHistory);
    if (b.dataset.mafiaTarget) {
      const target =
        b.dataset.mafiaTarget === "skip" ? null : Number(b.dataset.mafiaTarget);
      mafiaAction(b.dataset.targetAction, { target_id: target });
    }
    if (b.dataset.mafiaAction) {
      const action = b.dataset.mafiaAction;
      if (["leave", "cancel"].includes(action)) {
        sheet(
          `<h2>${action === "cancel" ? "Выйти и удалить комнату?" : "Покинуть партию?"}</h2><p class="sub">${action === "cancel" ? "Комната закроется для всех участников, приглашения перестанут действовать. Новую можно создать сразу." : state.mafia?.room?.status === "active" ? "Ты выбываешь из текущей партии. Остальные продолжат играть." : "Ты выйдешь из комнаты."}</p><button class="primary" id="mafia-leave-confirm">${action === "cancel" ? "Выйти и удалить" : "Выйти"}</button>`,
        );
        $("#mafia-leave-confirm").onclick = () =>
          mafiaAction(action, {}, { close: true });
      } else
        mafiaAction(
          action,
          action === "ready" ? { ready: !state.mafia.room.self.ready } : {},
        );
    }
    if (b.id === "mafia-rules")
      sheet(
        "<h2>Город живёт по правилам</h2>" +
          mafiaRules().replace("<details ", "<details open "),
      );
    if (b.dataset.rocketStake) {
      drafts.bet = b.dataset.rocketStake;
      patch();
    }
    if (b.id === "rocket-cashout" && state.rocket?.round)
      performAction("rocket", "rocket/cashout", {
        round_id: state.rocket.round.id,
      });
  });
  window.addEventListener("popstate", () => {
    const next = window.NoraShop?.route().view;
    if (data && views.has(next)) {
      tab = next;
      render();
      NoraShop.syncBack();
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      roleOpen = false;
      cancelAnimationFrame(frame);
      clearTimeout(pollTimer);
    } else if (liveViews.has(tab) || ["games", "interactive", "community"].includes(tab)) {
      load(tab === "community" ? "friends" : ["games", "interactive"].includes(tab) ? "mafia" : tab, true);
      animation();
      schedule();
    }
  });
  return {
    screen,
    invitationCard,
    mount,
    parent,
    refreshCurrent,
    icon,
    handles: (view) => views.has(view),
    live: (view) => liveViews.has(view),
    friendsCount: () => state.friends?.counts?.incoming || 0,
  };
})();
