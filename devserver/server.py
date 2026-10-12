"""Local development server: the same routing, auth and game logic as the Worker, in CPython.

Run:  uv run python -m devserver.server --port 8787
Then open http://localhost:8787/api/me?as=harry once (sets the dev cookie) and go to /.

It mirrors the deployed layout: paths in wrangler.jsonc's run_worker_first go through
app.web.handle; everything else is a static file from public/. WebSockets are bridged to
the in-process Hub. This is for building and tests; production runs on Cloudflare.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import mimetypes
import os
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from app.auth import KeyCache
from app.config import Config
from app.web import COMMON_HEADERS, CSP, HttpRequest, HttpResponse, Upgrade, handle
from devserver.hub import Hub, LocalSocket, WebPorts

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
WORKER_FIRST = ("/api/", "/ws/", "/game/")
WORKER_EXACT = ("/healthz", "/diag")

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".js")


def dev_csp(public_url: str) -> str:
    """The production CSP with this server's ws:// origin allowed for the socket."""
    ws_origin = public_url.replace("http://", "ws://").replace("https://", "wss://")
    return CSP.replace("connect-src 'self'", f"connect-src 'self' {ws_origin}")


def is_worker_path(path: str) -> bool:
    return path.startswith(WORKER_FIRST) or path in WORKER_EXACT


def static_file(path: str) -> Path | None:
    """Resolve like Workers Static Assets with html_handling = auto-trailing-slash."""
    if path.endswith("/"):
        path += "index.html"
    candidates = [path]
    if "." not in path.rsplit("/", 1)[-1]:
        candidates.append(f"{path}.html")
    public = PUBLIC.resolve()
    for candidate in candidates:
        target = (PUBLIC / candidate.lstrip("/")).resolve()
        if public in target.parents and target.is_file() and not target.name.startswith("_"):
            return target
    return None


class DevServer:
    def __init__(self, config: Config, hub: Hub) -> None:
        self.config = config
        self.hub = hub
        self.ports = WebPorts(hub, PUBLIC)

        async def no_certs() -> Any:
            return {"keys": []}

        self.keys = KeyCache(no_certs)
        self.csp = dev_csp(config.public_url)

    def _headers(self, headers: dict[str, str]) -> dict[str, str]:
        out = dict(headers)
        if out.get("content-type", "").startswith("text/html") or "content-security-policy" in out:
            out["content-security-policy"] = self.csp
        return out

    async def dispatch(self, request: web.Request) -> web.StreamResponse:
        path = request.path
        if is_worker_path(path):
            return await self._worker(request)
        target = static_file(path)
        if target is None:
            return web.Response(status=404, text="Not found", headers=COMMON_HEADERS)
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        headers = {**COMMON_HEADERS, "content-type": content_type, "cache-control": "no-cache"}
        if content_type == "text/html":
            headers["content-type"] = "text/html; charset=utf-8"
            headers["content-security-policy"] = self.csp
        return web.Response(body=target.read_bytes(), headers=headers)

    async def _worker(self, request: web.Request) -> web.StreamResponse:
        body = await request.read() if request.method in ("POST", "PATCH", "PUT") else b""
        req = HttpRequest(
            method=request.method,
            path=request.path,
            query=dict(request.query.items()),
            headers={k.lower(): v for k, v in request.headers.items()},
            body=body,
        )
        result = await handle(req, self.config, self.keys, self.ports)
        if isinstance(result, Upgrade):
            return await self._websocket(request, result)
        assert isinstance(result, HttpResponse)
        headers = self._headers(result.headers)
        return web.Response(status=result.status, body=result.body.encode("utf-8"), headers=headers)

    async def _websocket(self, request: web.Request, upgrade: Upgrade) -> web.StreamResponse:
        ws = web.WebSocketResponse(max_msg_size=64 * 1024)
        await ws.prepare(request)
        outbox: asyncio.Queue[str | None] = asyncio.Queue()

        async def writer() -> None:
            while True:
                text = await outbox.get()
                if text is None or ws.closed:
                    return
                with contextlib.suppress(ConnectionError, RuntimeError):
                    await ws.send_str(text)

        writer_task = asyncio.create_task(writer())
        sock: LocalSocket | None = await self.hub.connect(
            upgrade.game_id, upgrade.player, outbox.put_nowait
        )
        if sock is None:
            await ws.close(code=1008, message=b"not a player")
            outbox.put_nowait(None)
            await writer_task
            return ws
        try:
            async for msg in ws:
                if msg.type in (WSMsgType.TEXT, WSMsgType.BINARY):
                    await self.hub.message(upgrade.game_id, sock, msg.data)
                elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            await self.hub.disconnect(upgrade.game_id, sock)
            outbox.put_nowait(None)
            await writer_task
        return ws


def build_app(config: Config, data_dir: str | None = None) -> web.Application:
    hub = Hub(config, data_dir=data_dir)
    server = DevServer(config, hub)
    app = web.Application(client_max_size=64 * 1024)
    app["hub"] = hub
    app.router.add_route("*", "/{tail:.*}", server.dispatch)
    return app


def config_from_env(port: int) -> Config:
    defaults = {
        "APP_ENV": "development",
        "PUBLIC_URL": f"http://localhost:{port}",
        "EMAIL_ENABLED": "false",
    }
    return Config.from_env(lambda name: os.environ.get(name, defaults.get(name)))


def main() -> None:
    parser = argparse.ArgumentParser(description="labscloud-chess development server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8787")))
    parser.add_argument(
        "--data-dir", default=os.environ.get("DEV_DATA_DIR"), help="keep games in SQLite files here"
    )
    args = parser.parse_args()
    config = config_from_env(args.port)
    if not config.is_development:
        raise SystemExit("The dev server only runs with APP_ENV=development.")
    print(json.dumps({"event": "devserver_start", "url": config.public_url}))
    web.run_app(build_app(config, args.data_dir), host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
