"use client";

import { Avatar } from "./Avatar";
import { Card } from "./Card";
import type { RoomSnapshot } from "../lib/poker/view";
import styles from "./PokerTable.module.css";

const POSITIONS = [styles.bottom, styles.left, styles.topLeft, styles.topRight, styles.right];
const STREETS: Record<string, string> = { preflop: "Префлоп", flop: "Флоп", turn: "Тёрн", river: "Ривер", complete: "Итог раздачи" };

function Chips({ amount }: { amount: number }) {
  if (!amount) return null;
  return <span className={styles.bet}><i /><i /><i /><b>{amount.toLocaleString()}</b></span>;
}

export function PokerTable({ state }: { state: RoomSnapshot }) {
  const viewer = state.players.find((player) => player.id === state.viewerId);
  const relative = (seat: number) => viewer ? (seat - viewer.seat + 5) % 5 : seat;
  const openSeats = Array.from({ length: 5 }, (_, seat) => seat).filter((seat) => !state.players.some((player) => player.seat === seat));
  const streetLabel = state.hand ? STREETS[state.hand.street] ?? state.hand.street : "";
  const message = state.hand?.message ?? "Ждём игроков";
  const showMessage = !state.hand || message !== streetLabel;
  return (
    <section className={styles.shell} aria-label="Покерный стол">
      <div className={styles.light} />
      <div className={styles.table}>
        <div className={styles.rail} />
        <div className={styles.feltTexture} />
        <div className={styles.center}>
          <div className={styles.pot} data-poker-pot><span>Банк</span><strong key={state.pot}>{state.pot.toLocaleString()}</strong><div key={`pot-${state.pot}`} className={styles.potChips}><i /><i /><i /><i /></div></div>
          <div className={styles.board} data-poker-board>
            {Array.from({ length: 5 }, (_, index) => <Card key={`${state.hand?.id ?? "empty"}-${index}`} card={state.hand?.board[index] ?? null} delay={index * 70} placeholder={!state.hand?.board[index]} />)}
          </div>
          <div className={styles.stateLine}>{state.hand ? <span key={`${state.hand.id}-${state.hand.street}`} className={styles.street}>{streetLabel}</span> : null}{showMessage ? <p key={`${state.hand?.id}-${state.hand?.message}`} className={styles.message} aria-live="polite">{message}</p> : null}</div>
        </div>
        {state.players.map((player) => {
          const position = POSITIONS[relative(player.seat)];
          const isActor = state.hand?.actorId === player.id;
          const isWinner = state.hand?.winners.some((winner) => winner.playerId === player.id);
          return (
            <div key={player.id} className={`${styles.seat} ${position} ${isActor ? styles.active : ""} ${player.folded ? styles.folded : ""} ${isWinner ? styles.winner : ""}`}>
              <div className={styles.identity} data-poker-seat={relative(player.seat)}>
                <Avatar index={player.avatar} size={relative(player.seat) === 0 ? "lg" : "md"} />
                {isActor && state.hand?.deadlineAt ? <span className={styles.timer} style={{ animationDuration: `${Math.max(1, (state.hand.deadlineAt - state.serverTime) / 1000)}s` }} /> : null}
                <div><span>{player.name}{player.isBot || !player.connected ? <em>{player.isBot ? "БОТ" : "ОТОШЁЛ"}</em> : null}</span><strong key={player.stack} className={styles.stack}>{player.stack.toLocaleString()}</strong></div>
              </div>
              <div className={styles.hole}>{player.hole.map((card, index) => <Card key={`${state.hand?.id ?? "waiting"}-${index}`} card={card} small deal delay={index * 85} />)}</div>
              {player.lastAction ? <span key={`${state.hand?.id}-${player.lastAction}-${player.bet}-${player.committed}`} className={styles.action}>{player.lastAction}</span> : null}
              {player.sittingOut ? <span className={styles.sitting}>Пропускает</span> : null}
              <Chips key={`${state.hand?.id}-${state.hand?.street}-${player.bet}`} amount={state.hand?.street === "complete" ? 0 : player.bet} />
              {state.hand?.dealerSeat === player.seat ? <span key={state.hand.id} className={styles.button}>D</span> : null}
            </div>
          );
        })}
        {openSeats.map((seat) => <div key={`open-${seat}`} className={`${styles.openSeat} ${POSITIONS[relative(seat)]}`}>Свободно</div>)}
      </div>
    </section>
  );
}
