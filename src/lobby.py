"""Lobby Durable Object: the single owner of names, preferences and the game index."""

from __future__ import annotations

import secrets
from typing import Any

from js import Object
from pyodide.ffi import to_js
from workers import DurableObject, Response

from app.lobby_core import LobbyCore
from app.lobby_service import LobbyService
from app.log import log
from app.notify import Email
from glue import DOStorage, as_request, call_rpc, json_body, load_config, now_ms, read_rpc


class _Ports:
    def __init__(self, lobby: Lobby) -> None:
        self._lobby = lobby

    async def room(self, game_id: str, method: str, args: dict[str, Any]) -> tuple[int, Any]:
        stub = self._lobby.env.GAME_ROOM.getByName(game_id)
        return await call_rpc(stub, "game-room.internal", method, args)

    async def send_email(self, email: Email) -> None:
        try:
            binding = self._lobby.env.EMAIL
        except AttributeError:
            binding = None
        if binding is None:
            log("email_skipped", reason="no EMAIL binding")
            return
        message = {
            "to": email.to,
            "from": {"email": self._lobby.config.mail_from, "name": "labscloud chess"},
            "subject": email.subject,
            "text": email.text,
            "html": email.html,
        }
        await binding.send(to_js(message, dict_converter=Object.fromEntries))

    def now_ms(self) -> int:
        return now_ms()

    def choose(self, options: list[str]) -> str:
        return secrets.choice(options)


class Lobby(DurableObject):
    def __init__(self, ctx: Any, env: Any) -> None:
        super().__init__(ctx, env)
        self.config = load_config(env)
        self.core = LobbyCore(
            LobbyService(DOStorage(ctx), self.config.players), _Ports(self), self.config
        )

    async def fetch(self, request: Any) -> Response:
        req = as_request(request)
        try:
            method, args = await read_rpc(req)
        except (ValueError, TypeError):
            return json_body(400, {"code": "BAD_REQUEST"})
        status, body = await self.core.rpc(method, args)
        return json_body(status, body)
