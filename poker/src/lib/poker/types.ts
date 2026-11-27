export const RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"] as const;
export const SUITS = ["c", "d", "h", "s"] as const;

export type Rank = (typeof RANKS)[number];
export type Suit = (typeof SUITS)[number];
export type Card = `${Rank}${Suit}`;
export type Street = "preflop" | "flop" | "turn" | "river" | "complete";
export type BotStyle = "tight" | "balanced" | "aggressive";
export type PokerAction =
  | { type: "fold" }
  | { type: "check" }
  | { type: "call" }
  | { type: "raise"; amount: number };

export interface PlayerState {
  id: string;
  tokenHash: string;
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
  hole: Card[];
  lastAction?: string;
  handsWon: number;
  biggestPot: number;
  timeBankMs: number;
}

export interface HandWinner {
  playerId: string;
  amount: number;
  handName?: string;
  cards?: Card[];
}

export interface PotResult {
  amount: number;
  eligibleIds: string[];
  winnerIds: string[];
}

export interface HandState {
  id: string;
  street: Street;
  dealerSeat: number;
  smallBlindSeat: number;
  bigBlindSeat: number;
  actorId: string | null;
  deck: Card[];
  board: Card[];
  burns: Card[];
  currentBet: number;
  minRaise: number;
  actedIds: string[];
  lastAggressorId: string | null;
  deadlineAt: number | null;
  nextHandAt: number | null;
  startedAt: number;
  winners: HandWinner[];
  pots: PotResult[];
  message: string;
}

export interface RoomSettings {
  smallBlind: number;
  bigBlind: number;
  buyIn: number;
  actionSeconds: number;
}

export interface HistoryEntry {
  id: string;
  at: number;
  text: string;
  pot?: number;
}

export interface ChatEntry {
  id: string;
  playerId: string;
  name: string;
  text: string;
  at: number;
  reaction?: boolean;
}

export interface RoomState {
  code: string;
  version: number;
  hostId: string;
  settings: RoomSettings;
  players: PlayerState[];
  hand: HandState | null;
  paused: boolean;
  createdAt: number;
  updatedAt: number;
  history: HistoryEntry[];
  chat: ChatEntry[];
  recentCommandIds: string[];
}

export interface LegalActions {
  actorId: string;
  toCall: number;
  canFold: boolean;
  canCheck: boolean;
  canCall: boolean;
  canRaise: boolean;
  minRaiseTo: number;
  maxRaiseTo: number;
}

export interface HandScore {
  category: number;
  kickers: number[];
  name: string;
  cards: Card[];
}
