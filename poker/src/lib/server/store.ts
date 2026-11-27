import type { RoomState } from "../poker/types";

const rooms = new Map<string, RoomState>();
const limits = new Map<string, { count: number; expires: number }>();
const ROOM_TTL = 30 * 60_000;

export function sweep(now = Date.now()) {
  for (const [code, room] of rooms) {
    if (now - room.updatedAt >= ROOM_TTL) rooms.delete(code);
  }
  for (const [scope, limit] of limits) {
    if (limit.expires <= now) limits.delete(scope);
  }
}

export function createStoredRoom(room: RoomState): boolean {
  if (rooms.has(room.code)) return false;
  if (rooms.size >= 500) throw new Error("Все столы заняты. Попробуй позже");
  rooms.set(room.code, room);
  return true;
}

export function loadRoom(code: string): RoomState | null {
  return rooms.get(code) ?? null;
}

export function mutateRoom(code: string, mutate: (room: RoomState) => RoomState | null | void): RoomState {
  const current = loadRoom(code);
  if (!current) throw new Error("Стол не найден");
  const draft = structuredClone(current);
  const result = mutate(draft);
  if (result === null) return current;
  const next = result ?? draft;
  next.version = current.version + 1;
  next.updatedAt = Date.now();
  rooms.set(code, next);
  return next;
}

export function rateLimit(scope: string, limit: number, windowSeconds: number): void {
  const now = Date.now();
  const current = limits.get(scope);
  const next = !current || current.expires <= now
    ? { count: 1, expires: now + windowSeconds * 1000 }
    : { count: current.count + 1, expires: current.expires };
  limits.set(scope, next);
  if (next.count > limit) throw new Error("Слишком много запросов. Попробуй чуть позже");
}

export function touchRoom(room: RoomState): void {
  room.updatedAt = Date.now();
}
