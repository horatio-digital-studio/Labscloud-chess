"""Everything the server produces validates against docs/protocol.schema.json, and the
schema agrees with the strict client parser (contract tests, docs/test-plan.md §3)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from app.auth import KeyCache
from app.web import HttpRequest, HttpResponse, handle
from chess_core.protocol import ERROR_MESSAGES, ProtocolError, error_message, parse_client_message
from devserver.hub import Hub, LocalSocket, WebPorts
from tests.conftest import Clock, make_config

SCHEMA = json.loads(Path("docs/protocol.schema.json").read_text(encoding="utf-8"))
REGISTRY = Registry().with_resource(SCHEMA["$id"], Resource.from_contents(SCHEMA))
Draft202012Validator.check_schema(SCHEMA)


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"{SCHEMA['$id']}#/$defs/{name}"}, registry=REGISTRY)


def assert_valid(name: str, instance: Any) -> None:
    errors = sorted(validator(name).iter_errors(instance), key=lambda e: list(e.path))
    assert not errors, f"{name}: " + "; ".join(f"{list(e.path)}: {e.message}" for e in errors[:5])


JSON_HEADERS = {"content-type": "application/json"}


async def no_keys() -> Any:
    return {"keys": []}


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class World:
    def __init__(self, tmp: Path) -> None:
        (tmp / "game.html").write_text("x", encoding="utf-8")
        self.clock = Clock()
        self.hub = Hub(make_config(), clock=self.clock, chooser=lambda o: o[0])
        self.ports = WebPorts(self.hub, tmp)
        self.messages: list[dict[str, Any]] = []

    def rest(
        self,
        method: str,
        path: str,
        body: Any = None,
        query: dict[str, str] | None = None,
        player: str = "harry",
    ) -> tuple[int, Any]:
        raw = b"" if body is None else json.dumps(body).encode()
        response = run(
            handle(
                HttpRequest(method, path, {"as": player, **(query or {})}, JSON_HEADERS, raw),
                make_config(),
                KeyCache(no_keys),
                self.ports,
            )
        )
        assert isinstance(response, HttpResponse)
        return response.status, json.loads(response.body) if response.headers[
            "content-type"
        ].startswith("application/json") else response.body

    def connect(self, game_id: str, player: str) -> LocalSocket:
        sock = run(
            self.hub.connect(game_id, player, lambda text: self.messages.append(json.loads(text)))
        )
        assert sock is not None
        return sock

    def send(self, game_id: str, sock: LocalSocket, message: Any) -> None:
        run(
            self.hub.message(
                game_id, sock, message if isinstance(message, str) else json.dumps(message)
            )
        )


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def play_scenarios(world: World) -> None:
    """Drive games through every kind of state so all server messages get produced."""
    _, created = world.rest("POST", "/api/games", {"colour": "white"})
    game = created["game"]["id"]
    white, black = world.connect(game, "harry"), world.connect(game, "partner")
    world.send(game, white, {"type": "hello"})
    world.send(game, black, {"type": "hello", "since_ply": 0})
    world.send(game, white, {"type": "ping"})
    for ply, uci in enumerate(["e2e4", "e7e5", "d1h5", "b8c6", "f1c4"]):
        world.send(game, white if ply % 2 == 0 else black, {"type": "move", "uci": uci, "ply": ply})
    world.send(game, black, {"type": "draw_offer"})
    world.send(game, white, {"type": "draw_decline"})
    world.send(game, black, {"type": "takeback_request"})
    world.send(game, white, {"type": "takeback_decline"})
    world.send(game, black, {"type": "move", "uci": "g8f6", "ply": 5})
    world.send(game, black, {"type": "move", "uci": "a7a6", "ply": 6})  # NOT_YOUR_TURN error
    world.send(game, white, "garbage")  # BAD_MESSAGE
    world.send(game, black, {"type": "takeback_request"})  # undoes ...Nf6 only
    world.send(game, white, {"type": "takeback_accept"})
    world.send(game, black, {"type": "move", "uci": "a7a6", "ply": 5})
    world.send(game, white, {"type": "move", "uci": "h5f7", "ply": 6})  # Qxf7#
    world.send(game, white, {"type": "resign"})  # GAME_OVER error
    world.send(game, white, {"type": "rematch"})
    world.send(game, black, {"type": "rematch"})
    world.send(game, black, {"type": "rematch"})
    run(world.hub.disconnect(game, black))

    _, second = world.rest("POST", "/api/games", {"colour": "black"}, player="partner")
    game2 = second["game"]["id"]
    a, b = world.connect(game2, "harry"), world.connect(game2, "partner")
    for ply, uci in enumerate(["g1f3", "g8f6", "f3g1", "f6g8"] * 2):
        world.send(game2, a if ply % 2 == 0 else b, {"type": "move", "uci": uci, "ply": ply})
    world.send(game2, a, {"type": "draw_offer"})
    world.send(game2, a, {"type": "claim_draw"})


def test_every_server_message_matches_schema(world: World) -> None:
    play_scenarios(world)
    kinds = {m["type"] for m in world.messages}
    assert kinds == {"state", "presence", "error", "rematch_ready", "pong"}
    statuses = {m["status"] for m in world.messages if m["type"] == "state"}
    assert {"active", "checkmate", "draw_claimed"} <= statuses
    assert any(m["type"] == "state" and m["check"] for m in world.messages)
    assert any(m["type"] == "state" and m["can_claim_draw"] for m in world.messages)
    assert any(m["type"] == "state" and m["takeback_from"] for m in world.messages)
    assert any(m["type"] == "state" and m["draw_offer_from"] for m in world.messages)
    for message in world.messages:
        assert_valid("server_message", message)


def test_every_error_code_builds_valid_message() -> None:
    for code in ERROR_MESSAGES:
        assert_valid("server_error", error_message(code, None))
        assert_valid("rest_error", {"error": {"code": code, "message": ERROR_MESSAGES[code]}})


def test_rest_bodies_match_schema(world: World) -> None:
    play_scenarios(world)
    status, healthz = world.rest("GET", "/healthz")
    assert status == 200
    assert_valid("rest_healthz", healthz)
    assert_valid("rest_me", world.rest("GET", "/api/me")[1])
    assert_valid("rest_patch_me_request", {"name": "H", "notify": {"cooldown_minutes": 60}})
    assert_valid(
        "rest_me",
        world.rest("PATCH", "/api/me", {"name": "H", "notify": {"cooldown_minutes": 60}})[1],
    )
    for query in ({}, {"status": "active"}, {"status": "finished"}):
        listed = world.rest("GET", "/api/games", query=query)[1]
        assert listed["games"]
        assert_valid("rest_games_list", listed)
    assert_valid("rest_create_game_request", {"colour": "random"})
    status, created = world.rest("POST", "/api/games", {"colour": "random"})
    assert status == 201
    assert_valid("rest_create_game_response", created)
    assert_valid("rest_stats", world.rest("GET", "/api/stats")[1])
    assert_valid("server_state", world.rest("GET", f"/api/games/{created['game']['id']}")[1])
    for path in ("/api/games/00000000-0000-4000-8000-000000000000", "/nope"):
        assert_valid("rest_error", world.rest("GET", path)[1])
    assert_valid("rest_error", world.rest("PATCH", "/api/me", {"name": ""})[1])


GOOD_CLIENT = [
    {"type": "hello"},
    {"type": "hello", "since_ply": 3},
    {"type": "move", "uci": "e2e4", "ply": 0},
    {"type": "move", "uci": "a7a8q", "ply": 12},
    *(
        {"type": t}
        for t in (
            "resign",
            "draw_offer",
            "draw_accept",
            "draw_decline",
            "claim_draw",
            "takeback_request",
            "takeback_accept",
            "takeback_decline",
            "rematch",
            "ping",
        )
    ),
]
BAD_CLIENT = [
    {},
    {"type": "abort"},
    {"type": "move", "uci": "e2e4"},
    {"type": "move", "uci": "e2e4", "ply": 0, "x": 1},
    {"type": "move", "uci": "e2e4", "ply": -1},
    {"type": "move", "uci": "e2e4", "ply": True},
    {"type": "resign", "x": 1},
    {"type": "hello", "since_ply": -2},
]


@pytest.mark.parametrize("message", GOOD_CLIENT, ids=json.dumps)
def test_valid_client_messages_agree(message: dict[str, Any]) -> None:
    assert_valid("client_message", message)
    parse_client_message(json.dumps(message))


@pytest.mark.parametrize("message", BAD_CLIENT, ids=json.dumps)
def test_invalid_client_messages_agree(message: dict[str, Any]) -> None:
    assert list(validator("client_message").iter_errors(message))
    with pytest.raises(ProtocolError):
        parse_client_message(json.dumps(message))


def test_schema_and_parser_leave_uci_format_to_the_engine() -> None:
    # Both only length-limit uci so the server can answer BAD_FORMAT in the documented
    # order (protocol.md §5); the canonical pattern is checked by the engine.
    message = {"type": "move", "uci": "e1h1x", "ply": 0}
    assert_valid("client_message", message)
    assert parse_client_message(json.dumps(message)).uci == "e1h1x"
    too_long = {"type": "move", "uci": "a" * 17, "ply": 0}
    assert list(validator("client_message").iter_errors(too_long))
    with pytest.raises(ProtocolError):
        parse_client_message(json.dumps(too_long))
