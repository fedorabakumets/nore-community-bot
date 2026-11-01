"use strict";
window.NoraSea = (() => {
  const VIEWS = new Set(["sea"]);
  const state = { sea: null };
  const errors = {};
  let pollTimer = null,
    pending = false;
  const draft = { stake: "0" };
  let lastRoomId = "";
  let lastHtml = "";
  let snapshotVersion = 0, serverTime = 0, syncedAt = 0;

  const ROWS = "АБВГДЕЖЗИК";

  function cellCoord(i) {
    return ROWS[Math.floor(i / 10)] + ((i % 10) + 1);
  }

  // Classes: c0 empty, c1 own ship, c2 hit, c3 miss, c4 sunk
  function ownBoardHtml(entry) {
    const cells = entry.board
      .map((c) => `<span class="sea-cell ${c.sunk ? "c4" : c.hit ? "c2" : c.miss ? "c3" : c.ship ? "c1" : "c0"}"></span>`)
      .join("");
    return `<div class="sea-board">${cells}</div>`;
  }

  function enemyBoardHtml(entry, interactive, reveal) {
    const cells = entry.shots
      .map((s, i) => {
        const cls = reveal
          ? (s.sunk ? "c4" : s.hit ? "c2" : s.fired ? "c3" : reveal[i] ? "c1" : "c0")
          : !s.fired ? "c0" : s.sunk ? "c4" : s.hit ? "c2" : "c3";
        return interactive
          ? `<button class="sea-cell ${cls}" data-sea-shoot="${i}" aria-label="Клетка ${cellCoord(i)}" ${pending ? "disabled" : ""}></button>`
          : `<span class="sea-cell ${cls}"></span>`;
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
      `<p class="sub">${esc(i.sender_name)} зовёт · ${label}</p>` +
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
      ? "Ставка спишется при создании (с ботом) или при старте партии (с другом). Победитель забирает удвоенную ставку, при ничьей — возврат."
      : "Бесплатная партия: печеньки не списываются.";
    return (
      backBtn() +
      invites() +
      `<div class="play-title-row"><div><p class="eyebrow">С ботом или с другом · бесплатно или на 🍪</p><h1>Морской<br><em>бой</em></h1></div>` +
      `<span class="rocket-balance"><small>В кошельке</small><b>${number(s?.balance ?? data.user.cookies)} 🍪</b></span></div>` +
      `<p class="sub">Попал — стреляй ещё. Промах — ход переходит. Потопи весь флот.</p>` +
      errorBox() +
      (s && !s.enabled ? '<p class="game-restricted">Новые игры временно выключены администрацией.</p>' : "") +
      `<section class="card mafia-create"><span class="eyebrow">Соперник и режим</span><h2>Начнём бой.</h2>` +
      `<div class="stake-chips" role="group" aria-label="Ставка">${stakeChips()}</div>` +
      `<div class="pet-action-row"><button class="primary" id="sea-create-bot" ${pending || !s || !s.enabled ? "disabled" : ""}>Играть с ботом</button>` +
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
    return `<div class="mafia-player ${turn ? "you" : ""}"><span class="person-avatar">${esc((p.name || "?").match(/[\p{L}\p{N}]/u)?.[0]?.toUpperCase() || "?")}</span><b>${esc(p.name)}</b><small>${inLobby ? (p.ready ? "Готов" : "Собирается") : turn ? "Стреляет" : "Ждёт"} · кораблей: ${ships}${p.left ? " · вышел" : ""}</small></div>`;
  }

  function lobbyView(r) {
    const title = r.bot ? "Бот ждёт начала" : r.players.length === 2 ? "Соперник найден" : "Ждём соперника";
    const text = r.bot ? "Флот расставится случайно при старте." : "Пригласи друга — приглашение придёт в чат и в миниапку.";
    const stakeNote = r.stake ? `Ставка ${number(r.stake)} 🍪: с другом спишется у обоих при старте.` : "Партия бесплатная.";
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
    let eyebrow = done ? "Партия завершена" : myTurn ? "Твой ход" : "Ход соперника";
    let title = done ? (r.winner == null ? "Ничья" : iWon ? "Ты победил!" : "Победил " + esc(winnerName)) : myTurn ? "Выбери клетку на поле соперника" : "Ждём…";
    let stakeOutcome = "";
    if (done && r.stake) stakeOutcome = r.winner == null ? " · ставки возвращены" : iWon ? " · +" + number(r.stake) + " 🍪" : " · −" + number(r.stake) + " 🍪";
    return `<section class="card sea-arena"><div class="sea-turn ${myTurn ? "mine" : ""}"><span class="eyebrow">${eyebrow}</span><h3>${title}${stakeOutcome}</h3>${done ? "" : deadlineBadge(r)}</div>`;
  }

  function boardsView(r, me, foe, myTurn) {
    const foeLabel = foe?.id === -1 ? "Поле соперника · бот" : "Поле соперника";
    const reveal = r.status === "finished" ? foe?.ships : null;
    return (
      `<div class="sea-boards"><div><h4>${foeLabel}</h4>${enemyBoardHtml(me, myTurn, reveal)}</div>` +
      `<div><h4>Твой флот</h4>${ownBoardHtml(me)}</div></div>` +
      `<div class="mafia-players">${r.players.map(playerRow).join("")}</div></section>`
    );
  }

  function controlsView(r) {
    if (["finished", "cancelled"].includes(r.status)) {
      return `<div class="pet-action-row"><button class="primary" id="sea-again">Новая партия</button><button class="secondary" id="sea-home">К списку</button></div>`;
    }
    const cancel = r.host_id === data.user.user_id && r.status === "lobby" ? '<button class="secondary danger-action" data-sea-action="cancel">Закрыть комнату</button>' : "";
    return `<section class="card mafia-room-controls"><button class="secondary" data-sea-action="leave">Сдаться и выйти</button>${cancel}</section>`;
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

  function syncClock(response) {
    if (Number.isFinite(response.server_now)) {
      serverTime = response.server_now;
      syncedAt = performance.now();
    }
  }

  async function load(force = false, roomId = undefined, recover = false) {
    if (!auth || !data || (pending && !recover)) return;
    const version = ++snapshotVersion;
    try {
      const selected = roomId === undefined ? lastRoomId : roomId;
      const response = await api("sea" + (selected ? "?room_id=" + encodeURIComponent(selected) : ""));
      if (version !== snapshotVersion) return;
      state.sea = response;
      syncClock(response);
      delete errors.sea;
      if (response.room?.id) lastRoomId = response.room.id;
      else if (roomId !== undefined) lastRoomId = "";
      if (tab === "sea") patch();
    } catch (e) {
      if (version !== snapshotVersion) return;
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
      const now = serverTime ? serverTime + performance.now() - syncedAt : Date.now();
      const seconds = Math.max(0, Math.ceil((r.deadline - now) / 1000));
      t.textContent = String(seconds) + "с";
      t.classList.toggle("urgent", seconds < 10);
    }
  }

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
    ++snapshotVersion;
    try {
      const response = await api("sea/action", body);
      ++snapshotVersion;
      state.sea = { ...(state.sea || {}), ...response };
      syncClock(response);
      lastRoomId = response.room?.id || "";
      delete errors.sea;
      if (response.message && !opts.quiet) toast(response.message);
      if (opts.close) $("#sheet").close();
      patch();
      return response;
    } catch (e) {
      toast(e.message);
      await load(true, undefined, true);
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
          .map((p) => `<button class="invite-person" data-sea-invite-person="${p.id}"><span class="person-avatar">${esc((p.name || "?").match(/[\p{L}\p{N}]/u)?.[0]?.toUpperCase() || "?")}</span><span><b>${esc(p.name)}</b><small>Пригласить в комнату</small></span></button>`)
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

  function mount() {
    if (tab === "sea") load(true);
    timerTick();
    schedule();
  }

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
      perform({ action: "create", vs_bot: true, stake: Number(draft.stake) });
      return;
    }
    if (b.id === "sea-create-friend") {
      perform({ action: "create", vs_bot: false, stake: Number(draft.stake) });
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
        if (result && tab === "community") window.NoraCommunity?.reload();
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
      sheet(`<h2>${action === "cancel" ? "Закрыть комнату?" : "Сдаться и выйти?"}</h2><p class="sub">${action === "cancel" ? cancelText : "Партия завершится, победа засчитается сопернику."}</p><button class="primary" id="sea-leave-confirm">${action === "cancel" ? "Закрыть" : "Сдаться"}</button>`);
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

  setInterval(() => { if (!document.hidden && tab === "sea") timerTick(); }, 1000);

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
