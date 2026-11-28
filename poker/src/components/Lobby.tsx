import { copy } from "../i18n";
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
      if (!snapshot) throw new Error(copy("Не удалось открыть стол"));
      enter(snapshot.code);
    } catch (caught) {
      setError((caught as Error).message);
      setBusy(false);
    }
  }

  return <section className={styles.lobby}>
    <div className={styles.atmosphere} />
    <header className={styles.header}>
      <button type="button" className="poker-back" onClick={exit}>{copy("← Игры")}</button>
    </header>
    <div className={styles.stage}>
      <div className={styles.pitch}>
        <h1>{copy("Покер")}</h1>
        <p>{copy("Техасский холдем на 2–5 игроков. Ставки на печеньки Норы.")}</p>
        <div className={styles.features}><span>{balance === null ? copy("🍪 Печеньки Норы") : `${copy("🍪 Баланс:")} ${balance.toLocaleString()}`}</span></div>
      </div>
      <div className={styles.entry}>
        {!activeCode && <><label className={styles.label} htmlFor="poker-buyin">{copy("Сколько взять за стол · 🍪")}</label><input id="poker-buyin" type="number" min={5} max={Math.min(1000, balance ?? 1000)} step={1} value={buyIn} onChange={event => setBuyIn(Number(event.target.value))} /><p className={styles.label}>{copy("Неиспользованные печеньки вернутся при выходе.")}</p></>}
        <button className={styles.primary} onClick={activeCode ? () => enter(activeCode) : create} disabled={busy || (!activeCode && (balance === null || !Number.isInteger(buyIn) || buyIn < 5 || buyIn > Math.min(1000, balance)))}>
          {busy ? copy("Открываем стол…") : activeCode ? copy("Вернуться за стол") : `${copy("Сесть за стол · 🍪")} ${buyIn}`}
        </button>
        {saved && !activeCode && <button type="button" className="poker-back" disabled={busy} onClick={() => enter(saved)}>{copy("Вернуться к столу")}</button>}
        <form className={styles.joinRow} onSubmit={(event) => { event.preventDefault(); if (!activeCode && code.length === 8) enter(code); }}>
          <input aria-label={copy("Код стола")} value={code} onChange={(event) => setCode(event.target.value.toUpperCase().replace(/[^A-HJ-NP-Z2-9]/g, ""))} placeholder={copy("Код стола")} maxLength={8} />
          <button disabled={busy || Boolean(activeCode) || code.length !== 8}>{copy("Войти")}</button>
        </form>
        {error && <p className={styles.error} role="alert">{copy(error)}</p>}
      </div>
    </div>
  </section>;
}
