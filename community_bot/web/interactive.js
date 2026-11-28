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
    mafia: NoraI18n.t("Мафия"),
    detective: NoraI18n.t("Комиссар"),
    doctor: NoraI18n.t("Доктор"),
    civilian: NoraI18n.t("Мирный житель"),
  };
  const phaseNames = {
    lobby: NoraI18n.t("Собираемся"),
    night: NoraI18n.t("Город засыпает"),
    discussion: NoraI18n.t("Город просыпается"),
    vote: NoraI18n.t("Время решения"),
    finished: NoraI18n.t("Партия завершена"),
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
    locked: "M7 10V7a5 5 0 0 1 10 0v3 M6 10h12v10H6z M12 14v2",
    unlocked: "M7 10V7a5 5 0 0 1 9.4-2.4 M6 10h12v10H6z M12 14v2",
    refresh: "M20 9a8 8 0 1 0 0 6 M20 4v5h-5",
    plus: "M12 5v14 M5 12h14",
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
    goToTab(view);
  }
  function parent(view) {
    return (
      {
        games: "community",
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
      ? `<div class="play-connection" role="status">${esc(errors[view])}<button class="text-btn" data-game-retry="${view}">${NoraI18n.html("Обновить")}</button></div>`
      : "";
  }
  function interactiveScreen() {
    return `${mafiaInvites()}<p class="eyebrow">${NoraI18n.html("У каждого свой способ")}</p><h1>${NoraI18n.html("Побудем")}<br><em>${NoraI18n.html("вместе")}</em></h1><p class="sub play-intro">${NoraI18n.html("Заботься, играй, собирай своих.")}</p><button class="play-hero pet-hero" data-tab="pet"><span class="play-hero-copy"><span class="eyebrow">${NoraI18n.html("Твой маленький спутник")}</span><strong><em>${NoraI18n.html("Питомец")}</em></strong><span class="play-hero-description">${data.pet ? esc(data.pet.name) + NoraI18n.t(" ждёт тебя. Забота, походы и маленькие находки.") : NoraI18n.t("Заведи питомца. Заботься о нём и отправляй за приключениями.")}</span><span class="play-hero-cta">${data.pet ? NoraI18n.t("К питомцу") : NoraI18n.t("Знакомиться")} ${icon("arrow")}</span></span><span class="play-hero-art pet-orbit">${NoraShop.svg("pets")}<i></i><i></i><i></i></span></button><button class="play-hero games-hero" data-tab="games"><span class="play-hero-copy"><span class="eyebrow">${NoraI18n.html("Один или всей компанией")}</span><strong><em>${NoraI18n.html("Игры")}</em></strong><span class="play-hero-description">${NoraI18n.html("У города есть тайны.")}<br>${NoraI18n.html("У ракеты — свой предел.")}</span><span class="play-hero-cta">${NoraI18n.html("Выбрать игру")} ${icon("arrow")}</span></span><span class="play-hero-art">${icon("game")}<span class="art-plus">+</span></span></button><button class="play-friends-link" data-tab="friends">${icon("friends")}<span>${NoraI18n.html("Свои всегда рядом")}<small>${NoraI18n.html("Добавляй друзей и зови играть")}</small></span>${icon("arrow")}</button>`;
  }
  const games = { durak: NoraI18n.t("Дурак"), barricade: NoraI18n.t("Баррикада"), sea: NoraI18n.t("Морской бой"), mafia: NoraI18n.t("Мафия"), dot: "DOT", rocket: NoraI18n.t("Ракетка"), poker: NoraI18n.t("Покер"), dice: "DICE" };
  const gameChoices = ["durak", "barricade", "poker", "dot", "dice", "rocket"];
  const lobbyLimit = 5;
  let lobbyRooms = null, lobbyLoading = false, lobbyError = "", showAllLobbies = false;

  const gameGlyphs = {
    dice: `<g transform="rotate(-12 45 46)"><rect x="18" y="19" width="54" height="54" rx="11" fill="#2d303d" stroke="currentColor"/><rect x="22" y="23" width="46" height="46" rx="8" stroke="#ffffff" opacity=".25"/><g fill="#f1edf6" stroke="none"><circle cx="31" cy="32" r="4"/><circle cx="45" cy="46" r="4"/><circle cx="59" cy="60" r="4"/></g></g><g transform="rotate(15 76 64)"><rect x="58" y="46" width="34" height="34" rx="7" fill="#4b2633" stroke="#ff7895"/><circle cx="75" cy="63" r="5" fill="#ff9ab0" stroke="none"/></g>`,
    poker: `<g transform="rotate(12 61 45)"><rect x="44" y="15" width="37" height="54" rx="5" fill="#37333a"/><path d="M64 32c-4 4-9 7-9 12a4.7 4.7 0 0 0 9 2 4.7 4.7 0 0 0 9-2c0-5-5-8-9-12Z" fill="currentColor" stroke="none"/><path d="m62 52 2-5 2 5"/></g><circle cx="36" cy="70" r="18" fill="#702538" stroke="#f19a9d" stroke-width="3" stroke-dasharray="10 4"/><circle cx="36" cy="70" r="11" stroke="#e9979e"/>`,
    durak: `<g transform="rotate(13 65 47)"><rect x="51" y="19" width="37" height="56" rx="6" fill="#303035" stroke="currentColor"/><path d="M69.5 39c-3.8 5-9 7-9 12a4.8 4.8 0 0 0 9 2.1 4.8 4.8 0 0 0 9-2.1c0-5-5.2-7-9-12Z" fill="currentColor" stroke="none"/><path d="m67 58 2.5-5 2.5 5" fill="currentColor" stroke="none"/></g>
      <g transform="rotate(-12 44 48)"><rect x="25" y="20" width="38" height="57" rx="6" fill="#47474d" stroke="currentColor"/><path d="M44 57c-3-2.5-10-7-10-12.2a5.7 5.7 0 0 1 10-3.9 5.7 5.7 0 0 1 10 3.9C54 50 47 54.5 44 57Z" fill="var(--game-accent)" stroke="none"/><path d="M32 29h5m14 40h5" opacity=".55"/></g>`,
    barricade: `<rect x="22" y="19" width="60" height="60" rx="7" fill="#343439" stroke="currentColor"/><path d="M34 20v58m12-58v58m12-58v58m12-58v58M23 31h58M23 43h58M23 55h58M23 67h58" stroke="#77777f" stroke-width="1.2"/><path d="M34 43h24M70 55v24" stroke="#c3c3c9" stroke-width="3.8"/><path d="M46 67V43" stroke="var(--game-accent)" stroke-width="4.4"/><circle cx="64" cy="25" r="3.6" fill="#d2d2d6" stroke="none"/><circle cx="40" cy="73" r="3.6" fill="#d2d2d6" stroke="none"/>`,
    dot: `<g fill="#343439" stroke="currentColor"><rect x="20" y="16" width="13" height="20" rx="3"/><rect x="20" y="60" width="13" height="22" rx="3"/><rect x="71" y="16" width="13" height="31" rx="3"/><rect x="71" y="71" width="13" height="11" rx="3"/></g><path d="M12 51c15 13 26 14 39-1s22-1 34 7" stroke="#7b7b83" stroke-dasharray="2 5" stroke-width="1.8"/><circle cx="52" cy="49" r="8" fill="var(--game-accent)" stroke="none"/>`,
    rocket: `<g transform="rotate(35 52 48)"><path d="M43 51c-10 3-13 11-12 20l12-6m18-14c10 3 13 11 12 20l-12-6" fill="#414147" stroke="currentColor"/><path d="M52 12c-12 9-17 24-13 45l4 9h18l4-9c4-21-1-36-13-45Z" fill="#4b4b51" stroke="currentColor"/><circle cx="52" cy="36" r="7" fill="#202024" stroke="currentColor"/><path d="M43 58h18" stroke="#c0c0c6"/><path d="M47 71c-2 5 0 10 5 15 5-5 7-10 5-15Z" fill="var(--game-accent)" stroke="none"/></g>`
  };

  function gameShortcut(game, create = false) {
    const action = create ? "data-create-match" : "data-tab";
    const glyph = gameGlyphs[game];
    const soon = game === "dice" || game === "poker";
    return `<button type="button" class="game-shortcut game-${game}${glyph ? " game-shortcut-mono" : ""}" ${action}="${game}">
      ${glyph ? `<span class="game-shortcut-art" aria-hidden="true"><svg viewBox="0 0 104 96" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" focusable="false">${glyph}</svg>${soon ? '<span class="game-soon">SOON</span>' : ""}</span>` : ""}
      <span class="game-shortcut-name">${games[game]}</span>
    </button>`;
  }

  function noraGameCard() {
    return `<button type="button" class="nora-game-card" id="nora-game-open" aria-label="${NoraI18n.html("НОРА — войти в воксельный мир")}">
      <svg class="nora-game-card-art" viewBox="0 0 320 280" fill="none" shape-rendering="crispEdges" aria-hidden="true" focusable="false">
        <path fill="#152b2a" d="M0 174h24v-18h32v18h24v-40h24v-20h32v20h24v-16h32v16h24v-34h24v-16h24v16h24v36h32v144H0z"/>
        <path fill="#213d36" d="M0 214h36v-16h48v12h32v-22h56v12h40v-24h48v20h60v84H0z"/>
        <path fill="#40523d" d="m76 222 152-30 92 36-140 44z"/>
        <path fill="#23332c" d="m76 222 104 34v24L76 246z"/>
        <path fill="#334137" d="m180 256 140-28v24l-140 28z"/>
        <path fill="#6a6a50" d="m154 228 62-14 22 8-62 16z"/>
        <path fill="#8c8060" d="m176 238 62-16 14 6-62 16z"/>
        <path fill="#48554b" d="M154 210V110h12V86h16V74h64v12h16v24h12v100h-24v-96h-12V98h-48v16h-12v96z"/>
        <path fill="#819080" d="M154 110h12v-8h16V86h64v12h-56v16h-24v96h-12z"/>
        <path fill="#303f39" d="M246 86h12v24h16v100h-12v-92h-12V98h-4z"/>
        <path fill="#a89970" d="M166 132h12v8h-12zm0 38h12v8h-12zm84-36h12v8h-12zm0 38h12v8h-12zm-44-86h16v8h-16z"/>
        <g class="nora-card-portal">
          <path fill="#681e39" d="M178 210V114h12V98h48v16h12v96z"/>
          <path fill="#b72e50" d="M184 210v-90h12v-16h36v16h12v90z"/>
          <path fill="#eb4e65" d="M190 210v-84h12v-16h24v16h12v84z"/>
          <path fill="#ff9b8e" d="M196 206v-68h6v-12h12v-10h6v20h-12v70z"/>
          <path fill="#ffcdad" d="M202 148h6v32h-6zm0 42h6v10h-6z"/>
        </g>
        <path fill="#977b4b" d="M126 196h8v24h-8zm160-8h8v24h-8z"/>
        <path fill="#e69c56" d="M122 192h16v12h-16zm160-8h16v12h-16z"/>
        <path fill="#ffd69a" d="M126 184h8v16h-8zm160-8h8v16h-8z"/>
        <path fill="#39493b" d="M90 110h8v114h-8zm208-24h8v130h-8z"/>
        <path fill="#24473a" d="M62 144h16v-24h12V96h12v24h12v24h16v24h-16v18H78v-18H62zm212-22h12V98h12V74h12v24h10v68h-34v-20h-12z"/>
        <path fill="#346048" d="M78 144h12v-24h12v24h12v12H78zm208-22h12V98h12v36h-24z"/>
        <path fill="#5a7d55" d="M106 216h12v-8h16v8h8v12h-36zm158-2h12v-8h16v8h12v12h-40z"/>
        <path fill="#69858a" d="m272 48 8-16 8 16-8 20z"/>
        <path fill="#a5d4ca" d="m272 48 8-16v36z"/>
        <g class="nora-card-sparks" fill="#f4cd8d">
          <path d="M142 72h4v4h-4zm116-20h4v4h-4zm-22 8h4v4h-4zm-98 102h4v4h-4zm142-12h4v4h-4zm-46 84h4v4h-4z"/>
          <path d="M116 96h4v-4h4v4h4v4h-4v4h-4v-4h-4zm168-12h4v-4h4v4h4v4h-4v4h-4v-4h-4z"/>
        </g>
      </svg>
      <span class="nora-game-logo">N<span>O</span>RA</span>
      <span class="nora-game-card-bottom"><span>${NoraI18n.html("Войти в Нору")}</span><b aria-hidden="true">→</b></span>
    </button>`;
  }

  function lobbyRow(room) {
    const { id, game, action, locked } = room;
    const roomId = esc(id);
    const title = game === "durak" ? NoraI18n.t("Стол ") + room.title : room.title;
    const detail = action === "invite" ? NoraI18n.t("Приглашение") : action === "resume" ? NoraI18n.t("Моё лобби") : "";
    const name = games[game];
    const attributes = game === "barricade" ? `data-barricade-lobby="${roomId}"`
      : action === "invite" ? `data-${game}-respond="yes" data-room-id="${roomId}"`
      : action === "resume" && game !== "durak" ? `data-tab="${game}"`
      : game === "sea" && action === "join" ? `data-sea-join="${roomId}" data-locked="${locked ? 1 : 0}"`
      : game === "mafia" && action === "join" ? `data-mafia-join="${roomId}"`
      : game === "durak" ? `data-durak-lobby="${roomId}"` : "";
    const contents = `<span class="lobby-icon" aria-hidden="true"></span>
      <span class="lobby-copy"><b>${esc(title)}</b><small>${name}${detail ? " · " + detail : ""}${room.stake ? " · " + number(room.stake) + " 🍪" : ""}</small></span>
      <span class="lobby-count"><span class="sr-only">${room.players} ${NoraI18n.html("из")} ${room.capacity} ${NoraI18n.html("игроков")}</span><span aria-hidden="true">${room.players}/${room.capacity}</span></span>
      <span class="lobby-lock" role="img" aria-label="${locked ? NoraI18n.t("Закрытое лобби") : NoraI18n.t("Открытое лобби")}">${icon(locked ? "locked" : "unlocked")}</span>`;
    return `<li class="game-lobby-row game-${game}">
      ${attributes ? `<button type="button" class="lobby-entry" id="lobby-${game}-${roomId}" ${attributes}>${contents}</button>`
        : `<div class="lobby-entry">${contents}</div>`}
      ${action === "invite" && game !== "barricade" ? `<button type="button" class="lobby-side-action" data-${game}-respond="no" data-room-id="${roomId}" aria-label="${NoraI18n.html("Отклонить приглашение в")} ${esc(title)}">×</button>` : ""}
      ${room.admin ? `<button type="button" class="lobby-side-action" data-sea-admin-close="${roomId}" aria-label="${NoraI18n.html("Закрыть лобби")} ${esc(title)}">×</button>` : ""}
    </li>`;
  }

  function lobbyList() {
    const status = lobbyError ? ("<p class=\"lobby-status\" role=\"status\">" + NoraI18n.html("Не удалось обновить лобби.") + "</p>")
      : !lobbyRooms ? ("<p class=\"lobby-status\">" + NoraI18n.html("Загружаем лобби…") + "</p>")
      : !lobbyRooms.length ? ("<p class=\"lobby-status\">" + NoraI18n.html("Пока нет лобби") + "</p>") : "";
    const visible = showAllLobbies ? lobbyRooms : lobbyRooms?.slice(0, lobbyLimit);
    const more = (lobbyRooms?.length || 0) - lobbyLimit;
    return status + (visible?.length ? `<ul class="game-lobby-list" id="game-lobby-list">${visible.map(lobbyRow).join("")}</ul>` : "")
      + (more > 0 ? `<button type="button" class="lobby-more" id="games-show-all" aria-expanded="${showAllLobbies}" aria-controls="game-lobby-list">${showAllLobbies ? NoraI18n.t("Свернуть") : `${NoraI18n.t("Ещё")} ${more}`}</button>` : "");
  }

  function patchLobbies() {
    const el = $("#games-lobbies");
    if (!el) return;
    const focusId = el.contains(document.activeElement) && document.activeElement.id;
    el.innerHTML = lobbyList();
    if (focusId) (document.getElementById(focusId) || $("#games-refresh")).focus({ preventScroll: true });
  }

  async function reloadLobbies() {
    if (tab !== "games" || lobbyLoading) return;
    lobbyLoading = true;
    const refresh = $("#games-refresh");
    refresh?.setAttribute("aria-busy", "true");
    const previous = lobbyList();
    try {
      lobbyRooms = (await api("community/lobbies")).rooms.filter(room => room.game !== "sea" && room.game !== "mafia");
      lobbyError = "";
    } catch (error) {
      lobbyError = error.message || NoraI18n.t("Связь прервалась");
    } finally {
      lobbyLoading = false;
      refresh?.removeAttribute("aria-busy");
      if (previous !== lobbyList()) patchLobbies();
    }
  }

  function gamesScreen() {
    return `<section class="games-screen-fit"><div class="games-heading nora-page-heading">${back(parent("games"), NoraI18n.t("Коммьюнити"))}<h1>${NoraI18n.html("Игры")}</h1></div>
      <div class="games-catalog">
        <div class="game-shortcuts" role="group" aria-label="${NoraI18n.html("Выбор игры")}">${gameChoices.map(game => gameShortcut(game)).join("")}</div>
        ${noraGameCard()}
      </div>
      <section class="game-lobbies" aria-labelledby="game-lobbies-title">
        <div class="game-lobbies-head"><h2 id="game-lobbies-title">${NoraI18n.html("Лобби")}</h2>
          <button type="button" id="games-refresh" class="lobby-tool" aria-label="${NoraI18n.html("Обновить лобби")}">${icon("refresh")}</button>
          <button type="button" id="games-create" class="lobby-tool" aria-label="${NoraI18n.html("Создать матч")}" aria-haspopup="dialog">${icon("plus")}</button>
        </div>
        <div id="games-lobbies">${lobbyList()}</div>
      </section></section>`;
  }

  function chooseMatch() {
    sheet(`<div class="game-create-menu"><h2>${NoraI18n.html("Новый матч")}</h2>${gameChoices.filter(game => game !== "dot" && game !== "dice" && (game !== "poker" || data.beta_games_available === true)).map(game => gameShortcut(game, true)).join("")}</div>`);
    $("#sheet-content button")?.focus();
  }
  function friendRow(person, section) {
    const actions = {
      friends: [
        ["remove", NoraI18n.t("Удалить")],
        ["block", NoraI18n.t("Заблокировать")],
      ],
      incoming: [
        ["accept", NoraI18n.t("Принять")],
        ["decline", NoraI18n.t("Отклонить")],
        ["block", NoraI18n.t("Заблокировать")],
      ],
      outgoing: [["cancel", NoraI18n.t("Отозвать")]],
      blocked: [["unblock", NoraI18n.t("Разблокировать")]],
    }[section];
    return `<article class="friend-row"><div class="friend-person"><button class="person-visit" data-person-view="${person.id}" aria-label="${NoraI18n.html("Открыть профиль")} ${esc(person.name)}"><span class="person-avatar" data-person-avatar="${person.id}" ${person.has_avatar===false?"data-avatar-unavailable":""}>${initials(person.name)}</span><span><b>${NoraPrefix(person.prefix)}${esc(person.name)}</b><small>${person.username ? "@" + esc(person.username) : NoraI18n.t("Участник Норы")}</small>${section==='friends'?`<small class="person-presence ${person.presence?.online?'online':''}">${esc(window.NoraPeople?.presenceLine(person.presence)||'')}</small>`:''}</span></button>${section === "friends" && person.available !== false ? `<button class="icon-button" data-friend-play="${person.id}" aria-label="${NoraI18n.html("Пригласить")} ${esc(person.name)} ${NoraI18n.html("в игру")}">${icon("game")}</button>` : ""}</div><div class="friend-row-actions">${section==='friends'?`<button class="text-btn" data-friend-transfer="${person.id}" data-friend-name="${esc(person.name)}">${NoraI18n.html("Перевести 🍪")}</button>`:''}${actions.map(([action, label]) => `<button class="${action === "accept" ? "friend-accept" : "text-btn"}" data-friend-action="${action}" data-person-id="${person.id}" ${pending ? "disabled" : ""}>${label}</button>`).join("")}</div></article>`;
  }
  function friendsScreen() {
    const f = state.friends;
    const count = f?.friends?.length || 0;
    const online = f?.friends?.filter((p) => p.presence?.online).length || 0;
    const incoming = f?.incoming?.length || 0;
    const embedded = tab === "community";
    const search = ("<button class=\"secondary community-find\" data-community-search>" + NoraI18n.html("⌕ Найти участников") + "</button>");
    const list = `${errorBox("friends")}${search}
      ${!f ? ("<div class=\"empty\">" + NoraI18n.html("Загружаем друзей…") + "</div>") : ""}
      ${incoming ? `<section class="friend-section"><h2>${NoraI18n.html("Зовут дружить")} ${badge(incoming, true)}</h2>${f.incoming.map((p) => friendRow(p, "incoming")).join("")}</section>` : ""}
      ${f ? `<section class="friend-section">${embedded && !incoming ? "" : `<h2>${embedded ? NoraI18n.t("В списке") : NoraI18n.t("Друзья")} ${badge(count)}</h2>`}
        ${count ? f.friends.map((p) => friendRow(p, "friends")).join("") : ("<div class=\"card empty\">" + NoraI18n.html("Список пока пуст.") + "<br>" + NoraI18n.html("Начни с одного знакомого имени.") + "</div>")}
      </section>` : ""}
      ${f?.outgoing?.length ? `<section class="friend-section"><h2>${NoraI18n.html("Ждём ответа")}</h2>${f.outgoing.map((p) => friendRow(p, "outgoing")).join("")}</section>` : ""}
      ${f?.blocked?.length ? `<details class="play-details" data-detail="blocked"><summary>${NoraI18n.html("Заблокированные ·")} ${f.blocked.length}</summary>${f.blocked.map((p) => friendRow(p, "blocked")).join("")}</details>` : ""}`;
    if (embedded) {
      return `<details class="community-table community-friends" data-detail="community-friends" data-retain-open="community-friends">
        <summary id="community-friends-summary"><span class="community-friends-label">${NoraI18n.html("Друзья")} ${f ? `<span class="community-friends-online" aria-label="${NoraI18n.html("Онлайн")} ${online} ${NoraI18n.html("из")} ${count} ${NoraI18n.html("друзей")}">${online}/${count}</span>` : ""}${incoming ? ` ${badge("+" + incoming, true)}` : ""}</span><span class="community-chevron" aria-hidden="true">⌄</span></summary>
        <div class="community-table-body">${list}</div>
      </details>`;
    }
    return `${back("community", NoraI18n.t("Коммьюнити"))}<div class="play-title-row"><div><p class="eyebrow">${NoraI18n.html("Близкие по духу")}</p><h2><em>${NoraI18n.html("Друзья")}</em></h2></div><span class="play-title-icon">${icon("friends")}</span></div><p class="sub">${NoraI18n.html("Добавь участника Норы. Когда он примет заявку, сможете взаимодействовать друг с другом.")}</p>${list}`;
  }
  function roleExplanation(role) {
    return (
      state.mafia?.rules?.roles?.find((r) => r.id === role)?.description ||
      {
        civilian:
          NoraI18n.t("Слушай, сопоставляй и голосуй. Найдите всю мафию, пока она не сравнялась числом с городом."),
        mafia:
          NoraI18n.t("Вы знакомы с союзниками. Ночью договоритесь о цели, днём не выдавайте себя."),
        doctor:
          NoraI18n.t("Ночью защити одного игрока. Себя можно спасти один раз; одну цель нельзя лечить две ночи подряд."),
        detective:
          NoraI18n.t("Каждую ночь проверяй одного игрока. Результат проверки увидишь только ты."),
      }[role] ||
      ""
    );
  }
  function mafiaRules() {
    const rules = state.mafia?.rules;
    return `<details class="play-details" data-detail="mafia-rules"><summary>${NoraI18n.html("Как устроена «Мафия»")} ${icon("shield")}</summary><p class="sub">${rules?.min_players || 5}–${rules?.max_players || 12} ${NoraI18n.html("человек. Участие бесплатное — печеньки не списываются и не разыгрываются.")}</p>${(rules?.roles || Object.keys(roleNames).map((id) => ({ id, name: roleNames[id], description: roleExplanation(id) }))).map((r) => `<div class="rule-row"><b>${esc(r.name)}</b><p>${esc(r.description)}</p></div>`).join("")}${(
      rules?.sections || [
        {
          title: NoraI18n.t("Ночь → обсуждение → голосование"),
          text: NoraI18n.t("На ночь отводится 60 секунд, на обсуждение — 90, на голосование — 45. Таймер работает на сервере, даже если миниапка закрыта."),
        },
        {
          title: NoraI18n.t("Победа"),
          text: NoraI18n.t("Город побеждает, когда мафии не осталось. Мафия побеждает, когда сравнялась с городом по числу живых игроков."),
        },
      ]
    ).map(
      (r) =>
        `<div class="rule-row"><b>${esc(r.title)}</b><p>${esc(r.text)}</p></div>`,
    )}</details>`;
  }
  function invitationCard(i) {
    return `<section class="card mafia-invite"><span class="eyebrow">${NoraI18n.html("Друг приглашает в «Мафию»")}</span><h3>${esc(i.title)}</h3><p class="sub">${NoraPrefix(i.sender_prefix)}${esc(i.sender_name)} ${NoraI18n.html("зовёт тебя в комнату ·")} ${number(i.players_count)} ${NoraI18n.html("за столом")}</p><div class="pet-action-row"><button class="primary" data-mafia-respond="yes" data-room-id="${esc(i.room_id)}" ${pending ? "disabled" : ""}>${NoraI18n.html("Принять")}</button><button class="secondary" data-mafia-respond="no" data-room-id="${esc(i.room_id)}" ${pending ? "disabled" : ""}>${NoraI18n.html("Отклонить")}</button></div></section>`;
  }
  function roomControls(r) {
    if (!['lobby','active'].includes(r.status) || r.self.left) return '';
    return `<section class="card mafia-room-controls"><button class="secondary" data-mafia-action="leave">${r.host_id === r.self.id ? NoraI18n.t("Выйти и удалить комнату") : NoraI18n.t("Выйти из комнаты")}</button></section>`;
  }
  function mafiaInvites() {
    return (state.mafia?.invites || []).map(invitationCard).join('');
  }

  function mafiaHome() {
    const m = state.mafia;
    return `${back("games", NoraI18n.t("Игры"))}<div class="play-title-row"><div><p class="eyebrow">${NoraI18n.html("Бесплатно · 5–12 человек")}</p><h1>${NoraI18n.html("В городе")}<br><em>${NoraI18n.html("неспокойно")}</em></h1></div><span class="play-title-icon">${icon("mafia")}</span></div><p class="sub">${NoraI18n.html("Кто-то уже знает больше, чем говорит.")}<br>${NoraI18n.html("Собери друзей и проверь свою интуицию.")}</p>${errorBox("mafia")}${m && !m.enabled ? ("<p class=\"game-restricted\">" + NoraI18n.html("Новые игры временно выключены администрацией.") + "</p>") : ""}${mafiaInvites()}<section class="card mafia-create"><span class="eyebrow">${NoraI18n.html("Твой стол, твоя компания")}</span><h2>${NoraI18n.html("Начнём с приглашения.")}</h2><p class="sub">${NoraI18n.html("Создай комнату, позови друзей. Партия начнётся, когда все будут готовы.")}</p><button class="primary" id="mafia-create" ${pending || !m || !m.enabled ? "disabled" : ""}>${NoraI18n.html("Создать комнату")}</button><button class="secondary" data-tab="friends">${NoraI18n.html("Найти своих")}</button></section>${mafiaRules()}${m?.recent?.length ? `<details class="play-details" data-detail="mafia-recent"><summary>${NoraI18n.html("Прошлые партии ·")} ${m.recent.length}</summary>${m.recent.map((r) => `<button class="mafia-recent" data-mafia-history="${esc(r.id)}"><span><b>${esc(r.title)}</b><small>${winnerLabel(r.winner, r.status)}</small></span>${icon("arrow")}</button>`).join("")}</details>` : ""}`;
  }
  function winnerLabel(winner, status) {
    if (status === "cancelled") return NoraI18n.t("Комната закрыта");
    return (
      {
        town: NoraI18n.t("Победил город"),
        civilian: NoraI18n.t("Победил город"),
        civilians: NoraI18n.t("Победил город"),
        mafia: NoraI18n.t("Победила мафия"),
        draw: NoraI18n.t("Ничья"),
      }[winner] || NoraI18n.t("Партия завершена")
    );
  }
  function players(room) {
    return `<div class="mafia-players">${room.players.map((p) => `<div class="mafia-player ${!p.alive && room.status !== "lobby" ? "out" : ""} ${p.id === room.self.id ? "you" : ""}"><span class="person-avatar" data-person-avatar="${p.id}" ${p.has_avatar===false?"data-avatar-unavailable":""}>${initials(p.name)}${p.id === room.host_id ? ("<i class=\"host-dot\" title=\"" + NoraI18n.html("Создатель комнаты") + "\"></i>") : ""}</span><b>${NoraPrefix(p.prefix)}${esc(p.name)}</b><small>${p.left ? NoraI18n.t("Вышел") : room.status === "lobby" ? (p.ready ? NoraI18n.t("Готов") : NoraI18n.t("Собирается")) : p.role ? esc(roleNames[p.role] || p.role) : p.alive ? NoraI18n.t("В игре") : NoraI18n.t("Выбыл")}${p.id === room.self.id ? NoraI18n.t(" · ты") : ""}</small>${p.voted && room.phase === "vote" ? ("<span class=\"player-voted\" aria-label=\"" + NoraI18n.html("Голос принят") + "\">✓</span>") : ""}</div>`).join("")}</div>`;
  }
  function roleCard(room) {
    if (!room.self.role) return "";
    return `<button class="mafia-role ${roleOpen ? "revealed" : ""}" id="mafia-role" aria-expanded="${roleOpen}"><span class="role-symbol">${icon(roleOpen && room.self.role === "doctor" ? "shield" : "eye")}</span><span><small>${roleOpen ? NoraI18n.t("Твоя тайная роль") : NoraI18n.t("Только для тебя")}</small><b>${roleOpen ? esc(roleNames[room.self.role] || room.self.role) : NoraI18n.t("Нажми, чтобы узнать роль")}</b>${roleOpen ? `<span>${esc(roleExplanation(room.self.role))}</span>` : ("<span>" + NoraI18n.html("Не показывай экран другим игрокам") + "</span>")}</span></button>`;
  }
  function actionPanel(room) {
    if (room.self.left)
      return ("<p class=\"phase-hint\">" + NoraI18n.html("Ты покинул эту комнату. Вернись к списку, чтобы создать новую.") + "</p>");
    if (room.status === "lobby")
      return `<div class="mafia-lobby-actions"><button class="${room.self.ready ? "secondary" : "primary"}" data-mafia-action="ready" ${pending ? "disabled" : ""}>${room.self.ready ? NoraI18n.t("Я пока не готов") : NoraI18n.t("Я готов")}</button>${room.inviteable ? ("<button class=\"secondary\" id=\"mafia-invite\">" + NoraI18n.html("Пригласить друзей") + "</button>") : ""}${room.host_id === room.self.id ? `<button class="primary mafia-start" data-mafia-action="start" ${pending || room.players.filter((p) => !p.left).length < (state.mafia.rules.min_players || 5) || room.players.some((p) => !p.left && !p.ready) ? "disabled" : ""}>${NoraI18n.html("Начать партию")}</button><p class="footer-note">${NoraI18n.html("Нужно минимум")} ${state.mafia.rules.min_players || 5} ${plural(state.mafia.rules.min_players || 5, NoraI18n.t("игрок"), NoraI18n.t("игрока"), NoraI18n.t("игроков"))}${NoraI18n.html(". Каждый нажимает «Я готов».")}</p>` : ""}</div>`;
    if (room.status !== "active") return "";
    if (!room.self.alive)
      return ("<section class=\"card game-observer\"><b>" + NoraI18n.html("Ты наблюдаешь за городом.") + "</b><p class=\"sub\">" + NoraI18n.html("Роли ещё скрыты. Обсуждать партию можно с другими выбывшими в отдельном чате.") + "</p></section>");
    const available = room.available_targets || [];
    if (room.phase === "discussion")
      return ("<p class=\"phase-hint\">" + NoraI18n.html("Время слушать и убеждать. Голосование откроется после обсуждения.") + "</p>");
    if (room.phase === "night" && !available.length)
      return `<p class="phase-hint">${room.self.role === "civilian" ? NoraI18n.t("Город спит. Твой ход — на дневном обсуждении.") : NoraI18n.t("Сейчас нет доступных целей. Ждём рассвета.")}</p>`;
    if (!["night", "vote"].includes(room.phase)) return "";
    const target =
      room.phase === "vote" ? room.self.vote_target : room.self.night_target;
    const selected =
      room.phase === "vote" ? room.self.voted : room.self.night_target !== null;
    const verb =
      room.phase === "vote"
        ? NoraI18n.t("Кого подозреваешь?")
        : {
            mafia: NoraI18n.t("Цель этой ночи"),
            doctor: NoraI18n.t("Кого защитить?"),
            detective: NoraI18n.t("Кого проверить?"),
          }[room.self.role] || NoraI18n.t("Ночной ход");
    return `<section class="card mafia-targets"><span class="eyebrow">${selected ? NoraI18n.t("Твой выбор принят") : NoraI18n.t("Твой ход")}</span><h3>${verb}</h3><div class="target-grid">${room.players
      .filter((p) => available.includes(p.id))
      .map(
        (p) =>
          `<button class="target-button ${selected && target === p.id ? "chosen" : ""}" data-mafia-target="${p.id}" data-target-action="${room.phase === "vote" ? "vote" : "night"}" ${pending ? "disabled" : ""}><span class="person-avatar" data-person-avatar="${p.id}" ${p.has_avatar===false?"data-avatar-unavailable":""}>${initials(p.name)}</span><span>${esc(p.name)}${p.id === room.self.id ? NoraI18n.t(" · ты") : ""}</span>${selected && target === p.id ? "<b>✓</b>" : ""}</button>`,
      )
      .join(
        "",
      )}${room.phase === "vote" ? `<button class="target-button target-skip ${room.self.voted && target === null ? "chosen" : ""}" data-mafia-target="skip" data-target-action="vote" ${pending ? "disabled" : ""}>${NoraI18n.html("Никого не исключать")} ${room.self.voted && target === null ? "✓" : ""}</button>` : ""}</div><p class="sub">${room.phase === "vote" ? NoraI18n.t("Выбор можно изменить до конца голосования.") : NoraI18n.t("Выбор можно изменить до рассвета.")}</p></section>`;
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
    return `<section class="card mafia-chat"><div class="row"><h3>${chatChannel === "mafia" ? NoraI18n.t("Тайный чат мафии") : chatChannel === "ghost" ? NoraI18n.t("Чат выбывших") : NoraI18n.t("Голос города")}</h3><span class="chat-privacy">${chatChannel === "public" ? NoraI18n.t("Участники комнаты") : NoraI18n.t("Только своя команда")}</span></div>${!options.length && room.status === "active" ? ("<p class=\"sub\">" + NoraI18n.html("Ночью общий чат молчит. Вернёмся к обсуждению на рассвете.") + "</p>") : ""}<div class="mafia-chat-log" id="mafia-chat-log" role="log" aria-live="polite">${shown.length ? shown.map((m) => `<article class="chat-message ${m.user_id === room.self.id ? "mine" : ""}"><span><b>${NoraPrefix(m.prefix)}${esc(m.name)}</b><time>${esc(new Date(m.at).toLocaleTimeString(NoraI18n.locale, { hour: "2-digit", minute: "2-digit" }))}</time></span><p>${esc(m.text)}</p></article>`).join("") : ("<p class=\"chat-empty\">" + NoraI18n.html("Здесь пока тихо.") + "</p>")}</div>${options.length && room.status !== "finished" && room.status !== "cancelled" ? `<form id="mafia-chat-form"><label class="sr-only" for="mafia-chat-input">${NoraI18n.html("Сообщение в")} ${chatChannel === "mafia" ? NoraI18n.t("тайный чат") : chatChannel === "ghost" ? NoraI18n.t("чат выбывших") : NoraI18n.t("общий чат")}</label><div class="inline-form"><input id="mafia-chat-input" name="message" maxlength="500" autocomplete="off" placeholder="${NoraI18n.html("Слово тебе…")}" required value="${esc(drafts.chat)}"><button class="primary" type="submit" aria-label="${NoraI18n.html("Отправить сообщение")}" ${pending ? "disabled" : ""}>↑</button></div></form>` : ""}</section>`;
  }
  function mafiaRoom() {
    const r = state.mafia.room;
    const isDone = ["finished", "cancelled"].includes(r.status);
    const alive = r.players.filter((p) => p.alive && !p.left).length;
    return `${back("games", NoraI18n.t("Игры"))}<div class="mafia-room-heading"><div><p class="eyebrow">${NoraI18n.html("Мафия · бесплатно")}</p><h1>${esc(r.title)}</h1></div><button class="icon-button" id="mafia-rules" aria-label="${NoraI18n.html("Правила мафии")}">?</button></div>${errorBox("mafia")}<section class="phase-banner phase-${esc(r.phase)}"><span class="phase-symbol">${icon(r.phase === "night" ? "moon" : isDone ? "shield" : "sun")}</span><div><span class="eyebrow">${r.phase === "lobby" ? `${r.players.filter((p) => !p.left).length} / ${state.mafia.rules.max_players || 12} ${NoraI18n.t("за столом")}` : isDone ? NoraI18n.t("До следующей встречи") : `${NoraI18n.t("Круг")} ${number(r.round)} ${NoraI18n.t("· живы")} ${alive} / ${r.players.length}`}</span><h2>${isDone ? winnerLabel(r.winner, r.status) : phaseNames[r.phase] || esc(r.phase)}</h2></div>${!isDone && r.deadline ? ("<span class=\"phase-timer\" id=\"mafia-timer\" aria-label=\"" + NoraI18n.html("Оставшееся время") + "\">—</span>") : ""}</section>${roomControls(r)}${roleCard(r)}${players(r)}${actionPanel(r)}${r.self.investigations?.length ? `<details class="play-details private-results" data-detail="investigations"><summary>${NoraI18n.html("Твои проверки ·")} ${r.self.investigations.length}</summary>${r.self.investigations.map((p) => `<p><b>${NoraPrefix(p.prefix)}${esc(p.name)}</b> — ${p.mafia ? NoraI18n.t("мафия") : NoraI18n.t("не мафия")}<small>${NoraI18n.html("Ночь")} ${number(p.round)}</small></p>`).join("")}</details>` : ""}${chat(r)}${r.timeline?.length ? `<details class="play-details" data-detail="timeline"><summary>${NoraI18n.html("Что случилось в городе")}</summary><ol class="mafia-timeline">${r.timeline.map((item) => `<li>${esc(item.text)}</li>`).join("")}</ol></details>` : ""}${isDone ? `<button class="primary" id="mafia-new">${NoraI18n.html("Собрать новую партию")}</button><button class="secondary" id="mafia-current">${NoraI18n.html("К текущей комнате")}</button>` : ""}`;
  }
  function mafiaScreen() {
    return state.mafia?.room ? mafiaRoom() : mafiaHome();
  }
  function rocketBoard(round) {
    const flying = round && ["countdown", "flying"].includes(round.status);
    const final = round && !flying;
    return `<section class="rocket-board ${final && round.status !== "cashed_out" ? "rocket-crashed" : ""}" aria-label="${NoraI18n.html("Полёт ракеты")}"><div class="flight-grid"></div><div class="flight-heading"><span class="eyebrow" id="rocket-flight-label">${!round ? NoraI18n.t("Готовность к запуску") : round.status === "countdown" ? NoraI18n.t("Обратный отсчёт") : round.status === "flying" ? NoraI18n.t("В полёте") : round.status !== "cashed_out" ? NoraI18n.t("Полёт окончен") : NoraI18n.t("Печеньки забраны")}</span><strong id="rocket-multiplier">${final ? "×" + Number(round.cashout_multiplier || round.current_multiplier || 1).toFixed(2) : "×1.00"}</strong><span class="flight-caption" id="rocket-flight-caption">${!round ? NoraI18n.t("Твой момент где-то впереди.") : flying ? NoraI18n.t("Успей забрать до срыва.") : round.status !== "cashed_out" ? NoraI18n.t("Ставка не вернулась.") : NoraI18n.t("Выплата уже в общем кошельке.")}</span></div><svg class="rocket-graph" viewBox="0 0 340 200" aria-hidden="true"><defs><linearGradient id="flight-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--red)" stop-opacity=".28"/><stop offset="100%" stop-color="var(--red)" stop-opacity="0"/></linearGradient></defs><path id="rocket-area" fill="url(#flight-fill)" d="M22 176H318V176Z"/><path id="rocket-path" d="M22 176Q70 176 90 165" fill="none" stroke="var(--red)" stroke-width="3" stroke-linecap="round"/><g id="rocket-ship" transform="translate(90 165)"><circle r="17" fill="var(--red)" fill-opacity=".094"/><path d="M-9 7-5-6 9-13 9 1-4 9z" fill="#f7f5f1"/><circle cx="3" cy="-5" r="3" fill="var(--red)"/><path d="m-8 9-5 5 7-2" stroke="var(--red)" stroke-width="3" stroke-linecap="round"/></g><text x="22" y="196">${NoraI18n.html("СТАРТ")}</text><text x="290" y="196">×10</text></svg><span class="rocket-server-note">${NoraI18n.html("Расчёт на сервере")}</span></section>`;
  }
  function rocketScreen() {
    const s = state.rocket,
      r = s?.round || lastRocketResult,
      live = r && ["countdown", "flying"].includes(r.status);
    return `${back("games", NoraI18n.t("Игры"))}<div class="play-title-row"><div><p class="eyebrow">${NoraI18n.html("Соло · 18+")}</p><h1><em>${NoraI18n.html("Ракетка")}</em></h1></div><span class="rocket-balance"><small>${NoraI18n.html("В кошельке")}</small><b>${number(s?.balance ?? data.user.cookies)} 🍪</b></span></div>${errorBox("rocket")}${rocketBoard(r)}${live ? `<section class="card flight-controls"><div class="flight-stake"><span>${NoraI18n.html("В полёте")} <b>${number(r.bet)} 🍪</b></span><span>${NoraI18n.html("Автовыход")} <b>${r.auto_cashout ? "×" + Number(r.auto_cashout).toFixed(2) : NoraI18n.t("выключен")}</b></span></div><button class="primary rocket-cashout" id="rocket-cashout" ${pending || r.status === "countdown" ? "disabled" : ""}>${r.status === "countdown" ? NoraI18n.t("Готовимся к запуску…") : NoraI18n.t("Забрать")}</button><p class="footer-note">${NoraI18n.html("Выплата включает ставку. Сумма определяется в момент получения запроса сервером.")}</p></section>` : `${r ? `<section class="rocket-result ${r.status !== "cashed_out" ? "lost" : "won"}" role="status"><div><small>${r.status === "surrendered" ? NoraI18n.t("Полёт завершён досрочно") : r.status === "crashed" ? NoraI18n.t("Срыв на ×") + Number(r.proof?.crash_multiplier || r.current_multiplier || 1).toFixed(2) : NoraI18n.t("Выход на ×") + Number(r.cashout_multiplier || 1).toFixed(2)}</small><b>${r.status !== "cashed_out" ? "−" + number(r.bet) : "+" + number((r.payout || 0) - r.bet)} 🍪</b></div><p>${NoraI18n.html("Ставка")} ${number(r.bet)} ${NoraI18n.html("🍪 · выплата")} ${number(r.payout || 0)} 🍪</p></section>` : ""}<form id="rocket-bet-form" class="card rocket-form"><div class="row"><h3>${NoraI18n.html("Твой запуск")}</h3><span class="sub">1–100 🍪</span></div><label for="rocket-bet">${NoraI18n.html("Ставка в печеньках")}</label><input id="rocket-bet" name="bet" type="number" inputmode="numeric" min="1" max="100" step="1" value="${esc(drafts.bet)}" required><div class="stake-chips">${[5, 10, 25, 50, 100].map((n) => `<button type="button" data-rocket-stake="${n}" class="${Number(drafts.bet) === n ? "selected" : ""}">${n}</button>`).join("")}</div><label class="auto-toggle" for="rocket-auto-on"><span>${NoraI18n.html("Забрать автоматически")}<small>${NoraI18n.html("Сработает во время полёта")}</small></span><input id="rocket-auto-on" type="checkbox" ${drafts.autoOn ? "checked" : ""}></label><label for="rocket-auto" ${drafts.autoOn ? "" : "hidden"} id="rocket-auto-label">${NoraI18n.html("На множителе")}<input id="rocket-auto" name="auto" type="number" inputmode="decimal" min="1.1" max="10" step="0.01" value="${esc(drafts.auto)}" ${drafts.autoOn ? "required" : "disabled"}></label>${s && !s.eligible ? `<p class="game-restricted">${esc(s.reason || NoraI18n.t("Ставки сейчас недоступны"))}</p>` : ""}<button class="primary" type="submit" ${pending || !s?.eligible ? "disabled" : ""}>${NoraI18n.html("Проверить запуск")}</button><p class="footer-note">${NoraI18n.html("Списание — после подтверждения.")}<br>${NoraI18n.html("Срыв раньше твоего выхода означает потерю ставки.")}</p></form>`}<details class="play-details" data-detail="rocket-rules"><summary>${NoraI18n.html("Как летит ракета")}</summary><div class="rule-row"><b>${NoraI18n.html("Одна ставка — один полёт")}</b><p>${NoraI18n.html("Ставка от 1 до 100 печенек. После трёхсекундного отсчёта множитель растёт. Нажми «Забрать» до срыва: выплата = ставка × множитель, с округлением вниз.")}</p></div><div class="rule-row"><b>${NoraI18n.html("Автовыход — до запуска")}</b><p>${NoraI18n.html("Можно заранее выбрать множитель от ×1.10 до ×10.00. Он сохраняется на сервере и сработает без открытой миниапки. При достижении ×10 выплата автоматическая, если ракета не сорвалась раньше.")}</p></div><div class="rule-row"><b>${NoraI18n.html("Понятные условия")}</b><p>${NoraI18n.html("Точка срыва случайна и фиксируется до полёта. Теоретический возврат — не выше 97%, округление выплат его уменьшает. Каждый полёт независим. Предыдущие результаты ничего не предсказывают.")}</p></div><div class="rule-row"><b>${NoraI18n.html("Связь и результат")}</b><p>${NoraI18n.html("Анимация показывает приблизительный текущий множитель. Ручной выход принимается по времени сервера. При потере связи полёт продолжается; без автовыхода ставка может быть потеряна. Доступно с 18 лет, при заполненном профиле, без открытого стартер-пака и просроченного долга.")}</p></div></details>${rocketHistory()}${r ? `<details class="play-details" data-detail="rocket-proof"><summary>${NoraI18n.html("Проверка этого полёта")}</summary><p class="sub">${NoraI18n.html("SHA-256 фиксируется до запуска. После завершения открывается исходное значение для проверки результата.")}</p><label class="proof-label">${NoraI18n.html("Отпечаток")}<code>${esc(r.commitment || "—")}</code></label>${r.proof ? `<label class="proof-label">${NoraI18n.html("Исходное значение")}<code>${esc(r.proof.seed)}</code></label><p class="sub">${NoraI18n.html("Точка срыва: ×")}${Number(r.proof.crash_multiplier).toFixed(2)}<br>${esc(r.proof.algorithm || "")}</p>` : ("<p class=\"sub\">" + NoraI18n.html("Исходное значение скрыто до завершения полёта.") + "</p>")}</details>` : ""}`;
  }
  function rocketHistory() {
    const h = state.rocket?.history || [];
    const rows = h.map((r) => {
      const won = r.status === "cashed_out";
      const multiplier = r.cashout_multiplier ?? r.current_multiplier;
      const label = {crashed: NoraI18n.t("Срыв"), surrendered: NoraI18n.t("Сдался"), cashed_out: NoraI18n.t("Забрано")}[r.status];
      return `<div class="flight-history"><span><b>×${Number(multiplier || 1).toFixed(2)}</b><small>${label} ${NoraI18n.html("· ставка")} ${number(r.bet)}</small></span><strong class="${won ? "" : "red-number"}">${won ? "+" + number(r.payout - r.bet) : "−" + number(r.bet)} 🍪</strong></div>`;
    }).join("");
    return `<details class="play-details" data-detail="rocket-history"><summary>${NoraI18n.html("Твои последние полёты ·")} ${h.length}</summary>${rows || ("<p class=\"sub\">" + NoraI18n.html("Первый полёт ещё впереди.") + "</p>")}</details>`;
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
        if (tab === view || (view === "friends" && tab === "community") || (view === "mafia" && tab === "interactive")) patch();
      } catch (e) {
        if (epoch !== (epochs[view] || 0)) return;
        errors[view] = NoraI18n.t("Связь прервалась. ") + e.message;
        if (tab === view || (view === "friends" && tab === "community") || (view === "mafia" && tab === "interactive")) patch();
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
            : String(seconds) + NoraI18n.t("с");
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
            ? NoraI18n.t("До старта ") + countdown + "…"
            : NoraI18n.t("В полёте");
        if ($("#rocket-multiplier"))
          $("#rocket-multiplier").textContent = countdown
            ? String(countdown)
            : "×" + multiplier.toFixed(2);
        const button = $("#rocket-cashout");
        if (button) {
          button.disabled =
            pending || countdown > 0 || r.status === "countdown";
          button.textContent = countdown
            ? NoraI18n.t("До старта ") + countdown + "…"
            : NoraI18n.t("Забрать ≈ ") + number(Math.floor(r.bet * multiplier)) + " 🍪";
        }
      } else {
        const crash = Number(r.proof?.crash_multiplier || 0);
        if (r.status === "cashed_out" && crash > 0 && r.starts_at) {
          // Призрачный полёт: показываем, куда ракета долетела бы без забора.
          const elapsed = now("rocket") / 1000 - r.starts_at;
          const ghost = Math.exp(Math.max(0, elapsed) * s.rules.growth_rate);
          const done = ghost >= crash;
          multiplier = Math.min(crash, ghost);
          progress = Math.min(
            0.96,
            0.12 + (Math.log(multiplier) / Math.log(10)) * 0.84,
          );
          const cashedAt = Number(r.cashout_multiplier || 1);
          if ($("#rocket-flight-label"))
            $("#rocket-flight-label").textContent = done
              ? NoraI18n.t("Дальше ракета не улетела")
              : NoraI18n.t("Ракета летит дальше");
          if ($("#rocket-multiplier"))
            $("#rocket-multiplier").textContent = "×" + multiplier.toFixed(2);
          if ($("#rocket-flight-caption"))
            $("#rocket-flight-caption").textContent = done
              ? crash >= 10
                ? NoraI18n.t("Без забора ракета улетела бы в лимит ×10")
                : NoraI18n.t("Без забора срыв случился бы на ×") + crash.toFixed(2)
              : NoraI18n.t("Забрано на ×") +
                cashedAt.toFixed(2) +
                NoraI18n.t(" — смотрим, куда бы она долетела");
          if ($("#rocket-ship"))
            $("#rocket-ship").style.opacity = done ? ".2" : "";
          $(".rocket-board")?.classList.toggle("rocket-crashed", done);
        } else {
          multiplier = Number(
            r.cashout_multiplier || r.current_multiplier || 1,
          );
          progress = Math.min(
            0.96,
            0.12 + (Math.log(Math.max(1, multiplier)) / Math.log(10)) * 0.84,
          );
        }
      }
    }
    const x = 22 + progress * 286,
      y = 176 - progress * progress * 146;
    const path = `M22 176 Q${22 + (x - 22) * 0.57} 176 ${x} ${y}`;
    $("#rocket-path")?.setAttribute("d", path);
    $("#rocket-area")?.setAttribute("d", path + ` L${x} 176 Z`);
    $("#rocket-ship")?.setAttribute("transform", `translate(${x} ${y})`);
    if (["crashed", "surrendered"].includes(r?.status) && $("#rocket-ship"))
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
      if (tab === "interactive") load("mafia", true, null);
      if (tab === "games") reloadLobbies();
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
        await refreshCurrent();
      schedule();
    }, interval);
  }
  function refreshCurrent() {
    if (tab === "games") {
      reloadLobbies();
      return true;
    }
    if (liveViews.has(tab) || ["interactive", "community"].includes(tab)) {
      load(tab === "community" ? "friends" : tab === "interactive" ? "mafia" : tab, true);
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
      if (tab === view || (view === "friends" && tab === "community") || (view === "mafia" && tab === "interactive")) patch();
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
      if (tab === view || (view === "friends" && tab === "community") || (view === "mafia" && tab === "interactive")) patch();
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
        `<h2>${action === "block" ? NoraI18n.t("Заблокировать") : NoraI18n.t("Удалить из друзей")}?</h2><p class="sub">${esc(person.name)}${action === "block" ? NoraI18n.t(" не сможет присылать заявки и приглашения. Разблокировать можно в этом разделе.") : NoraI18n.t(" исчезнет из списка. Чтобы снова дружить, понадобится новая заявка.")}</p><button class="primary" id="friend-confirm">${action === "block" ? NoraI18n.t("Заблокировать") : NoraI18n.t("Удалить")}</button>`,
      );
      $("#friend-confirm").onclick = send;
    } else send();
  }
  function createRoom() {
    sheet(`<h2 id="mafia-create-heading" tabindex="-1">${NoraI18n.html("Новая игра в Мафию")}</h2><form id="mafia-create-form">
      <label for="mafia-room-title">${NoraI18n.html("Название")}</label>
      <input id="mafia-room-title" name="title" maxlength="60" placeholder="${NoraI18n.html("Вечер в Норе")}" value="${esc(drafts.room)}">
      <label class="game-visibility"><input type="checkbox" name="public" checked>${NoraI18n.html("Открытое лобби")}</label>
      <p class="sub">${NoraI18n.html("5–12 игроков · без ставок")}</p>
      <button class="primary" type="submit">${NoraI18n.html("Создать лобби")}</button>
    </form>`);
    $("#mafia-create-heading").focus();
  }
  async function inviteFriends(preselect = null) {
    await load("friends", true);
    const r = state.mafia?.room;
    if (!r || r.status !== "lobby") {
      toast(NoraI18n.t("Сначала создай комнату «Мафии»"));
      go("mafia");
      return;
    }
    const list = (state.friends?.friends || []).filter(
      (p) => p.available !== false && !r.players.some((x) => x.id === p.id),
    );
    sheet(
      `<span class="eyebrow">${NoraI18n.html("Собираем своих")}</span><h2>${NoraI18n.html("Позвать в «Мафию»")}</h2><p class="sub">${esc(r.title)} · ${r.players.length} ${NoraI18n.html("/ 12 игроков")}</p>${list.length ? list.map((p) => `<button class="invite-person ${p.id === preselect ? "preselected" : ""}" data-invite-person="${p.id}"><span class="person-avatar" data-person-avatar="${p.id}" ${p.has_avatar===false?"data-avatar-unavailable":""}>${initials(p.name)}</span><span><b>${NoraPrefix(p.prefix)}${esc(p.name)}</b><small>${NoraI18n.html("Пригласить в комнату")}</small></span>${icon("arrow")}</button>`).join("") : ("<p class=\"sub\">" + NoraI18n.html("Все доступные друзья уже за столом или список пока пуст.") + "</p>")}<button class="secondary" id="friends-from-invite">${NoraI18n.html("Добавить друзей")}</button>`,
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
        `<span class="eyebrow">${NoraI18n.html("До запуска — одно решение")}</span><h2>${NoraI18n.html("Отправляем")}<br>${NoraI18n.html("ракету?")}</h2><div class="amount">${number(q.bet)} 🍪</div><p class="sub">${NoraI18n.html("Эта сумма спишется из кошелька при запуске. Срыв до выхода — потеря всей ставки.")}</p><div class="quote-facts"><span>${NoraI18n.html("Автовыход")}<b>${q.auto_cashout ? "×" + Number(q.auto_cashout).toFixed(2) : NoraI18n.t("Выключен")}</b></span><span>${NoraI18n.html("Отсчёт")}<b>${NoraI18n.html("3 секунды")}</b></span></div><button class="primary" id="rocket-confirm">${NoraI18n.html("Списать")} ${number(q.bet)} ${NoraI18n.html("🍪 и запустить")}</button>`,
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
        { title: drafts.room.trim() || NoraI18n.t("Вечер в Норе"), public: e.target.elements.public.checked },
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
    if (b.id === "games-create") chooseMatch();
    if (b.id === "games-refresh") reloadLobbies();
    if (b.id === "games-show-all") {
      showAllLobbies = !showAllLobbies;
      patchLobbies();
    }
    if (b.dataset.createMatch) {
      const game = b.dataset.createMatch;
      if (game === "mafia") createRoom();
      else {
        $("#sheet").close();
        if (game === "durak") openDurak({ create: true });
        else if (game === "barricade") openBarricade({ create: true });
        else if (game === "poker") goToTab(game);
        else go(game);
      }
    }
    if (b.dataset.barricadeLobby) openBarricade({id: b.dataset.barricadeLobby});
    if (b.dataset.durakLobby) {
      const room = lobbyRooms?.find(r => r.game === "durak" && r.id === b.dataset.durakLobby);
      if (room) openDurak({ room });
    }
    if (b.dataset.mafiaJoin) {
      const result = await mafiaAction("join", { room_id: b.dataset.mafiaJoin });
      if (tab === "games") {
        if (result) go("mafia");
        else reloadLobbies();
      }
    }
    if (b.dataset.gameRetry) load(b.dataset.gameRetry, true);
    if (b.dataset.friendAction)
      friendAction(b.dataset.friendAction, Number(b.dataset.personId));
    if (b.dataset.friendPlay) {
      await load("mafia", true);
      go("mafia");
      if (state.mafia?.room?.status === "lobby")
        inviteFriends(Number(b.dataset.friendPlay));
      else if (!state.mafia?.room) createRoom();
      else toast(NoraI18n.t("Заверши текущую партию, чтобы пригласить друзей"));
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
        b.innerHTML = ("<span>" + NoraI18n.html("Приглашение отправлено ✓") + "</span>");
      }
    }
    if (b.dataset.mafiaRespond) {
      const result = await mafiaAction("respond", {
        room_id: b.dataset.roomId, accept: b.dataset.mafiaRespond === "yes",
      });
      if (tab === 'notices') await window.NoraCabinet?.reloadNotices();
      if (result && b.dataset.mafiaRespond === 'yes') go('mafia');
      else if (tab === "games") reloadLobbies();
    }
    if (b.dataset.mafiaHistory) load("mafia", true, b.dataset.mafiaHistory);
    if (b.dataset.mafiaTarget) {
      const target =
        b.dataset.mafiaTarget === "skip" ? null : Number(b.dataset.mafiaTarget);
      mafiaAction(b.dataset.targetAction, { target_id: target });
    }
    if (b.dataset.mafiaAction) {
      const action = b.dataset.mafiaAction;
      if (action === "leave") go("games");
      else
        mafiaAction(
          action,
          action === "ready" ? { ready: !state.mafia.room.self.ready } : {},
        );
    }
    if (b.id === "mafia-rules")
      sheet(
        ("<h2>" + NoraI18n.html("Город живёт по правилам") + "</h2>") +
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
    reloadLobbies,
    icon,
    handles: (view) => views.has(view),
    live: (view) => liveViews.has(view),
    friendsCount: () => state.friends?.counts?.incoming || 0,
  };
})();
