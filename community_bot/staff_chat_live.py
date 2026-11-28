"""Authenticated low-latency WebSocket transport for the staff community mirror.

The first WebSocket frame carries signed Telegram initData over TLS; no secrets
are put in the URL or exposed to other clients. The HTTP history remains the
authoritative source; socket events invalidate it immediately.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from aiohttp import WSMsgType, web

from community_bot.access import private_allowed
from community_bot.miniapp import validate_init_data
from community_bot.staff_chat import staff_allowed

logger = logging.getLogger(__name__)
MAX_CLIENTS = 48
MAX_SESSIONS_PER_USER = 3
MAX_QUEUE = 48
AUTH_TIMEOUT = 8
ROLE_CHECK_INTERVAL = 30


@dataclass(eq=False)
class Client:
    socket: web.WebSocketResponse
    uid: int
    name: str
    queue: asyncio.Queue[dict[str, Any]]
    sender: asyncio.Task | None = None
    last_typing: float = 0


class StaffChatHub:
    """Local fanout for the current NORA process, with backpressure and cleanup."""

    def __init__(self):
        self.clients: dict[web.WebSocketResponse, Client] = {}
        self.closed = False

    @property
    def online(self) -> int:
        return len({client.uid for client in self.clients.values()})

    async def _sender(self, client: Client) -> None:
        try:
            while not client.socket.closed:
                payload = await client.queue.get()
                await asyncio.wait_for(client.socket.send_json(payload), timeout=4)
        except (asyncio.CancelledError, ConnectionError, RuntimeError, TimeoutError, OSError):
            pass
        except Exception:
            logger.exception("Staff chat WebSocket delivery failed")
        finally:
            if not client.socket.closed:
                await client.socket.close()

    def _queue(self, client: Client, payload: dict) -> None:
        if client.socket.closed:
            return
        if client.queue.full():
            # Never block Telegram polling on a slow mobile connection.
            # The latest refresh event still lets the client reconcile state.
            while not client.queue.empty():
                try:
                    client.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            payload = {"type": "change", "operation": "sync", "ids": []}
        client.queue.put_nowait(payload)

    def broadcast(self, payload: dict, *, exclude_uid: int | None = None) -> None:
        if self.closed:
            return
        for client in tuple(self.clients.values()):
            if client.uid != exclude_uid:
                self._queue(client, payload)

    def publish(self, operation: str, ids: list[int]) -> None:
        """Called only after the corresponding SQLite write commits."""
        if operation not in {"message", "edit", "delete", "reaction"} or not ids:
            return
        self.broadcast({"type": "change", "operation": operation, "ids": ids[:100]})

    def join(self, socket: web.WebSocketResponse, uid: int, name: str) -> Client:
        if self.closed or len(self.clients) >= MAX_CLIENTS:
            raise ValueError("Слишком много подключений")
        if sum(1 for client in self.clients.values() if client.uid == uid) >= MAX_SESSIONS_PER_USER:
            raise ValueError("Этот чат открыт на слишком многих устройствах")
        client = Client(socket, uid, name, asyncio.Queue(maxsize=MAX_QUEUE))
        self.clients[socket] = client
        client.sender = asyncio.create_task(self._sender(client))
        self.broadcast({"type": "presence", "online": self.online})
        return client

    async def leave(self, socket: web.WebSocketResponse) -> None:
        client = self.clients.pop(socket, None)
        if client is None:
            return
        if client.sender:
            client.sender.cancel()
            try:
                await client.sender
            except asyncio.CancelledError:
                pass
        self.broadcast({"type": "presence", "online": self.online})

    def typing(self, client: Client) -> None:
        now = time.monotonic()
        if now - client.last_typing < 2.0:
            return
        client.last_typing = now
        self.broadcast(
            {"type": "typing", "user_id": client.uid, "name": client.name[:48]},
            exclude_uid=client.uid,
        )

    async def shutdown(self) -> None:
        self.closed = True
        for socket in tuple(self.clients):
            await self.leave(socket)
            if not socket.closed:
                await socket.close(code=1001, message=b"Service restart")


def emit(db, operation: str, ids: list[int]) -> None:
    hub = getattr(db, "_staff_chat_hub", None)
    if hub is not None:
        hub.publish(operation, ids)


async def _authorized(request: web.Request, raw: Any) -> dict | None:
    if not isinstance(raw, str):
        return None
    try:
        signed_user = validate_init_data(raw, request.app["settings"].bot_token)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    db, settings, uid = request.app["db"], request.app["settings"], signed_user["id"]
    ban = await db.ban_reset_state(uid)
    if not await private_allowed(db, settings, uid, ban=ban):
        return None
    registered = await db.get_user(uid)
    if not registered or not str(registered.get("city") or "").strip():
        return None
    if not await staff_allowed(db, settings, uid):
        return None
    return signed_user


async def connect(request: web.Request) -> web.StreamResponse:
    """Never publish chat data before validating the first signed frame."""
    hub: StaffChatHub = request.app["staff_chat_hub"]
    gate = request.app.get("staff_chat_handshake_gate")
    if hub.closed or len(hub.clients) >= MAX_CLIENTS or (gate and gate.locked()):
        return web.json_response({"error": "Чат перегружен"}, status=503)
    # Bound outstanding unauthenticated handshakes before accepting connections.
    if gate is not None:
        await gate.acquire()
    gate_held = gate is not None
    # WebSocket auth is *not* put in the URL: it would leak into access logs.
    socket = web.WebSocketResponse(heartbeat=25, max_msg_size=12288)
    client = None
    try:
        await socket.prepare(request)
        try:
            initial = await asyncio.wait_for(socket.receive(), timeout=AUTH_TIMEOUT)
            if initial.type != WSMsgType.TEXT:
                return socket
            login = json.loads(initial.data)
            if not isinstance(login, dict) or login.get("type") != "auth":
                return socket
            actor = await _authorized(request, login.get("init_data"))
            if actor is None:
                await socket.send_json({"type": "error", "reason": "access"})
                return socket
            uid = actor["id"]
            registered = await request.app["db"].get_user(uid)
            name = str(
                registered.get("profile_name") or registered.get("telegram_name")
                or actor.get("first_name") or "Участник"
            )[:48]
            try:
                client = hub.join(socket, uid, name)
            except ValueError:
                await socket.send_json({"type": "error", "reason": "limit"})
                return socket
            await socket.send_json({"type": "ready", "online": hub.online})
            if gate_held:
                gate.release()
                gate_held = False
        except (asyncio.TimeoutError, ValueError, TypeError, json.JSONDecodeError):
            await socket.send_json({"type": "error", "reason": "auth"})
            return socket

        last_check = time.monotonic()
        last_ping = 0.0
        while not socket.closed:
            try:
                msg = await socket.receive(timeout=ROLE_CHECK_INTERVAL)
            except asyncio.TimeoutError:
                # Even idle clients lose access after role/ban changes.
                actor = await _authorized(request, login["init_data"])
                if actor is None:
                    await socket.send_json({"type": "error", "reason": "access"})
                    break
                last_check = time.monotonic()
                continue
            if msg.type != WSMsgType.TEXT:
                if msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSED):
                    break
                continue
            if time.monotonic() - last_check >= ROLE_CHECK_INTERVAL:
                actor = await _authorized(request, login["init_data"])
                if actor is None:
                    await socket.send_json({"type": "error", "reason": "access"})
                    break
                last_check = time.monotonic()
            try:
                payload = json.loads(msg.data)
            except (ValueError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("type") == "ping":
                now = time.monotonic()
                if now-last_ping >= 5:
                    last_ping=now
                    hub._queue(client, {"type": "pong"})
            elif payload.get("type") == "typing":
                hub.typing(client)
    finally:
        if gate_held:
            gate.release()
        if client:
            await hub.leave(socket)
        if not socket.closed:
            await socket.close()
    return socket
