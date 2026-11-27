import { legalActions, totalPot } from "./engine";
import type { BotStyle, LegalActions, RoomSettings, RoomState } from "./types";

export interface PublicPlayer {
  id: string;
  name: string;
  avatar: number;
  seat: number;
  stack: number;
  bet: number;
  committed: number;
  folded: boolean;
  allIn: boolean;
  sittingOut: boolean;
  connected: boolean;
  isBot: boolean;
  botStyle?: BotStyle;
  hole: Array<string | null>;
  lastAction?: string;
  handsWon: number;
  biggestPot: number;
  timeBankMs: number;
}

export interface RoomSnapshot {
  code: string;
  version: number;
  viewerId: string | null;
  hostId: string;
  settings: RoomSettings;
  players: PublicPlayer[];
  hand: null | {
    id: string;
    street: string;
    dealerSeat: number;
    smallBlindSeat: number;
    bigBlindSeat: number;
    actorId: string | null;
    board: string[];
    currentBet: number;
    minRaise: number;
    deadlineAt: number | null;
    nextHandAt: number | null;
    winners: Array<{ playerId: string; amount: number; handName?: string; cards?: string[] }>;
    pots: Array<{ amount: number; eligibleIds: string[]; winnerIds: string[] }>;
    message: string;
  };
  paused: boolean;
  pot: number;
  legal: LegalActions | null;
  history: RoomState["history"];
  chat: RoomState["chat"];
  seatsOpen: number;
  serverTime: number;
}

export function snapshot(room: RoomState, viewerId: string | null): RoomSnapshot {
  const revealAll = room.hand?.street === "complete" && room.hand.winners.some((winner) => winner.cards);
  return {
    code: room.code,
    version: room.version,
    viewerId,
    hostId: room.hostId,
    settings: room.settings,
    players: room.players.map((player) => ({
      id: player.id, name: player.name, avatar: player.avatar, seat: player.seat, stack: player.stack,
      bet: player.bet, committed: player.committed, folded: player.folded, allIn: player.allIn,
      sittingOut: player.sittingOut, connected: player.connected, isBot: player.isBot, botStyle: player.botStyle,
      hole: player.id === viewerId || (revealAll && !player.folded) ? player.hole : player.hole.map(() => null),
      lastAction: player.lastAction, handsWon: player.handsWon, biggestPot: player.biggestPot, timeBankMs: player.timeBankMs,
    })),
    hand: room.hand ? {
      id: room.hand.id, street: room.hand.street, dealerSeat: room.hand.dealerSeat,
      smallBlindSeat: room.hand.smallBlindSeat, bigBlindSeat: room.hand.bigBlindSeat,
      actorId: room.hand.actorId, board: room.hand.board, currentBet: room.hand.currentBet,
      minRaise: room.hand.minRaise, deadlineAt: room.hand.deadlineAt, nextHandAt: room.hand.nextHandAt,
      winners: room.hand.winners, pots: room.hand.pots, message: room.hand.message,
    } : null,
    paused: room.paused,
    pot: room.hand?.street === "complete" ? room.hand.winners.reduce((sum, winner) => sum + winner.amount, 0) : totalPot(room),
    legal: viewerId ? legalActions(room, viewerId) : null,
    history: room.history,
    chat: room.chat,
    seatsOpen: 5 - room.players.length,
    serverTime: Date.now(),
  };
}
