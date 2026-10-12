"""Every verified position in docs/rules-catalogue.md against OUR engine (REQ-RULE-01)."""

from __future__ import annotations

from typing import Any

import pytest

from chess_core.engine import Position, initial_counts, position_key
from tests.fixtures.positions import POSITIONS


def _play_prefix(entry: dict[str, Any]) -> Position:
    position = Position(entry["fen"], initial_counts(entry["fen"]))
    for uci in entry["moves"]:
        assert position.move_error(position.turn, uci) is None, f"prefix move {uci} rejected"
        position.play(uci)
    return position


def _check(position: Position, expect: dict[str, Any], where: str) -> None:
    status, result = position.verdict()
    legal = position.legal_ucis()
    if "legal_count" in expect:
        assert len(legal) == expect["legal_count"], where
    for uci in expect.get("legal", []):
        assert position.move_error(position.turn, uci) is None, f"{where}: {uci} should be legal"
    for uci in expect.get("illegal", []):
        assert position.move_error(position.turn, uci) == "ILLEGAL_MOVE", (
            f"{where}: {uci} should be illegal"
        )
    if "status" in expect:
        assert status == expect["status"], where
    if "result" in expect:
        assert result == expect["result"], where
    if "check" in expect:
        assert position.is_check == expect["check"], where
    key = position_key(position.fen)
    if "claim_threefold" in expect:
        assert (position.counts.get(key, 0) >= 3) == expect["claim_threefold"], where
    if "claim_fifty" in expect:
        assert (position.board.halfmove_clock >= 100) == expect["claim_fifty"], where
    if "claim_draw" in expect:
        assert position.can_claim_draw() == expect["claim_draw"], where


@pytest.mark.parametrize("entry", POSITIONS, ids=[p["id"] for p in POSITIONS])
def test_position(entry: dict[str, Any]) -> None:
    position = _play_prefix(entry)
    expect = dict(entry["expect"])
    after = expect.pop("after_move", None)
    _check(position, expect, entry["id"])
    if after:
        after = dict(after)
        uci = after.pop("uci")
        assert position.move_error(position.turn, uci) is None, (
            f"{entry['id']}: {uci} should be legal"
        )
        position.play(uci)
        _check(position, after, f"{entry['id']} after {uci}")
