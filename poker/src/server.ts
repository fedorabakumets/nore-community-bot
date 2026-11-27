import { createHmac, randomBytes } from "node:crypto";
import { createInterface } from "node:readline";
import { stdin, stdout } from "node:process";
import { advanceRoom, authenticate, commandRoom, createRoom, joinRoom, snapshot } from "./lib/server/rooms";
import type { RoomCommand } from "./lib/server/rooms";
import { loadRoom, rateLimit, sweep, touchRoom } from "./lib/server/store";

const sessionKey = randomBytes(32);
const clock = setInterval(sweep, 60_000);

interface Request {
  action: "create" | "join" | "state" | "command";
  uid: string;
  name: string;
  code?: string;
  body?: { commandId: string; expectedVersion: number; command: RoomCommand };
}

async function dispatch({ action, uid, name, code, body }: Request) {
  const token = createHmac("sha256", sessionKey).update(uid).digest("base64url");
  const avatar = Number(BigInt(uid) % 12n);
  if (action === "create") {
    rateLimit(`create:${uid}`, 6, 60);
    const { room, playerId } = await createRoom(name, avatar, token);
    return { snapshot: snapshot(room, playerId) };
  }
  if (!code || !/^[A-HJ-NP-Z2-9]{8}$/.test(code)) throw new Error("Проверь код стола");
  const initial = loadRoom(code);
  if (!initial) return { status: 404, error: "Стол закрыт или код неверный" };
  let member = await authenticate(code, token);
  if (action === "join" && !member) {
    rateLimit(`join:${uid}`, 10, 60);
    const { room, playerId } = await joinRoom(code, name, avatar, token);
    return { snapshot: snapshot(room, playerId) };
  }
  if (!member) return action === "state"
    ? { snapshot: null, joinable: initial.players.length < 5 }
    : { status: 403, error: "Сначала займи место за столом" };
  touchRoom(member.room);
  const room = await advanceRoom(code, member.room.version);
  if (action === "command") {
    if (!body?.command || !["start", "poker", "addBot", "removeBot", "sitOut", "rebuy", "timeBank",
      "pause", "transferHost", "kick", "chat", "reaction"].includes(body.command.type)) {
      throw new Error("Неизвестное действие");
    }
    const next = await commandRoom(code, token, body.commandId, body.expectedVersion, body.command);
    return { snapshot: snapshot(next, member.player.id) };
  }
  return { snapshot: snapshot(room, member.player.id) };
}

try {
  for await (const line of createInterface({ input: stdin, crlfDelay: Infinity })) {
    try {
      const response = await dispatch(JSON.parse(line));
      stdout.write(JSON.stringify(response) + "\n");
    } catch (error) {
      const message = error instanceof Error ? error.message : "";
      const readable = /[а-я]/i.test(message) ? message : {
        "This table is full": "Все места за столом заняты",
        "The table changed; try again": "Ситуация за столом изменилась. Повтори ход",
        "Only the host can do that": "Это может сделать только хозяин стола",
        "Wait until the hand is over": "Дождись конца раздачи",
      }[message] ?? "Действие сейчас недоступно";
      stdout.write(JSON.stringify({ status: 400, error: readable }) + "\n");
    }
  }
} finally {
  clearInterval(clock);
}
