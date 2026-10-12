"""GameService move handling, status order, draw claims (REQ-RULE-02/03/06/07/08/09, REQ-RT-09)."""

from __future__ import annotations

from app.game_service import GameService
from chess_core.engine import Position, initial_counts, position_key
from chess_core.protocol import ClientMessage
from tests.unit.helpers import act, move, new_game, play_all

SCHOLARS = ["e2e4", "e7e5", "d1h5", "b8c6", "f1c4", "g8f6", "h5f7"]
KNIGHT_DANCE = ["g1f3", "g8f6", "f3g1", "f6g8"]


def test_rejected_move_leaves_state_unchanged() -> None:
    service = new_game()
    before = (service.row(), service.moves(), service.counts())
    for uci in ("e2e5", "e7e5", "zz99", "e1h1"):
        outcome = move(service, uci, colour="white")
        assert outcome.error is not None
    assert (service.row(), service.moves(), service.counts()) == before


def test_accepted_move_persisted_with_san_and_counts() -> None:
    service = new_game()
    outcome = move(service, "e2e4")
    assert outcome.error is None and outcome.changed and outcome.moved is not None
    assert outcome.moved.san == "e4"
    row = service.row()
    assert row.ply == 1 and row.status == "active"
    assert service.moves() == [{"ply": 1, "uci": "e2e4", "san": "e4", "by_colour": "white"}]
    assert service.counts()[position_key(row.current_fen)] == 1


def test_resend_same_ply_stale() -> None:
    service = new_game()
    first = service.handle("white", ClientMessage(type="move", uci="e2e4", ply=0), 1)
    second = service.handle("white", ClientMessage(type="move", uci="e2e4", ply=0), 2)
    assert first.error is None
    assert second.error == "NOT_YOUR_TURN"  # turn check comes before ply check
    black_resend = service.handle("black", ClientMessage(type="move", uci="e7e5", ply=0), 3)
    assert black_resend.error == "STALE_PLY"
    assert service.row().ply == 1


def test_status_order_checkmate_reported() -> None:
    service = new_game()
    play_all(service, SCHOLARS[:-1])
    outcome = move(service, SCHOLARS[-1])
    row = service.row()
    assert outcome.ended
    assert (row.status, row.result) == ("checkmate", "1-0")
    assert move(service, "a7a6", colour="black").error == "GAME_OVER"


def test_status_order_mate_beats_halfmove_clock() -> None:
    service = new_game("6k1/5ppp/8/8/8/8/8/3R2K1 w - - 149 80")
    move(service, "d1d8")
    assert service.row().status == "checkmate"


def test_can_claim_draw_threefold() -> None:
    service = new_game()
    play_all(service, KNIGHT_DANCE * 2)
    states = service.states({})
    assert states["white"]["can_claim_draw"] is True
    assert states["black"]["can_claim_draw"] is False


def test_can_claim_draw_fifty() -> None:
    service = new_game("8/8/8/4k3/8/8/8/R3K3 w - - 100 80")
    assert service.states({})["white"]["can_claim_draw"] is True


def test_can_claim_draw_only_for_side_to_move() -> None:
    service = new_game("8/8/8/4k3/8/8/8/R3K3 w - - 100 80")
    assert act(service, "black", "claim_draw").error == "NOT_YOUR_TURN"


def test_claim_draw_ends_game() -> None:
    service = new_game()
    assert act(service, "white", "claim_draw").error == "CANNOT_CLAIM"
    play_all(service, KNIGHT_DANCE * 2)
    outcome = act(service, "white", "claim_draw")
    row = service.row()
    assert outcome.ended and (row.status, row.result) == ("draw_claimed", "1/2-1/2")


def test_fivefold_ends_game_automatically() -> None:
    service = new_game()
    play_all(service, KNIGHT_DANCE * 4)
    assert service.row().status == "fivefold_repetition"


def test_promotion_requires_piece() -> None:
    service = new_game("8/P7/8/8/8/8/8/k6K w - - 0 1")
    assert move(service, "a7a8").error == "ILLEGAL_MOVE"
    assert move(service, "a7a8n").error is None
    assert service.moves()[-1]["san"].startswith("a8=N")


def test_castling_canonical_only() -> None:
    service = new_game("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    assert move(service, "e1h1").error == "ILLEGAL_MOVE"
    assert move(service, "e1g1").error is None
    assert service.moves()[-1]["san"] == "O-O"


def test_states_shape_and_legal_visibility() -> None:
    service = new_game()
    states = service.states({"white": True})
    white, black = states["white"], states["black"]
    assert white["you"] == "white" and black["you"] == "black"
    assert len(white["legal"]) == 20 and black["legal"] == []
    assert white["online"] == {"white": True, "black": False}
    assert white["last_move"] is None and white["moves"] == []
    play_all(service, ["e2e4"])
    states = service.states({})
    assert states["white"]["legal"] == [] and len(states["black"]["legal"]) == 20
    assert states["black"]["last_move"] == {"uci": "e2e4", "san": "e4"}


def test_terminal_state_has_no_legal_moves() -> None:
    service = new_game()
    play_all(service, SCHOLARS)
    for state in service.states({}).values():
        assert state["legal"] == [] and state["check"] is True and state["can_claim_draw"] is False


def test_init_is_idempotent_and_counts_start_position() -> None:
    service = new_game()
    play_all(service, ["e2e4"])
    service.init("g1", "partner", "harry", {}, 5)
    row = service.row()
    assert (row.white, row.ply) == ("harry", 1)
    fresh = new_game()
    assert fresh.counts() == initial_counts()


def test_exists_and_not_found() -> None:
    from app.storage import SqliteStorage

    empty = GameService(SqliteStorage())
    assert empty.exists() is False
    assert new_game().exists() is True


def test_position_counts_not_mutated_by_caller_copy() -> None:
    counts = initial_counts()
    position = Position("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", counts)
    position.play("e2e4")
    assert counts == initial_counts()
