"""Worker routing, auth gate, REST bodies and WebSocket upgrade checks
(REQ-AUTH-02..07, REQ-GAME-*, REQ-SEC-*)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.auth import KeyCache
from app.config import Config
from app.web import CSP, HttpRequest, HttpResponse, Upgrade, handle
from devserver.hub import Hub, WebPorts
from tests.conftest import Clock, make_config
from tests.fixtures.jwt_keys import jwk, sign

ORIGIN = "http://localhost:8787"
MISSING = "00000000-0000-4000-8000-000000000000"


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class Site:
    def __init__(self, tmp: Path, **overrides: Any) -> None:
        (tmp / "game.html").write_text("<html>game</html>", encoding="utf-8")
        (tmp / "diag.html").write_text("<html>diag</html>", encoding="utf-8")
        self.config: Config = make_config(**overrides)
        self.clock = Clock()
        self.hub = Hub(self.config, clock=self.clock, chooser=lambda o: o[0])
        self.ports = WebPorts(self.hub, tmp)

        async def certs() -> Any:
            return {"keys": [jwk("k1")]}

        self.keys = KeyCache(certs)

    def call(
        self,
        method: str,
        path: str,
        *,
        player: str | None = "harry",
        query: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        body: Any = None,
    ) -> HttpResponse | Upgrade:
        q = dict(query or {})
        if player is not None and self.config.is_development:
            q.setdefault("as", player)
        raw = (
            b""
            if body is None
            else (body if isinstance(body, bytes) else json.dumps(body).encode())
        )
        all_headers = dict(headers or {})
        if method in ("POST", "PATCH", "PUT", "DELETE"):
            all_headers.setdefault("content-type", "application/json")
        return run(
            handle(
                HttpRequest(method, path, q, all_headers, raw),
                self.config,
                self.keys,
                self.ports,
            )
        )

    def json(self, method: str, path: str, **kwargs: Any) -> tuple[int, Any]:
        response = self.call(method, path, **kwargs)
        assert isinstance(response, HttpResponse)
        return response.status, json.loads(response.body)

    def create(self, colour: str = "white", player: str = "harry") -> str:
        status, body = self.json("POST", "/api/games", player=player, body={"colour": colour})
        assert status == 201, body
        return str(body["game"]["id"])


@pytest.fixture
def site(tmp_path: Path) -> Site:
    return Site(tmp_path)


def error_code(response: Any) -> tuple[int, str]:
    assert isinstance(response, HttpResponse)
    return response.status, json.loads(response.body)["error"]["code"]


# --- healthz and the auth gate ------------------------------------------------------------------


def test_healthz_without_auth(site: Site) -> None:
    status, body = site.json("GET", "/healthz", player=None)
    assert status == 200
    assert body == {"ok": True, "version": "0.1.0", "commit": "abc1234", "env": "development"}
    assert error_code(site.call("POST", "/healthz", player=None)) == (405, "METHOD_NOT_ALLOWED")


@pytest.mark.parametrize(
    "path",
    [
        "/api/me",
        "/api/games",
        "/api/stats",
        f"/api/games/{MISSING}",
        "/game/x",
        "/diag",
        f"/ws/games/{MISSING}",
        "/nothing",
    ],
)
def test_everything_else_needs_auth(site: Site, path: str) -> None:
    assert error_code(site.call("GET", path, player=None)) == (403, "UNAUTHORISED")


def test_dev_bypass_sets_cookie_and_cookie_works(site: Site) -> None:
    response = site.call("GET", "/api/me", player="partner")
    assert isinstance(response, HttpResponse) and response.status == 200
    assert response.headers["set-cookie"].startswith("dev_as=partner;")
    assert "HttpOnly" in response.headers["set-cookie"]
    status, body = site.json(
        "GET", "/api/me", player=None, headers={"cookie": "x=1; dev_as=partner"}
    )
    assert status == 200 and body["player"] == "partner"


def test_production_requires_valid_jwt(tmp_path: Path) -> None:
    site = Site(tmp_path, app_env="production", public_url="https://chess.labscloud.uk")
    assert error_code(site.call("GET", "/api/me", player=None, query={"as": "harry"})) == (
        403,
        "UNAUTHORISED",
    )
    token = sign(
        {
            "aud": ["aud-tag"],
            "iss": "https://team.cloudflareaccess.com",
            "exp": 1_760_003_600,
            "email": "partner@example.test",
        }
    )
    status, body = site.json(
        "GET", "/api/me", player=None, headers={"cf-access-jwt-assertion": token}
    )
    assert status == 200 and body["player"] == "partner"
    stranger = sign(
        {
            "aud": ["aud-tag"],
            "iss": "https://team.cloudflareaccess.com",
            "exp": 1_760_003_600,
            "email": "eve@example.test",
        }
    )
    assert error_code(
        site.call("GET", "/api/me", player=None, headers={"cf-access-jwt-assertion": stranger})
    ) == (
        403,
        "NOT_A_PLAYER",
    )
    response = site.call("GET", "/api/me", player=None, headers={"cf-access-jwt-assertion": token})
    assert isinstance(response, HttpResponse) and "set-cookie" not in response.headers


def test_production_hides_diag(tmp_path: Path) -> None:
    site = Site(tmp_path, app_env="production", public_url="https://chess.labscloud.uk")
    token = sign(
        {
            "aud": ["aud-tag"],
            "iss": "https://team.cloudflareaccess.com",
            "exp": 1_760_003_600,
            "email": "harry@example.test",
        }
    )
    headers = {"cf-access-jwt-assertion": token}
    assert error_code(site.call("GET", "/diag", player=None, headers=headers)) == (404, "NOT_FOUND")
    assert error_code(
        site.call(
            "POST",
            "/api/diag/move",
            player=None,
            headers=headers,
            body={"game_id": MISSING, "uci": "e2e4"},
        )
    ) == (404, "NOT_FOUND")


# --- /api/me ----------------------------------------------------------------------------------------


def test_me_get_and_patch(site: Site) -> None:
    status, body = site.json("GET", "/api/me")
    assert (
        status == 200
        and body["notify"]["cooldown_minutes"] == 30
        and "email" not in json.dumps(body)
    )
    status, body = site.json(
        "PATCH", "/api/me", body={"name": "H", "notify": {"cooldown_minutes": 60}}
    )
    assert status == 200 and body["name"] == "H" and body["notify"]["cooldown_minutes"] == 60


@pytest.mark.parametrize(
    "body",
    [b"not json", b"\xff", {"name": ""}, {"notify": {"cooldown_minutes": 7}}, [], b"x" * 5000],
)
def test_me_patch_bad(site: Site, body: Any) -> None:
    assert error_code(site.call("PATCH", "/api/me", body=body)) == (400, "BAD_REQUEST")


def test_me_wrong_method(site: Site) -> None:
    assert error_code(site.call("DELETE", "/api/me")) == (405, "METHOD_NOT_ALLOWED")


# --- games --------------------------------------------------------------------------------------------


def test_create_and_list(site: Site) -> None:
    first = site.create("white")
    site.clock.advance(10)
    second = site.create("black", player="partner")
    status, body = site.json("GET", "/api/games")
    assert status == 200 and [g["id"] for g in body["games"]] == [second, first]
    status, body = site.json("GET", "/api/games", query={"status": "finished"})
    assert body == {"games": []}
    assert error_code(site.call("GET", "/api/games", query={"status": "old"})) == (
        400,
        "BAD_REQUEST",
    )


@pytest.mark.parametrize(
    "body", [{}, {"colour": "green"}, {"colour": "white", "x": 1}, None, "white", b"{"]
)
def test_create_bad_body(site: Site, body: Any) -> None:
    assert error_code(site.call("POST", "/api/games", body=body)) == (400, "BAD_REQUEST")


def test_games_wrong_method(site: Site) -> None:
    assert error_code(site.call("PUT", "/api/games")) == (405, "METHOD_NOT_ALLOWED")
    assert error_code(site.call("POST", "/api/stats")) == (405, "METHOD_NOT_ALLOWED")


def test_snapshot(site: Site) -> None:
    game_id = site.create()
    status, body = site.json("GET", f"/api/games/{game_id}", player="partner")
    assert (
        status == 200 and body["type"] == "state" and body["you"] == "black" and body["legal"] == []
    )
    assert error_code(site.call("GET", f"/api/games/{MISSING}")) == (404, "GAME_NOT_FOUND")
    assert error_code(site.call("GET", "/api/games/not-a-uuid")) == (404, "GAME_NOT_FOUND")
    assert error_code(site.call("GET", f"/api/games/{game_id.upper()}")) == (404, "GAME_NOT_FOUND")
    assert error_code(site.call("POST", f"/api/games/{game_id}")) == (405, "METHOD_NOT_ALLOWED")
    assert error_code(site.call("GET", f"/api/games/{game_id}/moves")) == (404, "NOT_FOUND")


def test_pgn_download(site: Site) -> None:
    game_id = site.create()
    response = site.call("GET", f"/api/games/{game_id}/pgn")
    assert isinstance(response, HttpResponse) and response.status == 200
    assert response.headers["content-type"] == "application/x-chess-pgn; charset=utf-8"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="labscloud-chess-2025-10-09-{game_id[:8]}.pgn"'
    )
    assert '[Site "localhost:8787"]' in response.body and response.body.rstrip().endswith("*")
    assert error_code(site.call("GET", f"/api/games/{MISSING}/pgn")) == (404, "GAME_NOT_FOUND")


def test_stats(site: Site) -> None:
    status, body = site.json("GET", "/api/stats")
    assert status == 200 and body["finished_games"] == 0


# --- websocket upgrade checks (protocol §2.9 order) -----------------------------------------------------


def ws_headers(**overrides: str) -> dict[str, str]:
    return {"origin": ORIGIN, "upgrade": "websocket", **overrides}


def test_ws_upgrade_ok(site: Site) -> None:
    game_id = site.create()
    result = site.call("GET", f"/ws/games/{game_id}", player="partner", headers=ws_headers())
    assert isinstance(result, Upgrade) and (result.game_id, result.player) == (game_id, "partner")
    result = site.call("GET", f"/ws/games/{game_id}", headers=ws_headers(upgrade="WebSocket"))
    assert isinstance(result, Upgrade)


def test_ws_checks(site: Site) -> None:
    game_id = site.create()
    path = f"/ws/games/{game_id}"
    assert error_code(
        site.call("GET", path, headers=ws_headers(origin="https://evil.example"))
    ) == (403, "BAD_ORIGIN")
    assert error_code(site.call("GET", path, headers={"upgrade": "websocket"})) == (
        403,
        "BAD_ORIGIN",
    )
    assert error_code(site.call("GET", path, headers={"origin": ORIGIN})) == (
        426,
        "UPGRADE_REQUIRED",
    )
    assert error_code(site.call("GET", f"/ws/games/{MISSING}", headers=ws_headers())) == (
        404,
        "GAME_NOT_FOUND",
    )
    assert error_code(site.call("GET", "/ws/games/zzz", headers=ws_headers())) == (
        404,
        "GAME_NOT_FOUND",
    )
    assert error_code(site.call("POST", path, headers=ws_headers())) == (405, "METHOD_NOT_ALLOWED")
    # Origin is checked before the upgrade header, before the game lookup.
    assert error_code(site.call("GET", f"/ws/games/{MISSING}", headers={})) == (403, "BAD_ORIGIN")


# --- pages, headers, misc -----------------------------------------------------------------------------------


def test_game_page_has_security_headers(site: Site) -> None:
    response = site.call("GET", f"/game/{MISSING}")
    assert (
        isinstance(response, HttpResponse)
        and response.status == 200
        and response.body == "<html>game</html>"
    )
    assert response.headers["content-security-policy"] == CSP
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"
    assert "frame-ancestors 'none'" in CSP and "script-src 'self'" in CSP and "unsafe" not in CSP


def test_json_responses_not_cached(site: Site) -> None:
    response = site.call("GET", "/api/me")
    assert isinstance(response, HttpResponse) and response.headers["cache-control"] == "no-store"


def test_diag_page_in_development(site: Site) -> None:
    response = site.call("GET", "/diag")
    assert isinstance(response, HttpResponse) and response.body == "<html>diag</html>"


def test_diag_move(site: Site) -> None:
    game_id = site.create()
    status, body = site.json("POST", "/api/diag/move", body={"game_id": game_id, "uci": "e2e4"})
    assert status == 200 and body == {"ok": True, "error": None, "ply": 1}
    assert error_code(site.call("POST", "/api/diag/move", body={"uci": "e2e4"})) == (
        400,
        "BAD_REQUEST",
    )
    assert error_code(site.call("GET", "/api/diag/move")) == (405, "METHOD_NOT_ALLOWED")


def test_unknown_path(site: Site) -> None:
    assert error_code(site.call("GET", "/api/nothing")) == (404, "NOT_FOUND")


def test_trailing_slash_tolerated(site: Site) -> None:
    status, _ = site.json("GET", "/api/me/")
    assert status == 200


def test_internal_errors_are_generic(site: Site) -> None:
    async def broken(method: str, args: dict[str, Any]) -> tuple[int, Any]:
        raise RuntimeError("secret detail")

    site.ports.lobby = broken  # type: ignore[method-assign]
    response = site.call("GET", "/api/me")
    assert error_code(response) == (500, "INTERNAL")
    assert isinstance(response, HttpResponse) and "secret" not in response.body


def test_missing_asset_is_500(tmp_path: Path) -> None:
    site = Site(tmp_path)
    (tmp_path / "game.html").unlink()
    assert error_code(site.call("GET", f"/game/{MISSING}")) == (500, "INTERNAL")


def test_asset_path_traversal_blocked(tmp_path: Path) -> None:
    (tmp_path / "public").mkdir()
    site = Site(tmp_path / "public")
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    assert run(site.ports.asset_text("/../secret.txt")) is None
    assert run(site.ports.asset_text("/game.html")) == "<html>game</html>"


def test_extensionless_asset_paths_like_the_assets_binding(tmp_path: Path) -> None:
    site = Site(tmp_path)
    assert run(site.ports.asset_text("/game")) == "<html>game</html>"
    assert run(site.ports.asset_text("/diag")) == "<html>diag</html>"
    assert run(site.ports.asset_text("/missing")) is None


def test_static_headers_file_uses_the_same_csp() -> None:
    headers = Path("public/_headers").read_text(encoding="utf-8")
    line = next(x for x in headers.splitlines() if "Content-Security-Policy:" in x)
    assert line.split("Content-Security-Policy:", 1)[1].strip() == CSP


def test_cross_site_writes_refused(site: Site) -> None:
    evil = b'{"colour":"x=","colour":"white"}'
    text = {"content-type": "text/plain"}
    assert error_code(
        site.call(
            "POST", "/api/games", body=evil, headers={"origin": "https://evil.example", **text}
        )
    ) == (403, "BAD_ORIGIN")
    assert error_code(
        site.call(
            "POST", "/api/games", body={"colour": "white"}, headers={"sec-fetch-site": "cross-site"}
        )
    ) == (403, "BAD_ORIGIN")
    assert error_code(site.call("POST", "/api/games", body=evil, headers=text)) == (
        400,
        "BAD_REQUEST",
    )
    assert error_code(
        site.call(
            "PATCH", "/api/me", body={"name": "Eve"}, headers={"origin": "https://evil.example"}
        )
    ) == (403, "BAD_ORIGIN")
    assert run(site.hub.lobby.rpc("list_games", {"player": "harry"}))[1]["games"] == []
    # Same-origin browser requests still work.
    headers = {
        "origin": ORIGIN,
        "sec-fetch-site": "same-origin",
        "content-type": "application/json; charset=utf-8",
    }
    status, _ = site.json("POST", "/api/games", body={"colour": "white"}, headers=headers)
    assert status == 201
