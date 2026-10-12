"""PGN export (REQ-GAME-06). Written here rather than using chess.pgn, which pulls in
python-chess's engine and SVG modules that we don't vendor."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

TAG_ORDER = ("Event", "Site", "Date", "White", "Black", "Result")
LINE_WIDTH = 80


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")


def pgn_date(epoch_ms: int) -> str:
    when = dt.datetime.fromtimestamp(epoch_ms / 1000, tz=dt.UTC)
    return when.strftime("%Y.%m.%d")


def export_pgn(
    *,
    site: str,
    epoch_ms: int,
    white: str,
    black: str,
    sans: Sequence[str],
    result: str | None,
) -> str:
    """Return a PGN string with the seven-tag-roster subset we use and the moves."""
    result_token = result or "*"
    tags = {
        "Event": "labscloud-chess",
        "Site": site,
        "Date": pgn_date(epoch_ms),
        "White": white,
        "Black": black,
        "Result": result_token,
    }
    header = "\n".join(f'[{name} "{_escape(tags[name])}"]' for name in TAG_ORDER)

    tokens: list[str] = []
    for index, san in enumerate(sans):
        if index % 2 == 0:
            tokens.append(f"{index // 2 + 1}.")
        tokens.append(san)
    tokens.append(result_token)

    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = f"{current} {token}" if current else token
        if len(candidate) > LINE_WIDTH and current:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return header + "\n\n" + "\n".join(lines) + "\n"
