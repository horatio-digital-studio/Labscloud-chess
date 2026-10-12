"""In-process wiring of LobbyCore, GameRoomCores and the web handler."""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from app.config import Config
from app.game_service import GameService
from app.lobby_core import LobbyCore
from app.lobby_service import LobbyService
from app.notify import Email
from app.room import GameRoomCore
from app.storage import SqliteStorage
from chess_core.engine import Colour


class LocalSocket:
    """A connected client as the room sees it. `outbox` collects sent messages."""

    def __init__(
        self, player: str, colour: Colour, on_send: Callable[[str], None] | None = None
    ) -> None:
        self._player = player
        self._colour: Colour = colour
        self.outbox: list[str] = []
        self.closed = False
        self._on_send = on_send

    @property
    def player(self) -> str:
        return self._player

    @property
    def colour(self) -> Colour:
        return self._colour

    def send(self, text: str) -> None:
        if self.closed:
            raise RuntimeError("socket closed")
        self.outbox.append(text)
        if self._on_send is not None:
            self._on_send(text)


class Hub:
    def __init__(
        self,
        config: Config,
        data_dir: str | None = None,
        clock: Callable[[], int] | None = None,
        chooser: Callable[[list[str]], str] | None = None,
    ) -> None:
        self.config = config
        self.data_dir = Path(data_dir) if data_dir else None
        if self.data_dir:
            self.data_dir.mkdir(parents=True, exist_ok=True)
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.chooser = chooser or secrets.choice
        self.sent_emails: list[Email] = []
        self.sockets: dict[str, list[LocalSocket]] = {}
        self._rooms: dict[str, GameRoomCore] = {}
        self._storages: dict[str, SqliteStorage] = {}
        self.lobby = LobbyCore(
            LobbyService(self._storage("lobby"), config.players), _LobbyPorts(self), config
        )

    def _storage(self, name: str) -> SqliteStorage:
        storage = self._storages.get(name)
        if storage is None:
            path = (
                ":memory:" if self.data_dir is None else os.fspath(self.data_dir / f"{name}.sqlite")
            )
            storage = SqliteStorage(path)
            self._storages[name] = storage
        return storage

    def room(self, game_id: str) -> GameRoomCore:
        core = self._rooms.get(game_id)
        if core is None:
            core = GameRoomCore(
                GameService(self._storage(f"game-{game_id}")),
                _RoomPorts(self, game_id),
                self.config,
            )
            self._rooms[game_id] = core
        return core

    def forget_memory(self) -> None:
        """Rebuild every core from storage, like a Durable Object eviction."""
        self._rooms.clear()
        self.lobby = LobbyCore(
            LobbyService(self._storage("lobby"), self.config.players),
            _LobbyPorts(self),
            self.config,
        )

    # ------------------------------------------------------------ connections
    async def connect(
        self, game_id: str, player: str, on_send: Callable[[str], None] | None = None
    ) -> LocalSocket | None:
        room = self.room(game_id)
        colour = room.colour_for(player)
        if colour is None:
            return None
        sock = LocalSocket(player, colour, on_send)
        self.sockets.setdefault(game_id, []).append(sock)
        await room.on_open(sock)
        return sock

    async def disconnect(self, game_id: str, sock: LocalSocket) -> None:
        sock.closed = True
        await self.room(game_id).on_close(sock)
        items = self.sockets.get(game_id, [])
        if sock in items:
            items.remove(sock)

    async def message(self, game_id: str, sock: LocalSocket, raw: Any) -> None:
        await self.room(game_id).on_message(sock, raw)


class _RoomPorts:
    def __init__(self, hub: Hub, game_id: str) -> None:
        self.hub = hub
        self.game_id = game_id

    def sockets(self) -> Sequence[LocalSocket]:
        return [s for s in self.hub.sockets.get(self.game_id, []) if not s.closed]

    async def lobby(self, method: str, args: dict[str, Any]) -> tuple[int, Any]:
        return await self.hub.lobby.rpc(method, args)

    def now_ms(self) -> int:
        return self.hub.clock()


class _LobbyPorts:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub

    async def room(self, game_id: str, method: str, args: dict[str, Any]) -> tuple[int, Any]:
        return await self.hub.room(game_id).rpc(method, args)

    async def send_email(self, email: Email) -> None:
        self.hub.sent_emails.append(email)

    def now_ms(self) -> int:
        return self.hub.clock()

    def choose(self, options: list[str]) -> str:
        return self.hub.chooser(options)


class WebPorts:
    """app.web.WebPorts for the dev server and tests."""

    def __init__(self, hub: Hub, public_dir: Path) -> None:
        self.hub = hub
        self.public_dir = public_dir

    async def lobby(self, method: str, args: dict[str, Any]) -> tuple[int, Any]:
        return await self.hub.lobby.rpc(method, args)

    async def room(self, game_id: str, method: str, args: dict[str, Any]) -> tuple[int, Any]:
        return await self.hub.room(game_id).rpc(method, args)

    async def asset_text(self, path: str) -> str | None:
        # Mirrors Workers Static Assets' default html_handling: "/game" serves game.html.
        if path != "/" and "." not in path.rsplit("/", 1)[-1]:
            path = f"{path}.html"
        target = (self.public_dir / path.lstrip("/")).resolve()
        if self.public_dir.resolve() not in target.parents or not target.is_file():
            return None
        return target.read_text(encoding="utf-8")

    def now_ms(self) -> int:
        return self.hub.clock()
