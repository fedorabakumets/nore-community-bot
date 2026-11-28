"use client";

import { copy } from "../i18n";

import { useCallback, useEffect, useRef, useState } from "react";
import type { RoomSnapshot } from "../lib/poker/view";
import type { RoomCommand } from "../lib/server/rooms";
import { playSound } from "../lib/client/sound";
import type { PokerApi } from "../client";
import { Avatar } from "./Avatar";
import { PokerTable } from "./PokerTable";
import styles from "./TableRoom.module.css";

export function TableRoom({ code, api, share, remember, lobby }: {
  code: string;
  api: PokerApi;
  share: (url: string) => void;
  remember: (code: string) => void;
  lobby: () => void;
}) {
  const endpoint = "poker/rooms/" + code;
  const [state, setState] = useState<RoomSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [joinable, setJoinable] = useState(false);
  const [entryAmount, setEntryAmount] = useState(0);
  const [online, setOnline] = useState(false);
  const [error, setError] = useState("");
  const [joining, setJoining] = useState(false);
  const [pending, setPending] = useState(false);
  const [raiseTo, setRaiseTo] = useState(0);
  const [drawer, setDrawer] = useState(false);
  const [chat, setChat] = useState("");
  const [sound, setSound] = useState(false);
  const [sharing, setSharing] = useState(false);
  const revision = useRef(0);
  const previous = useRef<{ hand?: string; board: number; winner: string; actor?: string | null } | null>(null);
  const accept = useCallback((snapshot?: RoomSnapshot | null) => {
    setState(current => snapshot && (!current || snapshot.version > current.version) ? snapshot : current);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number;
    async function refresh() {
      if (document.hidden) {
        timer = window.setTimeout(refresh, 1000);
        return;
      }
      try {
        const requestedRevision = revision.current;
        const result = await api(endpoint, undefined, controller.signal);
        if (controller.signal.aborted) return;
        if (result.snapshot) accept(result.snapshot);
        else if (requestedRevision === revision.current) setState(null);
        setJoinable(result.joinable === true);
        if (result.buyIn !== undefined) setEntryAmount(result.buyIn);
        setOnline(true);
        setLoading(false);
      } catch (caught) {
        if (controller.signal.aborted) return;
        const failure = caught as Error & { status?: number };
        setOnline(false);
        if ([401, 403, 404].includes(failure.status ?? 0)) {
          setState(null);
          setJoinable(false);
          setError(failure.message);
          setLoading(false);
          return;
        }
        setError(failure.message);
        setLoading(false);
      }
      timer = window.setTimeout(refresh, 850);
    }
    void refresh();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [accept, api, endpoint]);

  useEffect(() => {
    if (state?.viewerId) remember(code);
  }, [code, state?.viewerId]);

  useEffect(() => {
    if (state?.legal) setRaiseTo(Math.min(state.legal.minRaiseTo, state.legal.maxRaiseTo));
  }, [state?.hand?.id, state?.hand?.actorId, state?.legal?.minRaiseTo, state?.legal?.maxRaiseTo]);

  useEffect(() => {
    if (!state || !sound) return;
    const winner = state.hand?.winners.map((item) => item.playerId).join(",") ?? "";
    const current = { hand: state.hand?.id, board: state.hand?.board.length ?? 0, winner, actor: state.hand?.actorId };
    const old = previous.current;
    if (old && current.winner && current.winner !== old.winner) playSound("win");
    else if (old && current.hand && current.hand !== old.hand) playSound("card");
    else if (old && current.board > old.board) playSound("card");
    else if (old && old.actor !== current.actor && current.actor === state.viewerId) playSound("turn");
    previous.current = current;
  }, [sound, state]);

  async function join() {
    setJoining(true);
    setError("");
    try {
      const result = await api(endpoint + "/join", {});
      revision.current += 1;
      accept(result.snapshot);
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setJoining(false);
    }
  }

  async function command(command: RoomCommand) {
    if (pending || !state || !online) return;
    setPending(true);
    setError("");
    if (sound) playSound("chip");
    try {
      const result = await api(endpoint + "/command", {
        commandId: crypto.randomUUID(),
        expectedVersion: state.version,
        command,
      });
      revision.current += 1;
      accept(result.snapshot);
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setPending(false);
    }
  }

  async function cashOut() {
    if (pending || !online) return;
    setPending(true);
    try {
      await api(endpoint + "/leave", {});
      revision.current += 1;
      remember("");
      lobby();
    } catch (caught) { setError((caught as Error).message); }
    finally { setPending(false); }
  }

  async function invite() {
    setSharing(true);
    setError("");
    try {
      const { url } = await api(endpoint + "/link");
      if (!url) throw new Error(copy("Ссылка пока недоступна"));
      share(url);
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setSharing(false);
    }
  }

  function toggleSound() {
    setSound((enabled) => {
      if (!enabled) playSound("turn");
      return !enabled;
    });
  }

  useEffect(() => {
    if (!state?.legal || pending || drawer) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey || event.repeat || /INPUT|TEXTAREA/.test((event.composedPath()[0] as HTMLElement)?.tagName)) return;
      const key = event.key.toLowerCase();
      if (key === "f") void command({ type: "poker", action: { type: "fold" } });
      if (key === "c") void command({ type: "poker", action: state.legal!.canCheck ? { type: "check" } : { type: "call" } });
      if (key === "r" && state.legal!.canRaise) void command({ type: "poker", action: { type: "raise", amount: raiseTo } });
    };
    addEventListener("keydown", onKeyDown);
    return () => removeEventListener("keydown", onKeyDown);
  });

  if (loading) return <section className={styles.loading}><div className={styles.loader}>{copy("Тасуем колоду")}</div></section>;
  if (!state) return (
    <section className={styles.joinPage}>
      <div className={styles.joinBackdrop} />
      <div className={styles.joinCard}>
        <button type="button" className="poker-back" onClick={lobby}>{copy("← Покер")}</button>
        <h1>{copy("Стол")}{" "}{code}</h1>
        {joinable && <button className={styles.joinButton} onClick={join} disabled={joining}>{joining ? copy("Занимаем место…") : `${copy("Сесть за стол · 🍪")} ${entryAmount}`}</button>}
        <p role="status">{copy(error) || (joinable ? "" : copy("Все места заняты"))}</p>
      </div>
    </section>
  );

  const viewer = state.players.find((player) => player.id === state.viewerId)!;
  const host = state.hostId === state.viewerId;
  const betweenHands = !state.hand || state.hand.street === "complete";
  const eligible = state.players.filter((player) => !player.sittingOut && player.stack > 0).length;

  return (
    <section className={styles.room}>
      <div className={styles.backdrop} />
      <header className={styles.topbar}>
        <button className="poker-back" onClick={betweenHands ? cashOut : lobby} disabled={pending}>← {betweenHands ? copy("Выйти") : copy("Покер")}</button>
        <div className={styles.roomMeta}><span className={online ? styles.online : styles.reconnecting}>{online ? copy("На связи") : copy("Подключаемся")}</span><button onClick={invite} disabled={sharing}>{copy("Пригласить")}</button></div>
        <div className={styles.headerActions}><button aria-label={copy("Звук")} aria-pressed={sound} onClick={toggleSound}>{sound ? copy("Звук вкл.") : copy("Звук выкл.")}</button><button onClick={() => command({ type: "sitOut", value: !viewer.sittingOut })}>{viewer.sittingOut ? copy("Вернуться") : copy("Пропускать раздачи")}</button><button onClick={() => setDrawer((value) => !value)}>···</button></div>
      </header>
      <div className={styles.tableStage}>
        <PokerTable state={state} />
      </div>
      <div className={styles.reactions}>{["👏", "🔥", "😮", "♠", "♥"].map((reaction) => <button key={reaction} disabled={pending || !online} onClick={() => command({ type: "reaction", text: reaction })}>{reaction}</button>)}</div>
      <div className={`${styles.controls} ${pending ? styles.processing : ""}`} aria-busy={pending}>
        {state.legal ? <>
          <button className={styles.fold} disabled={pending || !online} onClick={() => command({ type: "poker", action: { type: "fold" } })}>{copy("Сбросить")}</button>
          <button className={styles.call} disabled={pending || !online} onClick={() => command({ type: "poker", action: state.legal!.canCheck ? { type: "check" } : { type: "call" } })}>{state.legal.canCheck ? copy("Пропустить", true) : `${copy("Уравнять", true) + " 🍪"} ${state.legal.toCall}`}</button>
          {state.legal.canRaise ? <div className={styles.raise}><div><span>{copy("До")}</span><strong>🍪 {raiseTo.toLocaleString()}</strong></div><input aria-label={copy("Размер повышения")} type="range" min={Math.min(state.legal.minRaiseTo, state.legal.maxRaiseTo)} max={state.legal.maxRaiseTo} step={1} value={raiseTo} onChange={(event) => setRaiseTo(Number(event.target.value))} /><div className={styles.presets}><button onClick={() => setRaiseTo(Math.min(state.legal!.maxRaiseTo, Math.max(state.legal!.minRaiseTo, Math.round(state.pot * .5 / state.settings.bigBlind) * state.settings.bigBlind)))}>{copy("½ банка")}</button><button onClick={() => setRaiseTo(Math.min(state.legal!.maxRaiseTo, Math.max(state.legal!.minRaiseTo, state.pot)))}>{copy("Банк", true)}</button><button onClick={() => setRaiseTo(state.legal!.maxRaiseTo)}>{copy("Всё")}</button>{viewer.timeBankMs > 0 ? <button onClick={() => command({ type: "timeBank" })}>+{viewer.timeBankMs / 1000}s</button> : null}<button className={styles.raiseButton} disabled={pending || !online} onClick={() => command({ type: "poker", action: { type: "raise", amount: raiseTo } })}>{copy("Повысить", true)}</button></div></div> : null}
        </> : <div className={styles.waitingControls}>
          {host && betweenHands && eligible >= 2 ? <button className={styles.deal} disabled={pending || !online} onClick={() => command({ type: "start" })}>{copy("Раздать карты")}</button> : null}
          {host && betweenHands && eligible < 2 ? <span>{copy("Пригласи второго игрока")}</span> : null}
          {!host && betweenHands ? <span>{copy("Ждём раздачу")}</span> : null}
          {!betweenHands ? <span>{state.hand?.actorId === viewer.id ? copy("Твой ход") : `${copy("Ходит")} ${state.players.find((player) => player.id === state.hand?.actorId)?.name ?? copy("игрок")}`}</span> : null}
          {betweenHands ? <button disabled={pending || !online} onClick={cashOut}>{copy("Забрать 🍪")}{" "}{viewer.stack.toLocaleString()}</button> : null}
        </div>}
      </div>
      {state.chat.filter((item) => item.reaction).slice(-1).map((item) => <div key={item.id} className={styles.reactionBurst}>{item.text}<small>{item.name}</small></div>)}
      <button className={`${styles.drawerScrim} ${drawer ? styles.drawerScrimOpen : ""}`} aria-label={copy("Закрыть журнал")} tabIndex={drawer ? 0 : -1} onClick={() => setDrawer(false)} />
      <aside inert={!drawer} className={`${styles.drawer} ${drawer ? styles.drawerOpen : ""}`}>
        <div className={styles.drawerHeader}><div><span>{copy("Журнал стола")}</span><strong>{state.players.length}{copy("/5 за столом")}</strong></div><button onClick={() => setDrawer(false)}>{copy("Закрыть")}</button></div>
        <div className={styles.tabs}><span>{copy("Чат")}</span></div>
        <div className={styles.seatActions}>
          <button disabled={!betweenHands || pending || !online} onClick={cashOut}>{copy("Забрать печеньки и выйти")}</button><button aria-pressed={sound} onClick={toggleSound}>{sound ? copy("Выключить звук") : copy("Включить звук")}</button>
          <button onClick={() => command({ type: "sitOut", value: !viewer.sittingOut })}>{viewer.sittingOut ? copy("Вернуться в игру") : copy("Пропускать раздачи")}</button>
        </div>
        <div className={styles.feed}>{state.chat.filter((item) => !item.reaction).length ? state.chat.filter((item) => !item.reaction).map((item) => <p key={item.id}><b>{item.name}</b>{item.text}</p>) : <div className={styles.empty}>{copy("Сообщений пока нет")}</div>}</div>
        <form onSubmit={(event) => { event.preventDefault(); if (chat.trim()) { void command({ type: "chat", text: chat }); setChat(""); } }}><input value={chat} onChange={(event) => setChat(event.target.value)} maxLength={180} placeholder={copy("Сообщение за стол")} /><button>{copy("Отправить")}</button></form>
        <div className={styles.history}><span>{copy("Последние раздачи")}</span>{state.history.map((entry) => <p key={entry.id}>{copy(entry.text)}<b>{entry.pot === undefined ? "" : `🍪 ${entry.pot.toLocaleString()}`}</b></p>)}</div>
        <div className={styles.roster}><span>{copy("Игроки")}</span>{state.players.map((player) => <p key={player.id}><span><Avatar index={player.avatar} size="sm" />{player.name}{player.isBot ? copy(" · бот") : ""}</span>{host && player.id !== viewer.id ? <span className={styles.seatActions}>{!player.isBot ? <button onClick={() => command({ type: "transferHost", playerId: player.id })}>{copy("Передать стол")}</button> : null}</span> : null}</p>)}</div>
        {host ? <button className={styles.pauseButton} onClick={() => command({ type: "pause", value: !state.paused })}>{state.paused ? copy("Продолжать раздачи") : copy("Пауза после раздачи")}</button> : null}
      </aside>
      {error ? <div className={styles.toast} role="alert">{copy(error)}<button onClick={() => setError("")}>{copy("Закрыть")}</button></div> : null}
    </section>
  );
}
