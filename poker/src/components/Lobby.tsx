import { useEffect, useState } from "react";
import type { PokerApi } from "../client";
import styles from "./Lobby.module.css";

export function Lobby({ api, enter, saved, exit }: {
  api: PokerApi;
  enter: (code: string) => void;
  saved: string;
  exit: () => void;
}) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [buyIn, setBuyIn] = useState(20);
  const [balance, setBalance] = useState<number | null>(null);
  const [activeCode, setActiveCode] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    api("poker/me", undefined, controller.signal).then(data => {
      setBalance(data.balance ?? 0); setActiveCode(data.code ?? null);
    }).catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [api]);

  async function create() {
    setBusy(true);
    setError("");
    try {
      const { snapshot } = await api("poker/rooms", { buyIn });
      if (!snapshot) throw new Error("Не удалось открыть стол");
      enter(snapshot.code);
    } catch (caught) {
      setError((caught as Error).message);
      setBusy(false);
    }
  }

  return <section className={styles.lobby}>
    <div className={styles.atmosphere} />
    <header className={styles.header}>
      <button type="button" className="poker-back" onClick={exit}>← Игры</button>
    </header>
    <div className={styles.stage}>
      <div className={styles.pitch}>
        <h1>Покер</h1>
        <p>Техасский холдем на 2–5 игроков. Ставки на печеньки Норы.</p>
        <div className={styles.features}><span>{balance === null ? "🍪 Печеньки Норы" : `🍪 Баланс: ${balance.toLocaleString()}`}</span></div>
      </div>
      <div className={styles.entry}>
        {!activeCode && <><label className={styles.label} htmlFor="poker-buyin">Сколько взять за стол · 🍪</label><input id="poker-buyin" type="number" min={5} max={Math.min(1000, balance ?? 1000)} step={1} value={buyIn} onChange={event => setBuyIn(Number(event.target.value))} /><p className={styles.label}>Неиспользованные печеньки вернутся при выходе.</p></>}
        <button className={styles.primary} onClick={activeCode ? () => enter(activeCode) : create} disabled={busy || (!activeCode && (balance === null || !Number.isInteger(buyIn) || buyIn < 5 || buyIn > Math.min(1000, balance)))}>
          {busy ? "Открываем стол…" : activeCode ? "Вернуться за стол" : `Сесть за стол · 🍪 ${buyIn}`}
        </button>
        {saved && !activeCode && <button type="button" className="poker-back" disabled={busy} onClick={() => enter(saved)}>Вернуться к столу</button>}
        <form className={styles.joinRow} onSubmit={(event) => { event.preventDefault(); if (!activeCode && code.length === 8) enter(code); }}>
          <input aria-label="Код стола" value={code} onChange={(event) => setCode(event.target.value.toUpperCase().replace(/[^A-HJ-NP-Z2-9]/g, ""))} placeholder="Код стола" maxLength={8} />
          <button disabled={busy || Boolean(activeCode) || code.length !== 8}>Войти</button>
        </form>
        {error && <p className={styles.error} role="alert">{error}</p>}
      </div>
    </div>
  </section>;
}
