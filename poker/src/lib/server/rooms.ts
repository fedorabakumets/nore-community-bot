import { createHash, randomBytes, randomUUID } from "node:crypto";
import { applyPokerAction, processDeadline, startHand } from "../poker/engine";
import { chooseBotAction } from "../poker/bots";
import type { BotStyle, PlayerState, PokerAction, RoomSettings, RoomState } from "../poker/types";
export { snapshot } from "../poker/view";
export type { RoomSnapshot } from "../poker/view";
import { createStoredRoom, loadRoom, mutateRoom, rateLimit } from "./store";

const CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
const REACTIONS = new Set(["👏", "🔥", "😮", "♠", "♥", "Nice hand", "Good luck"]);

export type RoomCommand =
  | { type: "start" }
  | { type: "poker"; action: PokerAction }
  | { type: "addBot"; style: BotStyle }
  | { type: "removeBot"; playerId: string }
  | { type: "sitOut"; value: boolean }
  | { type: "rebuy" }
  | { type: "timeBank" }
  | { type: "pause"; value: boolean }
  | { type: "transferHost"; playerId: string }
  | { type: "kick"; playerId: string }
  | { type: "chat"; text: string }
  | { type: "reaction"; text: string };

function tokenHash(token: string): string {
  return createHash("sha256").update(token).digest("base64url");
}

function cleanName(value: unknown): string {
  if (typeof value !== "string") throw new Error("Enter a display name");
  const name = value.replace(/[<>]/g, "").replace(/\s+/g, " ").trim().slice(0, 20);
  return name || "Участник";
}

function code(): string {
  return Array.from(randomBytes(8), (byte) => CODE_ALPHABET[byte % CODE_ALPHABET.length]).join("");
}

function nextOpenSeat(room: RoomState): number {
  for (let seat = 0; seat < 5; seat += 1) if (!room.players.some((player) => player.seat === seat)) return seat;
  return -1;
}

function newPlayer(name: string, avatar: number, seat: number, stack: number, token: string, botStyle?: BotStyle): PlayerState {
  const isBot = Boolean(botStyle);
  return {
    id: randomUUID(), tokenHash: tokenHash(token), name, avatar, seat, stack,
    bet: 0, committed: 0, folded: false, allIn: false, sittingOut: false,
    connected: true, isBot, botStyle, hole: [], handsWon: 0, biggestPot: 0, timeBankMs: isBot ? 0 : 30_000,
  };
}

export async function createRoom(nameValue: unknown, avatarValue: unknown, token: string, settingsValue?: Partial<RoomSettings>) {
  const name = cleanName(nameValue);
  const avatar = Math.max(0, Math.min(11, Number(avatarValue) || 0));
  const smallBlind = Math.max(1, Math.min(1_000, Math.trunc(settingsValue?.smallBlind ?? 10)));
  const bigBlind = Math.max(smallBlind * 2, Math.min(2_000, Math.trunc(settingsValue?.bigBlind ?? smallBlind * 2)));
  const buyIn = settingsValue?.buyIn === undefined ? bigBlind * 100 : Math.max(5, Math.min(1000, Math.trunc(settingsValue.buyIn)));
  const actionSeconds = Math.max(15, Math.min(60, Math.trunc(settingsValue?.actionSeconds ?? 25)));
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const roomCode = code();
    const host = newPlayer(name, avatar, 0, buyIn, token);
    const now = Date.now();
    const room: RoomState = {
      code: roomCode, version: 1, hostId: host.id,
      settings: { smallBlind, bigBlind, buyIn, actionSeconds }, players: [host], hand: null,
      paused: false, createdAt: now, updatedAt: now, history: [], chat: [], recentCommandIds: [],
    };
    if (createStoredRoom(room)) return { room, playerId: host.id, token };
  }
  throw new Error("Could not create a room");
}

export async function joinRoom(roomCode: string, nameValue: unknown, avatarValue: unknown, token: string) {
  const name = cleanName(nameValue);
  const avatar = Math.max(0, Math.min(11, Number(avatarValue) || 0));
  let joinedId = "";
  const room = mutateRoom(roomCode, (draft) => {
    const seat = nextOpenSeat(draft);
    if (seat < 0) throw new Error("This table is full");
    const guest = newPlayer(name, avatar, seat, draft.settings.buyIn, token);
    if (draft.hand && draft.hand.street !== "complete") guest.sittingOut = true;
    draft.players.push(guest);
    joinedId = guest.id;
  });
  return { room, playerId: joinedId, token };
}

export async function authenticate(roomCode: string, token: string | undefined): Promise<{ room: RoomState; player: PlayerState } | null> {
  if (!token) return null;
  const room = loadRoom(roomCode);
  const player = room?.players.find((candidate) => candidate.tokenHash === tokenHash(token));
  return room && player ? { room, player } : null;
}

function hostOnly(room: RoomState, playerId: string): void {
  if (room.hostId !== playerId) throw new Error("Only the host can do that");
}

function betweenHands(room: RoomState): void {
  if (room.hand && room.hand.street !== "complete") throw new Error("Wait until the hand is over");
}

export async function commandRoom(roomCode: string, token: string, commandId: string, expectedVersion: number, command: RoomCommand): Promise<RoomState> {
  if (!/^[a-zA-Z0-9_-]{8,80}$/.test(commandId)) throw new Error("Invalid command id");
  if (!Number.isSafeInteger(expectedVersion) || expectedVersion < 1) throw new Error("Invalid state version");
  const hash = tokenHash(token);
  rateLimit(`command:${roomCode}:${hash}`, command.type === "chat" ? 18 : 120, command.type === "chat" ? 10 : 60);
  return mutateRoom(roomCode, (room) => {
    const player = room.players.find((candidate) => candidate.tokenHash === hash);
    if (!player) throw new Error("Not authorized for this table");
    const receipt = player.id + ":" + commandId;
    if (room.recentCommandIds.includes(receipt)) return null;
    if (room.version !== expectedVersion) throw new Error("The table changed; try again");
    room.recentCommandIds = [...room.recentCommandIds.slice(-63), receipt];

    if (command.type === "start") {
      hostOnly(room, player.id);
      betweenHands(room);
      room.paused = false;
      startHand(room);
    } else if (command.type === "poker") {
      const action = command.action;
      if (!action || !["fold", "check", "call", "raise"].includes(action.type)
        || (action.type === "raise" && !Number.isSafeInteger(action.amount))) {
        throw new Error("Проверь действие и размер ставки");
      }
      applyPokerAction(room, player.id, action);
    } else if (command.type === "addBot") {
      hostOnly(room, player.id);
      betweenHands(room);
      const seat = nextOpenSeat(room);
      if (seat < 0) throw new Error("This table is full");
      const botNumber = room.players.filter((candidate) => candidate.isBot).length + 1;
      const names: Record<BotStyle, string[]> = { tight: ["Nora", "Theo"], balanced: ["Mira", "Jules"], aggressive: ["Rook", "Sable"] };
      if (!Object.hasOwn(names, command.style)) throw new Error("Неизвестный стиль бота");
      room.players.push(newPlayer(names[command.style][(botNumber - 1) % 2], (seat * 3 + botNumber) % 12, seat, room.settings.buyIn, randomBytes(32).toString("base64url"), command.style));
    } else if (command.type === "removeBot") {
      hostOnly(room, player.id);
      betweenHands(room);
      room.players = room.players.filter((candidate) => candidate.id !== command.playerId || !candidate.isBot);
    } else if (command.type === "sitOut") {
      player.sittingOut = Boolean(command.value);
    } else if (command.type === "rebuy") {
      betweenHands(room);
      if (player.stack >= room.settings.buyIn) throw new Error("Your stack is already full");
      player.stack = room.settings.buyIn;
    } else if (command.type === "timeBank") {
      if (room.hand?.actorId !== player.id || !room.hand.deadlineAt) throw new Error("Use your time bank during your turn");
      if (player.timeBankMs <= 0) throw new Error("Your time bank is empty");
      room.hand.deadlineAt += player.timeBankMs;
      player.timeBankMs = 0;
    } else if (command.type === "pause") {
      hostOnly(room, player.id);
      room.paused = Boolean(command.value);
    } else if (command.type === "transferHost") {
      hostOnly(room, player.id);
      const nextHost = room.players.find((candidate) => candidate.id === command.playerId && !candidate.isBot);
      if (!nextHost) throw new Error("Choose another guest player");
      room.hostId = nextHost.id;
    } else if (command.type === "kick") {
      hostOnly(room, player.id);
      betweenHands(room);
      if (command.playerId === player.id) throw new Error("The host cannot kick themselves");
      room.players = room.players.filter((candidate) => candidate.id !== command.playerId);
    } else {
      const isReaction = command.type === "reaction";
      const text = command.text.replace(/[<>]/g, "").trim().slice(0, isReaction ? 20 : 180);
      if (!text || (isReaction && !REACTIONS.has(text))) throw new Error("Message not allowed");
      room.chat.push({ id: randomUUID(), playerId: player.id, name: player.name, text, at: Date.now(), reaction: isReaction });
      room.chat = room.chat.slice(-40);
    }
  });
}

export async function advanceRoom(roomCode: string, expectedVersion: number): Promise<RoomState> {
  return mutateRoom(roomCode, (room) => {
    if (room.version !== expectedVersion) return null;
    const hand = room.hand;
    const now = Date.now();
    if (hand?.actorId && hand.deadlineAt && now >= hand.deadlineAt) {
      const actor = room.players.find((player) => player.id === hand.actorId);
      if (actor?.isBot) return applyPokerAction(room, actor.id, chooseBotAction(room, actor.id), now);
      return processDeadline(room, now);
    }
    if (hand?.street === "complete" && hand.nextHandAt && now >= hand.nextHandAt && !room.paused && room.players.filter((player) => !player.sittingOut && player.stack > 0).length >= 2) {
      return processDeadline(room, now);
    }
    return null;
  });
}
