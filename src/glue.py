"""Cloudflare runtime glue: the only code (with entry.py, game_room.py, lobby.py) that
touches the `workers`, `js` and `pyodide` modules. Kept deliberately small; all
behaviour lives in the `app` package, which is tested in CPython.

API facts used here are recorded in docs/platform-notes.md.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any, TypeVar
from urllib.parse import parse_qsl, urlsplit

from workers import Request, Response

from app.config import Config
from app.web import HttpRequest

T = TypeVar("T")


def now_ms() -> int:
    return int(time.time() * 1000)


def env_get(env: Any, name: str) -> Any:
    """Read a var/secret; None when it isn't set."""
    try:
        value = getattr(env, name)
    except AttributeError:
        return None
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def load_config(env: Any) -> Config:
    return Config.from_env(lambda name: env_get(env, name))


def as_request(request: Any) -> Request:
    return request if isinstance(request, Request) else Request(request)


async def to_http_request(request: Request) -> HttpRequest:
    url = urlsplit(request.url)
    method = str(request.js_object.method).upper()
    headers = {str(k).lower(): str(v) for k, v in request.headers.items()}
    body = b""
    if method in ("POST", "PATCH", "PUT"):
        body = (await request.text()).encode("utf-8")
    query: dict[str, str] = {}
    for key, value in parse_qsl(url.query, keep_blank_values=True):
        query.setdefault(key, value)
    return HttpRequest(method=method, path=url.path or "/", query=query, headers=headers, body=body)


def json_body(status: int, payload: Any) -> Response:
    return Response(
        json.dumps(payload, separators=(",", ":")),
        status=status,
        headers={"content-type": "application/json; charset=utf-8"},
    )


async def call_rpc(stub: Any, origin: str, method: str, args: dict[str, Any]) -> tuple[int, Any]:
    """POST a JSON RPC to a Durable Object stub (fetch-based, see platform notes §4)."""
    response = await stub.fetch(
        f"https://{origin}/rpc",
        method="POST",
        headers={"content-type": "application/json"},
        body=json.dumps({"method": method, "args": args}),
    )
    text = await response.text()
    try:
        payload = json.loads(text) if text else None
    except ValueError:
        payload = None
    return int(response.status), payload


async def read_rpc(request: Request) -> tuple[str, dict[str, Any]]:
    data = json.loads(await request.text())
    if not isinstance(data, dict) or not isinstance(data.get("method"), str):
        raise ValueError("bad rpc")
    args = data.get("args") or {}
    if not isinstance(args, dict):
        raise ValueError("bad rpc args")
    return data["method"], args


def _plain(value: Any) -> Any:
    """Convert a row value from the SDK's RPC conversion into plain Python."""
    if value is None or isinstance(value, str | int | float | bool):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    try:
        return value.to_py()
    except AttributeError:
        return value


def _row(row: Any) -> dict[str, Any]:
    mapping = row if isinstance(row, dict) else row.to_py()
    return {str(k): _plain(v) for k, v in mapping.items()}


class DOStorage:
    """app.storage.Storage over a Durable Object's SQLite (ctx.storage.sql)."""

    def __init__(self, ctx: Any) -> None:
        self._storage = ctx.storage
        self._sql = self._storage.sql

    def query(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        # Consume the cursor immediately (never across an await): platform notes §4.
        rows = self._sql.exec(sql, *params).toArray()
        return [_row(row) for row in rows]

    def execute(self, sql: str, *params: Any) -> None:
        self._sql.exec(sql, *params)

    def transaction(self, fn: Callable[[], T]) -> T:
        return self._storage.transactionSync(fn)


class DOSocket:
    """A hibernatable WebSocket plus the identity stored in its attachment."""

    def __init__(self, ws: Any, player: str, colour: Any) -> None:
        self.ws = ws
        self.player = player
        self.colour = colour

    @classmethod
    def from_ws(cls, ws: Any) -> DOSocket | None:
        try:
            data = json.loads(str(ws.deserializeAttachment()))
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        player, colour = data.get("player"), data.get("colour")
        if not isinstance(player, str) or colour not in ("white", "black"):
            return None
        return cls(ws, player, colour)

    def send(self, text: str) -> None:
        self.ws.send(text)

    def __eq__(self, other: object) -> bool:
        # JsProxy equality compares the underlying JavaScript objects.
        return isinstance(other, DOSocket) and bool(self.ws == other.ws)

    def __hash__(self) -> int:
        return hash((self.player, self.colour))


def list_sockets(ctx: Any) -> list[DOSocket]:
    sockets: list[DOSocket] = []
    for ws in ctx.getWebSockets():
        sock = DOSocket.from_ws(ws)
        if sock is not None:
            sockets.append(sock)
    return sockets
