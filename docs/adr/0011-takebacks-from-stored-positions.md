# ADR-0011: Takebacks restore stored positions; nothing is replayed

**Status:** Accepted
**Date:** 2026-10-12

## Context
Harry decided takebacks must be included. Undoing moves must restore the exact earlier position (castling rights, en passant, move counters) and keep repetition detection right, without breaking the no-replay rule of ADR-0007 that protects the 10 ms CPU budget.

## Decision
A takeback needs the opponent's agreement. On acceptance the GameRoom deletes the undone rows from `moves`, decrements their keys in `positions`, and sets `current_fen` to the stored `fen_after` of the new last move (or `start_fen`). One ply is undone if it is the opponent's turn, two if the opponent has already replied. Pending draw offers are cleared. Undone moves disappear from the move list and PGN.

## Consequences
- Constant, tiny CPU per takeback; no replay.
- `ply` can now go down, so clients must re-derive everything from each `state`, and `STALE_PLY` protects against a move racing a takeback.
- Checked against python-chess's own `pop()` on 47,177 random move/takeback steps with zero mismatches; property test P7 keeps it that way.

## Alternatives considered
- Replaying the remaining moves from the start: correct but CPU-expensive for long games.
- Unilateral takebacks without agreement: rejected; both players should agree.
