# ADR-0007: Track repetition counts; never replay moves on the hot path

**Status:** Accepted — CPU numbers pending S-04
**Date:** 2026-10-12

## Context
Workers Free allows 10 ms of CPU per invocation. python-chess detects repetition by walking the move history. In CPython on our workspace, a full replay of a 131-ply game plus repetition checks took 1.8 ms median (3.1 ms p95); Pyodide is slower by an unknown factor. The hot path (one FEN parse, legal moves, end checks) took 0.08 ms.

## Decision
Store `current_fen` and a `positions(key, count)` table, where `key` is the first four FEN fields. After each move, increment the new position's count. Fivefold = count ≥ 5; claimable threefold = count ≥ 3. Rebuild after hibernation = parse `current_fen` + load counts. The move list is only read for display and PGN.

## Consequences
- Constant, tiny CPU per move regardless of game length.
- Our repetition rule must match python-chess: checked on 77,044 positions with zero mismatches, and kept honest by property test P3.
- The starting position must be inserted with count 1 at game creation.

## Alternatives considered
- Replay on wake only: still a risk for long games on a cold object.
- Use python-chess's `can_claim_draw()`: includes "claim by next move" and scans history; not needed for v1.
