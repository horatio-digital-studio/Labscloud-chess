"""Turn the tail of a log file into a GitHub Actions error annotation.

Annotations are readable through the checks API, so a failure can be diagnosed without
downloading the full job log. Usage: annotate_failure.py TITLE LOGFILE [MAX_LINES]
"""

from __future__ import annotations

import sys
from pathlib import Path

MAX_CHARS = 30_000


def escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: annotate_failure.py TITLE LOGFILE [MAX_LINES]", file=sys.stderr)
        return 2
    title, path = argv[1], Path(argv[2])
    limit = int(argv[3]) if len(argv) > 3 else 80
    if not path.exists():
        print(f"::error title={escape(title)}::log file {path} not found")
        return 0
    tail = "\n".join(path.read_text(errors="replace").splitlines()[-limit:])
    print(f"::error title={escape(title)}::{escape(tail[-MAX_CHARS:])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
