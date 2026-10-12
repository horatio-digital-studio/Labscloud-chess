"""GameRoom behaviour shared by the Durable Object and the dev server.

The runtime adapter supplies the ports (sockets, a Lobby caller, a clock); this class
decides what to send to whom.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from app.config import Config
from app.game_service import GameNotFound, GameService
from app.log import log
from app.notify import move_label, result_line
from chess_core.engine import Colour
from chess_core.pgn import pgn_date
from chess_core.protocol import (
    ClientMessage,
    ProtocolError,
    dumps,
    error_message,
    parse_client_message,
    pong_message,
    presence_message,
    rematch_ready_message,
)


class Socket(Protocol):
    """One connected WebSocket. Equality must mean "the same underlying connection"."""

    def send(self, text: str) -> None: ...

    @property
    def player(self) -> str: ...

    @property
    def colour(self) -> Colour: ...


class RoomPorts(Protocol):
    def sockets(self) -> Sequence[Socket]: ...

    async def lobby(self, method: str, args: dict[str, Any]) -> tuple[int, Any]: ...

    def now_ms(self) -> int: ...


class GameRoomCore:
    def __init__(self, service: GameService, ports: RoomPorts, config: Config) -> None:
        self.service = service
        self.ports = ports
        self.config = config

    # ------------------------------------------------------------------ helpers
    def online(self, exclude: Socket | None = None) -> dict[str, bool]:
        colours = {s.colour for s in self.ports.sockets() if exclude is None or s != exclude}
        return {"white": "white" in colours, "black": "black" in colours}

    def _log(self, event: str, **fields: Any) -> None:
        """Structured log with the game's id and ply (REQ-NFR-06); never fails."""
        try:
            row = self.service.row()
            fields = {"game_id": row.id, "ply": row.ply, **fields}
        except Exception:  # noqa: S110 - logging must not raise
            pass
        log(event, **fields)

    def _send(self, sock: Socket, message: dict[str, Any]) -> None:
        try:
            sock.send(dumps(message))
        except Exception as exc:  # a socket closing mid-send must not break the others
            self._log("ws_send_failed", player=sock.player, error=type(exc).__name__)

    def _broadcast_states(self, exclude: Socket | None = None) -> None:
        states = self.service.states(self.online(exclude))
        for sock in self.ports.sockets():
            if exclude is None or sock != exclude:
                self._send(sock, states[sock.colour])

    def _broadcast(self, message: dict[str, Any], exclude: Socket | None = None) -> None:
        for sock in self.ports.sockets():
            if exclude is None or sock != exclude:
                self._send(sock, message)

    def colour_for(self, player: str) -> Colour | None:
        try:
            return self.service.row().colour_of(player)
        except GameNotFound:
            return None

    async def _lobby(self, method: str, args: dict[str, Any]) -> Any:
        try:
            status, body = await self.ports.lobby(method, args)
        except Exception as exc:
            self._log("lobby_call_failed", method=method, error=type(exc).__name__)
            return None
        if status >= 400:
            self._log("lobby_call_failed", method=method, status=status)
            return None
        return body

    async def _refresh_names(self) -> None:
        """Display names live in the Lobby (REQ-GAME-09); copy the current ones in."""
        names = await self._lobby("names", {})
        if isinstance(names, dict):
            self.service.set_names({str(k): str(v) for k, v in names.items()})

    # ---------------------------------------------------------------- rpc (HTTP)
    async def rpc(self, method: str, args: dict[str, Any]) -> tuple[int, Any]:
        now = self.ports.now_ms()
        try:
            if method == "init":
                self.service.init(
                    str(args["game_id"]),
                    str(args["white"]),
                    str(args["black"]),
                    dict(args["names"]),
                    now,
                )
                return 200, {"ok": True}
            if method == "exists":
                if not self.service.exists():
                    return 200, {"exists": False}
                row = self.service.row()
                return 200, {"exists": True, "white": row.white, "black": row.black}
            if method == "snapshot":
                colour = self.colour_for(str(args["player"]))
                if colour is None:
                    return (
                        (404, {"code": "GAME_NOT_FOUND"})
                        if not self.service.exists()
                        else (
                            403,
                            {"code": "NOT_A_PLAYER"},
                        )
                    )
                await self._refresh_names()
                return 200, self.service.states(self.online())[colour]
            if method == "pgn":
                row = self.service.row()
                await self._refresh_names()
                return 200, {
                    "pgn": self.service.pgn(self.config.site_host),
                    "date": pgn_date(row.created_at).replace(".", "-"),
                }
            if method == "diag_move":
                if self.config.app_env == "production":
                    return 404, {"code": "NOT_FOUND"}
                outcome = self.service.diag_move(str(args["uci"]), now)
                if outcome.changed:
                    self._broadcast_states()
                return 200, {
                    "ok": outcome.error is None,
                    "error": outcome.error,
                    "ply": self.service.row().ply,
                }
        except GameNotFound:
            return 404, {"code": "GAME_NOT_FOUND"}
        except (KeyError, TypeError, ValueError):
            return 400, {"code": "BAD_REQUEST"}
        return 404, {"code": "NOT_FOUND"}

    # --------------------------------------------------------------- websockets
    async def on_open(self, sock: Socket) -> None:
        self._broadcast(presence_message(self.online()), exclude=sock)

    async def on_close(self, sock: Socket) -> None:
        self._broadcast(presence_message(self.online(exclude=sock)), exclude=sock)

    async def on_message(self, sock: Socket, raw: Any) -> None:
        if not isinstance(raw, str | bytes | bytearray):
            self._send(sock, error_message("BAD_MESSAGE", None))
            return
        try:
            msg = parse_client_message(bytes(raw) if isinstance(raw, bytearray) else raw)
        except ProtocolError:
            self._send(sock, error_message("BAD_MESSAGE", None))
            return
        try:
            await self._dispatch(sock, msg)
        except GameNotFound:
            self._send(sock, error_message("GAME_NOT_FOUND", msg.type))
        except Exception as exc:
            self._log(
                "ws_handler_error", player=sock.player, type=msg.type, error=type(exc).__name__
            )
            self._send(sock, error_message("INTERNAL", msg.type))

    async def _dispatch(self, sock: Socket, msg: ClientMessage) -> None:
        now = self.ports.now_ms()
        if msg.type == "ping":
            self._send(sock, pong_message(now))
            return
        if msg.type == "hello":
            await self._refresh_names()
            self._send(sock, self.service.states(self.online())[sock.colour])
            # Re-sync the Lobby's index too, in case an earlier summary call failed
            # (e.g. the move that ended the game); stale or duplicate updates are ignored.
            await self._lobby("summary", {"summary": self.service.summary()})
            return

        before = self.service.row()
        outcome = self.service.handle(sock.colour, msg, now)
        if outcome.error:
            self._send(sock, error_message(outcome.error, msg.type))
            return
        if outcome.rematch_ready:
            self._send(sock, rematch_ready_message(outcome.rematch_ready))
            return
        if outcome.needs_rematch:
            created = await self._lobby("create_rematch", {"old_game_id": before.id})
            if isinstance(created, dict) and isinstance(created.get("game_id"), str):
                self.service.set_rematch_game(created["game_id"], self.ports.now_ms())
                self._broadcast(rematch_ready_message(created["game_id"]))
        if outcome.changed:
            self._broadcast_states()
            await self._lobby("summary", {"summary": self.service.summary()})
        if outcome.moved is not None and self.config.email_enabled:
            await self._maybe_nudge(sock, outcome.moved.san)
        if outcome.ended and self.config.email_enabled:
            await self._game_over_email()

    async def _maybe_nudge(self, sock: Socket, san: str) -> None:
        row = self.service.row()
        if row.terminal:
            return
        opponent_colour: Colour = "black" if sock.colour == "white" else "white"
        if self.online()[opponent_colour]:
            return
        await self._lobby(
            "nudge",
            {
                "to_player": row.player_of(opponent_colour),
                "from_player": sock.player,
                "game_id": row.id,
                "last_move": move_label(row.ply, san),
            },
        )

    async def _game_over_email(self) -> None:
        row = self.service.row()
        names = self.service.names(row)
        line = result_line(row.status, row.result, names[row.white], names[row.black])
        await self._lobby(
            "game_over",
            {"game_id": row.id, "line": line, "pgn": self.service.pgn(self.config.site_host)},
        )
