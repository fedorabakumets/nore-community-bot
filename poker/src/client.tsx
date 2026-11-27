import { useState } from "react";
import { createRoot } from "react-dom/client";
import { Lobby } from "./components/Lobby";
import { TableRoom } from "./components/TableRoom";
import type { RoomSnapshot } from "./lib/poker/view";
import "./globals.css";

type PokerResponse = { snapshot?: RoomSnapshot | null; joinable?: boolean; url?: string };
export type PokerApi = (path: string, body?: object, signal?: AbortSignal) => Promise<PokerResponse>;
export interface PokerOptions {
  api: PokerApi;
  code?: string;
  playerId: string;
  exit: () => void;
  share: (url: string) => void;
}

function Poker({ api, code = "", playerId, exit, share }: PokerOptions) {
  const storageKey = "nora-poker-table-" + playerId;
  const [room, setRoom] = useState(code);
  const [saved, setSaved] = useState(() => {
    try { return sessionStorage.getItem(storageKey) ?? ""; } catch { return ""; }
  });

  function remember(value: string) {
    setSaved(value);
    try {
      if (value) sessionStorage.setItem(storageKey, value);
      else sessionStorage.removeItem(storageKey);
    } catch { /* session storage is optional */ }
  }

  return room
    ? <TableRoom key={room} code={room} api={api} share={share} remember={remember} lobby={() => setRoom("")} />
    : <Lobby api={api} enter={setRoom} saved={saved} exit={exit} />;
}

export function mount(host: HTMLElement, options: PokerOptions) {
  const shadow = host.attachShadow({ mode: "open" });
  const stylesheet = document.createElement("link");
  stylesheet.rel = "stylesheet";
  stylesheet.href = "/poker-assets/table.css?v=booth-1";
  const container = document.createElement("div");
  container.hidden = true;
  const root = createRoot(container);
  stylesheet.onload = () => {
    container.hidden = false;
    root.render(<Poker {...options} />);
  };
  stylesheet.onerror = () => {
    container.hidden = false;
    container.textContent = "Покер не загрузился. Открой «Игры» и попробуй ещё раз.";
  };
  shadow.append(stylesheet, container);
  return () => {
    stylesheet.onload = stylesheet.onerror = null;
    root.unmount();
    shadow.replaceChildren();
  };
}
