"""Resign, draws, takebacks, rematch (REQ-ACT-01..14)."""

from __future__ import annotations

from chess_core.engine import Colour
from tests.unit.helpers import act, move, new_game, play_all
from tests.unit.test_engine import SCHOLARS


def test_resign_on_either_turn() -> None:
    cases: tuple[tuple[Colour, str], ...] = (("white", "0-1"), ("black", "1-0"))
    for resigner, result in cases:
        service = new_game()
        outcome = act(service, resigner, "resign")  # white to move, either may resign
        row = service.row()
        assert outcome.ended and (row.status, row.result) == ("resigned", result)


def test_actions_after_game_over_rejected() -> None:
    service = new_game()
    act(service, "white", "resign")
    for kind in (
        "resign",
        "draw_offer",
        "draw_accept",
        "draw_decline",
        "claim_draw",
        "takeback_request",
        "takeback_accept",
        "takeback_decline",
    ):
        assert act(service, "black", kind).error == "GAME_OVER", kind
    assert move(service, "e2e4", colour="white").error == "GAME_OVER"


def test_draw_offer_recorded() -> None:
    service = new_game()
    assert act(service, "white", "draw_offer").changed
    assert service.row().draw_offer_from == "white"


def test_repeat_offer_rejected() -> None:
    service = new_game()
    act(service, "white", "draw_offer")
    assert act(service, "white", "draw_offer").error == "DRAW_ALREADY_OFFERED"


def test_draw_accept() -> None:
    service = new_game()
    act(service, "white", "draw_offer")
    outcome = act(service, "black", "draw_accept")
    row = service.row()
    assert outcome.ended and (row.status, row.result, row.draw_offer_from) == (
        "draw_agreed",
        "1/2-1/2",
        None,
    )


def test_no_draw_offer() -> None:
    service = new_game()
    assert act(service, "black", "draw_accept").error == "NO_DRAW_OFFER"
    assert act(service, "black", "draw_decline").error == "NO_DRAW_OFFER"


def test_own_draw_offer() -> None:
    service = new_game()
    act(service, "white", "draw_offer")
    assert act(service, "white", "draw_accept").error == "OWN_DRAW_OFFER"
    assert act(service, "white", "draw_decline").error == "OWN_DRAW_OFFER"


def test_draw_decline_clears() -> None:
    service = new_game()
    act(service, "white", "draw_offer")
    assert act(service, "black", "draw_decline").changed
    assert service.row().draw_offer_from is None


def test_crossing_offers_accept() -> None:
    service = new_game()
    act(service, "white", "draw_offer")
    outcome = act(service, "black", "draw_offer")
    assert outcome.ended and service.row().status == "draw_agreed"


def test_offer_cleared_by_recipient_move() -> None:
    service = new_game()
    play_all(service, ["e2e4"])
    act(service, "white", "draw_offer")
    move(service, "e7e5")  # black, the recipient, moves
    assert service.row().draw_offer_from is None


def test_offer_not_cleared_by_offerer_move() -> None:
    service = new_game()
    act(service, "white", "draw_offer")
    move(service, "e2e4")  # white, the offerer, moves
    assert service.row().draw_offer_from == "white"


def test_takeback_request_recorded() -> None:
    service = new_game()
    play_all(service, ["e2e4"])
    assert act(service, "white", "takeback_request").changed
    assert service.row().takeback_from == "white"


def test_takeback_not_available_without_own_move() -> None:
    service = new_game()
    assert act(service, "white", "takeback_request").error == "TAKEBACK_NOT_AVAILABLE"
    play_all(service, ["e2e4"])
    assert act(service, "black", "takeback_request").error == "TAKEBACK_NOT_AVAILABLE"


def test_takeback_already_requested() -> None:
    service = new_game()
    play_all(service, ["e2e4", "e7e5"])
    act(service, "white", "takeback_request")
    assert act(service, "white", "takeback_request").error == "TAKEBACK_ALREADY_REQUESTED"
    assert act(service, "black", "takeback_request").error == "TAKEBACK_ALREADY_REQUESTED"


def test_takeback_one_ply_on_opponents_turn() -> None:
    service = new_game()
    play_all(service, ["e2e4", "e7e5", "g1f3"])
    fen_before = service.row().current_fen
    act(service, "white", "takeback_request")  # black to move: undo white's Nf3 only
    act(service, "black", "takeback_accept")
    row = service.row()
    assert row.ply == 2 and row.takeback_from is None
    assert [m["uci"] for m in service.moves()] == ["e2e4", "e7e5"]
    assert row.current_fen != fen_before
    assert row.current_fen == "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"


def test_takeback_two_plies_on_requesters_turn() -> None:
    service = new_game()
    play_all(service, ["e2e4", "e7e5", "g1f3", "b8c6"])
    act(service, "white", "takeback_request")  # white to move: undo ...Nc6 and Nf3
    act(service, "black", "takeback_accept")
    row = service.row()
    assert row.ply == 2
    assert [m["uci"] for m in service.moves()] == ["e2e4", "e7e5"]


def test_takeback_to_start_restores_start_fen() -> None:
    service = new_game()
    play_all(service, ["e2e4"])
    act(service, "white", "takeback_request")
    act(service, "black", "takeback_accept")
    row = service.row()
    assert row.ply == 0 and row.current_fen == row.start_fen and service.moves() == []


def test_takeback_cleared_by_move() -> None:
    service = new_game()
    play_all(service, ["e2e4"])
    act(service, "white", "takeback_request")
    move(service, "e7e5")
    assert service.row().takeback_from is None
    assert act(service, "black", "takeback_accept").error == "NO_TAKEBACK_REQUEST"


def test_no_takeback_request() -> None:
    service = new_game()
    assert act(service, "white", "takeback_accept").error == "NO_TAKEBACK_REQUEST"
    assert act(service, "white", "takeback_decline").error == "NO_TAKEBACK_REQUEST"


def test_own_takeback_request() -> None:
    service = new_game()
    play_all(service, ["e2e4"])
    act(service, "white", "takeback_request")
    assert act(service, "white", "takeback_accept").error == "OWN_TAKEBACK_REQUEST"
    assert act(service, "white", "takeback_decline").error == "OWN_TAKEBACK_REQUEST"
    assert act(service, "black", "takeback_decline").changed
    assert service.row().takeback_from is None


def test_takeback_clears_draw_offer() -> None:
    service = new_game()
    play_all(service, ["e2e4", "e7e5"])
    act(service, "black", "draw_offer")
    act(service, "black", "takeback_request")
    act(service, "white", "takeback_accept")
    assert service.row().draw_offer_from is None


def test_takeback_removes_moves_pgn_and_counts() -> None:
    service = new_game()
    play_all(service, ["g1f3", "g8f6", "f3g1", "f6g8", "g1f3"])
    counts_before = service.counts()
    act(service, "white", "takeback_request")
    act(service, "black", "takeback_accept")
    assert service.row().ply == 4
    assert service.pgn("x").split("\n\n")[1].strip() == "1. Nf3 Nf6 2. Ng1 Ng8 *"
    counts_after = service.counts()
    assert sum(counts_after.values()) == sum(counts_before.values()) - 1
    # positions with zero count are deleted
    assert all(v > 0 for v in counts_after.values())


def test_takeback_restores_castling_rights() -> None:
    service = new_game("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    play_all(service, ["e1g1"])
    act(service, "white", "takeback_request")
    act(service, "black", "takeback_accept")
    assert service.row().current_fen == "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
    assert move(service, "e1c1").error is None


def test_rematch_before_end_rejected() -> None:
    service = new_game()
    assert act(service, "white", "rematch").error == "REMATCH_NOT_AVAILABLE"


def test_rematch_votes_and_ready() -> None:
    service = new_game()
    play_all(service, SCHOLARS)
    first = act(service, "white", "rematch")
    assert first.changed and not first.needs_rematch
    second = act(service, "black", "rematch")
    assert second.needs_rematch
    service.set_rematch_game("new-id", 9)
    service.set_rematch_game("other-id", 10)  # idempotent
    assert service.row().rematch_game_id == "new-id"
    assert act(service, "white", "rematch").rematch_ready == "new-id"


def test_diag_move_plays_for_side_to_move() -> None:
    service = new_game()
    assert service.diag_move("e2e4", 1).error is None
    assert service.diag_move("e7e5", 2).error is None
    assert service.diag_move("e7e5", 3).error == "ILLEGAL_MOVE"
    assert service.row().ply == 2
