"""Lobby behaviour shared by the Durable Object and the dev server."""

from __future__ import annotations

from typing import Any, Protocol

from app.config import Config
from app.lobby_service import LobbyError, LobbyService, NewGame
from app.log import log
from app.notify import Email, game_over_email, invite_email, your_move_email


class LobbyPorts(Protocol):
    async def room(self, game_id: str, method: str, args: dict[str, Any]) -> tuple[int, Any]: ...

    async def send_email(self, email: Email) -> None: ...

    def now_ms(self) -> int: ...

    def choose(self, options: list[str]) -> str: ...


class LobbyCore:
    def __init__(self, service: LobbyService, ports: LobbyPorts, config: Config) -> None:
        self.service = service
        self.ports = ports
        self.config = config

    def game_url(self, game_id: str) -> str:
        return f"{self.config.public_url}/game/{game_id}"

    async def _email(self, email: Email) -> None:
        if not self.config.email_enabled:
            return
        try:
            await self.ports.send_email(email)
        except Exception as exc:  # REQ-NOTIFY-04: never affects game state
            log("email_failed", error=type(exc).__name__)

    async def _start(self, game: NewGame) -> dict[str, Any]:
        await self._init_room(game)
        return self.service.record_game(game, self.ports.now_ms())

    async def _rematch(self, old_game_id: str) -> str:
        """Exactly one rematch per game, even if two requests overlap (REQ-ACT-08).

        The index row is reserved *before* the first await, so an overlapping request
        finds it and re-runs the (idempotent) room init instead of creating a second game.
        """
        plan = self.service.plan_rematch(old_game_id)
        if isinstance(plan, dict):
            game = NewGame(str(plan["id"]), str(plan["white"]), str(plan["black"]), old_game_id)
            await self._init_room(game)
            return game.id
        self.service.record_game(plan, self.ports.now_ms())
        try:
            await self._init_room(plan)
        except Exception:
            self.service.delete_game(plan.id)
            raise
        return plan.id

    async def _init_room(self, game: NewGame) -> None:
        status, _ = await self.ports.room(
            game.id,
            "init",
            {
                "game_id": game.id,
                "white": game.white,
                "black": game.black,
                "names": self.service.names(),
            },
        )
        if status != 200:
            raise LobbyError("INTERNAL", 500, "game room did not initialise")

    async def rpc(self, method: str, args: dict[str, Any]) -> tuple[int, Any]:
        try:
            return await self._rpc(method, args)
        except LobbyError as exc:
            return exc.status, {"code": exc.code}
        except (KeyError, TypeError, ValueError):
            return 400, {"code": "BAD_REQUEST"}

    async def _rpc(self, method: str, args: dict[str, Any]) -> tuple[int, Any]:
        service = self.service
        if method == "names":
            return 200, service.names()
        if method == "me":
            return 200, service.me(str(args["player"]))
        if method == "update_me":
            return 200, service.update_me(str(args["player"]), args.get("body"))
        if method == "list_games":
            status = args.get("status")
            return 200, {
                "games": service.list_games(str(args["player"]), status if status else None)
            }
        if method == "stats":
            return 200, service.stats()
        if method == "create_game":
            player = str(args["player"])
            plan = service.plan_game(player, str(args.get("colour")), self.ports.choose)
            row = await self._start(plan)
            summary = service.game_summary_for(row, player)
            await self._invite(plan, player)
            return 201, {"game": summary, "url": f"/game/{plan.id}"}
        if method == "create_rematch":
            return 200, {"game_id": await self._rematch(str(args["old_game_id"]))}
        if method == "summary":
            service.upsert_summary(dict(args["summary"]))
            return 200, {"ok": True}
        if method == "nudge":
            await self._nudge(args)
            return 200, {"ok": True}
        if method == "game_over":
            await self._game_over(args)
            return 200, {"ok": True}
        return 404, {"code": "NOT_FOUND"}

    async def _invite(self, plan: NewGame, creator: str) -> None:
        opponent = self.config.players.opponent(creator)
        if not self.config.email_enabled or not self.service.invites_enabled(opponent.key):
            return
        names = self.service.names()
        colour = "white" if plan.white == opponent.key else "black"
        await self._email(
            invite_email(
                to=opponent.email,
                to_name=names[opponent.key],
                from_name=names[creator],
                your_colour=colour,
                game_url=self.game_url(plan.id),
            )
        )

    async def _nudge(self, args: dict[str, Any]) -> None:
        to_key, from_key = str(args["to_player"]), str(args["from_player"])
        recipient = self.config.players.by_key(to_key)
        if recipient is None or not self.config.email_enabled:
            return
        if not self.service.nudge_allowed(to_key, self.ports.now_ms()):
            return
        names = self.service.names()
        prefs = self.service.me(to_key)["notify"]
        await self._email(
            your_move_email(
                to=recipient.email,
                to_name=names[to_key],
                from_name=names.get(from_key, from_key),
                last_move_san=str(args["last_move"]),
                game_url=self.game_url(str(args["game_id"])),
                cooldown_minutes=int(prefs["cooldown_minutes"]),
            )
        )

    async def _game_over(self, args: dict[str, Any]) -> None:
        if not self.config.email_enabled:
            return
        names = self.service.names()
        for player in self.config.players.players:
            await self._email(
                game_over_email(
                    to=player.email,
                    to_name=names[player.key],
                    line=str(args["line"]),
                    game_url=self.game_url(str(args["game_id"])),
                    pgn=str(args["pgn"]),
                )
            )
