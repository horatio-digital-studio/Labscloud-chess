"""Email templates (docs/email-copy.md) and the result lines they use."""

from __future__ import annotations

import html
from dataclasses import dataclass

REASONS = {
    "checkmate": "checkmate",
    "resigned": "resignation",
    "stalemate": "stalemate",
    "insufficient_material": "insufficient material",
    "seventyfive_moves": "the 75-move rule",
    "fivefold_repetition": "fivefold repetition",
    "draw_agreed": "agreement",
    "draw_claimed": "claim",
}


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str
    html: str


def _html(paragraphs: list[str], link_text: str, link: str, pre: str | None = None) -> str:
    body = "".join(f"<p>{html.escape(p)}</p>" for p in paragraphs)
    button = (
        f'<p><a href="{html.escape(link, quote=True)}" '
        'style="display:inline-block;padding:10px 18px;background:#d4a843;color:#22170f;'
        f'text-decoration:none;font-weight:bold;border-radius:6px">{html.escape(link_text)}</a></p>'
    )
    block = f"<pre>{html.escape(pre)}</pre>" if pre else ""
    return (
        '<!doctype html><html lang="en-GB"><body style="font-family:Georgia,serif;color:#22170f">'
        f"{body}{button}{block}<p>— labscloud chess</p></body></html>"
    )


def result_line(status: str, result: str | None, white_name: str, black_name: str) -> str:
    reason = REASONS.get(status, status)
    if result == "1-0":
        winner, loser = white_name, black_name
    elif result == "0-1":
        winner, loser = black_name, white_name
    else:
        return f"Draw by {reason}"
    if status == "resigned":
        return f"{loser} resigned — {winner} won"
    return f"{winner} won by {reason}"


def invite_email(
    *, to: str, to_name: str, from_name: str, your_colour: str, game_url: str
) -> Email:
    colour = your_colour.capitalize()
    text = (
        f"Hi {to_name},\n\n{from_name} has started a new game and you're playing {colour}.\n\n"
        f"Play: {game_url}\n\n— labscloud chess\n"
        "You're getting this because invite emails are on. Turn them off in the lobby settings.\n"
    )
    return Email(
        to=to,
        subject=f"{from_name} started a game — you're {colour}",
        text=text,
        html=_html(
            [f"Hi {to_name},", f"{from_name} has started a new game and you're playing {colour}."],
            "Play",
            game_url,
        ),
    )


def your_move_email(
    *,
    to: str,
    to_name: str,
    from_name: str,
    last_move_san: str,
    game_url: str,
    cooldown_minutes: int,
) -> Email:
    text = (
        f"Hi {to_name},\n\n{from_name} played {last_move_san}. It's your move.\n\n"
        f"Play: {game_url}\n\n— labscloud chess\n"
        f"At most one of these every {cooldown_minutes} minutes. Change this in the lobby settings.\n"
    )
    return Email(
        to=to,
        subject=f"Your move against {from_name}",
        text=text,
        html=_html(
            [f"Hi {to_name},", f"{from_name} played {last_move_san}. It's your move."],
            "Play",
            game_url,
        ),
    )


def game_over_email(*, to: str, to_name: str, line: str, game_url: str, pgn: str) -> Email:
    text = f"Hi {to_name},\n\n{line}.\n\nRematch or review: {game_url}\n\nMoves (PGN):\n{pgn}\n— labscloud chess\n"
    return Email(
        to=to,
        subject=f"Game over: {line}",
        text=text,
        html=_html([f"Hi {to_name},", f"{line}."], "Rematch or review", game_url, pre=pgn),
    )


def move_label(ply: int, san: str) -> str:
    """'12. Nf3' for White's moves, '12… Nxe4' for Black's (ply is 1-based)."""
    number = (ply + 1) // 2
    return f"{number}. {san}" if ply % 2 == 1 else f"{number}… {san}"
