"""Email templates against docs/email-copy.md, result lines, move labels, logging
(REQ-NOTIFY-01..03, REQ-NFR-06)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.log import log_line
from app.notify import game_over_email, invite_email, move_label, result_line, your_move_email
from app.storage import SqliteStorage

DOC = Path("docs/email-copy.md").read_text(encoding="utf-8")
FIXTURES = Path("tests/fixtures/emails")
URL = "https://chess-staging.labscloud.uk/game/7d3c9a2e-5b1f-4c8e-9a0d-2f6b8e1c4a77"
PGN = (
    '[Event "labscloud-chess"]\n[Site "chess.labscloud.uk"]\n[Date "2026.10.12"]\n[White "Harry"]\n'
    '[Black "Partner"]\n[Result "1-0"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n'
)
VALUES = {
    "to_name": "Partner",
    "from_name": "Harry",
    "your_colour": "Black",
    "game_url": URL,
    "last_move_san": "1. e4",
    "cooldown_minutes": "30",
    "result_line": "Harry won by checkmate",
    "pgn": PGN.rstrip("\n"),
}


def doc_section(number: int) -> tuple[str, str]:
    """(subject, text) for section N of email-copy.md with the fixture values filled in."""
    section = DOC.split(f"\n## {number}. ", 1)[1].split("\n## ", 1)[0]
    subject = re.search(r"\*\*Subject:\*\* `([^`]+)`", section)
    body = re.search(r"```text\n(.*?)```", section, re.S)
    assert subject and body
    fill = lambda s: re.sub(r"\{(\w+)\}", lambda m: VALUES[m.group(1)], s)  # noqa: E731
    return fill(subject.group(1)), fill(body.group(1))


def rendered() -> dict[str, tuple[str, str, str]]:
    invite = invite_email(
        to="p@x", to_name="Partner", from_name="Harry", your_colour="black", game_url=URL
    )
    nudge = your_move_email(
        to="p@x",
        to_name="Partner",
        from_name="Harry",
        last_move_san="1. e4",
        game_url=URL,
        cooldown_minutes=30,
    )
    over = game_over_email(
        to="p@x", to_name="Partner", line="Harry won by checkmate", game_url=URL, pgn=PGN
    )
    return {
        name: (e.subject, e.text, e.html)
        for name, e in (("invite", invite), ("your_move", nudge), ("game_over", over))
    }


@pytest.mark.parametrize("number,name", [(1, "invite"), (2, "your_move"), (3, "game_over")])
def test_text_matches_email_copy_doc(number: int, name: str) -> None:
    subject, text = doc_section(number)
    got_subject, got_text, _ = rendered()[name]
    assert got_subject == subject
    assert got_text == text


@pytest.mark.parametrize("name", ["invite", "your_move", "game_over"])
def test_snapshots(name: str) -> None:
    _, text, html = rendered()[name]
    assert (FIXTURES / f"{name}.txt").read_text(encoding="utf-8") == text
    assert (FIXTURES / f"{name}.html").read_text(encoding="utf-8") == html


def test_html_has_one_link_no_images_and_escapes() -> None:
    email = invite_email(
        to="p@x", to_name="<b>P</b>", from_name="H&M", your_colour="white", game_url=URL
    )
    assert email.html.count("<a ") == 1 and "<img" not in email.html and "<link" not in email.html
    assert "&lt;b&gt;P&lt;/b&gt;" in email.html and "H&amp;M" in email.html


@pytest.mark.parametrize(
    "status,result,expected",
    [
        ("checkmate", "1-0", "Harry won by checkmate"),
        ("checkmate", "0-1", "Sam won by checkmate"),
        ("resigned", "1-0", "Sam resigned — Harry won"),
        ("resigned", "0-1", "Harry resigned — Sam won"),
        ("stalemate", "1/2-1/2", "Draw by stalemate"),
        ("draw_agreed", "1/2-1/2", "Draw by agreement"),
        ("draw_claimed", "1/2-1/2", "Draw by claim"),
        ("insufficient_material", "1/2-1/2", "Draw by insufficient material"),
        ("seventyfive_moves", "1/2-1/2", "Draw by the 75-move rule"),
        ("fivefold_repetition", "1/2-1/2", "Draw by fivefold repetition"),
    ],
)
def test_result_line(status: str, result: str, expected: str) -> None:
    assert result_line(status, result, "Harry", "Sam") == expected


@pytest.mark.parametrize(
    "ply,san,label",
    [(1, "e4", "1. e4"), (2, "e5", "1… e5"), (23, "Nf3", "12. Nf3"), (24, "Nxe4", "12… Nxe4")],
)
def test_move_label(ply: int, san: str, label: str) -> None:
    assert move_label(ply, san) == label


def test_log_drops_sensitive_fields() -> None:
    line = json.loads(
        log_line(
            "x",
            player="harry",
            email="a@b",
            Access_Token="t",
            jwt="j",
            cookie="c",
            client_secret="s",
            authorization="a",
            path="/api",
        )
    )
    assert line == {"event": "x", "player": "harry", "path": "/api"}


def test_sqlite_transaction_rolls_back_and_nests() -> None:
    storage = SqliteStorage()
    storage.execute("CREATE TABLE t (v INTEGER)")

    def failing() -> None:
        storage.execute("INSERT INTO t VALUES (1)")
        storage.transaction(lambda: storage.execute("INSERT INTO t VALUES (2)"))
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        storage.transaction(failing)
    assert storage.query("SELECT * FROM t") == []
    storage.transaction(lambda: storage.execute("INSERT INTO t VALUES (3)"))
    assert storage.query("SELECT v FROM t") == [{"v": 3}]
