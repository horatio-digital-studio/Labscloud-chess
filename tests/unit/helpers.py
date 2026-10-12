"""Small helpers for driving GameService in tests."""

from __future__ import annotations

from app.game_service import GameService, Outcome
from app.storage import SqliteStorage
from chess_core.engine import STARTING_FEN, Colour, Position
from chess_core.protocol import ClientMessage

NAMES = {"harry": "Harry", "partner": "Partner"}


def new_game(fen: str = STARTING_FEN, now: int = 1_000, game_id: str = "g1") -> GameService:
    service = GameService(SqliteStorage())
    service.init(game_id, "harry", "partner", NAMES, now, start_fen=fen)
    return service


def turn_of(service: GameService) -> Colour:
    row = service.row()
    return Position(row.current_fen, service.counts()).turn


def move(service: GameService, uci: str, colour: Colour | None = None, now: int = 2_000) -> Outcome:
    row = service.row()
    who = colour or turn_of(service)
    return service.handle(who, ClientMessage(type="move", uci=uci, ply=row.ply), now)


def act(service: GameService, colour: Colour, kind: str, now: int = 3_000) -> Outcome:
    return service.handle(colour, ClientMessage(type=kind), now)


def play_all(service: GameService, ucis: list[str]) -> None:
    for uci in ucis:
        outcome = move(service, uci)
        assert outcome.error is None, (uci, outcome.error)
