# ADR-0004: Server-authoritative rules with python-chess

**Status:** Accepted — python-chess vendored (see Consequences)
**Date:** 2026-10-12

## Context
Rules must be correct (castling, en passant, promotion, draws) and the project is to be Python, not TypeScript.

## Decision
All rule decisions happen on the server in `chess_core`, a thin wrapper over python-chess 1.11.2. The client receives the legal move list with every `state` and never decides legality or outcome. Moves are accepted only as canonical UCI strings that appear in the legal list.

## Consequences
- One source of truth; nothing to cheat by editing JS.
- No JS chess library needed in the browser.
- python-chess accepts `e1h1` as castling, so the wrapper compares strings, not `Move` objects (catalogue W08).
- python-chess is an sdist-only package on PyPI, and `pywrangler` installs with `--no-build`, so it can't be a normal dependency. **Decision (12 Oct 2026): vendor it.** `src/chess/__init__.py` is python-chess 1.11.2's core module, unmodified, with its GPL-3.0 licence alongside (`src/chess/LICENSE.txt`). Only the core is needed (no `chess.pgn`, `chess.svg`, engines); `chess_core/pgn.py` writes PGN itself. Ruff and pyright skip `src/chess`.

## Alternatives considered
- Hand-written move generator: large, bug-prone, no benefit.
- Client-side rules (chess.js): would split the rules across two languages.
