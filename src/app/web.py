"""The Worker's request handling, independent of the Cloudflare runtime.

src/entry.py converts the runtime's request into :class:`HttpRequest`, calls
:func:`handle`, and turns the result into a real response or a WebSocket hand-off.
The dev server does the same with aiohttp, so both run identical routing and checks.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.auth import DEV_COOKIE, AuthError, KeyCache, identify
from app.config import Config, Player
from app.log import log
from chess_core.protocol import ERROR_MESSAGES

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
MAX_BODY_BYTES = 4096

# Content-Security-Policy for pages the Worker serves; public/_headers carries the same
# policy for pages served directly from static assets.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self' wss://chess.labscloud.uk wss://chess-staging.labscloud.uk; "
    "manifest-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; object-src 'none'"
)
COMMON_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


@dataclass
class HttpRequest:
    method: str
    path: str
    query: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)  # lower-case names
    body: bytes = b""

    @property
    def cookies(self) -> dict[str, str]:
        jar: dict[str, str] = {}
        for part in self.headers.get("cookie", "").split(";"):
            name, sep, value = part.strip().partition("=")
            if sep and name:
                jar[name] = value
        return jar


@dataclass
class HttpResponse:
    status: int
    body: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Upgrade:
    """Hand the WebSocket upgrade to the GameRoom for this game and player."""

    game_id: str
    player: str
    headers: dict[str, str] = field(default_factory=dict)


class WebPorts(Protocol):
    async def lobby(self, method: str, args: dict[str, Any]) -> tuple[int, Any]: ...

    async def room(self, game_id: str, method: str, args: dict[str, Any]) -> tuple[int, Any]: ...

    async def asset_text(self, path: str) -> str | None:
        """Text of a static asset by URL path ("/game" → game.html, as the ASSETS binding does)."""
        ...

    def now_ms(self) -> int: ...


def json_response(
    status: int, payload: Any, extra: Mapping[str, str] | None = None
) -> HttpResponse:
    headers = {
        **COMMON_HEADERS,
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
    }
    if extra:
        headers.update(extra)
    return HttpResponse(
        status, json.dumps(payload, separators=(",", ":"), ensure_ascii=False), headers
    )


def error_response(status: int, code: str, extra: Mapping[str, str] | None = None) -> HttpResponse:
    return json_response(
        status,
        {"error": {"code": code, "message": ERROR_MESSAGES.get(code, "Something went wrong.")}},
        extra,
    )


def html_response(body: str, extra: Mapping[str, str] | None = None) -> HttpResponse:
    headers = {
        **COMMON_HEADERS,
        "content-type": "text/html; charset=utf-8",
        "content-security-policy": CSP,
        "cache-control": "no-cache",
    }
    if extra:
        headers.update(extra)
    return HttpResponse(200, body, headers)


def _rpc_response(status: int, body: Any, ok_status: int | None = None) -> HttpResponse:
    if status >= 400:
        code = body.get("code", "INTERNAL") if isinstance(body, dict) else "INTERNAL"
        return error_response(status, str(code))
    return json_response(ok_status or status, body)


def _parse_json(req: HttpRequest) -> Any:
    if len(req.body) > MAX_BODY_BYTES:
        raise ValueError("body too large")
    try:
        return json.loads(req.body.decode("utf-8") or "null")
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("bad json") from exc


def _write_guard(req: HttpRequest, config: Config) -> HttpResponse | None:
    """Cross-site request forgery guard for state-changing requests.

    Cloudflare Access's CF_Authorization cookie is SameSite=None by default, so a hostile
    page could otherwise make a logged-in browser POST a text/plain "JSON" form. Browsers
    always send Origin (and Sec-Fetch-Site) on such requests; ours are same-origin JSON.
    """
    origin = req.headers.get("origin")
    if origin is not None and origin != config.public_url:
        return error_response(403, "BAD_ORIGIN")
    if req.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        return error_response(403, "BAD_ORIGIN")
    content_type = req.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return error_response(400, "BAD_REQUEST")
    return None


async def handle(
    req: HttpRequest, config: Config, keys: KeyCache, ports: WebPorts
) -> HttpResponse | Upgrade:
    """Route one request that reached the Worker (run_worker_first paths)."""
    path = req.path.rstrip("/") or "/"
    method = req.method.upper()

    if path == "/healthz":
        if method not in ("GET", "HEAD"):
            return error_response(405, "METHOD_NOT_ALLOWED")
        return json_response(
            200,
            {"ok": True, "version": config.version, "commit": config.commit, "env": config.app_env},
        )

    try:
        player, dev_cookie = await identify(
            headers=req.headers,
            query=req.query,
            cookies=req.cookies,
            config=config,
            keys=keys,
            now_ms=ports.now_ms(),
        )
    except AuthError as exc:
        log("auth_rejected", code=exc.code, path=path)
        return error_response(403, exc.code)

    if method in ("POST", "PATCH", "PUT", "DELETE"):
        refused = _write_guard(req, config)
        if refused is not None:
            return refused

    extra: dict[str, str] = {}
    if dev_cookie and config.is_development:
        extra["set-cookie"] = f"{DEV_COOKIE}={dev_cookie}; Path=/; HttpOnly; SameSite=Lax"

    try:
        result = await _route(req, path, method, player, config, ports)
    except Exception as exc:
        log("request_failed", path=path, error=type(exc).__name__)
        result = error_response(500, "INTERNAL")
    result.headers.update(extra)
    return result


async def _route(
    req: HttpRequest, path: str, method: str, player: Player, config: Config, ports: WebPorts
) -> HttpResponse | Upgrade:
    parts = path.strip("/").split("/")

    if path == "/api/me":
        if method == "GET":
            return _rpc_response(*await ports.lobby("me", {"player": player.key}))
        if method == "PATCH":
            try:
                body = _parse_json(req)
            except ValueError:
                return error_response(400, "BAD_REQUEST")
            return _rpc_response(
                *await ports.lobby("update_me", {"player": player.key, "body": body})
            )
        return error_response(405, "METHOD_NOT_ALLOWED")

    if path == "/api/games":
        if method == "GET":
            status = req.query.get("status") or None
            return _rpc_response(
                *await ports.lobby("list_games", {"player": player.key, "status": status})
            )
        if method == "POST":
            try:
                body = _parse_json(req)
            except ValueError:
                return error_response(400, "BAD_REQUEST")
            if not isinstance(body, dict) or set(body) != {"colour"}:
                return error_response(400, "BAD_REQUEST")
            return _rpc_response(
                *await ports.lobby("create_game", {"player": player.key, "colour": body["colour"]})
            )
        return error_response(405, "METHOD_NOT_ALLOWED")

    if path == "/api/stats":
        if method != "GET":
            return error_response(405, "METHOD_NOT_ALLOWED")
        return _rpc_response(*await ports.lobby("stats", {}))

    if len(parts) in (3, 4) and parts[:2] == ["api", "games"]:
        game_id = parts[2]
        if not UUID_RE.match(game_id) or (len(parts) == 4 and parts[3] != "pgn"):
            return error_response(404, "NOT_FOUND" if len(parts) == 4 else "GAME_NOT_FOUND")
        if method != "GET":
            return error_response(405, "METHOD_NOT_ALLOWED")
        if len(parts) == 3:
            return _rpc_response(*await ports.room(game_id, "snapshot", {"player": player.key}))
        status, exists = await ports.room(game_id, "exists", {})
        if (
            status != 200
            or not exists.get("exists")
            or player.key not in (exists["white"], exists["black"])
        ):
            return error_response(404, "GAME_NOT_FOUND")
        status, body = await ports.room(game_id, "pgn", {})
        if status != 200:
            return _rpc_response(status, body)
        filename = f"labscloud-chess-{body['date']}-{game_id[:8]}.pgn"
        return HttpResponse(
            200,
            str(body["pgn"]),
            {
                **COMMON_HEADERS,
                "content-type": "application/x-chess-pgn; charset=utf-8",
                "content-disposition": f'attachment; filename="{filename}"',
                "cache-control": "no-store",
            },
        )

    if path == "/api/diag/move":
        if config.app_env == "production":
            return error_response(404, "NOT_FOUND")
        if method != "POST":
            return error_response(405, "METHOD_NOT_ALLOWED")
        try:
            body = _parse_json(req)
            game_id, uci = str(body["game_id"]), str(body["uci"])
        except (ValueError, KeyError, TypeError):
            return error_response(400, "BAD_REQUEST")
        if not UUID_RE.match(game_id):
            return error_response(404, "GAME_NOT_FOUND")
        return _rpc_response(*await ports.room(game_id, "diag_move", {"uci": uci}))

    if len(parts) == 3 and parts[:2] == ["ws", "games"]:
        game_id = parts[2]
        if method != "GET":
            return error_response(405, "METHOD_NOT_ALLOWED")
        if req.headers.get("origin", "") != config.public_url:
            return error_response(403, "BAD_ORIGIN")
        if req.headers.get("upgrade", "").lower() != "websocket":
            return error_response(426, "UPGRADE_REQUIRED")
        if not UUID_RE.match(game_id):
            return error_response(404, "GAME_NOT_FOUND")
        status, exists = await ports.room(game_id, "exists", {})
        if status != 200 or not exists.get("exists"):
            return error_response(404, "GAME_NOT_FOUND")
        if player.key not in (exists["white"], exists["black"]):
            return error_response(403, "NOT_A_PLAYER")
        return Upgrade(game_id=game_id, player=player.key)

    if len(parts) == 2 and parts[0] == "game":
        if method not in ("GET", "HEAD"):
            return error_response(405, "METHOD_NOT_ALLOWED")
        page = await ports.asset_text("/game")
        if page is None:
            return error_response(500, "INTERNAL")
        return html_response(page)

    if path == "/diag":
        if config.app_env == "production":
            return error_response(404, "NOT_FOUND")
        page = await ports.asset_text("/diag")
        if page is None:
            return error_response(500, "INTERNAL")
        return html_response(page)

    return error_response(404, "NOT_FOUND")
