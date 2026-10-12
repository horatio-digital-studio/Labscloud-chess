"""GameRoom core through the in-process hub (REQ-RT-01..06/08, REQ-ACT-*, REQ-NOTIFY-02/03)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest

from devserver.hub import Hub, LocalSocket


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def last(sock: LocalSocket, kind: str | None = None) -> dict[str, Any]:
    for text in reversed(sock.outbox):
        message = json.loads(text)
        if kind is None or message["type"] == kind:
            return message
    raise AssertionError(f"no {kind} message")


def of_type(sock: LocalSocket, kind: str) -> list[dict[str, Any]]:
    return [m for m in (json.loads(t) for t in sock.outbox) if m["type"] == kind]


def new_game(hub: Hub, colour: str = "white") -> str:
    status, body = run(hub.lobby.rpc("create_game", {"player": "harry", "colour": colour}))
    assert status == 201
    return str(body["game"]["id"])


def connect(hub: Hub, game_id: str, player: str) -> LocalSocket:
    sock = run(hub.connect(game_id, player))
    assert sock is not None
    return sock


def send(hub: Hub, game_id: str, sock: LocalSocket, message: dict[str, Any] | str) -> None:
    raw = message if isinstance(message, str) else json.dumps(message)
    run(hub.message(game_id, sock, raw))


def play(hub: Hub, game_id: str, socks: dict[str, LocalSocket], ucis: list[str]) -> None:
    for uci in ucis:
        row = hub.room(game_id).service.row()
        mover = socks["white"] if row.ply % 2 == 0 else socks["black"]
        send(hub, game_id, mover, {"type": "move", "uci": uci, "ply": row.ply})
        assert hub.room(game_id).service.row().ply == row.ply + 1, (uci, mover.outbox[-1])


@pytest.fixture
def table(hub: Hub) -> tuple[Hub, str, dict[str, LocalSocket]]:
    game_id = new_game(hub)
    socks = {"white": connect(hub, game_id, "harry"), "black": connect(hub, game_id, "partner")}
    return hub, game_id, socks


def test_hello_returns_full_state(table: tuple[Hub, str, dict[str, LocalSocket]]) -> None:
    hub, game_id, socks = table
    send(hub, game_id, socks["white"], {"type": "hello", "since_ply": 99})
    state = last(socks["white"], "state")
    assert state["you"] == "white" and state["ply"] == 0 and len(state["legal"]) == 20
    assert state["online"] == {"white": True, "black": True}
    assert state["players"]["white"] == {"player": "harry", "name": "Harry"}
    assert of_type(socks["black"], "state") == []  # hello replies only to the sender


def test_hello_picks_up_renamed_player(table: tuple[Hub, str, dict[str, LocalSocket]]) -> None:
    hub, game_id, socks = table
    run(hub.lobby.rpc("update_me", {"player": "partner", "body": {"name": "Sam"}}))
    send(hub, game_id, socks["white"], {"type": "hello"})
    assert last(socks["white"], "state")["players"]["black"]["name"] == "Sam"
    assert "Sam" in run(hub.room(game_id).rpc("pgn", {}))[1]["pgn"]


def test_move_broadcasts_state_to_everyone(table: tuple[Hub, str, dict[str, LocalSocket]]) -> None:
    hub, game_id, socks = table
    send(hub, game_id, socks["white"], {"type": "move", "uci": "e2e4", "ply": 0})
    white, black = last(socks["white"], "state"), last(socks["black"], "state")
    assert white["ply"] == black["ply"] == 1
    assert white["legal"] == [] and len(black["legal"]) == 20
    assert black["last_move"] == {"uci": "e2e4", "san": "e4"}


def test_errors_go_only_to_sender(table: tuple[Hub, str, dict[str, LocalSocket]]) -> None:
    hub, game_id, socks = table
    before = len(socks["black"].outbox)
    send(hub, game_id, socks["white"], {"type": "move", "uci": "e2e5", "ply": 0})
    error = last(socks["white"])
    assert (
        error["type"] == "error"
        and error["code"] == "ILLEGAL_MOVE"
        and error["in_reply_to"] == "move"
    )
    assert len(socks["black"].outbox) == before


@pytest.mark.parametrize(
    "raw", ["nonsense", '{"type":"move","uci":"e2e4"}', '{"type":"x"}', "x" * 2000]
)
def test_bad_message(table: tuple[Hub, str, dict[str, LocalSocket]], raw: str) -> None:
    hub, game_id, socks = table
    before = hub.room(game_id).service.row()
    send(hub, game_id, socks["white"], raw)
    error = last(socks["white"])
    assert (error["type"], error["code"], error["in_reply_to"]) == ("error", "BAD_MESSAGE", None)
    assert hub.room(game_id).service.row() == before


def test_non_text_message(table: tuple[Hub, str, dict[str, LocalSocket]]) -> None:
    hub, game_id, socks = table
    run(hub.message(game_id, socks["white"], 12345))
    assert last(socks["white"])["code"] == "BAD_MESSAGE"


def test_ping_pong(table: tuple[Hub, str, dict[str, LocalSocket]]) -> None:
    hub, game_id, socks = table
    send(hub, game_id, socks["black"], {"type": "ping"})
    assert last(socks["black"]) == {"type": "pong", "v": 1, "t": hub.clock()}


def test_presence_on_connect_and_disconnect(hub: Hub) -> None:
    game_id = new_game(hub)
    white = connect(hub, game_id, "harry")
    assert of_type(white, "presence") == []  # nobody to tell when the first socket connects
    black = connect(hub, game_id, "partner")
    assert last(white, "presence")["online"] == {"white": True, "black": True}
    assert of_type(black, "presence") == []  # the newcomer gets presence via its hello state
    run(hub.disconnect(game_id, black))
    assert last(white, "presence")["online"] == {"white": True, "black": False}


def test_two_sockets_for_one_player(table: tuple[Hub, str, dict[str, LocalSocket]]) -> None:
    hub, game_id, socks = table
    phone = connect(hub, game_id, "harry")
    send(hub, game_id, socks["white"], {"type": "move", "uci": "d2d4", "ply": 0})
    assert last(phone, "state")["ply"] == 1 and last(phone, "state")["you"] == "white"
    run(hub.disconnect(game_id, phone))
    assert last(socks["black"], "presence")["online"] == {"white": True, "black": True}


def test_dead_socket_does_not_break_broadcast(
    table: tuple[Hub, str, dict[str, LocalSocket]],
) -> None:
    hub, game_id, socks = table
    zombie = connect(hub, game_id, "harry")

    def explode(text: str) -> None:
        raise RuntimeError("gone")

    zombie.send = explode  # type: ignore[method-assign]
    send(hub, game_id, socks["white"], {"type": "move", "uci": "e2e4", "ply": 0})
    assert last(socks["black"], "state")["ply"] == 1


def test_stranger_cannot_connect(hub: Hub) -> None:
    game_id = new_game(hub)
    assert run(hub.connect(game_id, "mallory")) is None


def test_lobby_summary_updated_after_move(table: tuple[Hub, str, dict[str, LocalSocket]]) -> None:
    hub, game_id, socks = table
    play(hub, game_id, socks, ["e2e4"])
    hub.clock.advance(5)  # type: ignore[attr-defined]
    games = run(hub.lobby.rpc("list_games", {"player": "partner"}))[1]["games"]
    assert games[0]["ply"] == 1 and games[0]["your_turn"] is True


def test_eviction_gives_identical_state(table: tuple[Hub, str, dict[str, LocalSocket]]) -> None:
    hub, game_id, socks = table
    play(hub, game_id, socks, ["e2e4", "e7e5", "g1f3"])
    send(hub, game_id, socks["black"], {"type": "draw_offer"})
    send(hub, game_id, socks["white"], {"type": "hello"})
    before = last(socks["white"], "state")
    hub.forget_memory()
    send(hub, game_id, socks["white"], {"type": "hello"})
    assert last(socks["white"], "state") == before
    play(hub, game_id, socks, ["b8c6"])
    assert last(socks["white"], "state")["ply"] == 4


def test_resign_ends_game_and_lobby_counts_it(
    table: tuple[Hub, str, dict[str, LocalSocket]],
) -> None:
    hub, game_id, socks = table
    send(hub, game_id, socks["black"], {"type": "resign"})
    state = last(socks["white"], "state")
    assert (state["status"], state["result"]) == ("resigned", "1-0")
    stats = run(hub.lobby.rpc("stats", {}))[1]
    assert stats["players"]["harry"]["wins"] == 1 and stats["finished_games"] == 1


def test_takeback_flow_over_sockets(table: tuple[Hub, str, dict[str, LocalSocket]]) -> None:
    hub, game_id, socks = table
    play(hub, game_id, socks, ["e2e4"])
    send(hub, game_id, socks["white"], {"type": "takeback_request"})
    assert last(socks["black"], "state")["takeback_from"] == "white"
    send(hub, game_id, socks["black"], {"type": "takeback_accept"})
    state = last(socks["white"], "state")
    assert state["ply"] == 0 and state["moves"] == [] and state["takeback_from"] is None
    assert len(state["legal"]) == 20


def test_rematch_flow(table: tuple[Hub, str, dict[str, LocalSocket]]) -> None:
    hub, game_id, socks = table
    send(hub, game_id, socks["white"], {"type": "resign"})
    send(hub, game_id, socks["white"], {"type": "rematch"})
    assert last(socks["black"], "state")["rematch"] == {
        "white": True,
        "black": False,
        "game_id": None,
    }
    send(hub, game_id, socks["black"], {"type": "rematch"})
    ready_white, ready_black = (
        last(socks["white"], "rematch_ready"),
        last(socks["black"], "rematch_ready"),
    )
    new_id = ready_white["game_id"]
    assert ready_black["game_id"] == new_id
    row = hub.room(new_id).service.row()
    assert (row.white, row.black) == ("partner", "harry")  # colours swap
    assert last(socks["white"], "state")["rematch"]["game_id"] == new_id
    # a late third vote just points at the same game
    send(hub, game_id, socks["white"], {"type": "rematch"})
    assert of_type(socks["white"], "rematch_ready")[-1]["game_id"] == new_id
    finished = run(hub.lobby.rpc("list_games", {"player": "harry", "status": "active"}))[1]["games"]
    assert [g["rematch_of"] for g in finished] == [game_id]


def test_rematch_retries_if_lobby_failed(table: tuple[Hub, str, dict[str, LocalSocket]]) -> None:
    hub, game_id, socks = table
    send(hub, game_id, socks["white"], {"type": "resign"})
    room = hub.room(game_id)
    real = room.ports.lobby

    async def down(method: str, args: dict[str, Any]) -> tuple[int, Any]:
        if method == "create_rematch":
            raise RuntimeError("lobby unavailable")
        return await real(method, args)

    room.ports.lobby = down  # type: ignore[method-assign]
    send(hub, game_id, socks["white"], {"type": "rematch"})
    send(hub, game_id, socks["black"], {"type": "rematch"})
    assert of_type(socks["white"], "rematch_ready") == []
    room.ports.lobby = real  # type: ignore[method-assign]
    send(hub, game_id, socks["black"], {"type": "rematch"})
    assert len(of_type(socks["white"], "rematch_ready")) == 1


def test_rpc_snapshot_and_exists(table: tuple[Hub, str, dict[str, LocalSocket]]) -> None:
    hub, game_id, _ = table
    room = hub.room(game_id)
    assert run(room.rpc("exists", {})) == (
        200,
        {"exists": True, "white": "harry", "black": "partner"},
    )
    status, state = run(room.rpc("snapshot", {"player": "partner"}))
    assert status == 200 and state["you"] == "black"
    assert run(room.rpc("snapshot", {"player": "mallory"})) == (403, {"code": "NOT_A_PLAYER"})
    assert run(room.rpc("snapshot", {})) == (400, {"code": "BAD_REQUEST"})
    assert run(room.rpc("whatever", {})) == (404, {"code": "NOT_FOUND"})
    empty = hub.room("00000000-0000-4000-8000-000000000000")
    assert run(empty.rpc("exists", {})) == (200, {"exists": False})
    assert run(empty.rpc("snapshot", {"player": "harry"})) == (404, {"code": "GAME_NOT_FOUND"})
    assert run(empty.rpc("pgn", {})) == (404, {"code": "GAME_NOT_FOUND"})


def test_rpc_pgn_includes_date(table: tuple[Hub, str, dict[str, LocalSocket]]) -> None:
    hub, game_id, _ = table
    status, body = run(hub.room(game_id).rpc("pgn", {}))
    assert (
        status == 200
        and body["date"].count("-") == 2
        and body["pgn"].startswith('[Event "labscloud-chess"]')
    )


def test_diag_move_rpc(hub_factory: Callable[..., Hub]) -> None:
    hub = hub_factory()
    game_id = new_game(hub)
    sock = connect(hub, game_id, "partner")
    assert run(hub.room(game_id).rpc("diag_move", {"uci": "e2e4"})) == (
        200,
        {"ok": True, "error": None, "ply": 1},
    )
    assert last(sock, "state")["ply"] == 1
    prod = hub_factory(app_env="production")
    prod_id = new_game(prod)
    assert run(prod.room(prod_id).rpc("diag_move", {"uci": "e2e4"})) == (404, {"code": "NOT_FOUND"})


# --- emails from the room ------------------------------------------------------------------------------


def test_nudge_only_when_opponent_offline(hub_factory: Callable[..., Hub]) -> None:
    hub = hub_factory(email_enabled=True)
    game_id = new_game(hub)
    hub.sent_emails.clear()  # the invite
    white = connect(hub, game_id, "harry")
    black = connect(hub, game_id, "partner")
    send(hub, game_id, white, {"type": "move", "uci": "e2e4", "ply": 0})
    assert hub.sent_emails == []  # partner is online
    run(hub.disconnect(game_id, black))
    send(hub, game_id, white, {"type": "takeback_request"})
    assert hub.sent_emails == []  # only moves nudge
    hub2 = hub_factory(email_enabled=True)
    game2 = new_game(hub2)
    hub2.sent_emails.clear()
    w2 = connect(hub2, game2, "harry")
    send(hub2, game2, w2, {"type": "move", "uci": "e2e4", "ply": 0})
    [email] = hub2.sent_emails
    assert email.to == "partner@example.test" and "Harry played 1. e4." in email.text


def test_game_over_email_with_pgn(hub_factory: Callable[..., Hub]) -> None:
    hub = hub_factory(email_enabled=True)
    game_id = new_game(hub)
    socks = {"white": connect(hub, game_id, "harry"), "black": connect(hub, game_id, "partner")}
    hub.sent_emails.clear()
    play(hub, game_id, socks, ["e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7"])
    assert len(hub.sent_emails) == 2
    assert all(e.subject == "Game over: Harry won by checkmate" for e in hub.sent_emails)
    assert all("4. Qxf7# 1-0" in e.text for e in hub.sent_emails)


def test_no_emails_when_disabled(table: tuple[Hub, str, dict[str, LocalSocket]]) -> None:
    hub, game_id, socks = table
    run(hub.disconnect(game_id, socks["black"]))
    send(hub, game_id, socks["white"], {"type": "move", "uci": "e2e4", "ply": 0})
    send(hub, game_id, socks["white"], {"type": "resign"})
    assert hub.sent_emails == []


def test_hello_repairs_lobby_index_after_failed_summary(
    table: tuple[Hub, str, dict[str, LocalSocket]],
) -> None:
    hub, game_id, socks = table
    room = hub.room(game_id)
    real = room.ports.lobby

    async def flaky(method: str, args: dict[str, Any]) -> tuple[int, Any]:
        if method == "summary":
            raise RuntimeError("lobby restarting")
        return await real(method, args)

    room.ports.lobby = flaky  # type: ignore[method-assign]
    send(hub, game_id, socks["black"], {"type": "resign"})
    room.ports.lobby = real  # type: ignore[method-assign]
    games = run(hub.lobby.rpc("list_games", {"player": "harry"}))[1]["games"]
    assert games[0]["status"] == "active"  # the index missed the end of the game
    send(hub, game_id, socks["white"], {"type": "hello"})
    games = run(hub.lobby.rpc("list_games", {"player": "harry"}))[1]["games"]
    assert (games[0]["status"], games[0]["your_turn"]) == ("resigned", False)
    assert run(hub.lobby.rpc("stats", {}))[1]["players"]["harry"]["wins"] == 1


def test_overlapping_rematch_requests_create_one_game(
    table: tuple[Hub, str, dict[str, LocalSocket]],
) -> None:
    hub, game_id, _ = table
    real_room = hub.lobby.ports.room

    async def slow_room(game: str, method: str, args: dict[str, Any]) -> tuple[int, Any]:
        await asyncio.sleep(0.01)  # yield, so the two requests really interleave
        return await real_room(game, method, args)

    hub.lobby.ports.room = slow_room  # type: ignore[method-assign]

    async def both() -> list[Any]:
        return list(
            await asyncio.gather(
                hub.lobby.rpc("create_rematch", {"old_game_id": game_id}),
                hub.lobby.rpc("create_rematch", {"old_game_id": game_id}),
            )
        )

    first, second = run(both())
    assert first[0] == second[0] == 200
    assert first[1]["game_id"] == second[1]["game_id"]
    games = run(hub.lobby.rpc("list_games", {"player": "harry"}))[1]["games"]
    assert [g["rematch_of"] for g in games].count(game_id) == 1
    assert hub.room(first[1]["game_id"]).service.exists()


def test_snapshot_and_pgn_use_current_names(table: tuple[Hub, str, dict[str, LocalSocket]]) -> None:
    hub, game_id, _ = table
    run(hub.lobby.rpc("update_me", {"player": "harry", "body": {"name": "H. Graham"}}))
    room = hub.room(game_id)
    assert (
        run(room.rpc("snapshot", {"player": "partner"}))[1]["players"]["white"]["name"]
        == "H. Graham"
    )
    run(hub.lobby.rpc("update_me", {"player": "partner", "body": {"name": "Sam"}}))
    assert '[Black "Sam"]' in run(room.rpc("pgn", {}))[1]["pgn"]


def test_room_logs_carry_game_id_and_ply(
    table: tuple[Hub, str, dict[str, LocalSocket]], capsys: pytest.CaptureFixture[str]
) -> None:
    hub, game_id, socks = table
    room = hub.room(game_id)

    async def down(method: str, args: dict[str, Any]) -> tuple[int, Any]:
        raise RuntimeError("down")

    room.ports.lobby = down  # type: ignore[method-assign]
    send(hub, game_id, socks["white"], {"type": "move", "uci": "e2e4", "ply": 0})
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    failure = next(x for x in lines if x["event"] == "lobby_call_failed")
    assert failure["game_id"] == game_id and failure["ply"] == 1
