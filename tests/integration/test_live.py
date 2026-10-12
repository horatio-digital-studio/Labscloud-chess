"""End-to-end protocol tests against a running server (devserver locally, `pywrangler dev`
in CI). They use the development identity switch `?as=` (REQ-AUTH-06)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
import websockets
from websockets.typing import Origin

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


TIMEOUT = 10.0


def rest(base_url: str, player: str = "harry") -> httpx.Client:
    return httpx.Client(base_url=base_url, params={"as": player}, timeout=TIMEOUT)


def create_game(base_url: str, colour: str = "white", player: str = "harry") -> str:
    with rest(base_url, player) as client:
        response = client.post("/api/games", json={"colour": colour})
        assert response.status_code == 201, response.text
        return str(response.json()["game"]["id"])


class Conn:
    def __init__(self, ws: Any) -> None:
        self.ws = ws

    async def send(self, message: dict[str, Any] | str) -> None:
        await self.ws.send(message if isinstance(message, str) else json.dumps(message))

    async def recv(self, kind: str | None = None) -> dict[str, Any]:
        while True:
            message = json.loads(await asyncio.wait_for(self.ws.recv(), TIMEOUT))
            if kind is None or message["type"] == kind:
                return message

    async def hello(self) -> dict[str, Any]:
        await self.send({"type": "hello"})
        return await self.recv("state")

    async def quiet(self, seconds: float = 0.3) -> list[dict[str, Any]]:
        """Everything that arrives within `seconds` (to check nothing unexpected was sent)."""
        got: list[dict[str, Any]] = []
        try:
            while True:
                got.append(json.loads(await asyncio.wait_for(self.ws.recv(), seconds)))
        except TimeoutError:
            return got


@asynccontextmanager
async def connect(base_url: str, game_id: str, player: str) -> AsyncIterator[Conn]:
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
    async with websockets.connect(
        f"{ws_url}/ws/games/{game_id}?as={player}",
        origin=Origin(base_url),
        open_timeout=TIMEOUT,
    ) as ws:
        yield Conn(ws)


async def move(conn: Conn, uci: str, ply: int) -> None:
    await conn.send({"type": "move", "uci": uci, "ply": ply})


# --------------------------------------------------------------------- REST


def test_healthz(base_url: str) -> None:
    response = httpx.get(f"{base_url}/healthz", timeout=TIMEOUT)
    assert response.status_code == 200
    assert set(response.json()) == {"ok", "version", "commit", "env"}


def test_unauthenticated_request_rejected(base_url: str) -> None:
    response = httpx.get(f"{base_url}/api/me", timeout=TIMEOUT)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "UNAUTHORISED"


def test_me_and_name(base_url: str) -> None:
    with rest(base_url, "partner") as client:
        assert client.get("/api/me").json()["player"] == "partner"
        bad = client.patch("/api/me", json={"name": "x" * 25})
        assert bad.status_code == 400 and bad.json()["error"]["code"] == "BAD_REQUEST"
        saved = client.patch("/api/me", json={"name": "  Partner  "})
        assert saved.status_code == 200 and saved.json()["name"] == "Partner"


def test_create_list_and_snapshot(base_url: str) -> None:
    game_id = create_game(base_url, "black")
    with rest(base_url, "partner") as client:
        games = client.get("/api/games", params={"status": "active"}).json()["games"]
        mine = next(g for g in games if g["id"] == game_id)
        assert mine["you"] == "white" and mine["your_turn"] is True
        state = client.get(f"/api/games/{game_id}").json()
        assert state["type"] == "state" and state["you"] == "white" and len(state["legal"]) == 20
    with rest(base_url) as client:
        listed = client.get("/api/games").json()["games"]
        assert listed[0]["id"] == game_id  # newest first


def test_unknown_game_is_404(base_url: str) -> None:
    with rest(base_url) as client:
        response = client.get("/api/games/00000000-0000-4000-8000-000000000000")
        assert response.status_code == 404 and response.json()["error"]["code"] == "GAME_NOT_FOUND"


# ------------------------------------------------------------------ WebSockets


async def test_play_broadcast_and_errors(base_url: str) -> None:
    game_id = create_game(base_url)
    async with (
        connect(base_url, game_id, "harry") as white,
        connect(base_url, game_id, "partner") as black,
    ):
        assert (await white.hello())["you"] == "white"
        assert (await black.hello())["you"] == "black"
        await move(white, "e2e4", 0)
        for conn in (white, black):
            state = await conn.recv("state")
            assert state["ply"] == 1 and state["last_move"] == {"uci": "e2e4", "san": "e4"}
        # Errors go only to the sender and change nothing (REQ-RULE-03).
        await move(white, "d2d4", 1)
        error = await white.recv("error")
        assert error["code"] == "NOT_YOUR_TURN"
        assert [m for m in await black.quiet() if m["type"] == "state"] == []
        # Resending an accepted move is STALE_PLY (REQ-RT-09).
        await move(black, "e7e5", 1)
        await black.recv("state")
        await white.recv("state")
        await move(black, "e7e5", 1)
        assert (await black.recv("error"))["code"] == "NOT_YOUR_TURN"
        await move(white, "g1f3", 1)
        assert (await white.recv("error"))["code"] == "STALE_PLY"


async def test_bad_messages(base_url: str) -> None:
    game_id = create_game(base_url)
    async with connect(base_url, game_id, "harry") as white:
        await white.hello()
        for raw in (
            "not json",
            json.dumps({"type": "move", "uci": "e2e4"}),
            json.dumps({"type": "x"}),
            "x" * 1100,
        ):
            await white.send(raw)
            error = await white.recv("error")
            assert error["code"] == "BAD_MESSAGE"
        assert (await white.hello())["ply"] == 0


async def test_presence_and_two_sockets_per_player(base_url: str) -> None:
    game_id = create_game(base_url)
    async with connect(base_url, game_id, "harry") as laptop:
        await laptop.hello()
        async with connect(base_url, game_id, "partner") as black:
            presence = await laptop.recv("presence")
            assert presence["online"] == {"white": True, "black": True}
            async with connect(base_url, game_id, "harry") as phone:
                await phone.hello()
                await move(black, "e7e5", 0)
                assert (await black.recv("error"))["code"] == "NOT_YOUR_TURN"
                await move(phone, "e2e4", 0)
                assert (await laptop.recv("state"))["ply"] == 1
                assert (await phone.recv("state"))["ply"] == 1
        presence = await laptop.recv("presence")
        while presence["online"]["black"]:
            presence = await laptop.recv("presence")
        assert presence["online"] == {"white": True, "black": False}


async def test_reconnect_gets_identical_state(base_url: str) -> None:
    game_id = create_game(base_url)
    async with (
        connect(base_url, game_id, "harry") as white,
        connect(base_url, game_id, "partner") as black,
    ):
        await white.hello()
        await black.hello()
        for ply, uci in enumerate(["e2e4", "e7e5", "g1f3"]):
            await move(white if ply % 2 == 0 else black, uci, ply)
            await white.recv("state")
            await black.recv("state")
        await black.send({"type": "draw_offer"})
        before = await white.recv("state")
    async with (
        connect(base_url, game_id, "harry") as white,
        connect(base_url, game_id, "partner") as black,
    ):
        await black.hello()
        after = await white.hello()
        assert {k: v for k, v in after.items() if k != "online"} == {
            k: v for k, v in before.items() if k != "online"
        }


async def test_takeback_resign_rematch_and_pgn(base_url: str) -> None:
    game_id = create_game(base_url)
    async with (
        connect(base_url, game_id, "harry") as white,
        connect(base_url, game_id, "partner") as black,
    ):
        await white.hello()
        await black.hello()
        await move(white, "e2e4", 0)
        await black.recv("state")
        await white.send({"type": "takeback_request"})
        assert (await black.recv("state"))["takeback_from"] == "white"
        await black.send({"type": "takeback_accept"})
        state = await white.recv("state")
        while state["ply"] != 0:
            state = await white.recv("state")
        assert state["moves"] == [] and state["takeback_from"] is None
        await move(white, "d2d4", 0)
        await black.recv("state")
        await black.send({"type": "resign"})
        final = await white.recv("state")
        while final["status"] == "active":
            final = await white.recv("state")
        assert (final["status"], final["result"]) == ("resigned", "1-0")
        await white.send({"type": "rematch"})
        await black.send({"type": "rematch"})
        ready = await black.recv("rematch_ready")
        new_id = ready["game_id"]
        assert (await white.recv("rematch_ready"))["game_id"] == new_id
    with rest(base_url) as client:
        pgn = client.get(f"/api/games/{game_id}/pgn")
        assert pgn.status_code == 200
        assert "1. d4 1-0" in pgn.text and "e4" not in pgn.text.split("\n\n", 1)[1]
        assert pgn.headers["content-disposition"].startswith(
            'attachment; filename="labscloud-chess-'
        )
        rematch = client.get(f"/api/games/{new_id}").json()
        assert rematch["you"] == "black"  # colours swap
        games = client.get("/api/games").json()["games"]
        assert next(g for g in games if g["id"] == new_id)["rematch_of"] == game_id


async def test_upgrade_checks(base_url: str) -> None:
    game_id = create_game(base_url)
    ws_url = base_url.replace("http://", "ws://")
    with pytest.raises(websockets.InvalidStatus) as info:
        async with websockets.connect(
            f"{ws_url}/ws/games/{game_id}?as=harry",
            origin=Origin("https://evil.example"),
            open_timeout=TIMEOUT,
        ):
            pass
    assert info.value.response.status_code == 403
    with pytest.raises(websockets.InvalidStatus) as info:
        async with websockets.connect(
            f"{ws_url}/ws/games/00000000-0000-4000-8000-000000000000?as=harry",
            origin=Origin(base_url),
            open_timeout=TIMEOUT,
        ):
            pass
    assert info.value.response.status_code == 404
    plain = httpx.get(
        f"{base_url}/ws/games/{game_id}", params={"as": "harry"}, headers={"origin": base_url}
    )
    assert plain.status_code == 426
