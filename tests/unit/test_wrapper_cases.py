"""Validation order turn → ply → format → legality, through the game service (REQ-RULE-02/04)."""

from __future__ import annotations

from typing import Any

import pytest

from chess_core.protocol import ClientMessage
from tests.fixtures.positions import WRAPPER_CASES
from tests.unit.helpers import new_game, play_all


@pytest.mark.parametrize("case", WRAPPER_CASES, ids=[c["id"] for c in WRAPPER_CASES])
def test_wrapper_case(case: dict[str, Any]) -> None:
    service = new_game(case["fen"])
    play_all(service, case["moves"])
    before = service.row()
    outcome = service.handle(
        case["colour"], ClientMessage(type="move", uci=case["uci"], ply=case["ply"]), 9_999
    )
    assert outcome.error == case["error"]
    assert not outcome.changed
    assert service.row() == before  # REQ-RULE-03: nothing changed
