import { useState } from "react";
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

  async function create() {
    setBusy(true);
    setError("");
    try {
      const { snapshot } = await api("poker/rooms", {});
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
        <p>Техасский холдем на 2–5 мест. Позови друзей за стол или потренируйся с ботами.</p>
        <div className={styles.features}><span>Игровые фишки</span></div>
      </div>
      <div className={styles.entry}>
        <button className={styles.primary} onClick={create} disabled={busy}>
          {busy ? "Открываем стол…" : "Создать приватный стол"}
        </button>
        {saved && <button type="button" className="poker-back" disabled={busy} onClick={() => enter(saved)}>Вернуться к столу</button>}
        <form className={styles.joinRow} onSubmit={(event) => { event.preventDefault(); if (code.length === 8) enter(code); }}>
          <input aria-label="Код стола" value={code} onChange={(event) => setCode(event.target.value.toUpperCase().replace(/[^A-HJ-NP-Z2-9]/g, ""))} placeholder="Код стола" maxLength={8} />
          <button disabled={busy || code.length !== 8}>Войти</button>
        </form>
        {error && <p className={styles.error} role="alert">{error}</p>}
      </div>
    </div>
  </section>;
}
