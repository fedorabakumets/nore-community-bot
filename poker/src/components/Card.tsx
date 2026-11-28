import { copy } from "../i18n";
import type { CSSProperties } from "react";
import styles from "./Card.module.css";

const SUIT: Record<string, string> = { c: "♣", d: "♦", h: "♥", s: "♠" };
const PIPS: Record<string, Array<[number, number]>> = {
  "2": [[1, 0], [1, 4]],
  "3": [[1, 0], [1, 2], [1, 4]],
  "4": [[0, 0], [2, 0], [0, 4], [2, 4]],
  "5": [[0, 0], [2, 0], [1, 2], [0, 4], [2, 4]],
  "6": [[0, 0], [2, 0], [0, 2], [2, 2], [0, 4], [2, 4]],
  "7": [[0, 0], [2, 0], [1, 1], [0, 2], [2, 2], [0, 4], [2, 4]],
  "8": [[0, 0], [2, 0], [1, 1], [0, 2], [2, 2], [1, 3], [0, 4], [2, 4]],
  "9": [[0, 0], [2, 0], [0, 1], [2, 1], [1, 2], [0, 3], [2, 3], [0, 4], [2, 4]],
  "10": [[0, 0], [2, 0], [0, 1], [1, 1], [2, 1], [0, 3], [1, 3], [2, 3], [0, 4], [2, 4]],
};

export function Card({ card, small = false, delay = 0, deal = false, placeholder = false, highlighted = false }: { card: string | null; small?: boolean; delay?: number; deal?: boolean; placeholder?: boolean; highlighted?: boolean }) {
  const revealed = Boolean(card);
  const rank = card ? (card[0] === "T" ? "10" : card[0]) : "";
  const suit = card ? SUIT[card[1]] : "";
  const red = Boolean(card && (card[1] === "h" || card[1] === "d"));
  const style = { "--card-delay": `${delay}ms` } as CSSProperties;
  return (
    <span className={`${styles.slot} ${small ? styles.small : ""} ${placeholder ? styles.placeholder : ""} ${highlighted ? styles.highlighted : ""}`} style={style} aria-label={placeholder ? copy("Место для общей карты") : revealed ? `${rank} ${suit}` : copy("Закрытая карта")}>
      <span className={`${styles.motion} ${deal ? styles.dealt : ""}`}>
        <span className={`${styles.card} ${revealed ? styles.revealed : styles.concealed} ${red ? styles.red : ""}`}>
          <span className={`${styles.face} ${styles.front}`} aria-hidden="true">
            <span className={styles.corner}>{rank}<b>{suit}</b></span>
            {PIPS[rank] ? <span className={styles.pips}>{PIPS[rank].map(([column, row], index) => <i key={index} className={row > 2 ? styles.inverted : ""} style={{ gridColumn: column + 1, gridRow: row + 1 }}>{suit}</i>)}</span> : rank === "A" ? <span className={styles.ace}>{suit}</span> : rank ? <span className={styles.court}><b>{rank}</b><i>{suit}</i><em>{rank}</em></span> : null}
            <span className={`${styles.corner} ${styles.bottom}`}>{rank}<b>{suit}</b></span>
          </span>
          <span className={`${styles.face} ${styles.back}`} aria-hidden="true"><i /></span>
        </span>
      </span>
    </span>
  );
}
