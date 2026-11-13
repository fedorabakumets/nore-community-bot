"use strict";
window.NoraSea = (() => {
  const VIEWS = new Set(["sea"]);
  const state = { sea: null };
  const errors = {};
  let pollTimer = null,
    pending = false;
  const draft = { stake: "0", title: "", password: "" };
  let lastRoomId = "";
  let lastHtml = "";
  let serverClock = 0, receivedAt = 0;

  const ROWS = "АБВГДЕЖЗИК";

  function cellCoord(i) {
    return ROWS[Math.floor(i / 10)] + ((i % 10) + 1);
  }

  // Classes: c0 empty, c1 own ship, c2 hit, c3 miss, c4 sunk
  function ownBoardHtml(entry) {
    const cells = entry.board
      .map((c) => `<span class="sea-cell ${c.sunk ? "c4" : c.hit ? "c2" : c.miss ? "c3" : c.ship ? "c1" : "c0"}${c.last ? " last" : ""}"></span>`)
      .join("");
    return `<div class="sea-board">${cells}</div>`;
  }

  function enemyBoardHtml(entry, interactive, reveal) {
    const cells = entry.shots
      .map((s, i) => {
        const cls = reveal
          ? (s.sunk ? "c4" : s.hit ? "c2" : s.fired ? "c3" : reveal[i] ? "c1" : "c0")
          : !s.fired ? "c0" : s.sunk ? "c4" : s.hit ? "c2" : "c3";
        const marked = cls + (s.last ? " last" : "");
        return interactive && !s.fired
          ? `<button class="sea-cell ${marked}" data-sea-shoot="${i}" aria-label="Клетка ${cellCoord(i)}" ${pending ? "disabled" : ""}></button>`
          : `<span class="sea-cell ${marked}"></span>`;
      })
      .join("");
    return `<div class="sea-board">${cells}</div>`;
  }

  function backBtn() {
    return `<button class="text-btn play-back" data-tab="games">← Игры</button>`;
  }

  function errorBox() {
    return errors.sea
      ? `<div class="play-connection" role="status">${esc(errors.sea)}<button class="text-btn" data-sea-retry="1">Обновить</button></div>`
      : "";
  }

  function inviteCard(i) {
    const label = i.stake ? "ставка " + number(i.stake) + " 🍪" : "бесплатно";
    return (
      `<section class="card mafia-invite"><span class="eyebrow">Друг приглашает в Морской бой</span><h3>${esc(i.title)}</h3>` +
      `<p class="sub">${NoraPrefix(i.sender_prefix)}${esc(i.sender_name)} зовёт · ${label}</p>` +
      `<div class="pet-action-row"><button class="primary" data-sea-respond="yes" data-room-id="${esc(i.room_id)}" ${pending ? "disabled" : ""}>Принять</button>` +
      `<button class="secondary" data-sea-respond="no" data-room-id="${esc(i.room_id)}" ${pending ? "disabled" : ""}>Отклонить</button></div></section>`
    );
  }

  function invites() {
    return (state.sea?.invites || []).map(inviteCard).join("");
  }

  function rules() {
    const s = state.sea?.rules;
    const body = (s?.sections || [])
      .map((r) => `<div class="rule-row"><b>${esc(r.title)}</b><p>${esc(r.text)}</p></div>`)
      .join("");
    return `<details class="play-details" data-detail="sea-rules"><summary>Как устроен Морской бой</summary><p class="sub">Поле 10×10. Флот: один 4-палубный, два 3-палубных, три 2-палубных и четыре одиночных. Корабли не касаются друг друга и расставляются автоматически.</p>${body}</details>`;
  }

  function stakeChips() {
    const choices = state.sea?.rules?.stake_choices || [0, 5, 10, 25, 50, 100];
    return choices
      .map((n) => `<button type="button" data-sea-stake="${n}" class="${Number(draft.stake) === n ? "selected" : ""}">${n ? number(n) + " 🍪" : "Бесплатно"}</button>`)
      .join("");
  }

  function recentList() {
    const list = state.sea?.recent || [];
    if (!list.length) return "";
    const rows = list
      .map((r) => {
        const outcome = r.status === "cancelled" ? "Закрыта" : r.winner == null ? "Ничья" : "Завершена";
        const when = esc(new Date(r.finished_at).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }));
        return `<div class="flight-history"><span><b>${esc(r.title)}</b><small>${outcome} · ${r.stake ? number(r.stake) + " 🍪" : "бесплатно"}</small></span><time>${when}</time></div>`;
      })
      .join("");
    return `<details class="play-details" data-detail="sea-recent"><summary>Прошлые партии · ${list.length}</summary>${rows}</details>`;
  }

  function home() {
    const s = state.sea;
    const stakeNote = Number(draft.stake)
      ? "Ставка создателя спишется при создании, соперника — при старте. Победитель забирает удвоенную ставку, при ничьей — возврат."
      : "Бесплатная партия: печеньки не списываются.";
    return (
      backBtn() +
      invites() +
      `<div class="play-title-row"><div><p class="eyebrow">С ботом бесплатно · с другом бесплатно или на 🍪</p><h1>Морской<br><em>бой</em></h1></div>` +
      `<span class="rocket-balance"><small>В кошельке</small><b>${number(s?.balance ?? data.user.cookies)} 🍪</b></span></div>` +
      `<p class="sub">Попал — стреляй ещё. Промах — ход переходит. Потопи весь флот.</p>` +
      errorBox() +
      (s && !s.enabled ? '<p class="game-restricted">Новые игры временно выключены администрацией.</p>' : "") +
      `<section class="card mafia-create"><span class="eyebrow">Соперник и режим</span><h2>Начнём бой.</h2>` +
      `<label for="sea-title">Название комнаты</label><input id="sea-title" maxlength="60" placeholder="Морской бой" value="${esc(draft.title)}"><label for="sea-password">Пароль комнаты (необязательно)</label><input id="sea-password" type="password" maxlength="64" autocomplete="new-password" placeholder="От 4 символов" value="${esc(draft.password)}"><p class="sub">Пароль нужен для входа из списка. Личное приглашение другу действует без пароля.</p>` +
      `<label>Ставка для игры с другом</label><div class="stake-chips" role="group" aria-label="Ставка для игры с другом">${stakeChips()}</div>` +
      `<div class="pet-action-row"><button class="primary" id="sea-create-bot" ${pending || !s || !s.enabled ? "disabled" : ""}>С ботом бесплатно</button>` +
      `<button class="secondary" id="sea-create-friend" ${pending || !s || !s.enabled ? "disabled" : ""}>Комната для друга</button></div>` +
      `<p class="sub">${stakeNote}</p></section>` +
      rules() +
      recentList()
    );
  }

  function playerRow(p) {
    const ships = state.sea?.room?.ships_left?.[p.id] ?? "…";
    const turn = state.sea?.room?.turn === p.id;
    const inLobby = state.sea?.room?.status === "lobby";
    const kick = inLobby && state.sea.room.host_id === data.user.user_id && p.id !== data.user.user_id && p.id > 0 ? `<button class="text-btn" data-sea-kick="${p.id}">Исключить</button>` : "";
    return `<div class="mafia-player ${turn ? "you" : ""}"><span class="person-avatar">${esc((p.name || "?").match(/[\p{L}\p{N}]/u)?.[0]?.toUpperCase() || "?")}</span><b>${NoraPrefix(p.prefix)}${esc(p.name)}</b><small>${inLobby ? (p.ready ? "Готов" : "Собирается") : turn ? "Стреляет" : "Ждёт"} · кораблей: ${ships}${p.left ? " · вышел" : ""}</small>${kick}</div>`;
  }

  function lobbyView(r) {
    const title = r.bot ? "Бот ждёт начала" : r.players.length === 2 ? "Соперник найден" : "Ждём соперника";
    const text = r.bot ? "Флот расставится случайно при старте." : (r.locked ? "Лобби видно в коммьюнити. Для входа нужен пароль; личное приглашение действует без него." : "Лобби видно в коммьюнити. Можно также пригласить друга.");
    const stakeNote = r.stake ? `Ставка ${number(r.stake)} 🍪: создатель уже внёс ставку, соперник внесёт её при старте.` : "Партия бесплатная.";
    const inviteBtn = !r.bot ? `<button class="secondary" id="sea-invite">Пригласить друзей</button>` : "";
    const me = r.players.find((p) => p.id === data.user.user_id);
    const readyBtn = r.bot ? "" : `<button class="${me?.ready ? "secondary" : "primary"}" data-sea-ready="1" ${pending ? "disabled" : ""}>${me?.ready ? "Я пока не готов" : "Я готов"}</button>`;
    const canStart = r.host_id === data.user.user_id && (r.bot || (r.players.length === 2 && r.players.every((p) => p.ready)));
    return (
      `<section class="card mafia-create"><span class="eyebrow">Комната готова</span><h2>${title}</h2>` +
      `<p class="sub">${text}</p>` +
      `<div class="mafia-players">${r.players.map(playerRow).join("")}</div>` +
      `<div class="pet-action-row"><button class="primary" id="sea-start" ${pending || !canStart ? "disabled" : ""}>Начать бой</button>${readyBtn}${inviteBtn}</div>` +
      `<p class="sub">${stakeNote}</p></section>`
    );
  }

  function deadlineBadge(r) {
    return !r.deadline ? "" : `<span class="phase-timer" id="sea-timer">—</span>`;
  }

  function turnHead(r, myTurn, done, iWon, winnerName) {
    const title = r.winner == null ? "Ничья" : iWon ? "Ты победил!" : "Победил " + esc(winnerName);
    const stakeOutcome = done && r.stake ? (r.winner == null ? " · ставки возвращены" : iWon ? " · +" + number(r.stake) + " 🍪" : " · −" + number(r.stake) + " 🍪") : "";
    return `<section class="card sea-arena">${done ? `<div class="sea-turn"><h3>${title}${stakeOutcome}</h3></div>` : ""}`;
  }

  function boardsView(r, me, foe, myTurn) {
    const active = r.status === "active";
    const reveal = r.status === "finished" ? foe?.ships : null;
    const panel = (label, player, turn, board) => `<div class="sea-panel ${active ? (turn ? (myTurn ? "active" : "waiting") : "") : ""}"><div class="sea-panel-head"><strong>${label}</strong><span>Корабли ${r.ships_left?.[player?.id] ?? "…"}/10</span></div>${active ? `<div class="sea-panel-status"><span>${turn ? (myTurn ? "Ваш ход" : "Ход соперника") : "Ожидание"}</span>${turn ? deadlineBadge(r) : ""}</div>` : ""}${board}</div>`;
    return `<div class="sea-boards">${panel(foe?.id === -1 ? "Соперник · бот" : "Поле соперника", foe, active && !myTurn, enemyBoardHtml(me, myTurn, reveal))}${panel("Ваш флот", me, active && myTurn, ownBoardHtml(me))}</div></section>`;
  }

  function controlsView(r) {
    if (["finished", "cancelled"].includes(r.status)) {
      return `<div class="pet-action-row"><button class="primary" id="sea-again">Новая партия</button><button class="secondary" id="sea-home">К списку</button></div>`;
    }
    const cancel = r.host_id === data.user.user_id && r.status === "lobby" ? '<button class="secondary danger-action" data-sea-action="cancel">Закрыть комнату</button>' : "";
    return `<section class="card mafia-room-controls"><button class="secondary" data-sea-action="leave">${r.status === "lobby" ? "Выйти" : "Сдаться и выйти"}</button>${cancel}</section>`;
  }

  function logView(r) {
    if (!r.timeline?.length) return "";
    const open = r.status !== "active" ? "open" : "";
    const rows = r.timeline.map((t) => `<li>${esc(t.text)}</li>`).join("");
    return `<details class="play-details" data-detail="sea-log" ${open}><summary>Журнал боя</summary><ol class="mafia-timeline">${rows}</ol></details>`;
  }

  function room() {
    const r = state.sea.room;
    const done = ["finished", "cancelled"].includes(r.status);
    const me = r.players.find((p) => p.id === data.user.user_id);
    const foe = r.players.find((p) => p.id !== data.user.user_id);
    const myTurn = r.turn === data.user.user_id && !done;
    const winnerName = r.winner == null ? null : r.winner === -1 ? "Бот" : r.players.find((p) => p.id === r.winner)?.name || "соперник";
    const iWon = r.winner != null && r.winner === data.user.user_id;
    const heading =
      `<div class="mafia-room-heading"><div><p class="eyebrow">Морской бой${r.stake ? " · ставка " + number(r.stake) + " 🍪" : " · бесплатно"}</p><h1>${esc(r.title)}</h1></div></div>`;
    const body = r.status === "lobby" ? lobbyView(r) : turnHead(r, myTurn, done, iWon, winnerName) + boardsView(r, me, foe, myTurn);
    return backBtn() + heading + errorBox() + body + controlsView(r) + logView(r);
  }

  function screen() {
    return `<div id="sea-content">${state.sea?.room ? room() : home()}</div>`;
  }

  async function load(force = false, roomId = undefined) {
    if (!auth || !data) return;
    try {
      const selected = roomId === undefined ? lastRoomId : roomId;
      const response = await api("sea" + (selected ? "?room_id=" + encodeURIComponent(selected) : ""));
      state.sea = response;
      serverClock = response.server_now || Date.now();
      receivedAt = Date.now();
      delete errors.sea;
      if (response.room?.id) lastRoomId = response.room.id;
      else if (roomId !== undefined) lastRoomId = "";
      if (tab === "sea") patch();
    } catch (e) {
      if (lastRoomId && e.message.includes("Комната не найдена")) {
        lastRoomId = "";
        toast("Комната закрыта или вы больше не её участник");
        return load(true, null);
      }
      errors.sea = "Связь прервалась. " + e.message;
      if (tab === "sea") patch();
    }
  }

  function patch() {
    if (tab !== "sea") return;
    const el = $("#sea-content");
    if (!el) return;
    const html = screen();
    if (html === lastHtml) {
      timerTick();
      return;
    }
    const y = window.scrollY;
    const open = [...el.querySelectorAll("details[open]")].map((n) => n.dataset.detail);
    el.outerHTML = html;
    lastHtml = html;
    for (const key of open) {
      const node = $(`[data-detail="${key}"]`);
      if (node) node.open = true;
    }
    window.scrollTo(0, y);
    timerTick();
  }

  function timerTick() {
    const t = $("#sea-timer");
    const r = state.sea?.room;
    if (t && r?.deadline) {
      const seconds = Math.max(0, Math.ceil((r.deadline - (serverClock ? serverClock + Date.now() - receivedAt : Date.now())) / 1000));
      t.textContent = String(seconds) + "с";
      t.classList.toggle("urgent", seconds < 10);
    }
  }

  setInterval(() => { if (tab === "sea" && !document.hidden) timerTick(); }, 1000);

  function schedule() {
    clearTimeout(pollTimer);
    if (document.hidden || tab !== "sea") return;
    const r = state.sea?.room;
    const interval = r && r.status === "active" ? 2000 : r && r.status === "lobby" ? 4000 : 15000;
    pollTimer = setTimeout(async () => {
      if (!pending && !$("#sheet").open) await load(true);
      schedule();
    }, interval);
  }

  async function perform(body, opts = {}) {
    if (pending) return null;
    pending = true;
    try {
      const response = await api("sea/action", body);
      state.sea = { ...(state.sea || {}), ...response };
      if (response.server_now) { serverClock = response.server_now; receivedAt = Date.now(); }
      if (response.room?.id) lastRoomId = response.room.id;
      if (response.message && !opts.quiet) toast(response.message);
      if (opts.close && $("#sheet").open) $("#sheet").close();
      patch();
      return response;
    } catch (e) {
      toast(e.message);
      await load(true);
      return null;
    } finally {
      pending = false;
      patch();
      schedule();
    }
  }

  async function inviteFriends() {
    let friends;
    try {
      friends = await api("friends");
    } catch (e) {
      toast(e.message);
      return;
    }
    const list = (friends.friends || []).filter((p) => p.available !== false);
    const rows = list.length
      ? list
          .map((p) => `<button class="invite-person" data-sea-invite-person="${p.id}"><span class="person-avatar">${esc((p.name || "?").match(/[\p{L}\p{N}]/u)?.[0]?.toUpperCase() || "?")}</span><span><b>${NoraPrefix(p.prefix)}${esc(p.name)}</b><small>Пригласить в комнату</small></span></button>`)
          .join("")
      : '<p class="sub">Нет друзей для приглашения. Сначала добавь друзей в разделе «Коммьюнити».</p>';
    sheet(`<span class="eyebrow">Собираем флот</span><h2>Позвать в Морской бой</h2>${rows}<button class="secondary" id="sea-to-friends">Добавить друзей</button>`);
    $("#sea-to-friends").onclick = () => {
      $("#sheet").close();
      tab = "friends";
      render();
      window.scrollTo(0, 0);
    };
  }

  async function joinLobby(roomId, password) {
    const result = await perform({action: "join", room_id: roomId, password}, {close: true});
    if (result) { tab = "sea"; render(); window.scrollTo(0, 0); }
  }

  function mount() {
    if (tab === "sea") load(true);
    timerTick();
    schedule();
  }

  document.addEventListener("input", (e) => {
    if (e.target.id === "sea-title") draft.title = e.target.value;
    if (e.target.id === "sea-password") draft.password = e.target.value;
  });

  document.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.seaStake !== undefined) {
      draft.stake = b.dataset.seaStake;
      patch();
      return;
    }
    if (b.dataset.seaRetry !== undefined) {
      load(true);
      return;
    }
    if (b.id === "sea-create-bot") {
      perform({ action: "create", vs_bot: true, stake: 0 });
      return;
    }
    if (b.id === "sea-create-friend") {
      perform({ action: "create", vs_bot: false, stake: Number(draft.stake), title: draft.title, password: draft.password }).then((result) => { if (result) draft.password = ""; });
      return;
    }
    if (b.dataset.seaJoin) {
      const roomId = b.dataset.seaJoin;
      if (b.dataset.locked === "1") {
        sheet(`<h2>Пароль комнаты</h2><label for="sea-join-password">Введите пароль</label><input id="sea-join-password" type="password" maxlength="64" autocomplete="off"><button class="primary" id="sea-join-confirm">Подключиться</button>`);
        $("#sea-join-confirm").onclick = () => joinLobby(roomId, $("#sea-join-password").value);
      } else joinLobby(roomId, "");
      return;
    }
    if (b.dataset.seaAdminClose) {
      const roomId = b.dataset.seaAdminClose;
      sheet(`<h2>Закрыть комнату?</h2><p class="sub">Лобби будет закрыто, ставка создателя вернётся.</p><button class="primary" id="sea-admin-close-confirm">Закрыть комнату</button>`);
      $("#sea-admin-close-confirm").onclick = async () => { if (await perform({action: "admin_close", room_id: roomId}, {close: true})) window.NoraCommunity?.reload(); };
      return;
    }
    if (b.dataset.seaKick) {
      const userId = Number(b.dataset.seaKick);
      sheet(`<h2>Исключить участника?</h2><p class="sub">Он не сможет снова войти в эту комнату.</p><button class="primary" id="sea-kick-confirm">Исключить</button>`);
      $("#sea-kick-confirm").onclick = () => perform({action: "kick", room_id: state.sea?.room?.id, user_id: userId}, {close: true});
      return;
    }
    if (b.id === "sea-start") {
      perform({ action: "start", room_id: state.sea?.room?.id });
      return;
    }
    if (b.id === "sea-invite") {
      inviteFriends();
      return;
    }
    if (b.dataset.seaReady !== undefined) {
      const me = state.sea?.room?.players.find((p) => p.id === data.user.user_id);
      perform({ action: "ready", room_id: state.sea?.room?.id, ready: !me?.ready });
      return;
    }
    if (b.id === "sea-again" || b.id === "sea-home") {
      lastRoomId = "";
      load(true, null);
      return;
    }
    if (b.dataset.seaRespond) {
      const accept = b.dataset.seaRespond === "yes";
      perform({ action: "respond", room_id: b.dataset.roomId, accept }).then((result) => {
        if (tab === "notices") window.NoraCabinet?.reloadNotices();
        if (result && accept) {
          tab = "sea";
          render();
          window.scrollTo(0, 0);
        }
      });
      return;
    }
    if (b.dataset.seaInvitePerson) {
      const id = Number(b.dataset.seaInvitePerson);
      perform({ action: "invite", room_id: state.sea?.room?.id, user_id: id }).then((result) => {
        if (result && b.isConnected) {
          b.disabled = true;
          b.innerHTML = "<span>Приглашение отправлено ✓</span>";
        }
      });
      return;
    }
    if (b.dataset.seaShoot !== undefined) {
      const cell = Number(b.dataset.seaShoot);
      perform({ action: "shoot", room_id: state.sea?.room?.id, cell }, { quiet: true });
      return;
    }
    if (b.dataset.seaAction) {
      const action = b.dataset.seaAction;
      const cancelText = "Комната закроется" + (state.sea?.room?.stake ? ", ставка вернётся" : "") + ".";
      const lobby = state.sea?.room?.status === "lobby";
      sheet(`<h2>${action === "cancel" ? "Закрыть комнату?" : lobby ? "Выйти из комнаты?" : "Сдаться и выйти?"}</h2><p class="sub">${action === "cancel" ? cancelText : lobby ? "Ты покинешь лобби." : "Партия завершится, победа засчитается сопернику."}</p><button class="primary" id="sea-leave-confirm">${action === "cancel" ? "Закрыть" : lobby ? "Выйти" : "Сдаться"}</button>`);
      $("#sea-leave-confirm").onclick = () => perform({ action, room_id: state.sea?.room?.id }, { close: true });
      return;
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && tab === "sea") {
      load(true);
      schedule();
    }
  });

  window.addEventListener("popstate", () => {
    if (tab === "sea") schedule();
  });

  return {
    screen,
    parent: () => "games",
    load,
    inviteCard,
    mount,
    handles: (view) => VIEWS.has(view),
    refreshCurrent: () => {
      if (tab !== "sea") return false;
      load(true);
      return true;
    },
  };
})();