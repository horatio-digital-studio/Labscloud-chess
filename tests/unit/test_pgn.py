"""PGN export (REQ-GAME-06, REQ-ACT-14)."""

from __future__ import annotations

from chess_core.pgn import export_pgn, pgn_date

EPOCH = 1_760_227_200_000  # 2025-10-12T00:00:00Z


def test_date_is_utc() -> None:
    assert pgn_date(EPOCH) == "2025.10.12"
    assert pgn_date(EPOCH - 1) == "2025.10.11"


def test_scholars_mate_exact() -> None:
    text = export_pgn(
        site="chess.labscloud.uk",
        epoch_ms=EPOCH,
        white="Harry",
        black="Partner",
        sans=["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7#"],
        result="1-0",
    )
    assert text == (
        '[Event "labscloud-chess"]\n'
        '[Site "chess.labscloud.uk"]\n'
        '[Date "2025.10.12"]\n'
        '[White "Harry"]\n'
        '[Black "Partner"]\n'
        '[Result "1-0"]\n'
        "\n"
        "1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n"
    )


def test_active_game_uses_star_and_odd_ply() -> None:
    text = export_pgn(site="s", epoch_ms=EPOCH, white="A", black="B", sans=["e4"], result=None)
    assert '[Result "*"]' in text
    assert text.endswith("\n\n1. e4 *\n")


def test_empty_game() -> None:
    assert export_pgn(
        site="s", epoch_ms=EPOCH, white="A", black="B", sans=[], result=None
    ).endswith("\n\n*\n")


def test_tag_escaping() -> None:
    text = export_pgn(
        site="s", epoch_ms=EPOCH, white='Har"ry\\', black="B\nC", sans=[], result="1/2-1/2"
    )
    assert '[White "Har\\"ry\\\\"]' in text
    assert '[Black "B C"]' in text


def test_line_wrap_at_80() -> None:
    sans = ["Nf3", "Nf6", "Ng1", "Ng8"] * 30
    text = export_pgn(site="s", epoch_ms=EPOCH, white="A", black="B", sans=sans, result="1/2-1/2")
    movetext = text.split("\n\n", 1)[1].rstrip("\n").split("\n")
    assert len(movetext) > 1
    assert all(len(line) <= 80 for line in movetext)
    tokens = " ".join(movetext).split(" ")
    assert len(tokens) == 120 + 60 + 1  # moves + move numbers + result, no empty tokens
    assert tokens[:3] == ["1.", "Nf3", "Nf6"] and tokens[-2] == "Ng8"
    assert movetext[-1].endswith("1/2-1/2")
