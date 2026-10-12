"""Lobby service and core: names, preferences, game index, stats, emails
(REQ-GAME-01/03/04/05/08/09, REQ-NOTIFY-01/04/06)."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import pytest

from app.lobby_service import COOLDOWN_STEPS, LobbyError, LobbyService, NewGame, validate_name
from app.storage import SqliteStorage
from devserver.hub import Hub
from tests.conftest import Clock, make_config

UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def service() -> LobbyService:
    return LobbyService(SqliteStorage(), make_config().players)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


# --- names --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [("Harry", "Harry"), ("  Sam  ", "Sam"), ("x" * 24, "x" * 24), ("Zoë 🙂", "Zoë 🙂")],
)
def test_validate_name_accepts(raw: str, expected: str) -> None:
    assert validate_name(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "   ", "x" * 25, "a\nb", "a\tb", "a\x7fb", "a\x85b", "a\x9fb", None, 5, ["Harry"]]
)
def test_validate_name_rejects(raw: Any) -> None:
    with pytest.raises(LobbyError) as info:
        validate_name(raw)
    assert (info.value.code, info.value.status) == ("BAD_REQUEST", 400)


def test_default_names_from_config_then_saved() -> None:
    lobby = service()
    assert lobby.names() == {"harry": "Harry", "partner": "Partner"}
    lobby.update_me("partner", {"name": "  Sam "})
    assert lobby.names() == {"harry": "Harry", "partner": "Sam"}
    assert lobby.me("partner")["name"] == "Sam"


# --- preferences --------------------------------------------------------------------------------


def test_me_defaults() -> None:
    assert service().me("harry") == {
        "player": "harry",
        "name": "Harry",
        "notify": {"invites": True, "your_move": True, "cooldown_minutes": 30},
    }


def test_update_notify_subset() -> None:
    lobby = service()
    me = lobby.update_me("harry", {"notify": {"your_move": False, "cooldown_minutes": 1440}})
    assert me["notify"] == {"invites": True, "your_move": False, "cooldown_minutes": 1440}
    me = lobby.update_me("harry", {"notify": {"invites": False}})
    assert me["notify"] == {"invites": False, "your_move": False, "cooldown_minutes": 1440}


@pytest.mark.parametrize("minutes", COOLDOWN_STEPS)
def test_every_cooldown_step_accepted(minutes: int) -> None:
    assert (
        service().update_me("harry", {"notify": {"cooldown_minutes": minutes}})["notify"][
            "cooldown_minutes"
        ]
        == minutes
    )


def test_cooldown_steps_match_requirement() -> None:
    assert COOLDOWN_STEPS == (5, 10, 15, 30, 45, 60, 120, 240, 480, 720, 1440)


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        [],
        {"email": "x@y"},
        {"name": "ok", "extra": 1},
        {"notify": {}},
        {"notify": None},
        {"notify": {"invites": 1}},
        {"notify": {"your_move": "yes"}},
        {"notify": {"cooldown_minutes": 31}},
        {"notify": {"cooldown_minutes": 30.0001}},
        {"notify": {"cooldown_minutes": True}},
        {"notify": {"cooldown_minutes": "30"}},
        {"notify": {"sound": True}},
        {"name": ""},
        {"name": "ok", "notify": {"cooldown_minutes": 7}},  # all-or-nothing
    ],
)
def test_update_me_rejects_and_changes_nothing(body: Any) -> None:
    lobby = service()
    before = lobby.me("harry")
    with pytest.raises(LobbyError):
        lobby.update_me("harry", body)
    assert lobby.me("harry") == before


def test_unknown_player() -> None:
    with pytest.raises(LobbyError) as info:
        service().me("mallory")
    assert info.value.code == "NOT_A_PLAYER"


# --- games ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "creator,colour,white,black",
    [
        ("harry", "white", "harry", "partner"),
        ("harry", "black", "partner", "harry"),
        ("partner", "white", "partner", "harry"),
        ("partner", "black", "harry", "partner"),
    ],
)
def test_plan_game_colours(creator: str, colour: str, white: str, black: str) -> None:
    plan = service().plan_game(creator, colour, lambda options: options[0])
    assert (plan.white, plan.black) == (white, black)
    assert UUID4.match(plan.id)


def test_plan_game_random_uses_chooser_with_both_options() -> None:
    seen: list[list[str]] = []

    def chooser(options: list[str]) -> str:
        seen.append(list(options))
        return "black"

    plan = service().plan_game("harry", "random", chooser)
    assert seen == [["white", "black"]]
    assert plan.black == "harry"


@pytest.mark.parametrize("colour", ["", "WHITE", "red", "None"])
def test_plan_game_bad_colour(colour: str) -> None:
    with pytest.raises(LobbyError):
        service().plan_game("harry", colour, lambda o: o[0])


def test_ids_unique() -> None:
    lobby = service()
    ids = {lobby.plan_game("harry", "white", lambda o: o[0]).id for _ in range(200)}
    assert len(ids) == 200


def _record(
    lobby: LobbyService,
    white: str,
    black: str,
    now: int,
    game_id: str,
    rematch_of: str | None = None,
) -> None:
    lobby.record_game(NewGame(game_id, white, black, rematch_of), now)


def test_list_games_order_filter_and_your_turn() -> None:
    lobby = service()
    _record(lobby, "harry", "partner", 1, "a")
    _record(lobby, "partner", "harry", 2, "b")
    _record(lobby, "harry", "partner", 3, "c")
    lobby.upsert_summary(
        {"id": "a", "status": "active", "result": None, "ply": 3, "updated_at": 10}
    )
    lobby.upsert_summary(
        {"id": "c", "status": "checkmate", "result": "1-0", "ply": 7, "updated_at": 5}
    )

    games = lobby.list_games("harry", None)
    assert [g["id"] for g in games] == ["a", "c", "b"]
    by_id = {g["id"]: g for g in games}
    assert by_id["a"]["you"] == "white" and by_id["a"]["your_turn"] is False  # ply 3: black to move
    assert (
        by_id["b"]["you"] == "black" and by_id["b"]["your_turn"] is False
    )  # ply 0: white (partner)
    assert by_id["c"]["your_turn"] is False  # finished
    assert lobby.list_games("partner", None)[2]["your_turn"] is True  # b: partner is white at ply 0
    assert [g["id"] for g in lobby.list_games("harry", "active")] == ["a", "b"]
    assert [g["id"] for g in lobby.list_games("harry", "finished")] == ["c"]
    with pytest.raises(LobbyError):
        lobby.list_games("harry", "done")


def test_summary_carries_names() -> None:
    lobby = service()
    _record(lobby, "harry", "partner", 1, "a")
    lobby.update_me("harry", {"name": "H"})
    game = lobby.list_games("partner", None)[0]
    assert game["white"] == {"player": "harry", "name": "H"}
    assert game["black"] == {"player": "partner", "name": "Partner"}


def test_stats() -> None:
    lobby = service()
    outcomes = [
        ("harry", "partner", "1-0"),
        ("harry", "partner", "0-1"),
        ("partner", "harry", "1-0"),
        ("partner", "harry", "1/2-1/2"),
        ("harry", "partner", None),
    ]
    for index, (white, black, result) in enumerate(outcomes):
        game_id = f"g{index}"
        _record(lobby, white, black, index, game_id)
        status = "active" if result is None else "resigned"
        lobby.upsert_summary(
            {"id": game_id, "status": status, "result": result, "ply": 4, "updated_at": 9}
        )
    assert lobby.stats() == {
        "players": {
            "harry": {"wins": 1, "losses": 2, "draws": 1},
            "partner": {"wins": 2, "losses": 1, "draws": 1},
        },
        "names": {"harry": "Harry", "partner": "Partner"},
        "finished_games": 4,
    }


def test_plan_rematch_swaps_and_is_idempotent() -> None:
    lobby = service()
    _record(lobby, "harry", "partner", 1, "old")
    plan = lobby.plan_rematch("old")
    assert isinstance(plan, NewGame)
    assert (plan.white, plan.black, plan.rematch_of) == ("partner", "harry", "old")
    lobby.record_game(plan, 2)
    again = lobby.plan_rematch("old")
    assert isinstance(again, dict) and again["id"] == plan.id
    with pytest.raises(LobbyError):
        lobby.plan_rematch("missing")


# --- nudges ----------------------------------------------------------------------------------


def test_nudge_throttle_uses_player_cooldown() -> None:
    lobby = service()
    lobby.update_me("partner", {"notify": {"cooldown_minutes": 5}})
    assert lobby.nudge_allowed("partner", 0) is True
    assert lobby.nudge_allowed("partner", 5 * 60_000 - 1) is False
    assert lobby.nudge_allowed("partner", 5 * 60_000) is True
    lobby.update_me("partner", {"notify": {"your_move": False}})
    assert lobby.nudge_allowed("partner", 10**12) is False


def test_migrate_idempotent_across_instances() -> None:
    storage = SqliteStorage()
    first = LobbyService(storage, make_config().players)
    first.update_me("harry", {"name": "H"})
    second = LobbyService(storage, make_config().players)
    assert second.display_name("harry") == "H"


# --- core via the hub -----------------------------------------------------------------------------


def hub(**overrides: Any) -> Hub:
    return Hub(make_config(**overrides), clock=Clock(), chooser=lambda o: o[0])


def test_create_game_rpc_and_invite_email() -> None:
    h = hub(email_enabled=True)
    status, body = run(h.lobby.rpc("create_game", {"player": "harry", "colour": "random"}))
    assert status == 201
    game_id = body["game"]["id"]
    assert body["url"] == f"/game/{game_id}"
    assert body["game"]["you"] == "white" and body["game"]["your_turn"] is True
    assert h.room(game_id).service.row().white == "harry"
    [email] = h.sent_emails
    assert email.to == "partner@example.test"
    assert email.subject == "Harry started a game — you're Black"
    assert f"http://localhost:8787/game/{game_id}" in email.text


def test_no_invite_when_disabled_or_opted_out() -> None:
    h = hub(email_enabled=False)
    run(h.lobby.rpc("create_game", {"player": "harry", "colour": "white"}))
    assert h.sent_emails == []
    h = hub(email_enabled=True)
    run(h.lobby.rpc("update_me", {"player": "partner", "body": {"notify": {"invites": False}}}))
    run(h.lobby.rpc("create_game", {"player": "harry", "colour": "white"}))
    assert h.sent_emails == []


def test_email_failure_does_not_break_creation() -> None:
    h = hub(email_enabled=True)

    async def boom(email: Any) -> None:
        raise RuntimeError("smtp down")

    h.lobby.ports.send_email = boom  # type: ignore[method-assign]
    status, body = run(h.lobby.rpc("create_game", {"player": "harry", "colour": "white"}))
    assert status == 201
    assert (
        run(h.lobby.rpc("list_games", {"player": "harry"}))[1]["games"][0]["id"]
        == body["game"]["id"]
    )


def test_rpc_errors() -> None:
    h = hub()
    assert run(h.lobby.rpc("nope", {})) == (404, {"code": "NOT_FOUND"})
    assert run(h.lobby.rpc("me", {})) == (400, {"code": "BAD_REQUEST"})
    assert run(h.lobby.rpc("create_game", {"player": "harry", "colour": "green"})) == (
        400,
        {"code": "BAD_REQUEST"},
    )
    assert run(h.lobby.rpc("create_rematch", {"old_game_id": "missing"})) == (
        404,
        {"code": "GAME_NOT_FOUND"},
    )


def test_create_game_fails_cleanly_if_room_init_fails() -> None:
    h = hub()

    async def broken_room(game_id: str, method: str, args: dict[str, Any]) -> tuple[int, Any]:
        return 500, {"code": "INTERNAL"}

    h.lobby.ports.room = broken_room  # type: ignore[method-assign]
    assert run(h.lobby.rpc("create_game", {"player": "harry", "colour": "white"})) == (
        500,
        {"code": "INTERNAL"},
    )
    assert run(h.lobby.rpc("list_games", {"player": "harry"}))[1]["games"] == []


def test_nudge_rpc_respects_settings() -> None:
    h = hub(email_enabled=True)
    args = {"to_player": "partner", "from_player": "harry", "game_id": "g", "last_move": "1. e4"}
    run(h.lobby.rpc("nudge", args))
    run(h.lobby.rpc("nudge", args))  # within 30 minutes: throttled
    assert len(h.sent_emails) == 1
    email = h.sent_emails[0]
    assert email.subject == "Your move against Harry"
    assert "Harry played 1. e4. It's your move." in email.text
    assert "every 30 minutes" in email.text


def test_game_over_rpc_emails_both() -> None:
    h = hub(email_enabled=True)
    run(h.lobby.rpc("game_over", {"game_id": "g", "line": "Harry won by checkmate", "pgn": "PGN"}))
    assert sorted(e.to for e in h.sent_emails) == ["harry@example.test", "partner@example.test"]
    assert all(e.subject == "Game over: Harry won by checkmate" for e in h.sent_emails)


def test_late_summary_never_overwrites_newer() -> None:
    lobby = service()
    _record(lobby, "harry", "partner", 1, "a")
    lobby.upsert_summary(
        {"id": "a", "status": "resigned", "result": "1-0", "ply": 3, "updated_at": 20}
    )
    lobby.upsert_summary(
        {"id": "a", "status": "active", "result": None, "ply": 2, "updated_at": 10}
    )
    game = lobby.list_games("harry", None)[0]
    assert (game["status"], game["ply"]) == ("resigned", 3)


def test_rematch_reservation_released_if_room_fails() -> None:
    h = hub()
    run(h.lobby.rpc("create_game", {"player": "harry", "colour": "white"}))
    old = run(h.lobby.rpc("list_games", {"player": "harry"}))[1]["games"][0]["id"]

    async def broken_room(game_id: str, method: str, args: dict[str, Any]) -> tuple[int, Any]:
        return 500, {"code": "INTERNAL"}

    real = h.lobby.ports.room
    h.lobby.ports.room = broken_room  # type: ignore[method-assign]
    assert run(h.lobby.rpc("create_rematch", {"old_game_id": old}))[0] == 500
    assert len(run(h.lobby.rpc("list_games", {"player": "harry"}))[1]["games"]) == 1
    h.lobby.ports.room = real  # type: ignore[method-assign]
    status, body = run(h.lobby.rpc("create_rematch", {"old_game_id": old}))
    assert status == 200 and h.room(body["game_id"]).service.exists()
