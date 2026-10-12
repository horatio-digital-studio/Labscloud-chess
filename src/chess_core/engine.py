"""Chess rules wrapper around python-chess.

Everything here works from a FEN plus stored repetition counts: no move-list replay,
so the CPU cost per move stays tiny regardless of game length (ADR-0007).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import chess

Colour = Literal["white", "black"]
COLOURS: tuple[Colour, Colour] = ("white", "black")
STARTING_FEN = chess.STARTING_FEN
UCI_RE = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")

# Statuses set by the rules after a move, checked in this order (REQ-RULE-07).
RULE_STATUSES = (
    "checkmate",
    "stalemate",
    "insufficient_material",
    "seventyfive_moves",
    "fivefold_repetition",
)
ACTION_STATUSES = ("resigned", "draw_agreed", "draw_claimed")
TERMINAL_STATUSES = frozenset(RULE_STATUSES + ACTION_STATUSES)


def other(colour: Colour) -> Colour:
    return "black" if colour == "white" else "white"


def position_key(fen: str) -> str:
    """Repetition key: placement, side to move, castling rights, en passant square.

    python-chess's ``board.fen()`` only shows the en passant square when a legal
    en passant capture exists, which is exactly the FIDE notion of "same position".
    """
    return " ".join(fen.split()[:4])


def win_for(colour: Colour) -> str:
    return "1-0" if colour == "white" else "0-1"


@dataclass(frozen=True)
class PlayedMove:
    uci: str
    san: str
    fen_after: str
    key_after: str
    by_colour: Colour


class Position:
    """A board built from one FEN, with the game's repetition counts alongside."""

    def __init__(self, fen: str, counts: Mapping[str, int]) -> None:
        self.board = chess.Board(fen)
        self.counts = dict(counts)

    @property
    def turn(self) -> Colour:
        return "white" if self.board.turn == chess.WHITE else "black"

    @property
    def fen(self) -> str:
        return self.board.fen()

    @property
    def is_check(self) -> bool:
        return self.board.is_check()

    def legal_ucis(self) -> list[str]:
        return sorted(move.uci() for move in self.board.legal_moves)

    def move_error(self, colour: Colour, uci: str) -> str | None:
        """Turn, format and legality checks in the documented order (REQ-RULE-02).

        Ply and game-over checks belong to the caller, which knows the stored ply.
        Legality compares canonical UCI strings: python-chess would also accept the
        king-takes-rook castling form ``e1h1`` via ``Move in board.legal_moves``
        (REQ-RULE-04, catalogue W08).
        """
        if colour != self.turn:
            return "NOT_YOUR_TURN"
        if not UCI_RE.match(uci):
            return "BAD_FORMAT"
        if uci not in {move.uci() for move in self.board.legal_moves}:
            return "ILLEGAL_MOVE"
        return None

    def play(self, uci: str) -> PlayedMove:
        """Play an already-validated move and update the repetition counts."""
        by = self.turn
        move = chess.Move.from_uci(uci)
        san = self.board.san(move)
        self.board.push(move)
        fen_after = self.board.fen()
        key = position_key(fen_after)
        self.counts[key] = self.counts.get(key, 0) + 1
        return PlayedMove(uci=uci, san=san, fen_after=fen_after, key_after=key, by_colour=by)

    def verdict(self) -> tuple[str, str | None]:
        """(status, result) for the current position, rules checked in order."""
        board = self.board
        if board.is_checkmate():
            return "checkmate", win_for("black" if board.turn == chess.WHITE else "white")
        if board.is_stalemate():
            return "stalemate", "1/2-1/2"
        if board.is_insufficient_material():
            return "insufficient_material", "1/2-1/2"
        if board.is_seventyfive_moves():
            return "seventyfive_moves", "1/2-1/2"
        if self.counts.get(position_key(board.fen()), 0) >= 5:
            return "fivefold_repetition", "1/2-1/2"
        return "active", None

    def can_claim_draw(self) -> bool:
        """REQ-RULE-08: current position seen 3+ times, or 100+ halfmoves."""
        if self.board.halfmove_clock >= 100:
            return True
        return self.counts.get(position_key(self.board.fen()), 0) >= 3


def initial_counts(fen: str = STARTING_FEN) -> dict[str, int]:
    return {position_key(chess.Board(fen).fen()): 1}
