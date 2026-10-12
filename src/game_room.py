"""GameRoom Durable Object: one per game, owns the game and its WebSockets (ADR-0002)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

from js import WebSocketPair
from workers import DurableObject, Response

from app.game_service import GameService
from app.log import log
from app.room import GameRoomCore
from glue import (
    DOSocket,
    DOStorage,
    as_request,
    call_rpc,
    json_body,
    list_sockets,
    load_config,
    now_ms,
    read_rpc,
)


class _Ports:
    def __init__(self, room: GameRoom) -> None:
        self._room = room

    def sockets(self) -> list[DOSocket]:
        return list_sockets(self._room.ctx)

    async def lobby(self, method: str, args: dict[str, Any]) -> tuple[int, Any]:
        stub = self._room.env.LOBBY.getByName("lobby")
        return await call_rpc(stub, "lobby.internal", method, args)

    def now_ms(self) -> int:
        return now_ms()


class GameRoom(DurableObject):
    def __init__(self, ctx: Any, env: Any) -> None:
        super().__init__(ctx, env)
        self.core = GameRoomCore(GameService(DOStorage(ctx)), _Ports(self), load_config(env))

    async def fetch(self, request: Any) -> Response:
        req = as_request(request)
        url = urlsplit(req.url)
        if url.path == "/connect":
            return await self._connect(parse_qs(url.query).get("player", [""])[0])
        if url.path == "/rpc":
            try:
                method, args = await read_rpc(req)
            except (ValueError, TypeError):
                return json_body(400, {"code": "BAD_REQUEST"})
            status, body = await self.core.rpc(method, args)
            return json_body(status, body)
        return json_body(404, {"code": "NOT_FOUND"})

    async def _connect(self, player: str) -> Response:
        # The Worker has already verified identity, origin and the Upgrade header.
        colour = self.core.colour_for(player)
        if colour is None:
            return json_body(403, {"code": "NOT_A_PLAYER"})
        client, server = WebSocketPair.new().object_values()
        ctx: Any = self.ctx  # the SDK passes non-storage attributes straight to JS
        ctx.acceptWebSocket(server)
        server.serializeAttachment(json.dumps({"player": player, "colour": colour}))
        await self.core.on_open(DOSocket(server, player, colour))
        return Response(None, status=101, web_socket=client)

    async def webSocketMessage(self, ws: Any, message: Any) -> None:
        sock = DOSocket.from_ws(ws)
        if sock is None:
            ws.close(1008, "unknown connection")
            return
        await self.core.on_message(sock, message)

    async def webSocketClose(self, ws: Any, code: int, reason: str, was_clean: bool) -> None:
        sock = DOSocket.from_ws(ws)
        if sock is not None:
            await self.core.on_close(sock)
        try:
            ws.close(code, reason)
        except Exception as exc:  # already closed, or a reserved close code
            log("ws_close_ignored", error=type(exc).__name__)

    async def webSocketError(self, ws: Any, error: Any) -> None:
        sock = DOSocket.from_ws(ws)
        if sock is not None:
            await self.core.on_close(sock)
