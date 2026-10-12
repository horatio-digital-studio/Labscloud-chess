"""Property tests P1–P7 from docs/test-plan.md, using python-chess's full-history Board as
the oracle for our FEN-plus-counts design (ADR-0007, ADR-0011)."""

from __future__ import annotations

import json
import string

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import chess
from app.game_service import GameService
from chess_core.engine import COLOURS, STARTING_FEN, Colour, Position, initial_counts, other
from chess_core.pgn import export_pgn
from chess_core.protocol import SIMPLE_TYPES, ClientMessage, ProtocolError, parse_client_message
from tests.unit.helpers import act, move, new_game

SETTINGS = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def choose_move(data: st.DataObject, board: chess.Board) -> chess.Move:
    """A random legal move, often the reverse of our move two plies ago so that
    positions repeat and the repetition logic is actually exercised."""
    legal = sorted(board.legal_moves, key=lambda m: m.uci())
    if len(board.move_stack) >= 2 and data.draw(st.booleans()):
        previous = board.move_stack[-2]
        back = chess.Move(previous.to_square, previous.from_square)
        if back in legal:
            return back
    return data.draw(st.sampled_from(legal))


def oracle_claim(board: chess.Board) -> bool:
    return board.halfmove_clock >= 100 or board.is_repetition(3)


def oracle_status(board: chess.Board) -> str:
    if board.is_checkmate():
        return "checkmate"
    if board.is_stalemate():
        return "stalemate"
    if board.is_insufficient_material():
        return "insufficient_material"
    if board.is_seventyfive_moves():
        return "seventyfive_moves"
    if board.is_fivefold_repetition():
        return "fivefold_repetition"
    return "active"


def assert_matches(service: GameService, board: chess.Board) -> None:
    row = service.row()
    position = Position(row.current_fen, service.counts())
    assert row.current_fen == board.fen()  # P1
    assert position.legal_ucis() == sorted(m.uci() for m in board.legal_moves)  # P4
    assert position.is_check == board.is_check()
    assert row.status == oracle_status(board)  # P3 (fivefold)
    if row.status == "active":
        assert position.can_claim_draw() == oracle_claim(board)  # P3 (threefold / fifty)


@SETTINGS
@given(st.data(), st.integers(min_value=0, max_value=80))
def test_p1_p3_p4_random_games_match_oracle(data: st.DataObject, length: int) -> None:
    service = new_game()
    board = chess.Board()
    for _ in range(length):
        if service.row().status != "active":
            break
        chosen = choose_move(data, board)
        assert move(service, chosen.uci()).error is None
        board.push(chosen)
        assert_matches(service, board)
    # P4: a fresh service over the same storage (as after eviction) agrees too.
    rebuilt = GameService(service.storage)
    assert rebuilt.states({}) == service.states({})


@SETTINGS
@given(
    st.text(alphabet=string.ascii_lowercase + string.digits + "=-+#xO ", max_size=7)
    | st.builds(
        lambda f, r, f2, r2, p: f + r + f2 + r2 + p,
        st.sampled_from("abcdefghi"),
        st.sampled_from("0123456789"),
        st.sampled_from("abcdefghi"),
        st.sampled_from("0123456789"),
        st.sampled_from(["", "q", "r", "b", "n", "k", "p", "Q"]),
    )
)
def test_p2_only_legal_ucis_accepted(uci: str) -> None:
    service = new_game("r3k2r/pPpp1ppp/8/4pP2/8/8/P1PPP1PP/R3K2R w KQkq e6 0 2")
    board = chess.Board(service.row().current_fen)
    legal = {m.uci() for m in board.legal_moves}
    outcome = move(service, uci, colour="white")
    assert (outcome.error is None) == (uci in legal)
    if outcome.error is not None:
        assert outcome.error in ("BAD_FORMAT", "ILLEGAL_MOVE")
        assert service.row().ply == 0


@SETTINGS
@given(st.data(), st.integers(min_value=0, max_value=120))
def test_p5_pgn_reparses_to_same_moves(data: st.DataObject, length: int) -> None:
    board = chess.Board()
    sans: list[str] = []
    for _ in range(length):
        if board.is_game_over():
            break
        chosen = choose_move(data, board)
        sans.append(board.san(chosen))
        board.push(chosen)
    text = export_pgn(site="s", epoch_ms=0, white="A", black="B", sans=sans, result=None)
    movetext = text.split("\n\n", 1)[1].split()
    replay = chess.Board()
    reparsed: list[str] = []
    for token in movetext[:-1]:
        if token.endswith("."):
            continue
        played = replay.parse_san(token)
        reparsed.append(replay.san(played))
        replay.push(played)
    assert reparsed == sans and movetext[-1] == "*"
    assert all(len(line) <= 80 for line in text.splitlines())


client_messages = st.one_of(
    st.builds(
        lambda u, p: ClientMessage("move", u, p),
        st.from_regex(r"[a-h][1-8][a-h][1-8][qrbn]?", fullmatch=True),
        st.integers(min_value=0, max_value=10_000),
    ),
    st.builds(
        lambda s: ClientMessage("hello", since_ply=s),
        st.none() | st.integers(min_value=0, max_value=10_000),
    ),
    st.sampled_from(sorted(SIMPLE_TYPES)).map(ClientMessage),
)


def to_json(message: ClientMessage) -> dict[str, object]:
    if message.type == "move":
        return {"type": "move", "uci": message.uci, "ply": message.ply}
    if message.type == "hello":
        return (
            {"type": "hello"}
            if message.since_ply is None
            else {"type": "hello", "since_ply": message.since_ply}
        )
    return {"type": message.type}


@SETTINGS
@given(
    client_messages,
    st.text(min_size=1, max_size=8).filter(lambda k: k not in ("type", "uci", "ply", "since_ply")),
    st.integers() | st.text(max_size=5) | st.none(),
)
def test_p6_protocol_round_trip_and_extra_fields(
    message: ClientMessage, key: str, value: object
) -> None:
    payload = to_json(message)
    assert parse_client_message(json.dumps(payload)) == message
    try:
        parse_client_message(json.dumps({**payload, key: value}))
    except ProtocolError:
        pass
    else:
        raise AssertionError("an extra field was accepted")


@SETTINGS
@given(st.data(), st.integers(min_value=1, max_value=60))
def test_p7_takebacks_match_board_pop(data: st.DataObject, steps: int) -> None:
    service = new_game()
    board = chess.Board()
    for _ in range(steps):
        if service.row().status != "active":
            break
        row = service.row()
        mover = "white" if board.turn == chess.WHITE else "black"
        requester_options: list[Colour] = [
            c
            for c in COLOURS
            if any((index % 2 == 0) == (c == "white") for index in range(row.ply))
        ]
        if requester_options and data.draw(st.integers(0, 3)) == 0:
            requester = data.draw(st.sampled_from(requester_options))
            assert act(service, requester, "takeback_request").error is None
            responder = other(requester)
            assert act(service, responder, "takeback_accept").error is None
            # One ply if the requester moved last, two if the opponent has replied since.
            board.pop()
            if mover == requester:
                board.pop()
        else:
            chosen = choose_move(data, board)
            assert move(service, chosen.uci()).error is None
            board.push(chosen)
        assert service.row().ply == len(board.move_stack)
        assert_matches(service, board)
        assert [m["uci"] for m in service.moves()] == [m.uci() for m in board.move_stack]


def test_initial_counts_use_canonical_fen() -> None:
    # A FEN with a pointless en passant square must count as the same position.
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
    assert initial_counts(fen) == {"rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -": 1}
    assert initial_counts() == {" ".join(STARTING_FEN.split()[:4]): 1}
