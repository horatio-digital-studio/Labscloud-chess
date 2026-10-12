"""Worker entry point: request routing and the WebSocket hand-off (ADR-0006).

Static assets (CSS, JS, fonts, the lobby page) are served by Cloudflare without
running this code; only the run_worker_first paths in wrangler.jsonc reach it.
"""

from __future__ import annotations

import json
from typing import Any

from js import Request as JsRequest
from workers import Response, WorkerEntrypoint, fetch

from app.auth import KeyCache
from app.config import ConfigError
from app.log import log
from app.web import HttpRequest, Upgrade, handle
from game_room import GameRoom
from glue import as_request, call_rpc, env_get, json_body, load_config, now_ms, to_http_request
from lobby import Lobby

__all__ = ["Default", "GameRoom", "Lobby"]

# Created lazily on the first request (never at import time: the module is snapshotted
# at deploy, so no network or clock use may happen here).
_KEY_CACHES: dict[str, KeyCache] = {}


def _key_cache(team_domain: str) -> KeyCache:
    cache = _KEY_CACHES.get(team_domain)
    if cache is None:
        certs_url = f"{team_domain}/cdn-cgi/access/certs"

        async def fetch_jwks() -> Any:
            response = await fetch(certs_url)
            if int(response.status) != 200:
                raise RuntimeError(f"certs fetch failed: {response.status}")
            return json.loads(await response.text())

        cache = KeyCache(fetch_jwks=fetch_jwks)
        _KEY_CACHES[team_domain] = cache
    return cache


class _Ports:
    def __init__(self, env: Any) -> None:
        self._env = env

    async def lobby(self, method: str, args: dict[str, Any]) -> tuple[int, Any]:
        return await call_rpc(self._env.LOBBY.getByName("lobby"), "lobby.internal", method, args)

    async def room(self, game_id: str, method: str, args: dict[str, Any]) -> tuple[int, Any]:
        return await call_rpc(
            self._env.GAME_ROOM.getByName(game_id), "game-room.internal", method, args
        )

    async def asset_text(self, path: str) -> str | None:
        response = await self._env.ASSETS.fetch(f"https://assets.local{path}")
        if int(response.status) != 200:
            return None
        return await response.text()

    def now_ms(self) -> int:
        return now_ms()


class Default(WorkerEntrypoint):
    async def fetch(self, request: Any) -> Response:
        req = as_request(request)
        try:
            config = load_config(self.env)
        except ConfigError as exc:
            log("config_error", detail=str(exc), app_env=env_get(self.env, "APP_ENV"))
            return json_body(
                500, {"error": {"code": "INTERNAL", "message": "Server misconfigured."}}
            )

        http_request: HttpRequest = await to_http_request(req)
        result = await handle(
            http_request, config, _key_cache(config.access_team_domain), _Ports(self.env)
        )

        if isinstance(result, Upgrade):
            # Hand the original upgrade request to the game's Durable Object. The internal
            # URL is only reachable through the binding, so the player key in it is trusted.
            stub = self.env.GAME_ROOM.getByName(result.game_id)
            forwarded = JsRequest.new(
                f"https://game-room.internal/connect?player={result.player}", req.js_object
            )
            return await stub.fetch(forwarded)

        return Response(result.body, status=result.status, headers=result.headers)
